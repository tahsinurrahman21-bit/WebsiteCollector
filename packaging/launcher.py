"""Entry point used for the standalone (PyInstaller) Windows build.

The normal source install starts the app with ``run.bat``, which passes
``--root <project folder>``.  A frozen ``WebsiteCollector.exe`` has no batch
launcher, so this wrapper supplies the folder that contains the executable as
the storage root.  All data (cache, temp, output, logs, browser_data,
settings.json) is therefore kept next to the .exe, exactly like the source
version keeps it next to run.bat.

This file does not change any application behaviour; it only chooses the
root folder before handing over to ``app.main.main``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main() -> int:
    root = _install_root()
    # Same environment the batch launcher sets up.
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(root / "browser_data" / "browsers")
    temp = root / "temp"
    try:
        temp.mkdir(parents=True, exist_ok=True)
        for key in ("TEMP", "TMP", "TMPDIR"):
            os.environ[key] = str(temp)
    except OSError:
        pass  # app.main reports unwritable storage and offers another folder

    if not getattr(sys, "frozen", False) and str(root) not in sys.path:
        sys.path.insert(0, str(root))  # allow `python packaging/launcher.py`

    if "--root" not in sys.argv[1:]:
        sys.argv = [sys.argv[0], "--root", str(root), *sys.argv[1:]]

    from app.main import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
