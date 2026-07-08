"""Orquestación: resolver ruta → leer → backup → plan → IA → revisar → actualizar Notion."""

import datetime
import json
import re

from . import config
from .agents import make_agent, resolve_provider
from .blocks_to_md import blocks_to_md
from .md_to_blocks import md_to_blocks
from .notion_api import NotionAPI, looks_like_id_or_url


def _slug(path):
    return re.sub(r"[^\w.\-]+", "-", path, flags=re.UNICODE).strip("-") or "pagina"


def _collect(notion, page_id, path, recursive):
    tree = notion.fetch_block_tree(page_id)
    entries = [{
        "id": page_id,
        "path": path,
        "title": path.rsplit("/", 1)[-1],
        "tree": tree,
        "md": blocks_to_md(tree),
    }]
    if recursive:
        for sub_id, sub_title in notion.child_pages(tree):
            entries += _collect(notion, sub_id, f"{path}/{sub_title}", True)
    return entries


def _build_map(entries, max_chars_per_page=3000):
    """Mapa completo de la sección para la pasada de planificación."""
    lines = ["## Rutas de la sección"]
    lines += [f"- {e['path']}" for e in entries]
    lines += ["", "## Contenido actual de cada página", ""]
    for e in entries:
        body = e["md"].strip() or "(página vacía)"
        if len(body) > max_chars_per_page:
            body = body[:max_chars_per_page] + "\n… (contenido recortado para el plan)"
        lines += [f"### {e['path']}", "", body, ""]
    return "\n".join(lines)


def _update_manifest(backup_dir, filename, entry):
    """Apunta en manifest.json qué página corresponde a cada archivo del backup."""
    manifest_path = backup_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[filename] = {"page_id": entry["id"], "path": entry["path"]}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def run(route, dry_run=False, recursive=True, assume_yes=False,
        model=None, use_search=True, instructions=None, review=True, provider=None,
        plan=True):
    provider = resolve_provider(model, provider)
    config.validate(provider=provider)
    notion = NotionAPI(config.NOTION_TOKEN)
    agent = make_agent(model, use_search=use_search, provider=provider)

    print(f"🔍 Resolviendo ruta «{route}»…")
    page_id, title = notion.resolve(route)
    if looks_like_id_or_url(route):
        display = title
    else:
        display = "/".join(s.strip() for s in route.split("/") if s.strip())

    print("📚 Recopilando páginas…")
    entries = _collect(notion, page_id, display, recursive)

    print(f"\nPáginas a procesar ({len(entries)}):")
    for e in entries:
        print(f"  • {e['path']}")
    if instructions:
        print(f"\n🎯 Instrucciones extra ({agent.model}): {instructions}")

    if dry_run:
        print("\nModo --dry-run: Notion NO se modificará; el resultado se guarda en preview/.")
    elif not assume_yes:
        answer = input(
            f"\n¿Actualizar estas {len(entries)} página(s) en Notion? "
            "Su contenido actual se reemplazará (queda backup local). [s/N]: "
        )
        if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado.")
            return

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_dir = config.BACKUP_DIR / stamp
    ok, skipped, failed = [], [], []

    # Pasada de planificación: la IA ve el mapa completo antes de tocar nada.
    context = None
    if plan and len(entries) > 1:
        print(f"\n🗺️  Generando plan editorial global ({len(entries)} páginas)…")
        try:
            plan_text = agent.plan(_build_map(entries), instructions=instructions)
            backup_dir.mkdir(parents=True, exist_ok=True)
            plan_file = backup_dir / "_plan.md"
            plan_file.write_text(plan_text + "\n", encoding="utf-8")
            print(f"   📋 Plan guardado en {plan_file.relative_to(config.ROOT)}")
            routes = "\n".join(f"- {e['path']}" for e in entries)
            context = f"Páginas de la sección:\n{routes}\n\nPlan editorial:\n{plan_text}"
        except Exception as ex:
            print(f"   ⚠️  No se pudo generar el plan ({ex}); se continúa sin él.")

    for idx, entry in enumerate(entries, 1):
        print(f"\n[{idx}/{len(entries)}] {entry['path']}")
        try:
            result = _process(notion, agent, entry, backup_dir, stamp, dry_run,
                              instructions, review, context)
            (ok if result else skipped).append(entry["path"])
        except Exception as ex:  # una página fallida no detiene el resto
            failed.append((entry["path"], ex))
            print(f"   ❌ Error: {ex}")

    print("\n" + "─" * 50)
    print(f"Resumen → ✅ {len(ok)} completadas · ⚠️ {len(skipped)} omitidas · ❌ {len(failed)} con error")
    for p, ex in failed:
        print(f"   ❌ {p}: {ex}")
    if dry_run and ok:
        print(f"\nRevisa preview/{stamp}/ y, si te convence, ejecuta sin --dry-run para aplicarlo.")


def _process(notion, agent, entry, backup_dir, stamp, dry_run, instructions, review, context=None):
    md = entry["md"]

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{_slug(entry['path'])}.md"
    backup_file.write_text(md, encoding="utf-8")
    _update_manifest(backup_dir, backup_file.name, entry)
    print(f"   💾 Backup: {backup_file.relative_to(config.ROOT)}")

    if not md.strip() and not instructions:
        print("   ⚠️  Página sin contenido de texto; se omite.")
        return False
    if not md.strip():
        md = "(La página está vacía: genera el contenido desde cero según las instrucciones.)\n"

    print(f"   🤖 {agent.model} mejorando redacción y datos…")
    improved = agent.improve(entry["title"], entry["path"], md,
                             instructions=instructions, context=context)

    if review:
        print("   🔎 Revisando el borrador (formato, meta-comentarios, código)…")
        improved = agent.review(entry["title"], entry["path"], improved, instructions=instructions)

    if dry_run:
        out = config.PREVIEW_DIR / stamp / f"{_slug(entry['path'])}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(improved + "\n", encoding="utf-8")
        print(f"   📝 Vista previa: {out.relative_to(config.ROOT)}")
        return True

    blocks = md_to_blocks(improved)
    print(f"   ✍️  Actualizando Notion ({len(blocks)} bloques)…")
    kept = notion.clear_page(entry["id"])
    if kept:
        print(f"   📎 {kept} bloque(s) conservados (subpáginas, bases de datos o archivos subidos) "
              "quedan al inicio de la página.")
    notion.append_blocks(entry["id"], blocks)
    print("   ✅ Página actualizada")
    return True
