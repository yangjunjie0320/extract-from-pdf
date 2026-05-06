import re
from pathlib import Path

import fitz

_SIZE_RE = re.compile(r"^\[pos=\d+%, size=(\d+\.\d+)")


def _block_text(block: dict) -> str:
    parts = []
    for line in block.get("lines", []):
        line_text = ""
        for span in line.get("spans", []):
            line_text += span["text"]
        parts.append(line_text.strip())
    return " ".join(p for p in parts if p)


def _block_font_info(block: dict) -> tuple[str, float]:
    fonts: dict[str, int] = {}
    sizes: dict[float, int] = {}
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            text_len = len(span.get("text", ""))
            name = span.get("font", "")
            size = span.get("size", 0.0)
            fonts[name] = fonts.get(name, 0) + text_len
            sizes[size] = sizes.get(size, 0) + text_len
    font = max(fonts, key=fonts.get) if fonts else ""  # type: ignore[arg-type]
    size = max(sizes, key=sizes.get) if sizes else 0.0  # type: ignore[arg-type]
    return font, size


def compute_doc_stats(layout_dir: Path) -> str:
    """Compute document-wide font size distribution from all layout files.

    Returns a string like "10.0pt:68%, 8.5pt:14%, 12.0pt:10%, 6.5pt:8%",
    sorted by character count descending.
    """
    size_chars: dict[float, int] = {}
    for layout_file in sorted(layout_dir.glob("page_*.layout.txt")):
        for line in layout_file.read_text(encoding="utf-8").splitlines():
            m = _SIZE_RE.match(line)
            if not m:
                continue
            size = float(m.group(1))
            text = line[line.index("]") + 1 :].strip()
            size_chars[size] = size_chars.get(size, 0) + len(text)

    total = sum(size_chars.values())
    if not total:
        return ""

    sorted_sizes = sorted(size_chars.items(), key=lambda x: x[1], reverse=True)
    return ", ".join(
        f"{size:.1f}pt:{chars / total * 100:.0f}%" for size, chars in sorted_sizes
    )


def extract_to_layout(
    pdf_path: str,
    layout_dir: Path,
    pages_filter: tuple[int, int] | None = None,
) -> list[int]:
    """Extract layout text from PDF pages and write to layout_dir.

    Skips pages whose .layout.txt already exists (resume support).
    Returns the list of page numbers processed or already present.
    """
    layout_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    page_numbers: list[int] = []

    for i, page in enumerate(doc):
        n = i + 1
        if pages_filter is not None:
            start, end = pages_filter
            if not (start <= n <= end):
                continue

        out_path = layout_dir / f"page_{n:04d}.layout.txt"
        page_numbers.append(n)

        if out_path.exists():
            continue

        page_height = page.rect.height
        data = page.get_text("dict")
        text_blocks = [b for b in data.get("blocks", []) if b.get("type", 0) == 0]

        if not text_blocks:
            out_path.write_text("", encoding="utf-8")
            continue

        parts: list[str] = []
        for block in text_blocks:
            text = _block_text(block)
            if not text.strip():
                continue

            y_top = block["bbox"][1]
            font, size = _block_font_info(block)
            pos_pct = y_top / page_height * 100

            style_hints = []
            if "Bold" in font or "bold" in font:
                style_hints.append("bold")
            if "Italic" in font or "italic" in font:
                style_hints.append("italic")
            style_str = f", {', '.join(style_hints)}" if style_hints else ""

            parts.append(f"[pos={pos_pct:.0f}%, size={size:.1f}{style_str}] {text}")

        out_path.write_text("\n".join(parts), encoding="utf-8")

    doc.close()
    return page_numbers
