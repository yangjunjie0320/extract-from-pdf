import csv
import re
from pathlib import Path

from src.llm import call_api

_CHARS_PER_TOKEN = 2


def _load_glossary(glossary_path: Path) -> str:
    lines = []
    with open(glossary_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = (row.get("source") or "").strip()
            tgt = (row.get("target") or "").strip()
            if src and tgt:
                lines.append(f"{src} -> {tgt}")
    return "\n".join(lines)


def _load_rules(rules_path: Path) -> str:
    return rules_path.read_text(encoding="utf-8").strip()


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def _split_into_chunks(body: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    paragraphs = re.split(r"\n{2,}", body)
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0
    overlap_chars = overlap_tokens * _CHARS_PER_TOKEN

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)
        if current_tokens + para_tokens > max_tokens and current_parts:
            chunks.append("\n\n".join(current_parts))
            overlap_text = "\n\n".join(current_parts)[-overlap_chars:]
            current_parts = [overlap_text, para] if overlap_text else [para]
            current_tokens = _estimate_tokens("\n\n".join(current_parts))
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks if chunks else [body]


def _translate_chunk(
    text: str,
    prev_overlap: str,
    glossary: str,
    rules: str,
    config: dict,
    timeout: int,
) -> str:
    prompt = config["translate_prompt"].format(
        glossary=glossary,
        rules=rules,
        prev_overlap=prev_overlap,
        text=text,
    )
    return call_api(prompt, config, timeout=timeout)


def translate_markdown(
    content_path: Path,
    output_path: Path,
    config: dict,
    glossary_path: Path | None,
    rules_path: Path | None,
    timeout: int = 180,
) -> None:
    glossary = _load_glossary(glossary_path) if glossary_path else ""
    rules = _load_rules(rules_path) if rules_path else ""
    max_chunk_tokens: int = config.get("max_chunk_tokens", 32000)
    overlap_tokens: int = config.get("overlap_tokens", 500)

    content = content_path.read_text(encoding="utf-8")
    raw_sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    translated_sections: list[str] = []
    total = len(raw_sections)

    for i, section in enumerate(raw_sections):
        if not section.strip():
            continue

        title_match = re.match(r"^## (.+)\n", section)
        if title_match:
            de_title = title_match.group(1)
            body = section[title_match.end() :]
            print(f"Translating section {i + 1}/{total}: {de_title[:60]}...")
            zh_title = _translate_chunk(
                de_title, "", glossary, rules, config, timeout
            ).strip()
        else:
            body = section
            zh_title = ""
            print(f"Translating section {i + 1}/{total} (no title)...")

        body = body.strip()
        if not body:
            if zh_title:
                translated_sections.append(f"## {zh_title}\n")
            continue

        if _estimate_tokens(body) <= max_chunk_tokens:
            translated_body = _translate_chunk(
                body, "", glossary, rules, config, timeout
            )
            result = ""
            if zh_title:
                result += f"## {zh_title}\n\n"
            result += translated_body.strip()
            translated_sections.append(result)
        else:
            chunks = _split_into_chunks(body, max_chunk_tokens, overlap_tokens)
            parts: list[str] = []
            prev_overlap = ""
            for j, chunk in enumerate(chunks):
                print(f"  chunk {j + 1}/{len(chunks)}...")
                translated = _translate_chunk(
                    chunk, prev_overlap, glossary, rules, config, timeout
                )
                parts.append(translated.strip())
                overlap_chars = overlap_tokens * _CHARS_PER_TOKEN
                prev_overlap = chunk[-overlap_chars:]

            result = ""
            if zh_title:
                result += f"## {zh_title}\n\n"
            result += "\n\n".join(parts)
            translated_sections.append(result)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(translated_sections))
        f.write("\n")
