"""Proveedor Codex CLI: usa tu cuenta de ChatGPT (Plus/Pro) en vez de una API key.

Requiere tener instalado el CLI oficial (npm install -g @openai/codex) y haber
iniciado sesión una vez con «codex login» (OAuth con tu cuenta de ChatGPT).
El consumo sale de la cuota de tu plan de ChatGPT, no de créditos de API.
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path

from .llm_base import BaseAgent

AUTH_FILE = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"


class CodexCliAgent(BaseAgent):
    def __init__(self, model=None, use_search=True, command="codex"):
        self.command = command
        self._model_flag = (model or "").strip()
        self.model = self._model_flag or "Codex CLI (modelo por defecto)"
        self.use_search = use_search
        # Directorio vacío como workspace para que el CLI no escanee tu proyecto.
        self._workdir = tempfile.mkdtemp(prefix="auto_notion_codex_")

    @staticmethod
    def check_auth():
        if not AUTH_FILE.exists():
            raise RuntimeError(
                "Codex CLI no tiene sesión iniciada. Ejecuta «codex login» en la terminal "
                "(o «codex login --device-auth» si no se abre el navegador) y reintenta."
            )

    def _generate(self, system, prompt, use_search):
        self.check_auth()
        # Codex no tiene flag de system prompt en exec: se antepone al mensaje.
        full_prompt = f"{system}\n\n---\n\n{prompt}"

        out_file = tempfile.NamedTemporaryFile(
            "r", suffix=".md", delete=False, encoding="utf-8"
        )
        out_file.close()
        try:
            cmd = [
                self.command, "exec", "-",
                "--skip-git-repo-check",
                "--sandbox", "read-only",
                "--output-last-message", out_file.name,
            ]
            if use_search:
                # En codex exec la búsqueda web se activa vía config (no hay flag --search).
                cmd += ["-c", "tools.web_search=true", "-c", 'web_search="live"']
            if self._model_flag:
                cmd += ["--model", self._model_flag]

            env = os.environ.copy()
            env["NO_COLOR"] = "1"

            delay = 15
            last = None
            for _ in range(3):
                try:
                    proc = subprocess.run(
                        cmd, input=full_prompt, capture_output=True, text=True,
                        timeout=600, env=env, cwd=self._workdir,
                    )
                except FileNotFoundError:
                    raise RuntimeError(
                        "No se encontró el comando «codex». Instálalo con: "
                        "npm install -g @openai/codex"
                    ) from None
                except subprocess.TimeoutExpired:
                    last = "timeout de 10 minutos"
                    continue

                text = Path(out_file.name).read_text(encoding="utf-8").strip()
                if proc.returncode == 0 and text:
                    return text

                combined = f"{(proc.stderr or '').strip()}\n{(proc.stdout or '').strip()}"[:600]
                lowered = combined.lower()
                if "usage limit" in lowered or "rate limit" in lowered or "429" in lowered:
                    last = "límite de uso del plan de ChatGPT alcanzado"
                    time.sleep(delay)
                    delay = min(delay * 2, 120)
                    continue
                if "login" in lowered or "auth" in lowered or "401" in lowered:
                    raise RuntimeError(
                        "Sesión de Codex CLI caducada o inválida. Ejecuta «codex login» "
                        "en la terminal para volver a iniciar sesión."
                    )
                last = combined or f"código de salida {proc.returncode}"
                time.sleep(5)
            raise RuntimeError(f"Codex CLI falló tras varios intentos: {last}")
        finally:
            os.unlink(out_file.name)

    def list_models(self):
        return [
            "(vacío) → modelo por defecto del CLI",
            "gpt-5.4",
            "gpt-5.4-codex",
            "gpt-5.5",
            "— configura con CODEX_MODEL en .env o --modelo NOMBRE --proveedor codex",
        ]
