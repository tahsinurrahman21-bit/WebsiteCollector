from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .config import Storage


def main():
    root = Path(__file__).resolve().parent.parent
    storage = Storage.defaults(root)
    storage.prepare()
    print("Website Collector setup check")
    print("Project:", root)
    print("Python:", sys.executable)
    failures = 0
    for package in ("PySide6", "playwright", "httpx", "bs4", "lxml", "pymupdf", "docx", "pptx", "PIL", "olefile"):
        try:
            importlib.import_module(package)
            print("OK:", package)
        except ImportError as exc:
            failures += 1
            print("MISSING:", package, str(exc))
    if not failures:
        from playwright.sync_api import sync_playwright
        from .browser import installed_browser
        from .document_parser import find_libreoffice
        with sync_playwright() as playwright:
            if Path(playwright.chromium.executable_path).is_file():
                print("OK: downloaded Chromium")
            elif installed_browser():
                print("OK: Playwright can use", installed_browser())
            else:
                failures += 1
                print("MISSING: browser. Rerun setup.bat or install Microsoft Edge.")
        office = find_libreoffice()
        print("LibreOffice:", office or "Optional; not installed. Office visuals and legacy DOC/PPT text will be unavailable.")
    print("Runtime processing is local. No LLM services, keys or tokens are used.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
