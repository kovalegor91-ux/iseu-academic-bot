import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from config import OUTPUT_DIR
from core.reference_parser import ReferenceParser

logger = logging.getLogger(__name__)

KB_DIR = OUTPUT_DIR / "knowledge_base"
USERS_KB_DIR = KB_DIR / "users"
GLOBAL_KB_DIR = KB_DIR / "global"
PROFILES_DIR = KB_DIR / "profiles"

for d in [KB_DIR, USERS_KB_DIR, GLOBAL_KB_DIR, PROFILES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

class KnowledgeBase:
    """
    Persistent Academic Reference & Learning System:
    - Stores multi-document reference libraries per user and globally across ISEU students.
    - Aggregates structural patterns, headings, fonts, and academic vocabulary into learning profiles.
    - Provides few-shot context for Gemini based on 'my_docs' or 'global_docs'.
    """

    @classmethod
    def add_document(cls, user_id: int, filename: str, file_bytes: bytes) -> Dict[str, Any]:
        """Save and learn from an uploaded .docx or .pptx document."""
        user_dir = USERS_KB_DIR / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        user_file_path = user_dir / filename
        with open(user_file_path, "wb") as f:
            f.write(file_bytes)

        # Also store copy in global shared pool
        global_filename = f"{user_id}_{filename}"
        global_file_path = GLOBAL_KB_DIR / global_filename
        with open(global_file_path, "wb") as f:
            f.write(file_bytes)

        # Parse document
        parsed_data = ReferenceParser.parse_file(user_file_path)
        parsed_data["filename"] = filename
        parsed_data["file_size"] = len(file_bytes)

        # Update user profile
        cls._update_profile(str(user_id), parsed_data, is_user=True)
        # Update global institute profile
        cls._update_profile("global", parsed_data, is_user=False)

        stats = cls.get_stats(user_id)
        logger.info(f"KnowledgeBase: added '{filename}' for user {user_id}. User docs: {stats['user_docs']}, Global docs: {stats['global_docs']}")
        return {
            "parsed": parsed_data,
            "stats": stats
        }

    @classmethod
    def _update_profile(cls, profile_key: str, doc_data: Dict[str, Any], is_user: bool = True):
        """Append document metadata and learned patterns to profile."""
        profile_file = PROFILES_DIR / f"profile_{profile_key}.json"
        profile: Dict[str, Any] = {
            "documents": [],
            "learned_headings": [],
            "learned_vocabulary": [],
            "sample_texts": [],
            "fonts": [],
            "total_docs": 0
        }

        if profile_file.exists():
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load profile {profile_key}: {e}")

        # Update documents list (replace if existing filename)
        fname = doc_data.get("filename", "")
        profile["documents"] = [d for d in profile.get("documents", []) if d.get("filename") != fname]
        profile["documents"].append({
            "filename": fname,
            "type": doc_data.get("type", "docx"),
            "file_size": doc_data.get("file_size", 0),
            "headings_count": len(doc_data.get("headings", [])) or doc_data.get("slide_count", 0),
            "font": doc_data.get("font_name", "Times New Roman")
        })

        # Aggregate headings
        for h in doc_data.get("headings", []):
            if h and h not in profile["learned_headings"]:
                profile["learned_headings"].append(h)
        profile["learned_headings"] = profile["learned_headings"][:30]

        # Aggregate sample texts
        sample = doc_data.get("sample_text", "")
        if sample:
            clean_sample = sample[:1000].strip()
            if clean_sample not in profile["sample_texts"]:
                profile["sample_texts"].append(clean_sample)
        profile["sample_texts"] = profile["sample_texts"][:8]

        # Track fonts
        fnt = doc_data.get("font_name")
        if fnt and fnt not in profile["fonts"]:
            profile["fonts"].append(fnt)

        profile["total_docs"] = len(profile["documents"])

        try:
            with open(profile_file, "w", encoding="utf-8") as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving profile {profile_key}: {e}")

    @classmethod
    def get_stats(cls, user_id: int) -> Dict[str, int]:
        """Get document counts for this user and the global repository."""
        user_dir = USERS_KB_DIR / str(user_id)
        user_cnt = len(list(user_dir.glob("*.*"))) if user_dir.exists() else 0
        global_cnt = len(list(GLOBAL_KB_DIR.glob("*.*"))) if GLOBAL_KB_DIR.exists() else 0
        return {
            "user_docs": user_cnt,
            "global_docs": max(global_cnt, user_cnt)
        }

    @classmethod
    def get_user_documents(cls, user_id: int) -> List[Dict[str, Any]]:
        """Return list of reference documents uploaded by this user."""
        profile_file = PROFILES_DIR / f"profile_{user_id}.json"
        if profile_file.exists():
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("documents", [])
            except Exception:
                pass
        return []

    @classmethod
    def delete_user_document(cls, user_id: int, filename: str) -> Dict[str, Any]:
        """Remove a document from the user's personal knowledge base."""
        user_dir = USERS_KB_DIR / str(user_id)
        target_file = user_dir / filename
        if target_file.exists():
            try:
                target_file.unlink()
            except Exception as e:
                logger.warning(f"Could not delete file {target_file}: {e}")

        profile_file = PROFILES_DIR / f"profile_{user_id}.json"
        if profile_file.exists():
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                profile["documents"] = [
                    d for d in profile.get("documents", []) if d.get("filename") != filename
                ]
                profile["total_docs"] = len(profile["documents"])
                with open(profile_file, "w", encoding="utf-8") as f:
                    json.dump(profile, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Could not update profile after deleting {filename}: {e}")

        return {
            "documents": cls.get_user_documents(user_id),
            "stats": cls.get_stats(user_id)
        }


    @classmethod
    def get_learning_context(cls, user_id: int, mode: str = "my_docs") -> str:
        """
        Build instruction prompt context based on selected learning mode:
        - 'my_docs': only user's uploaded documents
        - 'global_docs': aggregate knowledge base of all student documents across the institute
        - 'standard': standard GOST without few-shot samples
        """
        if mode == "standard":
            return ""

        profile_key = str(user_id) if mode == "my_docs" else "global"
        profile_file = PROFILES_DIR / f"profile_{profile_key}.json"

        # Fallback to user if global empty, or vice-versa
        if not profile_file.exists():
            if mode == "my_docs":
                profile_file = PROFILES_DIR / "profile_global.json"
            else:
                profile_file = PROFILES_DIR / f"profile_{user_id}.json"

        if not profile_file.exists():
            return ""

        try:
            with open(profile_file, "r", encoding="utf-8") as f:
                p = json.load(f)
        except Exception as e:
            logger.debug(f"Failed to load learning profile {profile_key}: {e}")
            return ""

        headings = p.get("learned_headings", [])[:12]
        samples = p.get("sample_texts", [])[:3]
        total_docs = p.get("total_docs", 0)

        if not headings and not samples:
            return ""

        mode_desc = (
            f"личных образцах пользователя ({total_docs} загруженных документов)"
            if mode == "my_docs"
            else f"общей базе знаний студентов МГЭИ им. А.Д. Сахарова ({total_docs} проанализированных работ)"
        )

        samples_block = "\n---\n".join(samples)

        return f"""
ВАЖНО! ОБУЧЕНИЕ И КЛОНИРОВАНИЕ СТИЛЯ НА ОСНОВЕ БАЗЫ ОБРАЗЦОВ:
Генерация выполняется на основе {mode_desc}.
Тебе необходимо строго перенять академический тон, терминологию, стилистические конструкции и глубину проработки из этих документов:

1. Характерная структура заголовков из базы образцов:
{json.dumps(headings, ensure_ascii=False, indent=2)}

2. Фрагменты стиля и лексики из базы документов:
{samples_block}

Требование: Сохраняй аналогичную манеру изложения, плотность терминов и структуру подачи материала!
"""
