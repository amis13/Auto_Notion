"""Selección de proveedor LLM: Gemini API, Gemini CLI, Codex CLI, Claude CLI u OpenRouter."""

from . import config
from .claude_agent import ClaudeCliAgent
from .codex_agent import CodexCliAgent
from .gemini_agent import GeminiAgent
from .gemini_cli_agent import GeminiCliAgent
from .openrouter_agent import OpenRouterAgent
from .lmstudio_agent import LMStudioAgent

PROVIDERS = ("gemini", "gemini-cli", "codex", "claude", "openrouter", "lmstudio")


def resolve_provider(model=None, provider=None):
    """Proveedor efectivo: flag explícito > modelo con «/» (estilo OpenRouter) > .env."""
    if provider:
        return provider
    if model and "/" in model:
        return "openrouter"
    return config.LLM_PROVIDER


def make_agent(model=None, use_search=True, provider=None, think=None,
               lm_context=None, lm_max_tokens=None):
    provider = resolve_provider(model, provider)
    if provider == "lmstudio":
        return LMStudioAgent(
            config.LMSTUDIO_API_BASE,
            model or config.LMSTUDIO_MODEL,
            use_search=use_search,
            think=think or config.LMSTUDIO_THINK,
            context_length=lm_context or config.LMSTUDIO_CONTEXT_LENGTH,
            max_tokens=lm_max_tokens or config.LMSTUDIO_MAX_TOKENS,
            api_token=config.LMSTUDIO_API_TOKEN,
        )
    if provider == "openrouter":
        return OpenRouterAgent(
            config.OPENROUTER_API_KEY, model or config.OPENROUTER_MODEL, use_search=use_search
        )
    if provider == "gemini-cli":
        return GeminiCliAgent(model or config.GEMINI_CLI_MODEL, use_search=use_search)
    if provider == "codex":
        return CodexCliAgent(model or config.CODEX_MODEL, use_search=use_search)
    if provider == "claude":
        return ClaudeCliAgent(model or config.CLAUDE_MODEL, use_search=use_search)
    if provider == "gemini":
        return GeminiAgent(
            config.GEMINI_API_KEY, model or config.GEMINI_MODEL, use_search=use_search
        )
    raise ValueError(f"Proveedor desconocido: «{provider}». Usa uno de: {', '.join(PROVIDERS)}")
