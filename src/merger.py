from pathlib import Path


def merge_to_markdown(cleaned: list[dict], output_path: Path) -> None:
    sections: list[dict] = []
    current: dict | None = None

    for page in cleaned:
        if page.get("page_type") in ("cover", "toc"):
            if current:
                sections.append(current)
                current = None
            continue

        title = (page.get("title") or "").strip()
        body = (page.get("body") or "").strip()
        cont = bool(page.get("continuation"))

        if title and not cont:
            if current:
                sections.append(current)
            current = {"title": title, "body_parts": [body] if body else []}
        else:
            if current is None:
                current = {"title": "", "body_parts": []}
            if body:
                current["body_parts"].append(body)

    if current:
        sections.append(current)

    with open(output_path, "w", encoding="utf-8") as f:
        for s in sections:
            if s["title"]:
                f.write(f"## {s['title']}\n\n")
            f.write("\n\n".join(s["body_parts"]))
            f.write("\n\n")
