"""Entry point for the browser version; desktop behavior stays in app_6.py."""

from __future__ import annotations

import os
import runpy
from pathlib import Path


os.environ["SISTEMA_WEB_MODE"] = "1"
APP_SCRIPT = Path(__file__).resolve().with_name("app_6.py")
runpy.run_path(str(APP_SCRIPT), run_name="__main__")
