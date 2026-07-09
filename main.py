#!/usr/bin/env python3
"""Auto Notion: mejora páginas de Notion con IA (redacción + investigación).

Ejemplos:
  python main.py "web/docs/Web3"
  python main.py "web/docs/Web3" --prompt "añade una sección sobre wallets y una guía de seguridad"
  python main.py "web/docs/Web3" --dry-run
  python main.py "web/docs" --excluir docs/Archivo --excluir "docs/Notas internas"
  python main.py --listar-modelos
"""

import argparse
import sys

from auto_notion import config
from auto_notion.pipeline import run


def main():
    parser = argparse.ArgumentParser(
        description="Mejora la redacción, los datos y el formato de páginas de Notion usando IA "
                    "(Gemini, Codex, Claude, OpenRouter o LM Studio).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 1)[1],
    )
    parser.add_argument(
        "ruta", nargs="?",
        help="Ruta de la página, ej. web/docs/Web3 (también vale una URL o un ID de Notion)",
    )
    parser.add_argument(
        "-p", "--prompt", metavar="TEXTO",
        help="Instrucciones extra para la IA, ej. \"añade una guía para X\" o \"mete secciones para X\"",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="No modifica Notion; guarda el resultado propuesto en preview/",
    )
    parser.add_argument(
        "--no-recursivo", dest="recursive", action="store_false",
        help="Procesa solo la página indicada, sin sus subpáginas",
    )
    parser.add_argument(
        "-e", "--excluir", "--exclude", dest="exclude", action="append", metavar="RUTA",
        help="Excluye una subpágina y todo su subárbol, ej. --excluir docs/x. "
             "Repetible para excluir varias",
    )
    parser.add_argument(
        "-y", "--si", "--yes", dest="yes", action="store_true",
        help="No pedir confirmación antes de actualizar",
    )
    parser.add_argument(
        "--modelo", metavar="NOMBRE",
        help=f"Modelo a usar (Gemini: {config.GEMINI_MODEL}; OpenRouter: {config.OPENROUTER_MODEL}). "
             "Un modelo con «/» (ej. openai/gpt-5.5) activa OpenRouter automáticamente",
    )
    parser.add_argument(
        "--proveedor", choices=["gemini", "gemini-cli", "codex", "claude", "openrouter", "lmstudio"],
        help=f"Proveedor LLM (por defecto: {config.LLM_PROVIDER}, de .env). "
             "gemini-cli, codex y claude usan tu cuenta. lmstudio usa servidor local.",
    )
    parser.add_argument(
        "--sin-busqueda", dest="search", action="store_false",
        help="Desactiva la búsqueda web (grounding con Google Search)",
    )
    parser.add_argument(
        "--sin-revision", dest="review", action="store_false",
        help="Omite el paso de revisión del borrador antes de publicar (más rápido, menos fiable)",
    )
    parser.add_argument(
        "--sin-plan", dest="plan", action="store_false",
        help="Omite el plan editorial global previo (la IA no verá el mapa de la sección)",
    )
    parser.add_argument(
        "--think", choices=["auto", "on", "off"],
        help="Controla thinking en modelos locales compatibles tipo Qwen vía LM Studio "
             "(/think o /no_think). Por defecto: LMSTUDIO_THINK en .env.",
    )
    parser.add_argument(
        "--lm-context", metavar="native|loaded|N",
        help="Solo LM Studio: contexto al cargar el modelo. native/max usa max_context_length "
             "del modelo; loaded conserva la carga actual; N fuerza un número de tokens. "
             "Por defecto: LMSTUDIO_CONTEXT_LENGTH.",
    )
    parser.add_argument(
        "--lm-max-tokens", type=int, metavar="N",
        help="Solo LM Studio: max_tokens para la respuesta. Útil con páginas largas y reasoning.",
    )
    parser.add_argument(
        "--listar-modelos", action="store_true",
        help="Lista los modelos disponibles del proveedor activo y sale",
    )
    args = parser.parse_args()

    try:
        if args.listar_modelos:
            from auto_notion.agents import make_agent, resolve_provider
            provider = resolve_provider(args.modelo, args.proveedor)
            config.validate(require_notion=False, provider=provider)
            agent = make_agent(
                args.modelo,
                provider=provider,
                think=args.think,
                lm_context=args.lm_context,
                lm_max_tokens=args.lm_max_tokens,
            )
            print(f"Modelos disponibles ({provider}):")
            for name in agent.list_models():
                print(f"  • {name}")
            return

        route = args.ruta or input("Ruta de la página en Notion (ej. web/docs/Web3): ").strip()
        if not route:
            sys.exit("No se indicó ninguna ruta.")

        instructions = args.prompt
        if instructions is None and args.ruta is None:
            # Modo interactivo: ofrecer instrucciones opcionales.
            instructions = input(
                "Instrucciones extra para la IA (opcional, Enter para omitir): "
            ).strip() or None

        run(
            route,
            dry_run=args.dry_run,
            recursive=args.recursive,
            assume_yes=args.yes,
            model=args.modelo,
            use_search=args.search,
            instructions=instructions,
            review=args.review,
            provider=args.proveedor,
            plan=args.plan,
            exclude=args.exclude,
            think=args.think,
            lm_context=args.lm_context,
            lm_max_tokens=args.lm_max_tokens,
        )
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
    except LookupError as e:
        sys.exit(f"❌ {e}")


if __name__ == "__main__":
    main()
