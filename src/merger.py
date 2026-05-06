import json
import re
from pathlib import Path

from src.schema import CleanedBatch

# Matches sentence-ending punctuation including curly quotes and guillemet
_SENTENCE_END = re.compile("[.!?;:”)\\]””»`]\\s*$")
_HYPHEN_END = re.compile("-\\s*$")
_SKIP_PAGE_TYPES = frozenset({"cover", "copyright", "dedication", "toc", "blank"})


def _load_batches(cleaned_dir: Path) -> list[CleanedBatch]:
    batch_files = sorted(cleaned_dir.glob("batch_*.json"))
    batches: list[CleanedBatch] = []
    for p in batch_files:
        with open(p, encoding="utf-8") as f:
            batches.append(json.load(f))
    return batches


def merge_to_markdown(cleaned_dir: Path, output_path: Path) -> None:
    batches = _load_batches(cleaned_dir)

    body_parts: list[str] = []
    prev_body: str = ""

    for batch in batches:
        for page in batch["pages"]:
            if page.get("page_type") in _SKIP_PAGE_TYPES:
                continue

            body = (page.get("body_md") or "").strip()
            if not body:
                continue

            if prev_body:
                if _HYPHEN_END.search(prev_body):
                    # Strip trailing hyphen and join directly (broken word across pages)
                    body_parts[-1] = prev_body.rstrip().rstrip("-") + body.lstrip()
                    prev_body = body_parts[-1]
                    continue
                elif not _SENTENCE_END.search(prev_body):
                    # Mid-sentence break: join with space
                    body_parts[-1] = prev_body + " " + body
                    prev_body = body_parts[-1]
                    continue

            body_parts.append(body)
            prev_body = body

    merged = "\n\n".join(body_parts)
    # Ensure heading markers always start on their own line
    merged = re.sub(r"(?<![\n#])(#{1,6} )", r"\n\n\1", merged)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(merged)
        if body_parts:
            f.write("\n")
