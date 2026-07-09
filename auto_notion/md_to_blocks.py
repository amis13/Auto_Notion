"""Convierte Markdown extendido a bloques de la API de Notion.

Sintaxis soportada además del Markdown estándar:
  > [!💡] texto              → callout (también [!NOTE], [!TIP], [!WARNING]…, y |color)
  +++ Título … +++           → toggle (bloque plegable)
  ::: columns / ::: column   → columnas
  $$ expresión $$            → ecuación en bloque (KaTeX); $inline$ en texto
  ![video](url) ![audio](url) ![pdf](url) ![file](url) ![embed](url)
  [toc]                      → índice de la página
  URL sola en una línea      → tarjeta bookmark
  __subrayado__  ==resaltado==
"""

import re

# Lenguajes que acepta la API de Notion en bloques de código (subconjunto habitual).
NOTION_LANGS = {
    "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript", "c++", "c#",
    "css", "dart", "diff", "docker", "elixir", "erlang", "flow", "fortran", "f#",
    "gherkin", "glsl", "go", "graphql", "groovy", "haskell", "html", "java",
    "javascript", "json", "julia", "kotlin", "latex", "less", "lisp", "lua",
    "makefile", "markdown", "markup", "matlab", "mermaid", "nix", "objective-c",
    "ocaml", "pascal", "perl", "php", "plain text", "powershell", "prolog",
    "protobuf", "python", "r", "ruby", "rust", "sass", "scala", "scheme", "scss",
    "shell", "solidity", "sql", "swift", "typescript", "vb.net", "verilog", "vhdl",
    "visual basic", "webassembly", "xml", "yaml",
}
LANG_ALIASES = {
    "js": "javascript", "jsx": "javascript", "node": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "py": "python", "sh": "shell", "zsh": "shell", "console": "shell",
    "yml": "yaml", "cpp": "c++", "cs": "c#", "golang": "go", "rb": "ruby",
    "dockerfile": "docker", "md": "markdown", "plaintext": "plain text",
    "text": "plain text", "txt": "plain text", "": "plain text",
}

# Colores válidos de la API (texto y fondo).
NOTION_COLORS = {
    "default", "gray", "brown", "orange", "yellow", "green", "blue", "purple",
    "pink", "red", "gray_background", "brown_background", "orange_background",
    "yellow_background", "green_background", "blue_background",
    "purple_background", "pink_background", "red_background",
}

# Admonitions tipo GitHub → (emoji, color de callout).
ADMONITIONS = {
    "note": ("💡", "blue_background"),
    "info": ("ℹ️", "blue_background"),
    "tip": ("✅", "green_background"),
    "success": ("✅", "green_background"),
    "important": ("⭐", "purple_background"),
    "question": ("❓", "purple_background"),
    "warning": ("⚠️", "yellow_background"),
    "caution": ("🚨", "red_background"),
    "danger": ("🚨", "red_background"),
    "error": ("❌", "red_background"),
    "example": ("📝", "gray_background"),
}

MEDIA_KEYWORDS = {
    "video": "video", "vídeo": "video",
    "audio": "audio",
    "pdf": "pdf",
    "file": "file", "archivo": "file",
    "embed": "embed",
}

_MAX_TEXT = 2000

_FENCE_OPEN = re.compile(r"^\s*```\s*([^`]*?)\s*$")
_FENCE_CLOSE = re.compile(r"^\s*```\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST = re.compile(r"^(\s*)(?:([-*+])|(\d+)[.)])\s+(.*)$")
_TODO = re.compile(r"^\[([ xX])\]\s+(.*)$")
_HR = re.compile(r"^ {0,3}(-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE = re.compile(r"^ {0,3}>\s?(.*)$")
_CALLOUT_HEAD = re.compile(r"^\[!([^\]|]+?)(?:\|([a-z_]+))?\]\s*(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_IMG_LINE = re.compile(r"^!\[([^\]]*)\]\((\S+?)(?:\s+\"[^\"]*\")?\)\s*$")
_TOGGLE_OPEN = re.compile(r"^\+\+\+\s+(.+)$")
_TOGGLE_CLOSE = re.compile(r"^\+\+\+\s*$")
_COLS_OPEN = re.compile(r"^:::\s*column(?:s|as)\s*$", re.IGNORECASE)
_COL_SEP = re.compile(r"^:::\s*column(?:a)?\s*$", re.IGNORECASE)
_COLS_CLOSE = re.compile(r"^:::\s*$")
# Marcadores huérfanos (::: o +++ fuera de contexto, incluso varios juntos): se descartan.
_ORPHAN_MARKER = re.compile(r"^(?::{3,}\s*)+$")
_ASIDE_OPEN = re.compile(r"^<aside>\s*$", re.IGNORECASE)
_ASIDE_CLOSE = re.compile(r"^</aside>\s*$", re.IGNORECASE)
_BARE_URL = re.compile(r"^https?://\S+$")
_TOC = re.compile(r"^\[toc\]$", re.IGNORECASE)
_EQ_LINE = re.compile(r"^\$\$\s*(.+?)\s*\$\$$")

_INLINE = re.compile(
    r"(?P<code>`(?P<code_text>[^`]+)`)"
    r"|(?P<bi>\*\*\*(?P<bi_text>.+?)\*\*\*)"
    r"|(?P<b>\*\*(?P<b_text>.+?)\*\*)"
    r"|(?P<u>__(?P<u_text>.+?)__)"
    r"|(?P<i>(?<!\*)\*(?P<i_text>[^*]+?)\*(?!\*))"
    r"|(?P<iu>(?<![\w_])_(?P<iu_text>[^_]+?)_(?![\w_]))"
    r"|(?P<s>~~(?P<s_text>.+?)~~)"
    r"|(?P<hl>==(?P<hl_text>.+?)==)"
    r"|(?P<ieq>\$(?P<ieq_text>(?=\S)[^$\n]+?(?<=\S))\$)"
    r"|(?P<img>!\[(?P<img_alt>[^\]]*)\]\((?P<img_url>[^)\s]+)(?:\s+\"[^\"]*\")?\))"
    r"|(?P<link>\[(?P<l_text>[^\]]+)\]\((?P<l_url>[^)\s]+)(?:\s+\"[^\"]*\")?\))",
    re.DOTALL,
)


def _norm_lang(lang):
    lang = (lang or "").strip().lower()
    lang = LANG_ALIASES.get(lang, lang)
    return lang if lang in NOTION_LANGS else "plain text"


def _norm_color(color, default="default"):
    color = (color or "").strip().lower()
    return color if color in NOTION_COLORS else default


def _rt(content, ann=None, href=None):
    """Objetos rich_text de Notion, troceados al límite de 2000 caracteres."""
    if not content:
        return []
    ann = {k: v for k, v in (ann or {}).items() if v and v != "default"}
    out = []
    for i in range(0, len(content), _MAX_TEXT):
        obj = {"type": "text", "text": {"content": content[i : i + _MAX_TEXT]}}
        if href and href.startswith(("http://", "https://")):
            obj["text"]["link"] = {"url": href}
        if ann:
            obj["annotations"] = dict(ann)
        out.append(obj)
    return out


def parse_inline(text, ann=None, href=None):
    ann = ann or {}
    out = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out += _rt(text[pos : m.start()], ann, href)
        if m.group("code"):
            out += _rt(m.group("code_text"), {**ann, "code": True}, href)
        elif m.group("bi"):
            out += parse_inline(m.group("bi_text"), {**ann, "bold": True, "italic": True}, href)
        elif m.group("b"):
            out += parse_inline(m.group("b_text"), {**ann, "bold": True}, href)
        elif m.group("u"):
            out += parse_inline(m.group("u_text"), {**ann, "underline": True}, href)
        elif m.group("i"):
            out += parse_inline(m.group("i_text"), {**ann, "italic": True}, href)
        elif m.group("iu"):
            out += parse_inline(m.group("iu_text"), {**ann, "italic": True}, href)
        elif m.group("s"):
            out += parse_inline(m.group("s_text"), {**ann, "strikethrough": True}, href)
        elif m.group("hl"):
            out += parse_inline(m.group("hl_text"), {**ann, "color": "yellow_background"}, href)
        elif m.group("ieq"):
            eq = {"type": "equation", "equation": {"expression": m.group("ieq_text")}}
            clean = {k: v for k, v in ann.items() if v and v != "default"}
            if clean:
                eq["annotations"] = clean
            out.append(eq)
        elif m.group("img"):
            out += _rt(m.group("img_alt") or "imagen", ann, m.group("img_url"))
        elif m.group("link"):
            out += parse_inline(m.group("l_text"), ann, m.group("l_url"))
        pos = m.end()
    if pos < len(text):
        out += _rt(text[pos:], ann, href)
    return out


def _node(t, data):
    return {"type": t, t: data}


def _clamp_depth(nodes, depth=0, max_depth=2):
    """La API admite dos niveles de anidamiento por petición; lo más profundo se aplana."""
    out = []
    for nd in nodes:
        kids = nd.pop("_children", None)
        out.append(nd)
        if kids:
            clamped = _clamp_depth(kids, depth + 1, max_depth)
            if depth < max_depth:
                nd["_children"] = clamped
            else:
                out.extend(clamped)
    return out


def _serialize(nodes):
    out = []
    for nd in nodes:
        t = nd["type"]
        data = dict(nd[t])
        kids = nd.get("_children")
        if kids:
            data["children"] = _serialize(kids)
        out.append({"object": "block", "type": t, t: data})
    return out


def _split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def _scan_block(lines, i, close_re, sep_re=None):
    """Avanza desde `i` hasta la línea que cierra (respetando fences ```).
    Devuelve (segmentos, índice tras el cierre). Los segmentos se parten en sep_re."""
    segments, current = [], []
    in_fence = False
    n = len(lines)
    while i < n:
        line = lines[i]
        if _FENCE_OPEN.match(line) if not in_fence else _FENCE_CLOSE.match(line):
            in_fence = not in_fence
            current.append(line)
            i += 1
            continue
        if not in_fence:
            if close_re.match(line.strip()):
                segments.append(current)
                return segments, i + 1
            if sep_re and sep_re.match(line.strip()):
                segments.append(current)
                current = []
                i += 1
                continue
        current.append(line)
        i += 1
    segments.append(current)  # sin cierre explícito: hasta el final
    return segments, i


def _hoist_tables(children):
    """Las tablas no pueden ir dentro de columnas (exceden el anidamiento): se extraen."""
    kept, hoisted = [], []
    for nd in children:
        (hoisted if nd["type"] == "table" else kept).append(nd)
    return kept, hoisted


def _parse_callout_head(content):
    m = _CALLOUT_HEAD.match(content)
    if not m:
        return None
    token, color, rest = m.group(1).strip(), m.group(2), m.group(3)
    key = token.lower()
    if key in ADMONITIONS:
        emoji, default_color = ADMONITIONS[key]
    elif token and not (token.isascii() and token.isalnum()):
        emoji, default_color = token, "default"  # emoji personalizado
    else:
        emoji, default_color = "💡", "default"
    return emoji, _norm_color(color, default_color), rest


def _parse_blocks(lines):
    blocks = []
    stack = []  # [(indent, nodo)] para listas anidadas
    para = []
    quote = []          # líneas de cita o callout
    quote_meta = None   # None = cita; (emoji, color) = callout

    def flush_para():
        nonlocal para
        if para:
            text = " ".join(para).strip()
            if text:
                blocks.append(_node("paragraph", {"rich_text": parse_inline(text)}))
            para = []

    def flush_quote():
        nonlocal quote, quote_meta
        if quote:
            rt = []
            for j, q in enumerate(quote):
                if j:
                    rt.append({"type": "text", "text": {"content": "\n"}})
                rt.extend(parse_inline(q))
            if rt:
                if quote_meta:
                    emoji, color = quote_meta
                    blocks.append(_node("callout", {
                        "rich_text": rt,
                        "icon": {"type": "emoji", "emoji": emoji},
                        "color": color,
                    }))
                else:
                    blocks.append(_node("quote", {"rich_text": rt}))
            quote = []
        quote_meta = None

    def flush_all():
        flush_para()
        flush_quote()
        stack.clear()

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        fence = _FENCE_OPEN.match(line)
        if fence:
            flush_all()
            lang = _norm_lang(fence.group(1))
            body = []
            i += 1
            while i < n and not _FENCE_CLOSE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # cierre del bloque (o fin del texto)
            blocks.append(_node("code", {"rich_text": _rt("\n".join(body)), "language": lang}))
            continue

        if not stripped:
            flush_para()
            flush_quote()
            i += 1
            continue

        q = _QUOTE.match(line)
        if q:
            flush_para()
            stack.clear()
            content = q.group(1)
            if not quote:  # primera línea: ¿es un callout?
                head = _parse_callout_head(content)
                if head:
                    quote_meta = (head[0], head[1])
                    content = head[2]
            quote.append(content)
            i += 1
            continue
        flush_quote()

        # Toggle: +++ Título … +++
        tg = _TOGGLE_OPEN.match(stripped)
        if tg and not _TOGGLE_CLOSE.match(stripped):
            flush_all()
            segments, i = _scan_block(lines, i + 1, _TOGGLE_CLOSE)
            node = _node("toggle", {"rich_text": parse_inline(tg.group(1).strip())})
            kids = _parse_blocks(segments[0])
            if kids:
                node["_children"] = kids
            blocks.append(node)
            continue

        # Callout en formato de exportación de Notion: <aside> emoji … </aside>
        if _ASIDE_OPEN.match(stripped):
            flush_all()
            segments, i = _scan_block(lines, i + 1, _ASIDE_CLOSE)
            icon, content = "💡", []
            for ln in segments[0]:
                s = ln.strip()
                if not content and s and len(s) <= 4 and not s[0].isascii():
                    icon = s
                    continue
                content.append(s)
            while content and not content[0]:
                content.pop(0)
            while content and not content[-1]:
                content.pop()
            rt = []
            for j, ln in enumerate(content):
                if j:
                    rt.append({"type": "text", "text": {"content": "\n"}})
                rt.extend(parse_inline(ln))
            if rt:
                blocks.append(_node("callout", {
                    "rich_text": rt,
                    "icon": {"type": "emoji", "emoji": icon},
                    "color": "default",
                }))
            continue

        # Columnas: ::: columns / ::: column / :::
        if _COLS_OPEN.match(stripped):
            flush_all()
            segments, i = _scan_block(lines, i + 1, _COLS_CLOSE, sep_re=_COL_SEP)
            columns, hoisted_all = [], []
            for seg in segments:
                kids = _parse_blocks(seg)
                kids, hoisted = _hoist_tables(kids)
                hoisted_all += hoisted
                if kids:
                    columns.append({"type": "column", "column": {}, "_children": kids})
            if len(columns) >= 2:
                blocks.append({"type": "column_list", "column_list": {}, "_children": columns})
            else:  # una sola columna no es válida: se vuelca el contenido en secuencia
                for col in columns:
                    blocks.extend(col["_children"])
            blocks.extend(hoisted_all)
            continue

        # Marcadores huérfanos fuera de contexto (::: column suelto, :::, ::: :::, +++ sin
        # abrir): nunca deben llegar como texto literal a Notion — se descartan.
        if _COL_SEP.match(stripped) or _ORPHAN_MARKER.match(stripped) or _TOGGLE_CLOSE.match(stripped):
            flush_all()
            i += 1
            continue

        # Ecuación en bloque: $$ … $$
        eq = _EQ_LINE.match(stripped)
        if eq:
            flush_all()
            blocks.append(_node("equation", {"expression": eq.group(1)}))
            i += 1
            continue
        if stripped == "$$":
            flush_all()
            expr = []
            i += 1
            while i < n and lines[i].strip() != "$$":
                expr.append(lines[i])
                i += 1
            i += 1
            blocks.append(_node("equation", {"expression": "\n".join(expr).strip()}))
            continue

        # Índice de la página
        if _TOC.match(stripped):
            flush_all()
            blocks.append(_node("table_of_contents", {"color": "default"}))
            i += 1
            continue

        # URL sola en una línea → bookmark (solo si no hay párrafo a medias)
        if not para and _BARE_URL.match(stripped):
            flush_all()
            blocks.append(_node("bookmark", {"url": stripped}))
            i += 1
            continue

        # Imagen o media tipada: ![video](url), ![audio](url), ![pdf](url)…
        img = _IMG_LINE.match(stripped)
        if img and img.group(2).startswith(("http://", "https://", "_preserve_:")):
            flush_all()
            alt, url = img.group(1).strip(), img.group(2)
            if url.startswith("_preserve_:"):
                blocks.append(_node("_preserve", {"id": url.split(":", 1)[1]}))
                i += 1
                continue
            keyword = alt.split(":", 1)[0].strip().lower()
            caption = alt.split(":", 1)[1].strip() if ":" in alt else ""
            media = MEDIA_KEYWORDS.get(keyword)
            if media == "embed":
                data = {"url": url}
                if caption:
                    data["caption"] = _rt(caption)
                blocks.append(_node("embed", data))
            elif media:
                data = {"type": "external", "external": {"url": url}}
                if caption:
                    data["caption"] = _rt(caption)
                blocks.append(_node(media, data))
            else:
                data = {"type": "external", "external": {"url": url}}
                if alt:
                    data["caption"] = _rt(alt)
                blocks.append(_node("image", data))
            i += 1
            continue

        h = _HEADING.match(stripped)
        if h:
            flush_all()
            level = min(len(h.group(1)), 3)
            blocks.append(_node(f"heading_{level}", {"rich_text": parse_inline(h.group(2).strip())}))
            i += 1
            continue

        if _HR.match(line):
            flush_all()
            blocks.append(_node("divider", {}))
            i += 1
            continue

        if (
            stripped.startswith("|")
            and i + 1 < n
            and "|" in lines[i + 1]
            and "-" in lines[i + 1]
            and _TABLE_SEP.match(lines[i + 1])
        ):
            flush_all()
            rows = [_split_row(stripped)]
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i].strip()))
                i += 1
            width = max(len(r) for r in rows)

            def cells(row):
                return [parse_inline(c) for c in (row + [""] * (width - len(row)))[:width]]

            children = [
                {"object": "block", "type": "table_row", "table_row": {"cells": cells(r)}}
                for r in rows
            ]
            blocks.append(_node("table", {
                "table_width": width,
                "has_column_header": True,
                "has_row_header": False,
                "children": children,
            }))
            continue

        li = _LIST.match(line)
        if li:
            flush_para()
            indent = len(li.group(1).expandtabs(4))
            content = li.group(4)
            todo = _TODO.match(content)
            if todo:
                node = _node("to_do", {
                    "rich_text": parse_inline(todo.group(2)),
                    "checked": todo.group(1).lower() == "x",
                })
            elif li.group(3) is not None:
                node = _node("numbered_list_item", {"rich_text": parse_inline(content)})
            else:
                node = _node("bulleted_list_item", {"rich_text": parse_inline(content)})
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                stack[-1][1].setdefault("_children", []).append(node)
            else:
                blocks.append(node)
            stack.append((indent, node))
            i += 1
            continue

        stack.clear()
        para.append(stripped)
        i += 1

    flush_para()
    flush_quote()
    return blocks


def md_to_blocks(md):
    lines = md.replace("\r\n", "\n").split("\n")
    return _serialize(_clamp_depth(_parse_blocks(lines)))
