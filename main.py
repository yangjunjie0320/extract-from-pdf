import argparse
import logging
import sys
from pathlib import Path

from src.cleaner import clean_pages
from src.config import load_config
from src.extractor import compute_doc_stats, extract_to_layout
from src.latex_writer import write_latex
from src.merger import merge_to_markdown
from src.translator import translate_markdown

logger = logging.getLogger(__name__)

_STAGES = ("extract", "clean", "merge", "translate", "latex")


def _parse_pages(spec: str) -> tuple[int, int]:
    if "-" in spec:
        parts = spec.split("-", 1)
        return int(parts[0]), int(parts[1])
    n = int(spec)
    return n, n


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract, clean, merge, and translate text from a PDF."
    )
    parser.add_argument("--pdf", required=True, help="Path to the input PDF file")
    parser.add_argument(
        "--output", required=True, help="Directory to write output files"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--pages",
        help="Page range to process, e.g. 1-10 or 5 (default: all)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint (skip stages whose output already exists)",
    )
    parser.add_argument(
        "--resume-from",
        choices=_STAGES,
        dest="resume_from",
        help="Force re-run from this stage onwards, ignoring existing output",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Write verbose debug log to output/debug.log",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        logger.error("Config error: %s", e)
        sys.exit(1)

    log_level = cfg.get("runtime", {}).get("log_level", "INFO")
    logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    book_name = Path(args.pdf).stem
    layout_dir = output_dir / "layout"
    cleaned_dir = output_dir / "cleaned"
    content_path = output_dir / "content.md"
    translated_path = output_dir / f"{book_name}.md"
    latex_path = output_dir / f"{book_name}.tex"

    pages_filter: tuple[int, int] | None = None
    if args.pages:
        try:
            pages_filter = _parse_pages(args.pages)
        except ValueError:
            logger.error(
                "Invalid --pages value: %r. Use formats like '1-10' or '5'.", args.pages
            )
            sys.exit(1)

    # Determine which stages to force-rerun
    force_from_idx = (
        _STAGES.index(args.resume_from) if args.resume_from else len(_STAGES)
    )

    def should_run(stage: str) -> bool:
        idx = _STAGES.index(stage)
        if idx >= force_from_idx:
            return True
        # Without --resume, always run; with --resume, skip if output exists
        if not args.resume:
            return True
        if stage == "extract":
            return not layout_dir.exists() or not any(layout_dir.iterdir())
        if stage == "clean":
            return not cleaned_dir.exists() or not any(cleaned_dir.glob("batch_*.json"))
        if stage == "merge":
            return not content_path.exists()
        if stage == "translate":
            return not translated_path.exists()
        if stage == "latex":
            return not latex_path.exists()
        return True

    def _read_prompt(section: str, key: str = "prompt") -> str:
        section_cfg = cfg.get(section, {})
        path_str = section_cfg.get(key)
        if not path_str:
            logger.error("Error: %s.%s not set in config.yaml.", section, key)
            sys.exit(1)
        p = Path(path_str)
        if not p.exists():
            logger.error(
                "Error: prompt file not found: %s\nCreate it or update %s.%s in config.yaml.",
                p,
                section,
                key,
            )
            sys.exit(1)
        return p.read_text(encoding="utf-8")

    # Stage 1: Extract — always processes the full PDF regardless of --pages
    if should_run("extract"):
        logger.info("Extracting layout from %s...", args.pdf)
        try:
            all_page_numbers = extract_to_layout(args.pdf, layout_dir, None)
        except Exception as e:
            logger.error("Failed to extract PDF: %s", e)
            sys.exit(1)
        logger.info("Extract done. %d pages in %s", len(all_page_numbers), layout_dir)
    else:
        layout_files = sorted(layout_dir.glob("page_*.layout.txt"))
        all_page_numbers = []
        for f in layout_files:
            try:
                # filename: page_0001.layout.txt — strip both .txt and .layout
                n = int(Path(f.stem).stem.split("_")[1])
                all_page_numbers.append(n)
            except (IndexError, ValueError):
                pass
        logger.info("Skipping extract. Found %d layout files.", len(all_page_numbers))

    # Apply --pages filter for downstream stages
    if pages_filter is not None:
        page_numbers = [
            n for n in all_page_numbers if pages_filter[0] <= n <= pages_filter[1]
        ]
        logger.info(
            "--pages %d-%d: %d pages selected for cleaning.",
            pages_filter[0],
            pages_filter[1],
            len(page_numbers),
        )
    else:
        page_numbers = all_page_numbers

    # Stage 2: Clean
    if should_run("clean"):
        if not page_numbers:
            logger.error("Error: no pages to clean. Run extract stage first.")
            sys.exit(1)
        cleaner_prompt = _read_prompt("cleaning")
        doc_stats = compute_doc_stats(layout_dir)
        logger.info("Document font distribution: %s", doc_stats)
        logger.info("Cleaning %d pages...", len(page_numbers))
        try:
            clean_pages(
                page_numbers, layout_dir, cleaned_dir, cleaner_prompt, cfg, doc_stats
            )
        except RuntimeError as e:
            logger.error("Cleaning failed: %s", e)
            sys.exit(1)
        batch_count = len(list(cleaned_dir.glob("batch_*.json")))
        logger.info("Clean done. %d batch files in %s", batch_count, cleaned_dir)
    else:
        logger.info("Skipping clean. Using existing files in %s", cleaned_dir)

    # Stage 3: Merge
    if should_run("merge"):
        if not cleaned_dir.exists() or not any(cleaned_dir.glob("batch_*.json")):
            logger.error(
                "Error: no cleaned batch files found in %s.\nRun the clean stage first.",
                cleaned_dir,
            )
            sys.exit(1)
        logger.info("Merging pages into Markdown...")
        merge_to_markdown(cleaned_dir, content_path)
        logger.info("Merge done. Written to %s", content_path)
    else:
        logger.info("Skipping merge. Using existing %s", content_path)

    # Stage 4: Translate
    if should_run("translate"):
        if not content_path.exists():
            logger.error(
                "Error: %s not found.\nRun the merge stage first.", content_path
            )
            sys.exit(1)
        translator_prompt = _read_prompt("translation")
        logger.info("Translating...")
        try:
            translate_markdown(content_path, translated_path, cfg, translator_prompt)
        except RuntimeError as e:
            logger.error("Translation failed: %s", e)
            sys.exit(1)
        logger.info("Translate done. Written to %s", translated_path)
    else:
        logger.info("Skipping translate. Using existing %s", translated_path)

    # Stage 5: LaTeX
    if should_run("latex"):
        tmpl = cfg.get("latex", {}).get("template")
        if not tmpl:
            logger.info("Skipping latex (no latex.template in config).")
        else:
            if not translated_path.exists():
                logger.error(
                    "Error: %s not found.\nRun the translate stage first.",
                    translated_path,
                )
                sys.exit(1)
            logger.info("Generating LaTeX from %s...", translated_path)
            try:
                write_latex(translated_path, latex_path, cfg)
            except RuntimeError as e:
                logger.error("LaTeX generation failed: %s", e)
                sys.exit(1)
            logger.info("LaTeX done. Written to %s", latex_path)
    else:
        logger.info("Skipping latex. Using existing %s", latex_path)


if __name__ == "__main__":
    main()
