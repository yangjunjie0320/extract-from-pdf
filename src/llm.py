import time

import requests


def call_api(
    prompt: str,
    config: dict,
    timeout: int,
    max_retries: int = 3,
    response_format: dict | None = None,
    max_tokens: int | None = None,
) -> str:
    payload: dict = {
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens or config.get("max_tokens", 8192),
    }
    if response_format:
        payload["response_format"] = response_format

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
            return resp.json()["choices"][0]["message"]["content"]
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

    raise RuntimeError(
        f"API request failed after {max_retries} attempts: {last_error}\n"
        "Check your network connection and api_url in config.yaml."
    )
