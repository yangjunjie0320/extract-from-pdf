import concurrent.futures
import csv
import logging
import re
from pathlib import Path

from src.llm_client import call_api

logger = logging.getLogger(__name__)

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


def _split_into_chunks(body: str, max_tokens: int) -> list[str]:
    paragraphs = re.split(r"\n{2,}", body)
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)
        if current_tokens + para_tokens > max_tokens and current_parts:
            chunks.append("\n\n".join(current_parts))
            current_parts = [para]
            current_tokens = para_tokens
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks if chunks else [body]


def _translate_chunk_worker(
    chunk_id: str,
    text: str,
    glossary: str,
    rules: str,
    prompt_template: str,
    cfg: dict,
    cache_dir: Path,
) -> str:
    cache_path = cache_dir / f"{chunk_id}.md"
    try:
        return cache_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        pass

    logger.info("Translating %s...", chunk_id)
    prompt = prompt_template.format(
        glossary=glossary,
        rules=rules,
        text=text,
    )

    log_path = cache_dir / "logs" / f"{chunk_id}.json"
    translated = call_api(
        prompt,
        model=cfg["translation"]["model"],
        api_config=cfg["api"],
        log_path=log_path,
    ).strip()
    cache_path.write_text(translated, encoding="utf-8")
    return translated


def translate_markdown(
    content_path: Path,
    output_path: Path,
    cfg: dict,
    prompt_template: str,
) -> None:
    trans_cfg: dict = cfg.get("translation", {})

    glossary_path_str = trans_cfg.get("glossary")
    glossary_path = Path(glossary_path_str) if glossary_path_str else None
    rules_path_str = trans_cfg.get("rules")
    rules_path = Path(rules_path_str) if rules_path_str else None

    glossary = (
        _load_glossary(glossary_path)
        if glossary_path and glossary_path.exists()
        else ""
    )
    rules = _load_rules(rules_path) if rules_path and rules_path.exists() else ""

    max_chunk_tokens: int = trans_cfg.get("max_tokens", 120000)
    max_workers: int = cfg.get("runtime", {}).get("workers", 4)

    cache_dir = output_path.parent / "cache_trans"
    cache_dir.mkdir(parents=True, exist_ok=True)

    content = content_path.read_text(encoding="utf-8")

    if _estimate_tokens(content) <= max_chunk_tokens:
        chunks = [content]
    else:
        chunks = _split_into_chunks(content, max_chunk_tokens)

    logger.info(
        "Submitting %d translation chunks with %d workers...", len(chunks), max_workers
    )

    tasks = []
    for j, chunk in enumerate(chunks):
        tasks.append(
            {
                "chunk_id": f"chunk_{j:04d}",
                "text": chunk,
            }
        )

    results: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _translate_chunk_worker,
                t["chunk_id"],
                t["text"],
                glossary,
                rules,
                prompt_template,
                cfg,
                cache_dir,
            ): t["chunk_id"]
            for t in tasks
        }
        for future in concurrent.futures.as_completed(futures):
            chunk_id = futures[future]
            try:
                results[chunk_id] = future.result()
            except Exception as e:
                logger.error("Translation failed for %s: %s", chunk_id, e)
                raise

    ordered = [results[t["chunk_id"]] for t in tasks]
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(ordered))
        f.write("\n")
