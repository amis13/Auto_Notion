"""Proveedor Claude Code CLI: usa tu cuenta de Claude (Pro/Max) en vez de una API key.

Requiere tener instalado Claude Code (https://claude.com/claude-code) y sesión
iniciada (se inicia con «claude» → /login). El consumo sale de la cuota de tu plan.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .llm_base import BaseAgent

CREDS_FILE = Path.home() / ".claude" / ".credentials.json"


class ClaudeCliAgent(BaseAgent):
    def __init__(self, model=None, use_search=True, command="claude"):
        self.command = command
        self._model_flag = (model or "").strip()
        self.model = self._model_flag or "Claude CLI (modelo por defecto)"
        self.use_search = use_search
        # Directorio vacío como workspace para que el CLI no escanee tu proyecto.
        self._workdir = tempfile.mkdtemp(prefix="auto_notion_claude_")

    @staticmethod
    def check_auth():
        if not CREDS_FILE.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "Claude CLI no tiene sesión iniciada. Ejecuta «claude» en la terminal "
                "e inicia sesión con /login, y vuelve a intentarlo."
            )

    def _generate(self, system, prompt, use_search):
        self.check_auth()
        cmd = [
            self.command, "-p",
            "--output-format", "json",
            "--system-prompt", system,
        ]
        if use_search:
            # Permite solo búsqueda/lectura web; el resto de herramientas queda denegado.
            cmd += ["--allowedTools", "WebSearch", "WebFetch"]
        if self._model_flag:
            cmd += ["--model", self._model_flag]

        env = os.environ.copy()
        env["NO_COLOR"] = "1"

        delay = 15
        last = None
        for _ in range(3):
            try:
                proc = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True,
                    timeout=600, env=env, cwd=self._workdir,
                )
            except FileNotFoundError:
                raise RuntimeError(
                    "No se encontró el comando «claude». Instala Claude Code: "
                    "npm install -g @anthropic-ai/claude-code"
                ) from None
            except subprocess.TimeoutExpired:
                last = "timeout de 10 minutos"
                continue

            text, is_error = self._extract_response(proc.stdout or "")
            if proc.returncode == 0 and text.strip() and not is_error:
                return text

            combined = f"{(proc.stderr or '').strip()}\n{text}"[:600]
            lowered = combined.lower()
            if "rate limit" in lowered or "overloaded" in lowered or "429" in lowered or "usage limit" in lowered:
                last = "límite de uso del plan de Claude alcanzado"
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            if "login" in lowered or "credential" in lowered or "authentication" in lowered or "401" in lowered:
                raise RuntimeError(
                    "Sesión de Claude CLI caducada o inválida. Ejecuta «claude» y usa "
                    "/login para volver a iniciar sesión."
                )
            last = combined or f"código de salida {proc.returncode}"
            time.sleep(5)
        raise RuntimeError(f"Claude CLI falló tras varios intentos: {last}")

    @staticmethod
    def _extract_response(stdout):
        """Salida --output-format json: objeto con «result» e «is_error»."""
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(stdout[start : end + 1])
                return data.get("result") or "", bool(data.get("is_error"))
            except (json.JSONDecodeError, AttributeError):
                pass
        return stdout.strip(), False

    def list_models(self):
        return [
            "(vacío) → modelo por defecto de tu plan (recomendado)",
            "sonnet | opus | haiku  (alias del más reciente de cada familia)",
            "también nombres completos, ej. claude-sonnet-5, claude-opus-4-8",
            "— configura con CLAUDE_MODEL en .env o --modelo NOMBRE --proveedor claude",
        ]
