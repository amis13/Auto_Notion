#!/usr/bin/env python3
"""Restaura páginas de Notion desde un backup local.

Uso:
  # Restaurar todas las páginas de una carpeta de backup (bajo una ruta raíz)
  python restaurar.py backups/2026-07-07_220714 docs

  # Restaurar una sola página desde su archivo
  python restaurar.py backups/2026-07-07_220714/docs-Github.md docs/Github

Antes de restaurar, el contenido actual de cada página se guarda en
backups/<fecha>_pre-restauracion/ por si quieres volver atrás.
"""

import datetime
import sys
from pathlib import Path

from auto_notion import config
from auto_notion.blocks_to_md import blocks_to_md
from auto_notion.md_to_blocks import md_to_blocks
from auto_notion.notion_api import NotionAPI, looks_like_id_or_url
from auto_notion.pipeline import _collect, _slug


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    source = Path(sys.argv[1])
    route = sys.argv[2]
    if not source.exists():
        sys.exit(f"❌ No existe: {source}")

    config.validate()
    notion = NotionAPI(config.NOTION_TOKEN)

    print(f"🔍 Resolviendo ruta «{route}»…")
    page_id, title = notion.resolve(route)
    display = title if looks_like_id_or_url(route) else \
        "/".join(s.strip() for s in route.split("/") if s.strip())

    single_file = source.is_file()
    print("📚 Recopilando páginas…")
    entries = _collect(notion, page_id, display, recursive=not single_file)

    plan = []
    for entry in entries:
        file = source if single_file else source / f"{_slug(entry['path'])}.md"
        if file.exists():
            plan.append((entry, file))
        else:
            print(f"  (sin backup, se salta) {entry['path']}")

    if not plan:
        sys.exit("❌ Ningún archivo del backup coincide con las páginas de esa ruta.")

    print(f"\nSe restaurarán {len(plan)} página(s):")
    for entry, file in plan:
        print(f"  • {entry['path']}  ←  {file.name}")

    answer = input("\n¿Restaurar? El contenido actual se reemplaza (se guarda copia antes). [s/N]: ")
    if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
        print("Cancelado.")
        return

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    pre_dir = config.BACKUP_DIR / f"{stamp}_pre-restauracion"
    pre_dir.mkdir(parents=True, exist_ok=True)

    for idx, (entry, file) in enumerate(plan, 1):
        print(f"\n[{idx}/{len(plan)}] {entry['path']}")
        try:
            current_md = blocks_to_md(entry["tree"])
            (pre_dir / f"{_slug(entry['path'])}.md").write_text(current_md, encoding="utf-8")
            blocks = md_to_blocks(file.read_text(encoding="utf-8"))
            kept = notion.clear_page(entry["id"])
            if kept:
                print(f"   📎 {kept} bloque(s) conservados (subpáginas/archivos)")
            if blocks:
                notion.append_blocks(entry["id"], blocks)
            print("   ✅ Restaurada")
        except Exception as ex:
            print(f"   ❌ Error: {ex}")

    print(f"\nCopia del estado anterior en: {pre_dir.relative_to(config.ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
    except LookupError as e:
        sys.exit(f"❌ {e}")
