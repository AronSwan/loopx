from __future__ import annotations

import os
from pathlib import Path

ZCODE_INSTALL_SURFACE = "zcode"
ZCODE_HOME_ENV = "ZCODE_HOME"
DEFAULT_ZCODE_HOME = ".zcode"
SKILLS_SUBDIR = "skills"
SKILLS_ROOT_LABEL = "ZCODE_HOME/skills"


def zcode_home(value: str | None = None) -> Path:
    """ZCode discovers user skills from ZCODE_HOME/skills (default ~/.zcode).

    While ZCode provides native Goal Mode and Automations, LoopX currently
    reaches ZCode through its skill facade where the session turn loop is
    gated by LoopX quota should-run.
    """
    raw = (
        value
        or os.environ.get(ZCODE_HOME_ENV)
        or os.environ.get("ZCODE_AGENTS_HOME")
        or str(Path.home() / DEFAULT_ZCODE_HOME)
    )
    return Path(raw).expanduser()
