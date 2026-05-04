import json

from src.llm import call_api


def clean_page(
    raw_text: str,
    config: dict,
    prev_tail: str = "",
    timeout: int = 60,
) -> dict:
    prompt = config["clean_prompt"].format(text=raw_text, prev_tail=prev_tail)
    content = call_api(
        prompt,
        config,
        timeout=timeout,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Unexpected API response format: {e}\n"
            "The model may not support json_object response format."
        ) from e


def clean_pages(
    pages: list[dict],
    config: dict,
    timeout: int = 60,
) -> list[dict]:
    results = []
    prev_tail = ""
    tail_chars: int = config.get("prev_tail_chars", 500)
    total = len(pages)
    for page in pages:
        n = page["page_number"]
        print(f"Cleaning page {n}/{total}...")
        cleaned = clean_page(
            page["raw_text"], config, prev_tail=prev_tail, timeout=timeout
        )
        results.append({"page_number": n, **cleaned})
        merged = (cleaned.get("title", "") + "\n" + cleaned.get("body", "")).strip()
        prev_tail = merged[-tail_chars:]
    return results
