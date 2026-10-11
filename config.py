import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# API Keys & Bot Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# WebApp Configuration (Render.com compatibility)
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8080")))
WEBAPP_URL = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBAPP_URL", f"http://localhost:{WEBAPP_PORT}"))


# Paths
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"
WEBAPP_DIR = BASE_DIR / "webapp"
SESSIONS_DIR = BASE_DIR / "sessions"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Load University Standards
STANDARDS_FILE = TEMPLATES_DIR / "sakharov_standards.json"
if STANDARDS_FILE.exists():
    with open(STANDARDS_FILE, "r", encoding="utf-8") as f:
        SAKHAROV_STANDARDS = json.load(f)
else:
    SAKHAROV_STANDARDS = {}
