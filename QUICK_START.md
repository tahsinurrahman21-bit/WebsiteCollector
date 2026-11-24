# Quick start

**Ready-to-run version (from the Releases page)**

1. Extract the ZIP into a folder you own (for example `Documents\WebsiteCollector`) — not into `Program Files`.
2. Double-click `WebsiteCollector.exe`. If Windows SmartScreen appears, click **More info → Run anyway**.

**Source version**

1. Install 64-bit Python 3.11–3.14 from python.org (tick *Add python.exe to PATH*).
2. Double-click `setup.bat` once and wait for *Setup finished*.
3. Double-click `run.bat` whenever you want to use the app.

**Using the app**

1. Paste website URLs, one per line, in the **Websites** tab.
2. Click **Start collection**.
3. Click **Open output folder** when it finishes. You get:
   - `website_content.txt` — page text, links and document text
   - `website_content.pdf` — page screenshots, images and document pages

Each run creates a new folder under `output\`, so earlier results are never overwritten. Click **Cancel** to stop early and keep a partial result.

Optional: install [LibreOffice](https://www.libreoffice.org/download/) to include Word and PowerPoint pages in the PDF.

Only collect content you are allowed to access. See **README.md** for settings, troubleshooting and limitations.
