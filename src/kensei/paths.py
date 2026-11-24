from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_dir, user_state_dir


def root() -> Path:
    """Repo root of the Kensei subproject (kensei/)."""
    override = os.environ.get("KENSEI_HOME")
    if override:
        return Path(override).expanduser().resolve()
    # src/kensei/paths.py -> src/kensei -> src -> kensei
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    override = os.environ.get("KENSEI_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return root() / "data"


def data_dir(*parts: str) -> Path:
    return data_root().joinpath(*parts)


def derived_dir(*parts: str) -> Path:
    return data_dir("derived", *parts)


def config_dir(*parts: str) -> Path:
    return (root() / "config").joinpath(*parts)


def models_dir(*parts: str) -> Path:
    return (root() / "models").joinpath(*parts)


def prompt_path() -> Path:
    return root() / "prompts" / "kensei_system.md"


def default_scope_path() -> Path:
    return Path(user_config_dir("kensei", appauthor=False)) / "scope.yaml"


def state_dir() -> Path:
    return Path(user_state_dir("kensei", appauthor=False))


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
