"""Proveedor Gemini CLI: usa tu cuenta de Google (OAuth) en vez de una API key.

Requiere tener instalado el CLI oficial (npm install -g @google/gemini-cli) y haber
iniciado sesión una vez ejecutando «gemini» en la terminal (Login with Google).
Cuota gratuita con cuenta personal: ~60 peticiones/min y ~1000/día de Gemini Pro.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .llm_base import BaseAgent

OAUTH_CREDS = Path.home() / ".gemini" / "oauth_creds.json"


class GeminiCliAgent(BaseAgent):
    def __init__(self, model=None, use_search=True, command="gemini"):
        self.command = command
        self._model_flag = (model or "").strip()
        self.model = self._model_flag or "Gemini CLI (Pro por defecto)"
        self.use_search = use_search
        # Directorio vacío como workspace para que el CLI no escanee tu proyecto.
        self._workdir = tempfile.mkdtemp(prefix="auto_notion_gemini_cli_")

    @staticmethod
    def check_auth():
        if not OAUTH_CREDS.exists():
            raise RuntimeError(
                "Gemini CLI no tiene sesión iniciada. Ejecuta «gemini» en la terminal, "
                "elige «Login with Google» y vuelve a intentarlo."
            )

    def _generate(self, system, prompt, use_search):
        self.check_auth()
        sys_prompt = system
        if use_search:
            sys_prompt += (
                "\n\nTienes disponible la herramienta google_web_search: úsala para "
                "verificar y actualizar los datos antes de redactar."
            )
        else:
            sys_prompt += "\n\nNo uses herramientas: responde directamente con el texto."

        sys_file = tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        )
        try:
            sys_file.write(sys_prompt)
            sys_file.close()
            env = os.environ.copy()
            env["GEMINI_SYSTEM_MD"] = sys_file.name  # reemplaza el system prompt del CLI
            env["NO_COLOR"] = "1"

            cmd = [self.command, "-p", prompt, "-o", "json", "--approval-mode", "plan"]
            if self._model_flag:
                cmd += ["-m", self._model_flag]

            delay = 15
            last = None
            for _ in range(3):
                try:
                    proc = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=600,
                        env=env, cwd=self._workdir,
                    )
                except FileNotFoundError:
                    raise RuntimeError(
                        "No se encontró el comando «gemini». Instálalo con: "
                        "npm install -g @google/gemini-cli"
                    ) from None
                except subprocess.TimeoutExpired:
                    last = "timeout de 10 minutos"
                    continue

                out = proc.stdout or ""
                err = (proc.stderr or "").strip()
                text = self._extract_response(out)
                if proc.returncode == 0 and text.strip():
                    return text

                full_combined = f"{err}\n{out}"
                lowered = full_combined.lower()
                if "429" in lowered or "quota" in lowered or "exhausted" in lowered:
                    last = "cuota/límite del CLI alcanzado"
                    time.sleep(delay)
                    delay = min(delay * 2, 120)
                    continue
                if "login" in lowered or "credential" in lowered or "auth" in lowered:
                    raise RuntimeError(
                        "Sesión de Gemini CLI caducada o inválida. Ejecuta «gemini» en la "
                        "terminal para volver a iniciar sesión."
                    )
                last = full_combined[-600:] if len(full_combined) > 600 else full_combined
                last = last or f"código de salida {proc.returncode}"
                time.sleep(5)
            raise RuntimeError(f"Gemini CLI falló tras varios intentos: {last}")
        finally:
            os.unlink(sys_file.name)

    @staticmethod
    def _extract_response(stdout):
        """Salida -o json: un objeto con el campo «response» (puede haber logs antes)."""
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(stdout[start : end + 1])
                return data.get("response") or ""
            except (json.JSONDecodeError, AttributeError):
                pass
        return stdout.strip()

    def list_models(self):
        return [
            "(vacío) → modelo por defecto del CLI: Gemini Pro con fallback automático",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "— configura con GEMINI_CLI_MODEL en .env o --modelo NOMBRE --proveedor gemini-cli",
        ]
