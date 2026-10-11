import os
import logging
from aiohttp import web
from pathlib import Path
from config import WEBAPP_HOST, WEBAPP_PORT, WEBAPP_DIR

logger = logging.getLogger(__name__)

async def index_handler(request):
    index_file = WEBAPP_DIR / "index.html"
    return web.FileResponse(index_file)

async def health_handler(request):
    return web.json_response({"status": "ok", "app": "ISEU Academic Bot WebApp"})

def create_webapp():
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
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
