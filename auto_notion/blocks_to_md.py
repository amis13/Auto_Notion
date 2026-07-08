"""Convierte un árbol de bloques de Notion (con «_children») a Markdown extendido."""

import re


def _rt_to_md(rich_text):
    out = []
    for t in rich_text or []:
        if t.get("type") == "equation":
            expr = (t.get("equation") or {}).get("expression", "")
            if expr:
                out.append(f"${expr}$")
            continue
        s = t.get("plain_text", "")
        if not s:
            continue
        ann = t.get("annotations") or {}
        if ann.get("code"):
            s = f"`{s}`"
        else:
            if ann.get("bold") and ann.get("italic"):
                s = f"***{s}***"
            elif ann.get("bold"):
                s = f"**{s}**"
            elif ann.get("italic"):
                s = f"*{s}*"
            if ann.get("underline"):
                s = f"__{s}__"
            if ann.get("strikethrough"):
                s = f"~~{s}~~"
            if ann.get("color") == "yellow_background":
                s = f"=={s}=="
        href = t.get("href")
        if href:
            s = f"[{s}]({href})"
        out.append(s)
    return "".join(out)


def _file_url(data):
    kind = data.get("type")
    if kind in ("external", "file"):
        return (data.get(kind) or {}).get("url", ""), kind
    return "", kind


def _plain(rich_text):
    return "".join(t.get("plain_text", "") for t in rich_text or [])


def _media_line(kind, data):
    url, source = _file_url(data)
    if source != "external" or not url:
        return None  # archivos subidos a Notion: se conservan aparte (URLs caducan)
    caption = _rt_to_md(data.get("caption")).replace("\n", " ").strip()
    alt = f"{kind}: {caption}" if caption else kind
    return f"![{alt}]({url})"


def _render(blocks, indent):
    pad = "  " * indent
    lines = []
    num = 0
    for b in blocks:
        t = b.get("type")
        data = b.get(t) or {}
        kids = b.get("_children") or []
        rt = _rt_to_md(data.get("rich_text"))
        if t != "numbered_list_item":
            num = 0

        if t == "paragraph":
            if rt:
                lines += [pad + rt, ""]
            if kids:
                lines += _render(kids, indent + 1)

        elif t in ("heading_1", "heading_2", "heading_3"):
            lines += ["", pad + "#" * int(t[-1]) + " " + rt, ""]
            if kids:  # encabezados desplegables
                lines += _render(kids, indent)

        elif t == "bulleted_list_item":
            lines.append(pad + "- " + rt)
            if kids:
                lines += _render(kids, indent + 1)

        elif t == "numbered_list_item":
            num += 1
            lines.append(pad + f"{num}. " + rt)
            if kids:
                lines += _render(kids, indent + 1)

        elif t == "to_do":
            mark = "x" if data.get("checked") else " "
            lines.append(pad + f"- [{mark}] " + rt)
            if kids:
                lines += _render(kids, indent + 1)

        elif t == "toggle":
            lines += ["", pad + "+++ " + rt]
            if kids:
                lines += _render(kids, indent)
            lines += [pad + "+++", ""]

        elif t == "quote":
            lines.append("")
            for ln in (rt or "").split("\n"):
                lines.append(pad + "> " + ln)
            for ln in _render(kids, 0):
                lines.append(pad + ("> " + ln if ln else ">"))
            lines.append("")

        elif t == "callout":
            icon = data.get("icon") or {}
            emoji = icon.get("emoji", "💡") if icon.get("type") == "emoji" else "💡"
            color = data.get("color", "default")
            head = f"[!{emoji}]" if color == "default" else f"[!{emoji}|{color}]"
            lines.append("")
            for j, ln in enumerate((rt or "").split("\n")):
                lines.append(pad + "> " + (f"{head} " if j == 0 else "") + ln)
            for ln in _render(kids, 0):
                lines.append(pad + ("> " + ln if ln else ">"))
            lines.append("")

        elif t == "code":
            lang = data.get("language", "") or ""
            if lang == "plain text":
                lang = "text"
            content = _plain(data.get("rich_text"))
            lines += ["", pad + f"```{lang}"]
            lines += [pad + ln for ln in content.split("\n")]
            lines += [pad + "```", ""]

        elif t == "divider":
            lines += ["", "---", ""]

        elif t == "image":
            url, kind = _file_url(data)
            if kind == "external" and url:
                caption = _rt_to_md(data.get("caption")).replace("\n", " ")
                lines += ["", pad + f"![{caption}]({url})", ""]

        elif t in ("video", "audio", "pdf", "file"):
            media = _media_line(t, data)
            if media:
                lines += [pad + media, ""]

        elif t == "embed":
            url = data.get("url", "")
            if url:
                caption = _rt_to_md(data.get("caption")).replace("\n", " ").strip()
                alt = f"embed: {caption}" if caption else "embed"
                lines += [pad + f"![{alt}]({url})", ""]

        elif t == "bookmark":
            url = data.get("url", "")
            if url:
                caption = _rt_to_md(data.get("caption")).strip()
                lines += [pad + (f"[{caption}]({url})" if caption else url), ""]

        elif t == "link_preview":
            url = data.get("url", "")
            if url:
                lines += [pad + f"[{url}]({url})", ""]

        elif t == "equation":
            expr = data.get("expression", "")
            if expr:
                lines += [pad + f"$$ {expr} $$", ""]

        elif t == "table_of_contents":
            lines += [pad + "[toc]", ""]

        elif t == "table":
            rows = [k for k in kids if k.get("type") == "table_row"]
            if rows:
                grid = [
                    [_rt_to_md(cell).replace("|", "\\|").replace("\n", " ")
                     for cell in (r.get("table_row") or {}).get("cells", [])]
                    for r in rows
                ]
                width = max(len(r) for r in grid)
                grid = [r + [""] * (width - len(r)) for r in grid]
                lines.append("")
                lines.append(pad + "| " + " | ".join(grid[0]) + " |")
                lines.append(pad + "| " + " | ".join(["---"] * width) + " |")
                for r in grid[1:]:
                    lines.append(pad + "| " + " | ".join(r) + " |")
                lines.append("")

        elif t == "column_list":
            cols = [k for k in kids if k.get("type") == "column"]
            if cols:
                lines += ["", pad + "::: columns"]
                for j, col in enumerate(cols):
                    if j:
                        lines.append(pad + "::: column")
                    lines += _render(col.get("_children") or [], indent)
                lines += [pad + ":::", ""]

        elif t in ("child_page", "child_database"):
            pass  # se procesan como páginas aparte / se conservan

        elif t in ("column", "synced_block"):
            if kids:
                lines += _render(kids, indent)

        elif t in ("breadcrumb", "table_row"):
            pass

        else:
            if rt:
                lines += [pad + rt, ""]
            if kids:
                lines += _render(kids, indent)
    return lines


def blocks_to_md(blocks):
    text = "\n".join(_render(blocks or [], 0))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n" if text else ""
