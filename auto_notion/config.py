import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")

# Proveedor LLM: "gemini" (API key), "gemini-cli" (cuenta de Google) u "openrouter" (GPT y otros)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Modelo para Gemini CLI; vacío = el que el CLI use por defecto (Pro con fallback)
GEMINI_CLI_MODEL = os.getenv("GEMINI_CLI_MODEL", "")

# Modelo para Codex CLI (cuenta de ChatGPT); vacío = el del CLI por defecto
CODEX_MODEL = os.getenv("CODEX_MODEL", "")

# Modelo para Claude CLI (cuenta de Claude); vacío = el del plan por defecto
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-5.5")

BACKUP_DIR = ROOT / "backups"
PREVIEW_DIR = ROOT / "preview"


def validate(require_notion=True, provider=None):
    provider = provider or LLM_PROVIDER
    missing = []
    if require_notion and not NOTION_TOKEN:
        missing.append("NOTION_TOKEN")
    if provider == "openrouter" and not OPENROUTER_API_KEY:
        missing.append("OPENROUTER_API_KEY")
    if provider == "gemini" and not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if missing:
        sys.exit(
            f"❌ Faltan variables en .env: {', '.join(missing)}.\n"
            "   Copia .env.example a .env y completa los valores."
        )
