import json
import time
import requests


def clean_page(
    raw_text: str,
    config: dict,
    timeout: int = 60,
    max_retries: int = 3,
) -> dict:
    prompt = config["clean_prompt"].format(text=raw_text)
    payload = {
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                config["api_url"],
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except requests.exceptions.Timeout as e:
            last_error = e
            wait = 2**attempt
            print(f"  [attempt {attempt + 1}] timeout, retrying in {wait}s")
            time.sleep(wait)
        except requests.exceptions.HTTPError as e:
            last_error = e
            if resp.status_code < 500:
                raise RuntimeError(
                    f"API returned {resp.status_code}: {resp.text}\n"
                    "Check api_key and api_url in config.yaml."
                ) from e
            wait = 2**attempt
            print(
                f"  [attempt {attempt + 1}] server error {resp.status_code}, retrying in {wait}s"
            )
            time.sleep(wait)
        except (json.JSONDecodeError, KeyError) as e:
            raise RuntimeError(
                f"Unexpected API response format: {e}\n"
                "The model may not support json_object response format."
            ) from e

    raise RuntimeError(
        f"API request failed after {max_retries} attempts: {last_error}\n"
        "Check your network connection and api_url in config.yaml."
    )


def clean_pages(
    pages: list[dict],
    config: dict,
    timeout: int = 60,
) -> list[dict]:
    results = []
    total = len(pages)
    for page in pages:
        n = page["page_number"]
        print(f"Cleaning page {n}/{total}...")
        cleaned = clean_page(page["raw_text"], config, timeout=timeout)
        results.append({"page_number": n, **cleaned})
    return results
