# extract-from-pdf

Extract, clean, and translate academic PDFs into Chinese Markdown.

## What it does

Runs a four-stage pipeline on a PDF:

```
PDF
 -> Extractor   layout/page_NNNN.layout.json   (font sizes, positions)
 -> Cleaner     cleaned/batch_NNN-NNN.json      (LLM strips headers/footers/footnotes)
 -> Merger      content.md                      (joins pages, repairs hyphenation)
 -> Translator  translated.md                   (LLM translates to Chinese)
```

Each stage writes files to disk; interrupted runs resume from the last completed stage with `--resume`.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- A DeepSeek API key (or any OpenAI-compatible endpoint)

## Setup

```bash
git clone https://github.com/yourname/extract-from-pdf
cd extract-from-pdf
uv sync
cp config.example.yaml config.yaml
# edit config.yaml: set api.api_key and model names
```

## Usage

Process a single PDF:

```bash
uv run python -u main.py \
  --pdf path/to/book.pdf \
  --output ./output/book \
  --config config.yaml
```

Test on a subset of pages:

```bash
uv run python -u main.py --pdf book.pdf --output ./output/test --pages 1-20 --config config.yaml
```

Resume an interrupted run:

```bash
uv run python -u main.py --pdf book.pdf --output ./output/book --config config.yaml --resume
```

Re-run only the translation stage (keeps existing `content.md`):

```bash
uv run python -u main.py --pdf book.pdf --output ./output/book --config config.yaml --resume-from translate
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and fill in your values:

```yaml
api:
  base_url: https://api.deepseek.com
  api_key: YOUR_API_KEY_HERE
  timeout: 120
  max_retries: 3
  max_tokens: 320000

runtime:
  workers: 4          # parallel LLM threads
  log_level: INFO

cleaning:
  model: deepseek-v4-flash
  prompt: ./prompts/cleaner.md
  batch_size: 10      # pages per LLM call
  context_pages: 1    # overlap pages for context

translation:
  model: deepseek-v4-pro
  prompt: ./prompts/translator.md
  glossary: ./glossary.csv   # optional: term -> translation CSV
  rules: ./rules.txt         # optional: plain-text translation rules
  max_tokens: 120000         # chunk size threshold
```

`glossary` and `rules` are optional; the pipeline skips them silently if the files do not exist.

## Customising prompts

Edit `prompts/cleaner.md` to change how pages are classified and formatted. Edit `prompts/translator.md` to change translation behaviour. Both files are Jinja-style templates — see the variable names at the top of each file.

For domain-specific translation, supply a `glossary.csv` (columns: `source,target`) and a `rules.txt` (free-form instructions injected into every translation request).

## Output layout

```
output/<name>/
  layout/                 # raw extraction (one file per page)
  cleaned/                # LLM cleaning results (JSON batches)
    logs/                 # raw LLM request/response logs
  cache_trans/            # per-chunk translation cache
    logs/                 # raw LLM request/response logs
  content.md              # cleaned original text
  translated.md           # Chinese translation
```

## Limitations

- Multi-column layouts are not detected; text order may be wrong for two-column pages.
- Mathematical formulae and figures are dropped.
- Tables are extracted as plain text without structure.
