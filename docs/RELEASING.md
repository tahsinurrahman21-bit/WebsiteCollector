# Publishing and releasing

## Can it be a standalone app?

**Yes.** Website Collector is a pure-Python Qt app, so it is packaged with **PyInstaller** into a folder containing `WebsiteCollector.exe`. Users download one ZIP, extract it and double-click the `.exe` — no Python, pip or setup needed.

| Piece | How the standalone build handles it |
| --- | --- |
| Python + packages (PySide6, PyMuPDF, httpx, …) | Bundled by PyInstaller in `_internal\` |
| Playwright driver (Node.js) | Bundled as package data |
| Chromium browser | Bundled in `browser_data\browsers` by default (about +150 MB). Build with `-NoBrowser` for a smaller ZIP; the app then falls back to Microsoft Edge, which every Windows 10/11 PC has. |
| LibreOffice | Not bundled (large, optional, separate license). Users install it if they want Word/PowerPoint pages. |
| Data folders | Created next to the `.exe` on first start (`packaging/launcher.py` passes `--root`). |

Expected size: roughly 150–250 MB without Chromium, 300–450 MB with it, which is well under GitHub's 2 GB limit per release file.

Known caveats:

- The `.exe` is not code-signed, so Windows SmartScreen will warn on first launch. Signing needs a paid certificate.
- The app must be extracted into a writable folder (not `Program Files`).
- `app/config.py` still has `DEFAULT_ROOT = G:/WebsiteCollector`. Both launchers (`run.bat` and the `.exe`) always pass the real folder with `--root`, so this only matters if someone runs `python -m app.main` without `--root`. Changing the default to the project folder is a recommended small follow-up.
- A few interface texts still mention the G: drive (Storage tab hint, LibreOffice file browser start folder, setup messages). These are cosmetic.

## Option 1 — Automatic build on GitHub (recommended)

The workflow `.github/workflows/release.yml` builds the ZIP on a Windows machine provided by GitHub:

1. Push the repository to GitHub (see below).
2. On GitHub, open **Releases → Draft a new release**.
3. Click **Choose a tag**, type `v1.1.1` and select **Create new tag on publish**.
4. Title: `Website Collector 1.1.1`. Paste the notes from `CHANGELOG.md`.
5. Click **Publish release**.
6. Open the **Actions** tab and wait for *Build Windows release* to turn green (about 10 minutes). The ZIP and its `.sha256` file are then attached to the release automatically.

To test a build without publishing, use **Actions → Build Windows release → Run workflow**. The ZIP appears under that run's **Artifacts**.

## Option 2 — Build on your own PC

```bat
build_release.bat
```

or, without bundling Chromium:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1 -NoBrowser
```

The result is `release\WebsiteCollector-<version>-windows-x64.zip` plus a `.sha256` file. **Test it:** extract it to a new folder, double-click `WebsiteCollector.exe` and collect one page. Then upload both files on the GitHub release page (drag them onto *Attach binaries*). `build/`, `dist/`, `release/` and `.venv-build/` are ignored by git.

## Publishing the repository with GitHub Desktop

1. **File → Add local repository…** → choose the project folder → if asked, click **create a repository** (Git ignore: *None* — the project already has a `.gitignore`; License: *None* — the project already has `LICENSE`).
2. In the **Changes** list, check that **only** these appear: `app/`, `tests/`, `packaging/`, `docs/`, `.github/`, the `.bat`/`.ps1` scripts, `requirements*.txt`, `README.md`, `QUICK_START.md`, `CHANGELOG.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, `.gitignore` and `.gitattributes`.
   It must **not** show `.venv`, `cache`, `temp`, `output`, `logs`, `browser_data`, `tools`, `work`, `deliverables`, `settings.json`, `last_urls.txt` or any `.zip`/`.msi`.
3. Summary: `Initial public release` → **Commit to main**.
4. **Publish repository** → untick *Keep this code private* if you want it public → **Publish repository**.
5. Create the release as described in Option 1.

## Before every release

- [ ] Bump `__version__` in `app/__init__.py` and the window title in `app/gui.py`.
- [ ] Add an entry to `CHANGELOG.md`.
- [ ] Run `run_tests.bat`.
- [ ] Check that no logs, outputs, settings or URL lists are staged.
- [ ] If dependency versions changed, update `requirements-lock.txt` and re-check `THIRD_PARTY_NOTICES.md`.
