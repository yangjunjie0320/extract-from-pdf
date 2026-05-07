import concurrent.futures
import json
import logging
import re
import time
from pathlib import Path

from src.llm_client import call_api
from src.schema import CleanedBatch, CleanedPage

logger = logging.getLogger(__name__)


def _parse_json(content: str) -> list | dict:
    text = content.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Unexpected API response format: {e}\n"
            f"Response (first 500 chars): {content[:500]}"
        ) from e


def _read_layout(layout_dir: Path, page_num: int) -> str:
    path = layout_dir / f"page_{page_num:04d}.layout.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _build_batch_text(layout_dir: Path, page_numbers: list[int]) -> str:
    parts = []
    for n in page_numbers:
        text = _read_layout(layout_dir, n)
        parts.append(f"Page {n}\n{text}")
    return "\n\n".join(parts)


def _call_llm_for_batch(
    batch_pages: list[int],
    layout_dir: Path,
    cleaned_dir: Path,
    prompt_template: str,
    context_pages: int,
    all_page_numbers: list[int],
    cfg: dict,
    doc_stats: str,
) -> tuple[list[CleanedPage], set[int]]:
    """Call LLM for a batch, return (pages, missing_pages)."""
    first = batch_pages[0]
    last = batch_pages[-1]
    batch_id = f"{first:03d}-{last:03d}"

    batch_text = _build_batch_text(layout_dir, batch_pages)

    idx_first = all_page_numbers.index(first)
    idx_last = all_page_numbers.index(last)
    prev_pages = all_page_numbers[max(0, idx_first - context_pages) : idx_first]
    next_pages = all_page_numbers[idx_last + 1 : idx_last + 1 + context_pages]
    prev_context = _build_batch_text(layout_dir, prev_pages) if prev_pages else ""
    next_context = _build_batch_text(layout_dir, next_pages) if next_pages else ""

    prompt = prompt_template.format(
        batch_text=batch_text,
        prev_context=prev_context,
        next_context=next_context,
        doc_stats=doc_stats,
    )

    model: str = cfg["cleaning"]["model"]
    api_config: dict = cfg["api"]
    max_retries: int = api_config.get("max_retries", 3)

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            log_path = cleaned_dir / "logs" / f"batch_{batch_id}.json"
            content = call_api(
                prompt,
                model=model,
                api_config=api_config,
                response_format={"type": "json_object"},
                log_path=log_path,
            )
            raw = _parse_json(content)
            return _normalize_pages(raw, batch_pages)
        except ValueError as e:
            last_error = e
            wait = 5 * (2**attempt)
            logger.warning(
                "  [batch %s] JSON parse failed on attempt %d, retrying in %ds... (%s)",
                batch_id,
                attempt + 1,
                wait,
                e,
            )
            time.sleep(wait)
        except RuntimeError:
            raise
    raise RuntimeError(
        f"Failed to get valid JSON after {max_retries} attempts for batch {batch_id}: {last_error}\n"
        "Try reducing cleaning.batch_size in config.yaml."
    )


def _clean_batch_worker(
    batch_pages: list[int],
    layout_dir: Path,
    cleaned_dir: Path,
    prompt_template: str,
    context_pages: int,
    all_page_numbers: list[int],
    cfg: dict,
    doc_stats: str,
) -> CleanedBatch:
    first = batch_pages[0]
    last = batch_pages[-1]
    batch_id = f"{first:03d}-{last:03d}"
    out_path = cleaned_dir / f"batch_{batch_id}.json"

    try:
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pass
    except Exception:
        pass  # corrupt file, re-clean

    logger.info("Cleaning batch %s (%d pages)...", batch_id, len(batch_pages))

    pages, missing = _call_llm_for_batch(
        batch_pages,
        layout_dir,
        cleaned_dir,
        prompt_template,
        context_pages,
        all_page_numbers,
        cfg,
        doc_stats,
    )

    # If LLM truncated output, split into halves and retry each half separately
    if missing and len(batch_pages) > 1:
        logger.warning(
            "  [batch %s] LLM returned only %d/%d pages, splitting and retrying...",
            batch_id,
            len(batch_pages) - len(missing),
            len(batch_pages),
        )
        mid = len(batch_pages) // 2
        halves = [batch_pages[:mid], batch_pages[mid:]]
        pages_by_num: dict[int, CleanedPage] = {}
        for half in halves:
            half_pages, half_missing = _call_llm_for_batch(
                half,
                layout_dir,
                cleaned_dir,
                prompt_template,
                context_pages,
                all_page_numbers,
                cfg,
                doc_stats,
            )
            if half_missing:
                logger.warning(
                    "  [batch %s] still missing %d page(s) after split: %s",
                    batch_id,
                    len(half_missing),
                    sorted(half_missing),
                )
            for p in half_pages:
                pages_by_num[p["page"]] = p
        pages = [pages_by_num[n] for n in batch_pages]

    result: CleanedBatch = {"batch_id": batch_id, "pages": pages}

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def _normalize_pages(
    raw: list | dict, batch_pages: list[int]
) -> tuple[list[CleanedPage], set[int]]:
    """Return (pages, missing_page_numbers). missing is non-empty when LLM truncated output."""
    if isinstance(raw, dict):
        candidates = [v for v in raw.values() if isinstance(v, list)]
        raw = candidates[0] if candidates else [raw]

    items_by_page: dict[int, dict] = {}
    for item in raw:
        if isinstance(item, dict):
            p = item.get("page")
            if isinstance(p, int):
                items_by_page[p] = item

    pages: list[CleanedPage] = []
    missing: set[int] = set()
    for page_num in batch_pages:
        item = items_by_page.get(page_num)
        if item is None:
            missing.add(page_num)
            item = {}
        pages.append(
            CleanedPage(
                page=page_num,
                page_type=item.get("page_type", "body"),
                book_page=item.get("book_page") or None,
                body_md=item.get("body_md", ""),
                warnings=item.get("warnings", []),
            )
        )
    return pages, missing


def clean_pages(
    page_numbers: list[int],
    layout_dir: Path,
    cleaned_dir: Path,
    prompt_template: str,
    cfg: dict,
    doc_stats: str,
) -> list[CleanedBatch]:
    cleaned_dir.mkdir(parents=True, exist_ok=True)

    batch_size: int = cfg.get("cleaning", {}).get("batch_size", 3)
    context_pages: int = cfg.get("cleaning", {}).get("context_pages", 1)
    max_workers: int = cfg.get("runtime", {}).get("workers", 4)

    batches: list[list[int]] = [
        page_numbers[i : i + batch_size]
        for i in range(0, len(page_numbers), batch_size)
    ]

    logger.info(
        "Starting %d batches (batch_size=%d, context_pages=%d) with %d workers...",
        len(batches),
        batch_size,
        context_pages,
        max_workers,
    )

    results: list[CleanedBatch | None] = [None] * len(batches)
    failures: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(
                _clean_batch_worker,
                batch,
                layout_dir,
                cleaned_dir,
                prompt_template,
                context_pages,
                page_numbers,
                cfg,
                doc_stats,
            ): idx
            for idx, batch in enumerate(batches)
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                first_page = batches[idx][0]
                last_page = batches[idx][-1]
                msg = f"batch_{first_page:03d}-{last_page:03d}: {e}"
                logger.warning("Batch failed: %s", msg)
                failures.append(msg)

    if failures:
        failed_list = "\n  ".join(failures)
        raise RuntimeError(
            f"{len(failures)} batch(es) failed:\n  {failed_list}\n"
            "Re-run with --resume to retry only failed batches."
        )

    return [r for r in results if r is not None]
