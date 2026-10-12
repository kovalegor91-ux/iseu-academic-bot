import os
import json
import base64
import logging
import asyncio
from aiohttp import web
from pathlib import Path
from typing import Optional, Callable, Awaitable, Dict, Any
from config import WEBAPP_HOST, WEBAPP_PORT, WEBAPP_DIR, OUTPUT_DIR
from core.session_manager import SessionManager
from core.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

STAGED_UPLOADS_DIR = OUTPUT_DIR / "uploads" / "webapp_staged"
STAGED_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_generate_callback: Optional[Callable[[int, Dict[str, Any]], Awaitable[None]]] = None

def set_generate_callback(cb: Callable[[int, Dict[str, Any]], Awaitable[None]]):
    """Register callback from bot.py to trigger generation directly via HTTP API."""
    global _generate_callback
    _generate_callback = cb

def _update_session_from_payload(user_id: int, data: Dict[str, Any]):
    """Persist all user parameters and rules from WebApp into SessionManager."""
    session = SessionManager.get_session(user_id)

    if "custom_rules" in data:
        session.custom_rules = str(data["custom_rules"])
    if "no_subsections" in data:
        session.no_subsections = bool(data["no_subsections"])
    if "no_appendix" in data:
        session.no_appendix = bool(data["no_appendix"])

    param_fields = [
        "faculty", "department", "custom_department", "discipline",
        "student_name", "education_form", "student_course",
        "student_group", "student_subgroup", "supervisor",
        "page_count", "slide_count", "include_images",
        "learning_mode", "sections_config"
    ]
    for field in param_fields:
        if field in data and data[field] is not None:
            session.params[field] = data[field]

    SessionManager.save_session(user_id)
    return session

async def index_handler(request: web.Request):
    index_file = WEBAPP_DIR / "index.html"
    resp = web.FileResponse(index_file)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

async def style_handler(request: web.Request):
    style_file = WEBAPP_DIR / "style.css"
    resp = web.FileResponse(style_file)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

async def health_handler(request: web.Request):
    return web.json_response({"status": "ok", "app": "ISEU Academic Bot WebApp"})

async def api_user_state_handler(request: web.Request):
    """Return saved user session parameters and uploaded reference documents."""
    uid_str = request.query.get("user_id", "").strip()
    if not uid_str or not uid_str.isdigit():
        return web.json_response({"status": "no_user_id"})

    user_id = int(uid_str)
    session = SessionManager.get_session(user_id)
    docs = KnowledgeBase.get_user_documents(user_id)
    stats = KnowledgeBase.get_stats(user_id)

    return web.json_response({
        "status": "ok",
        "params": session.params,
        "custom_rules": session.custom_rules,
        "no_subsections": session.no_subsections,
        "no_appendix": session.no_appendix,
        "documents": docs,
        "stats": stats
    })

async def api_save_state_handler(request: web.Request):
    """Save user form fields on the server."""
    try:
        data = await request.json()
        uid_str = str(data.get("user_id", "")).strip()
        if not uid_str or not uid_str.isdigit():
            return web.json_response({"status": "no_user_id"})

        user_id = int(uid_str)
        _update_session_from_payload(user_id, data)
        return web.json_response({"status": "ok"})
    except Exception as e:
        logger.error(f"Error in /api/save_state: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def api_upload_reference_handler(request: web.Request):
    """Receive reference file (.docx / .pptx) over HTTP without Telegram's 4KB sendData limit."""
    try:
        data = await request.json()
        filename = os.path.basename(data.get("filename", "reference.docx"))
        b64_content = data.get("base64", "")
        uid_str = str(data.get("user_id", "")).strip()

        if not b64_content:
            return web.json_response({"status": "error", "message": "Empty file content"}, status=400)

        file_bytes = base64.b64decode(b64_content)

        if uid_str and uid_str.isdigit():
            user_id = int(uid_str)
            res = KnowledgeBase.add_document(user_id, filename, file_bytes)
            session = SessionManager.get_session(user_id)
            session.reference_data = res["parsed"]
            SessionManager.save_session(user_id)
            return web.json_response({
                "status": "ok",
                "staged": False,
                "filename": filename,
                "documents": KnowledgeBase.get_user_documents(user_id),
                "stats": res["stats"]
            })
        else:
            # Stage file on disk so handle_webapp_data can claim it when sendData arrives with user_id
            staged_path = STAGED_UPLOADS_DIR / filename
            with open(staged_path, "wb") as f:
                f.write(file_bytes)
            logger.info(f"Staged reference upload '{filename}' ({len(file_bytes)} bytes) awaiting sendData.")
            return web.json_response({
                "status": "ok",
                "staged": True,
                "filename": filename
            })
    except Exception as e:
        logger.error(f"Error in /api/upload_reference: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def api_delete_reference_handler(request: web.Request):
    """Delete a reference document from the user's library."""
    try:
        data = await request.json()
        filename = os.path.basename(data.get("filename", ""))
        uid_str = str(data.get("user_id", "")).strip()

        if uid_str and uid_str.isdigit() and filename:
            user_id = int(uid_str)
            res = KnowledgeBase.delete_user_document(user_id, filename)
            return web.json_response({
                "status": "ok",
                "documents": res["documents"],
                "stats": res["stats"]
            })

        # Also remove from staged if exists
        if filename:
            staged_path = STAGED_UPLOADS_DIR / filename
            if staged_path.exists():
                try:
                    staged_path.unlink()
                except Exception:
                    pass
        return web.json_response({"status": "ok"})
    except Exception as e:
        logger.error(f"Error in /api/delete_reference: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def api_generate_handler(request: web.Request):
    """Trigger generation directly from WebApp via HTTP POST when user_id is known."""
    try:
        data = await request.json()
        uid_str = str(data.get("user_id", "")).strip()
        if not uid_str or not uid_str.isdigit() or _generate_callback is None:
            return web.json_response({"status": "fallback_send_data", "started": False})

        user_id = int(uid_str)
        session = _update_session_from_payload(user_id, data)

        # Claim any staged files if present
        staged_files = data.get("staged_files", [])
        for sf_name in staged_files:
            safe_name = os.path.basename(sf_name)
            staged_path = STAGED_UPLOADS_DIR / safe_name
            if staged_path.exists():
                try:
                    with open(staged_path, "rb") as f:
                        fbytes = f.read()
                    res = KnowledgeBase.add_document(user_id, safe_name, fbytes)
                    session.reference_data = res["parsed"]
                    staged_path.unlink()
                except Exception as ex:
                    logger.warning(f"Failed to claim staged file {safe_name}: {ex}")

        SessionManager.save_session(user_id)

        # Spawn generation in background asyncio task
        asyncio.create_task(_generate_callback(user_id, data))
        return web.json_response({"status": "ok", "started": True})
    except Exception as e:
        logger.error(f"Error in /api/generate: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e), "started": False}, status=500)

def create_webapp():
    # Allow up to 50 MB request bodies for large .docx/.pptx reference files
    app = web.Application(client_max_size=50 * 1024 * 1024)
    app.router.add_get("/", index_handler)
    app.router.add_get("/style.css", style_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/user_state", api_user_state_handler)
    app.router.add_post("/api/save_state", api_save_state_handler)
    app.router.add_post("/api/upload_reference", api_upload_reference_handler)
    app.router.add_post("/api/delete_reference", api_delete_reference_handler)
    app.router.add_post("/api/generate", api_generate_handler)
    app.router.add_static("/", WEBAPP_DIR)
    return app

async def start_webapp_server():
    app = create_webapp()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    logger.info(f"WebApp server running at http://{WEBAPP_HOST}:{WEBAPP_PORT}")
    return runner

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_webapp(), host=WEBAPP_HOST, port=WEBAPP_PORT)
