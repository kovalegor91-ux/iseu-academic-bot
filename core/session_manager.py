import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from config import SESSIONS_DIR

logger = logging.getLogger(__name__)

class UserSession:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.reference_data: Optional[Dict[str, Any]] = None
        self.current_doc_data: Optional[Dict[str, Any]] = None
        self.current_pres_data: Optional[Dict[str, Any]] = None
        self.current_docx_path: Optional[str] = None
        self.current_pptx_path: Optional[str] = None
        self.current_image_map: Dict[str, str] = {}
        self.revision_count: int = 0
        self.last_mode: str = "doc"  # 'doc', 'pres', 'bundle'
        self.custom_rules: str = ""
        self.no_subsections: bool = False
        self.no_appendix: bool = False
        self.params: Dict[str, Any] = {
            "faculty": "Факультет мониторинга окружающей среды",
            "department": "Кафедра экологического мониторинга",
            "student_name": "Иванов И.И.",
            "student_course": "3",
            "student_group": "301",
            "supervisor": "доцент, к.б.н. Петров П.П.",
            "include_images": True,
            "anti_ai_style": True
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "reference_data": self.reference_data,
            "current_doc_data": self.current_doc_data,
            "current_pres_data": self.current_pres_data,
            "current_docx_path": self.current_docx_path,
            "current_pptx_path": self.current_pptx_path,
            "current_image_map": self.current_image_map,
            "revision_count": self.revision_count,
            "last_mode": self.last_mode,
            "custom_rules": self.custom_rules,
            "no_subsections": self.no_subsections,
            "no_appendix": self.no_appendix,
            "params": self.params
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserSession':
        sess = cls(data["user_id"])
        sess.reference_data = data.get("reference_data")
        sess.current_doc_data = data.get("current_doc_data")
        sess.current_pres_data = data.get("current_pres_data")
        sess.current_docx_path = data.get("current_docx_path")
        sess.current_pptx_path = data.get("current_pptx_path")
        sess.current_image_map = data.get("current_image_map", {})
        sess.revision_count = data.get("revision_count", 0)
        sess.last_mode = data.get("last_mode", "doc")
        sess.custom_rules = data.get("custom_rules", "")
        sess.no_subsections = data.get("no_subsections", False)
        sess.no_appendix = data.get("no_appendix", False)
        sess.params = data.get("params", sess.params)
        return sess

class SessionManager:
    _sessions: Dict[int, UserSession] = {}

    @classmethod
    def get_session(cls, user_id: int) -> UserSession:
        if user_id not in cls._sessions:
            # Try load from disk
            sess_file = SESSIONS_DIR / f"session_{user_id}.json"
            if sess_file.exists():
                try:
                    with open(sess_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    cls._sessions[user_id] = UserSession.from_dict(data)
                except Exception as e:
                    logger.warning(f"Failed to load session for {user_id}: {e}")
                    cls._sessions[user_id] = UserSession(user_id)
            else:
                cls._sessions[user_id] = UserSession(user_id)
        return cls._sessions[user_id]

    @classmethod
    def save_session(cls, user_id: int):
        sess = cls._sessions.get(user_id)
        if sess:
            sess_file = SESSIONS_DIR / f"session_{user_id}.json"
            try:
                with open(sess_file, "w", encoding="utf-8") as f:
                    json.dump(sess.to_dict(), f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Failed to save session for {user_id}: {e}")

    @classmethod
    def clear_session(cls, user_id: int):
        if user_id in cls._sessions:
            del cls._sessions[user_id]
        sess_file = SESSIONS_DIR / f"session_{user_id}.json"
        if sess_file.exists():
            try:
                sess_file.unlink()
            except Exception:
                pass
