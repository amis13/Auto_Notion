"""Proveedor LMStudio (Modelos locales con API compatible con OpenAI)."""

import time
import httpx
from .llm_base import BaseAgent

_RETRYABLE = {408, 429, 500, 502, 503, 524}

class LMStudioAgent(BaseAgent):
    def __init__(self, api_base, model, use_search=False, think="auto",
                 context_length="native", max_tokens="", api_token=""):
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.use_search = False  # Local models generally don't have built-in web search
        self.think = (think or "auto").strip().lower()
        if self.think not in ("auto", "on", "off"):
            raise ValueError("LMSTUDIO_THINK/--think debe ser: auto, on u off")
        self.context_length = self._parse_context_length(context_length)
        self.max_tokens = self._parse_positive_int(max_tokens, "LMSTUDIO_MAX_TOKENS")
        self.api_token = (api_token or "").strip()
        self._context_prepared = False

    @staticmethod
    def _parse_positive_int(value, label):
        if value is None or str(value).strip() == "":
            return None
        try:
            parsed = int(str(value).strip())
        except ValueError as exc:
            raise ValueError(f"{label} debe ser un entero positivo") from exc
        if parsed <= 0:
            raise ValueError(f"{label} debe ser un entero positivo")
        return parsed

    @classmethod
    def _parse_context_length(cls, value):
        value = (str(value or "native").strip().lower())
        if value in ("loaded", "current", "actual"):
            return "loaded"
        if value in ("native", "max", "maximum", "nativo"):
            return "native"
        return cls._parse_positive_int(value, "LMSTUDIO_CONTEXT_LENGTH/--lm-context")

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _native_api_base(self):
        if self.api_base.endswith("/api/v1"):
            return self.api_base
        if self.api_base.endswith("/v1"):
            return self.api_base[:-3] + "/api/v1"
        return self.api_base + "/api/v1"

    @staticmethod
    def _model_identifiers(info):
        ids = []
        for key in ("key", "selected_variant", "display_name", "path", "filename"):
            value = info.get(key)
            if value:
                ids.append(str(value))
        ids.extend(str(v) for v in info.get("variants") or [] if v)
        for inst in info.get("loaded_instances") or []:
            if inst.get("id"):
                ids.append(str(inst["id"]))
        return ids

    def _model_matches(self, info):
        target = self.model.casefold()
        for candidate in self._model_identifiers(info):
            candidate_norm = candidate.casefold()
            if (
                candidate_norm == target
                or candidate_norm.endswith("/" + target)
                or target.endswith("/" + candidate_norm)
            ):
                return True
        return False

    def _matching_model_info(self, models):
        for info in models:
            if self._model_matches(info):
                return info

        loaded = [m for m in models if m.get("loaded_instances")]
        if self.model == "local-model" and len(loaded) == 1:
            return loaded[0]
        return None

    def _matching_loaded_instance(self, info):
        instances = info.get("loaded_instances") or []
        for inst in instances:
            inst_id = str(inst.get("id") or "")
            if inst_id and (
                inst_id.casefold() == self.model.casefold()
                or inst_id.casefold().endswith("/" + self.model.casefold())
            ):
                return inst
        return instances[0] if instances else None

    @staticmethod
    def _loaded_context(instance):
        if not instance:
            return None
        try:
            return int((instance.get("config") or {}).get("context_length") or 0) or None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _load_model_id(info):
        return (
            info.get("selected_variant")
            or info.get("key")
            or (info.get("variants") or [None])[0]
        )

    def _get_native_models(self):
        try:
            resp = httpx.get(
                f"{self._native_api_base()}/models",
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code == 404:
                raise RuntimeError(
                    "LM Studio no expone /api/v1/models. Actualiza LM Studio o usa "
                    "LMSTUDIO_CONTEXT_LENGTH=loaded."
                )
            resp.raise_for_status()
            return resp.json().get("models", [])
        except httpx.ConnectError:
            raise RuntimeError(
                f"No se pudo conectar a LM Studio en {self._native_api_base()}. "
                "Asegúrate de que el servidor local está iniciado."
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"LM Studio /api/v1/models falló: {exc}") from exc

    def _post_native(self, endpoint, payload, timeout=900):
        try:
            resp = httpx.post(
                f"{self._native_api_base()}{endpoint}",
                json=payload,
                headers=self._headers(),
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            details = ""
            if getattr(exc, "response", None) is not None:
                details = f": {exc.response.text[:300]}"
            raise RuntimeError(f"LM Studio {endpoint} falló{details}") from exc

    def _ensure_context_loaded(self):
        if self._context_prepared or self.context_length == "loaded":
            return

        models = self._get_native_models()
        info = self._matching_model_info(models)
        if not info:
            known = ", ".join(
                (m.get("selected_variant") or m.get("key") or m.get("display_name") or "?")
                for m in models[:8]
            )
            raise RuntimeError(
                f"No encontré «{self.model}» en LM Studio /api/v1/models. "
                f"Modelos detectados: {known or 'ninguno'}."
            )

        max_context = self._parse_positive_int(
            info.get("max_context_length"), "max_context_length de LM Studio"
        )
        target_context = max_context if self.context_length == "native" else self.context_length
        if target_context > max_context:
            raise RuntimeError(
                f"El contexto solicitado ({target_context}) supera el máximo nativo "
                f"de «{self.model}» ({max_context})."
            )

        instance = self._matching_loaded_instance(info)
        loaded_context = self._loaded_context(instance)
        if loaded_context == target_context:
            print(f"   🧠 LM Studio contexto: {loaded_context} tokens ({self.model})")
            self._context_prepared = True
            return

        if instance and instance.get("id"):
            print(
                f"   🧠 Recargando LM Studio: contexto actual {loaded_context or '?'} → "
                f"{target_context} tokens"
            )
            self._post_native("/models/unload", {"instance_id": instance["id"]}, timeout=120)
        else:
            print(f"   🧠 Cargando LM Studio con contexto {target_context} tokens")

        model_id = self._load_model_id(info)
        if not model_id:
            raise RuntimeError(f"LM Studio no devolvió un identificador cargable para «{self.model}».")

        data = self._post_native(
            "/models/load",
            {
                "model": model_id,
                "context_length": target_context,
                "echo_load_config": True,
            },
        )
        instance_id = data.get("instance_id")
        if instance_id:
            self.model = instance_id
        actual_context = (data.get("load_config") or {}).get("context_length") or target_context
        print(f"   🧠 LM Studio listo: {actual_context} tokens ({self.model})")
        self._context_prepared = True

    def _apply_think_switch(self, prompt):
        """Qwen3-compatible soft switch for thinking mode.

        LM Studio exposes an OpenAI-compatible API, so we use Qwen's documented
        prompt switches instead of relying on server-specific request fields.
        """
        if self.think == "on":
            return f"{prompt}\n\n/think"
        if self.think == "off":
            return f"{prompt}\n\n/no_think"
        return prompt

    def _generate(self, system, prompt, use_search):
        self._ensure_context_loaded()
        prompt = self._apply_think_switch(prompt)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        headers = self._headers()

        delay = 5
        last = None
        for _ in range(3):
            try:
                resp = httpx.post(
                    f"{self.api_base}/chat/completions",
                    json=payload, headers=headers, timeout=600,
                )
                if resp.status_code == 404:
                    raise RuntimeError(f"LMStudio: Endpoint no encontrado (404) en {self.api_base}/chat/completions. Asegúrate de que el servidor local de LMStudio está encendido.")
                if resp.status_code in _RETRYABLE:
                    last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("error"):
                    raise RuntimeError(f"LMStudio devolvió un error: {data['error']}")
                text = (data["choices"][0]["message"].get("content") or "").strip()
                if not text:
                    raise RuntimeError("LMStudio devolvió una respuesta vacía")
                return text
            except httpx.ConnectError:
                raise RuntimeError(f"No se pudo conectar a LMStudio en {self.api_base}. Asegúrate de que el servidor local está iniciado.")
            except httpx.HTTPError as e:
                last = e
                time.sleep(delay)
                delay *= 2
        raise RuntimeError(f"LMStudio falló tras varios intentos: {last}")

    def list_models(self):
        try:
            models = self._get_native_models()
            if models:
                rows = []
                for info in models:
                    model_id = (
                        info.get("selected_variant")
                        or info.get("key")
                        or info.get("display_name")
                        or "?"
                    )
                    instance = (info.get("loaded_instances") or [None])[0]
                    loaded_context = self._loaded_context(instance)
                    native_context = info.get("max_context_length") or "?"
                    if loaded_context:
                        rows.append(f"{model_id} (ctx actual: {loaded_context}; nativo: {native_context})")
                    else:
                        rows.append(f"{model_id} (no cargado; nativo: {native_context})")
                return rows
        except Exception as e:
            print(f"   ⚠️  No se pudo consultar /api/v1/models en LM Studio: {e}")

        try:
            resp = httpx.get(f"{self.api_base}/models", timeout=10)
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json().get("data", [])]
            return ids
        except Exception as e:
            print(f"   ⚠️  No se pudieron listar los modelos de LMStudio: {e}")
            return [self.model]
