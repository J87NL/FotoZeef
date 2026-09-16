from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "fotozeef" / "core"

PROBE = """
import importlib
import sys

for name in {modules!r}:
    importlib.import_module(name)

qt = {{"PySide6", "shiboken6"}}
leaked = sorted(m for m in sys.modules if m.split(".")[0] in qt)
if leaked:
    raise SystemExit("Qt leaked into core: " + ", ".join(leaked))
"""


def test_core_modules_import_without_qt() -> None:
    modules = sorted(
        f"fotozeef.core.{path.stem}" for path in CORE.glob("*.py") if path.stem != "__init__"
    )
    assert modules, "no core modules found"
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(modules=modules)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
