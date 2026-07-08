"""Proveedor OpenRouter (GPT y otros modelos, API compatible con OpenAI)."""

import time

import httpx

from .llm_base import BaseAgent

API_BASE = "https://openrouter.ai/api/v1"
_RETRYABLE = {408, 429, 500, 502, 503, 524}


class OpenRouterAgent(BaseAgent):
    def __init__(self, api_key, model, use_search=True):
        self.api_key = api_key
        self.model = model
        self.use_search = use_search

    def _generate(self, system, prompt, use_search):
        model = self.model
        # El sufijo :online activa la búsqueda web de OpenRouter para cualquier modelo.
        if use_search and not model.endswith(":online"):
            model += ":online"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Title": "Auto Notion",
        }

        delay = 10
        last = None
        for _ in range(4):
            try:
                resp = httpx.post(
                    f"{API_BASE}/chat/completions",
                    json=payload, headers=headers, timeout=600,
                )
                if resp.status_code == 401:
                    raise RuntimeError("OPENROUTER_API_KEY inválida (401). Revisa .env")
                if resp.status_code == 402:
                    raise RuntimeError(
                        "Sin créditos en OpenRouter (402). Recarga en https://openrouter.ai/credits"
                    )
                if resp.status_code == 404:
                    raise RuntimeError(
                        f"Modelo «{model}» no encontrado en OpenRouter (404). "
                        "Lista los disponibles con --listar-modelos --proveedor openrouter"
                    )
                if resp.status_code in _RETRYABLE:
                    last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                resp.raise_for_status()
                data = resp.json()
                # OpenRouter puede devolver 200 con un objeto de error dentro.
                if data.get("error"):
                    err = data["error"]
                    if err.get("code") in _RETRYABLE:
                        last = err.get("message", "error")
                        time.sleep(delay)
                        delay = min(delay * 2, 60)
                        continue
                    raise RuntimeError(f"OpenRouter: {err.get('message', err)}")
                text = (data["choices"][0]["message"].get("content") or "").strip()
                if not text:
                    raise RuntimeError("OpenRouter devolvió una respuesta vacía")
                return text
            except httpx.HTTPError as e:
                last = e
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise RuntimeError(f"OpenRouter falló tras varios intentos: {last}")

    def list_models(self):
        resp = httpx.get(f"{API_BASE}/models", timeout=60)
        resp.raise_for_status()
        ids = [m["id"] for m in resp.json().get("data", [])]
        return sorted(i for i in ids if i.startswith("openai/"))
