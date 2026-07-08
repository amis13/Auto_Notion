#!/usr/bin/env python3
"""Sube archivos Markdown de new_pages/ a Notion como páginas nuevas.

Cada «# Título» (H1) del archivo abre una página nueva con ese título; el contenido
hasta el siguiente H1 es el cuerpo de la página (admite todo el Markdown extendido:
callouts, toggles, columnas, ecuaciones, media…). Si el archivo no tiene ningún H1,
se crea una sola página con el nombre del archivo.

Uso:
  python subir.py new_pages/guia.md docs         # sube las páginas del archivo bajo «docs»
  python subir.py new_pages docs                 # todos los .md de la carpeta
  python subir.py new_pages/guia.md docs --mejorar   # la IA mejora cada página antes de subir

Opciones: --mejorar, --proveedor, --modelo, --sin-busqueda, -y/--si
"""

import argparse
import re
import sys
from pathlib import Path

from auto_notion import config
from auto_notion.md_to_blocks import md_to_blocks
from auto_notion.notion_api import NotionAPI, looks_like_id_or_url

_H1 = re.compile(r"^#\s+(.+)$")
_FENCE = re.compile(r"^\s*```")


def split_pages(md, fallback_title):
    """Parte un Markdown en [(título, contenido)] usando los H1 como divisores.
    Respeta los bloques de código (un «# comentario» dentro de ``` no divide)."""
    pages = []
    title, buf = None, []
    in_fence = False
    for line in md.replace("\r\n", "\n").split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        h1 = None if in_fence else _H1.match(line.strip())
        if h1:
            if title is not None or any(l.strip() for l in buf):
                pages.append((title or fallback_title, "\n".join(buf).strip()))
            title, buf = h1.group(1).strip(), []
        else:
            buf.append(line)
    if title is not None or any(l.strip() for l in buf):
        pages.append((title or fallback_title, "\n".join(buf).strip()))
    return pages


def main():
    parser = argparse.ArgumentParser(
        description="Sube archivos Markdown como páginas nuevas de Notion (H1 = nueva página).",
    )
    parser.add_argument("origen", help="Archivo .md o carpeta con archivos .md (ej. new_pages)")
    parser.add_argument("destino", help="Ruta de la página padre en Notion (ej. docs), URL o ID")
    parser.add_argument("--mejorar", action="store_true",
                        help="Pasa cada página por la IA (mejora + revisión) antes de subirla")
    parser.add_argument("--proveedor", choices=["gemini", "gemini-cli", "codex", "claude", "openrouter"])
    parser.add_argument("--modelo", metavar="NOMBRE")
    parser.add_argument("--sin-busqueda", dest="search", action="store_false")
    parser.add_argument("-y", "--si", "--yes", dest="yes", action="store_true",
                        help="No pedir confirmación")
    args = parser.parse_args()

    origen = Path(args.origen)
    if not origen.exists():
        sys.exit(f"❌ No existe: {origen}")
    files = sorted(origen.glob("*.md")) if origen.is_dir() else [origen]
    files = [f for f in files if not f.name.startswith("_")]  # _plantilla.md etc. se ignoran
    if not files:
        sys.exit(f"❌ No hay archivos .md en {origen} (los que empiezan por «_» se ignoran)")

    from auto_notion.agents import make_agent, resolve_provider
    provider = resolve_provider(args.modelo, args.proveedor)
    config.validate(provider=provider if args.mejorar else None)
    notion = NotionAPI(config.NOTION_TOKEN)

    print(f"🔍 Resolviendo destino «{args.destino}»…")
    parent_id, parent_title = notion.resolve(args.destino)
    display = parent_title if looks_like_id_or_url(args.destino) else args.destino

    plan = []
    for f in files:
        for title, body in split_pages(f.read_text(encoding="utf-8"), f.stem):
            plan.append((f, title, body))
    if not plan:
        sys.exit("❌ Los archivos están vacíos.")

    print(f"\nSe crearán {len(plan)} página(s) nuevas bajo «{display}»:")
    for f, title, body in plan:
        extra = " (+ mejora IA)" if args.mejorar else ""
        print(f"  • {display}/{title}  ←  {f.name}{extra}")

    if not args.yes:
        answer = input(f"\n¿Crear estas {len(plan)} página(s) en Notion? [s/N]: ")
        if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado.")
            return

    agent = None
    if args.mejorar:
        agent = make_agent(args.modelo, use_search=args.search, provider=provider)
        print(f"🤖 Mejorando con {agent.model} antes de subir…")

    ok, failed = 0, []
    for idx, (f, title, body) in enumerate(plan, 1):
        print(f"\n[{idx}/{len(plan)}] {display}/{title}")
        try:
            md = body
            if agent and md.strip():
                print("   🤖 Mejorando…")
                md = agent.improve(title, f"{display}/{title}", md)
                print("   🔎 Revisando…")
                md = agent.review(title, f"{display}/{title}", md)
            blocks = md_to_blocks(md) if md.strip() else []
            print(f"   ✍️  Creando página ({len(blocks)} bloques)…")
            notion.create_page(parent_id, title, blocks)
            print("   ✅ Creada")
            ok += 1
        except Exception as ex:
            failed.append((title, ex))
            print(f"   ❌ Error: {ex}")

    print("\n" + "─" * 50)
    print(f"Resumen → ✅ {ok} creadas · ❌ {len(failed)} con error")
    for t, ex in failed:
        print(f"   ❌ {t}: {ex}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
    except LookupError as e:
        sys.exit(f"❌ {e}")
