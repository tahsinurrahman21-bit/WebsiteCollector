# Changelog

## 1.1.1 — first public release

- Batch collection of websites into one UTF-8 TXT and one PDF per run.
- Chromium screenshots (Playwright), clean HTML text extraction, linked PDF/DOCX/PPTX documents and content images.
- Optional LibreOffice integration for Word/PowerPoint pages and legacy DOC/PPT text.
- Fast mode (default) and optional GPU-accelerated browser rendering.
- Up to four concurrent resource downloads while honouring robots.txt and crawl delays.
- A failed DNS lookup or connection is retried once; persistent network errors name the host.
- Cancel saves a labelled partial TXT/PDF.
- Standalone Windows build (`WebsiteCollector.exe`) via PyInstaller; falls back to Microsoft Edge if Chromium is not bundled.
