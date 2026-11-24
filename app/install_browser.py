"""Install the exact Playwright Chromium build with Windows curl if Node download fails."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import playwright
from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(root / "browser_data" / "browsers")
    with sync_playwright() as instance:
        executable = Path(instance.chromium.executable_path)
    if executable.is_file():
        print("Chromium is already installed:", executable)
        return 0
    metadata = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    browser = next(item for item in json.loads(metadata.read_text(encoding="utf-8"))["browsers"] if item["name"] == "chromium")
    version = browser["browserVersion"]
    # This fallback supports Playwright releases using the official Chrome for Testing layout.
    if os.name != "nt" or executable.parent.name != "chrome-win64":
        print("Run: python -m playwright install chromium")
        return 1
    url = f"https://cdn.playwright.dev/builds/cft/{version}/win64/chrome-win64.zip"
    archive = root / "temp" / f"chromium-{browser['revision']}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["curl.exe", "--fail", "--location", "--retry", "2", "--connect-timeout", "20",
                             "--max-time", "600", "--max-filesize", str(600 * 1048576),
                             "--output", str(archive), url])
    if result.returncode:
        print("Browser download failed. Check the connection, then rerun setup.bat.")
        return 1
    destination = executable.parent.parent.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        if sum(item.file_size for item in bundle.infolist()) > 2 * 1024**3:
            raise RuntimeError("Unexpected browser archive size")
        for item in bundle.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination):
                raise RuntimeError("Unsafe path in browser archive")
        bundle.extractall(destination)
    if not executable.is_file():
        raise RuntimeError("Browser archive did not contain the expected executable")
    (destination / "INSTALLATION_COMPLETE").touch()
    print("Chromium installed:", executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
