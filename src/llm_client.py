import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


def call_api(
    prompt: str,
    *,
    model: str,
    api_config: dict,
    response_format: dict | None = None,
    log_path: Path | None = None,
) -> str:
    url = api_config["base_url"].rstrip("/") + "/chat/completions"
    timeout: int = api_config.get("timeout", 120)
    max_retries: int = api_config.get("max_retries", 3)

    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": api_config.get("max_tokens", 8192),
    }
    if response_format:
        payload["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {api_config['api_key']}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if log_path is not None:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_entry = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "model": model,
                    "prompt": prompt,
                    "response": content,
                }
                log_path.write_text(
                    json.dumps(log_entry, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            return content
        except requests.exceptions.Timeout as e:
            last_error = e
            wait = 2**attempt
            logger.warning("  [attempt %d] timeout, retrying in %ds", attempt + 1, wait)
            time.sleep(wait)
        except requests.exceptions.HTTPError as e:
            last_error = e
            status = resp.status_code
            if status == 429:
                wait = 2 ** (attempt + 2)
                logger.warning(
                    "  [attempt %d] rate limited (429), retrying in %ds",
                    attempt + 1,
                    wait,
                )
                time.sleep(wait)
            elif status < 500:
                raise RuntimeError(
                    f"API returned {status}: {resp.text}\n"
                    "Check api.api_key and api.base_url in config.yaml."
                ) from e
            else:
                wait = 2**attempt
                logger.warning(
                    "  [attempt %d] server error %d, retrying in %ds",
                    attempt + 1,
                    status,
                    wait,
                )
                time.sleep(wait)
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ) as e:
            last_error = e
            wait = 2**attempt
            logger.warning(
                "  [attempt %d] connection error, retrying in %ds", attempt + 1, wait
            )
            time.sleep(wait)

    raise RuntimeError(
        f"API request failed after {max_retries} attempts: {last_error}\n"
        "Check your network connection and api.base_url in config.yaml."
    )
