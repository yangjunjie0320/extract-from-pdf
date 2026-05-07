import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_CONTENT_PATTERN = re.compile(
    r"% content begin\n.*?% content end",
    re.DOTALL,
)


def write_latex(
    translated_path: Path,
    output_path: Path,
    cfg: dict,
) -> None:
    tmpl_str: str = cfg.get("latex", {}).get("template", "")
    tmpl_path = Path(tmpl_str)
    if not tmpl_path.exists():
        raise RuntimeError(
            f"LaTeX template not found: {tmpl_path}\n"
            "Check latex.template in config.yaml."
        )

    try:
        result = subprocess.run(
            ["pandoc", "-f", "markdown", "-t", "latex", str(translated_path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "pandoc not found in PATH.\n"
            "Install pandoc (https://pandoc.org/installing.html) or remove latex.template from config.yaml."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"pandoc failed (exit {e.returncode}):\n{e.stderr.strip()}"
        ) from e

    body = result.stdout

    template = tmpl_path.read_text(encoding="utf-8")
    if not _CONTENT_PATTERN.search(template):
        raise RuntimeError(
            f"Template {tmpl_path} is missing content markers.\n"
            "Add these two lines where the body should appear:\n"
            "  % content begin\n"
            "  % content end"
        )

    replacement = "% content begin\n" + body.rstrip("\n") + "\n% content end"
    filled = _CONTENT_PATTERN.sub(lambda _: replacement, template)
    output_path.write_text(filled, encoding="utf-8")
