"""Proveedor Gemini (Google AI Studio)."""

import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from .llm_base import BaseAgent, clean_output  # noqa: F401  (clean_output re-exportado)


class GeminiAgent(BaseAgent):
    def __init__(self, api_key, model, use_search=True):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.use_search = use_search

    def _generate(self, system, prompt, use_search):
        kwargs = {"system_instruction": system, "temperature": 0.3}
        if use_search:
            kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        config = types.GenerateContentConfig(**kwargs)

        delay = 10
        last = None
        for _ in range(4):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                text = self._text(resp)
                if not text.strip():
                    raise RuntimeError("Gemini devolvió una respuesta vacía")
                return text
            except genai_errors.APIError as e:
                if "depleted" in str(e) or "prepayment" in str(e):
                    raise RuntimeError(
                        "Sin créditos en la API de Gemini. Recarga o revisa la facturación en "
                        "https://ai.studio/projects"
                    ) from e
                if "limit: 0" in str(e):
                    raise RuntimeError(
                        f"El modelo «{self.model}» no tiene cuota en tu plan (límite 0). "
                        "Con API key gratuita usa un modelo flash, ej. gemini-2.5-flash "
                        "(cámbialo en .env o con --modelo)."
                    ) from e
                if "PerDay" in str(e):
                    raise RuntimeError(
                        f"Cuota diaria gratuita agotada para «{self.model}». "
                        "Espera al reinicio (medianoche, hora del Pacífico) o usa otro modelo, "
                        "ej. --modelo gemini-2.5-flash-lite"
                    ) from e
                last = e
                if getattr(e, "code", None) in (429, 500, 503):
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise
        raise RuntimeError(f"Gemini falló tras varios intentos: {last}")

    @staticmethod
    def _text(resp):
        try:
            if resp.text:
                return resp.text
        except Exception:
            pass
        parts = []
        for cand in getattr(resp, "candidates", None) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "text", None):
                    parts.append(part.text)
        return "".join(parts)

    def list_models(self):
        return sorted(
            m.name.removeprefix("models/")
            for m in self.client.models.list()
            if "gemini" in m.name
        )
