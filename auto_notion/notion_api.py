"""Cliente de la API de Notion: rutas tipo web/docs/Web3, lectura y escritura de bloques."""

import re
import time

from notion_client import Client
from notion_client.errors import APIResponseError, HTTPResponseError, RequestTimeoutError

# Bloques cuyo contenido pertenece a otra página: no se recorre hacia dentro.
NO_RECURSE = {"child_page", "child_database", "unsupported"}

# Bloques multimedia: si el archivo está subido a Notion (type == "file"),
# se conservan al reescribir la página porque sus URLs firmadas caducan.
MEDIA_TYPES = {"image", "video", "file", "pdf", "audio"}

_ID_RE = re.compile(r"[0-9a-f]{32}")


def page_title(page):
    """Título de un objeto page de la API."""
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return "(sin título)"


def looks_like_id_or_url(text):
    text = text.strip()
    if "notion.so" in text or text.lower().startswith(("http://", "https://")):
        return True
    return bool(re.fullmatch(r"[0-9a-fA-F-]{32,36}", text))


class NotionAPI:
    def __init__(self, token):
        self.client = Client(auth=token)

    # ------------------------------------------------------------------ retry

    def _call(self, fn, **kwargs):
        delay = 1.0
        last = None
        for _ in range(6):
            try:
                return fn(**kwargs)
            except APIResponseError as e:
                last = e
                status = getattr(e, "status", 0) or 0
                if e.code == "rate_limited" or status >= 500:
                    headers = getattr(e, "headers", None) or {}
                    retry_after = headers.get("retry-after")
                    time.sleep(float(retry_after) if retry_after else delay)
                    delay = min(delay * 2, 30)
                    continue
                raise
            except (HTTPResponseError, RequestTimeoutError) as e:
                last = e
                time.sleep(delay)
                delay = min(delay * 2, 30)
        raise RuntimeError(f"Notion no respondió tras varios reintentos: {last}")

    # ---------------------------------------------------------------- lectura

    def list_children(self, block_id):
        out, cursor = [], None
        while True:
            kwargs = {"block_id": block_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self._call(self.client.blocks.children.list, **kwargs)
            out.extend(resp.get("results", []))
            if not resp.get("has_more"):
                return out
            cursor = resp.get("next_cursor")

    def fetch_block_tree(self, block_id):
        """Bloques de una página con sus hijos anidados en «_children» (sin entrar en subpáginas)."""
        blocks = self.list_children(block_id)
        for b in blocks:
            if b.get("has_children") and b.get("type") not in NO_RECURSE:
                b["_children"] = self.fetch_block_tree(b["id"])
        return blocks

    def child_pages(self, block_tree):
        """Subpáginas (id, título) en orden de aparición, a cualquier profundidad."""
        found = []

        def walk(blocks):
            for b in blocks:
                if b.get("type") == "child_page":
                    found.append((b["id"], b["child_page"].get("title", "(sin título)")))
                else:
                    walk(b.get("_children") or [])

        walk(block_tree)
        return found

    # ------------------------------------------------------------------ rutas

    def resolve(self, route):
        """Resuelve una ruta «web/docs/Web3», una URL o un ID. Devuelve (page_id, título)."""
        route = route.strip()
        if looks_like_id_or_url(route):
            m = _ID_RE.search(route.lower()) or _ID_RE.search(route.lower().replace("-", ""))
            if not m:
                raise LookupError(f"No se pudo extraer un ID de página de «{route}»")
            page = self._call(self.client.pages.retrieve, page_id=m.group(0))
            return page["id"], page_title(page)

        segments = [s.strip() for s in route.split("/") if s.strip()]
        if not segments:
            raise LookupError("La ruta está vacía")

        current_id, current_title = self._search_page(segments[0])
        for seg in segments[1:]:
            current_id, current_title = self._find_child(current_id, current_title, seg)
        return current_id, current_title

    def _search_page(self, name):
        cursor = None
        exact = []
        while True:
            kwargs = {
                "query": name,
                "filter": {"value": "page", "property": "object"},
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self._call(self.client.search, **kwargs)
            for page in resp.get("results", []):
                if page.get("object") != "page" or page.get("archived"):
                    continue
                title = page_title(page)
                if title.casefold() == name.casefold():
                    exact.append((page["id"], title))
            if exact or not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        if not exact:
            raise LookupError(
                f"No se encontró ninguna página llamada «{name}». "
                "Comprueba el nombre y que la página esté compartida con la integración "
                "(··· → Conexiones → tu integración)."
            )
        if len(exact) > 1:
            print(f"   ⚠️  Hay {len(exact)} páginas llamadas «{name}»; se usa la primera. "
                  "Si no es la correcta, pasa la URL de la página.")
        return exact[0]

    def _find_child(self, parent_id, parent_title, name):
        tree = self.fetch_block_tree(parent_id)
        subpages = self.child_pages(tree)
        for sub_id, sub_title in subpages:
            if sub_title.casefold() == name.casefold():
                return sub_id, sub_title
        available = ", ".join(t for _, t in subpages) or "(ninguna)"
        raise LookupError(
            f"«{parent_title}» no tiene ninguna subpágina llamada «{name}». "
            f"Subpáginas disponibles: {available}"
        )

    # --------------------------------------------------------------- escritura

    def clear_page(self, page_id):
        """Borra el contenido de la página conservando subpáginas, bases de datos
        y archivos subidos a Notion. Devuelve cuántos bloques se conservaron."""
        kept = 0
        for b in self.list_children(page_id):
            t = b.get("type")
            data = b.get(t) or {}
            preserve = t in ("child_page", "child_database") or (
                t in MEDIA_TYPES and data.get("type") == "file"
            )
            if preserve:
                kept += 1
            else:
                self._call(self.client.blocks.delete, block_id=b["id"])
        return kept

    def append_blocks(self, page_id, blocks, batch=50):
        for i in range(0, len(blocks), batch):
            self._call(
                self.client.blocks.children.append,
                block_id=page_id,
                children=blocks[i : i + batch],
            )

    def replace_page_content(self, page_id, new_blocks):
        children = self.list_children(page_id)
        preserved_ids = set()
        anchor_id = None
        blocks_to_delete = []

        for i, b in enumerate(children):
            t = b.get("type")
            data = b.get(t) or {}
            is_preserved = t in ("child_page", "child_database") or (
                t in MEDIA_TYPES and data.get("type") == "file"
            )
            if is_preserved:
                preserved_ids.add(b["id"])
            else:
                if anchor_id is None:
                    anchor_id = b["id"]
                else:
                    blocks_to_delete.append(b["id"])

        for b_id in blocks_to_delete:
            self._call(self.client.blocks.delete, block_id=b_id)

        current_after_id = anchor_id
        if current_after_id is None and children:
            current_after_id = children[0]["id"]

        batch = []
        
        def flush_batch():
            nonlocal current_after_id, batch
            if not batch: return
            for i in range(0, len(batch), 50):
                kwargs = {"block_id": page_id, "children": batch[i : i + 50]}
                if current_after_id:
                    kwargs["after"] = current_after_id
                resp = self._call(self.client.blocks.children.append, **kwargs)
                if resp.get("results"):
                    current_after_id = resp["results"][-1]["id"]
            batch = []

        for nb in new_blocks:
            if nb.get("type") == "_preserve":
                flush_batch()
                p_id = nb["_preserve"]["id"]
                if p_id in preserved_ids:
                    current_after_id = p_id
            else:
                batch.append(nb)
        
        flush_batch()

        if anchor_id:
            self._call(self.client.blocks.delete, block_id=anchor_id)
        
        return len(preserved_ids)

    def create_page(self, parent_id, title, blocks=None):
        """Crea una subpágina bajo parent_id y devuelve su id."""
        blocks = blocks or []
        page = self._call(
            self.client.pages.create,
            parent={"page_id": parent_id},
            properties={"title": {"title": [{"type": "text", "text": {"content": title}}]}},
            children=blocks[:50],
        )
        if len(blocks) > 50:
            self.append_blocks(page["id"], blocks[50:])
        return page["id"]
