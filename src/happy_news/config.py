"""Load the three YAML files that configure the system."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    root: Path
    sources: dict[str, Any]
    editorial: dict[str, Any]
    evergreen: list[dict[str, Any]]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required config file is missing: {path}")
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load(root: Path | None = None) -> Config:
    root = Path(root) if root is not None else PACKAGE_ROOT
    feeds = root / "feeds"
    sources = _read_yaml(feeds / "sources.yaml")
    editorial = _read_yaml(feeds / "editorial.yaml")
    evergreen_data = _read_yaml(feeds / "evergreen.yaml")
    return Config(
        root=root,
        sources=sources,
        editorial=editorial,
        evergreen=evergreen_data.get("stories", []),
    )
