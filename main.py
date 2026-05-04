import argparse
import json
import sys
from pathlib import Path

import yaml

from cleaner import clean_pages
from extractor import extract_pages


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        config = yaml.safe_load(f)
    required = {"model", "api_key", "api_url", "clean_prompt"}
    missing = required - config.keys()
    if missing:
        raise ValueError(
            f"Missing required config fields: {', '.join(sorted(missing))}\n"
            f"Add them to {config_path}."
        )
    if config["api_key"] == "YOUR_API_KEY_HERE":
        raise ValueError(
            "api_key is not set in config.yaml.\n"
            "Replace YOUR_API_KEY_HERE with your actual DeepSeek API key."
        )
    return config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract and clean text from a scanned PDF using an LLM."
    )
    parser.add_argument("pdf", help="Path to the input PDF file")
    parser.add_argument("output_dir", help="Directory to write output files")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="API request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--pages",
        help="Page range to process, e.g. 1-10 or 5 (default: all pages)",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting pages from {args.pdf}...")
    try:
        pages = extract_pages(args.pdf)
    except Exception as e:
        print(f"Failed to open PDF: {e}", file=sys.stderr)
        sys.exit(1)

    if args.pages:
        pages = _filter_pages(pages, args.pages)

    print(f"Cleaning {len(pages)} pages with {config['model']}...")
    try:
        cleaned = clean_pages(pages, config, timeout=args.timeout)
    except RuntimeError as e:
        print(f"Cleaning failed: {e}", file=sys.stderr)
        sys.exit(1)

    out_path = output_dir / "cleaned.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"Done. Written {len(cleaned)} pages to {out_path}")


def _filter_pages(pages: list[dict], spec: str) -> list[dict]:
    if "-" in spec:
        parts = spec.split("-", 1)
        start, end = int(parts[0]), int(parts[1])
    else:
        start = end = int(spec)
    filtered = [p for p in pages if start <= p["page_number"] <= end]
    if not filtered:
        print(
            f"Warning: page range {spec} matched no pages "
            f"(PDF has {len(pages)} pages).",
            file=sys.stderr,
        )
    return filtered


if __name__ == "__main__":
    main()
