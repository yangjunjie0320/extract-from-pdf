from pathlib import Path

import yaml

_REQUIRED_FIELDS: list[tuple[str, ...]] = [
    ("api", "base_url"),
    ("api", "api_key"),
    ("cleaning", "model"),
    ("cleaning", "prompt"),
    ("translation", "model"),
    ("translation", "prompt"),
]


def _get_nested(cfg: dict, *keys: str) -> object:
    node: object = cfg
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def load_config(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.example.yaml to config.yaml and fill in the values."
        )
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid config file: {path}\nExpected a YAML mapping.")

    missing = []
    for keys in _REQUIRED_FIELDS:
        if _get_nested(cfg, *keys) is None:
            missing.append(".".join(keys))
    if missing:
        raise ValueError(
            f"Missing required config fields: {', '.join(missing)}\nAdd them to {path}."
        )

    api_key = cfg["api"]["api_key"]
    if api_key in ("YOUR_API_KEY_HERE", "", None):
        raise ValueError(
            "api.api_key is not set in config.yaml.\n"
            "Replace the placeholder with your actual API key."
        )

    return cfg
