import argparse
import json
import sys
from pathlib import Path

import yaml

from src.cleaner import clean_pages
from src.extractor import extract_pages
from src.merger import merge_to_markdown
from src.translator import translate_markdown


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
        description="Extract, clean, merge, and translate text from a scanned PDF."
    )
    parser.add_argument("pdf", help="Path to the input PDF file")
    parser.add_argument("output_dir", help="Directory to write output files")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--stage",
        choices=["extract", "merge", "translate", "all"],
        default="all",
        help="Which stage(s) to run (default: all)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="API request timeout in seconds for extract stage (default: 60)",
    )
    parser.add_argument(
        "--pages",
        help="Page range to process in extract stage, e.g. 1-10 or 5 (default: all)",
    )
    parser.add_argument(
        "--glossary",
        default=None,
        help="Path to glossary CSV file (used in translate stage)",
    )
    parser.add_argument(
        "--rules",
        default=None,
        help="Path to translation rules TXT file (used in translate stage)",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cleaned_path = output_dir / "cleaned.json"
    content_path = output_dir / "content.md"
    translated_path = output_dir / "translated.md"

    run_extract = args.stage in ("extract", "all")
    run_merge = args.stage in ("merge", "all")
    run_translate = args.stage in ("translate", "all")

    if run_extract:
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

        with open(cleaned_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        print(f"Extract done. Written {len(cleaned)} pages to {cleaned_path}")

    if run_merge:
        if not cleaned_path.exists():
            print(
                f"Error: {cleaned_path} not found.\nRun with --stage extract first.",
                file=sys.stderr,
            )
            sys.exit(1)

        with open(cleaned_path, encoding="utf-8") as f:
            cleaned = json.load(f)

        print(f"Merging {len(cleaned)} pages into Markdown...")
        merge_to_markdown(cleaned, content_path)
        print(f"Merge done. Written to {content_path}")

    if run_translate:
        if not content_path.exists():
            print(
                f"Error: {content_path} not found.\nRun with --stage merge first.",
                file=sys.stderr,
            )
            sys.exit(1)
        if "translate_prompt" not in config:
            print(
                "Error: translate_prompt not found in config.yaml.\n"
                "See config.example.yaml for the required fields.",
                file=sys.stderr,
            )
            sys.exit(1)

        translate_timeout: int = config.get("translate_timeout", args.timeout)
        glossary_path = Path(args.glossary) if args.glossary else None
        rules_path = Path(args.rules) if args.rules else None

        print("Translating...")
        try:
            translate_markdown(
                content_path,
                translated_path,
                config,
                glossary_path=glossary_path,
                rules_path=rules_path,
                timeout=translate_timeout,
            )
        except RuntimeError as e:
            print(f"Translation failed: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Translate done. Written to {translated_path}")


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
