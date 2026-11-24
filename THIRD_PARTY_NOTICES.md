# Third-party notices

Website Collector's own source code (the `app/`, `tests/` and `packaging/` folders and the scripts in the project root) is licensed under the GNU AGPL v3.0 (see `LICENSE`).

The project **does not own** any of the components below. They are installed by `setup.bat` from PyPI or downloaded from their official sources, and the standalone release bundles some of them. Each remains under its own license; their license files are included inside the installed packages (and inside `_internal\` in the standalone build).

## Python packages (versions from `requirements-lock.txt`)

| Component | Version | License | Project |
| --- | --- | --- | --- |
| PySide6 / shiboken6 (Qt for Python) | 6.11.2 | LGPL-3.0-only (or GPL-2.0/3.0) | https://www.qt.io/qt-for-python |
| Qt libraries (bundled with PySide6) | 6.11 | LGPL-3.0 | https://www.qt.io |
| Playwright for Python | 1.63.0 | Apache-2.0 | https://playwright.dev/python |
| PyMuPDF (MuPDF) | 1.28.2 | AGPL-3.0, or Artifex commercial license | https://pymupdf.readthedocs.io |
| httpx | 0.28.1 | BSD-3-Clause | https://www.python-httpx.org |
| httpcore | 1.0.9 | BSD-3-Clause | https://github.com/encode/httpcore |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| anyio | 4.15.1 | MIT | https://github.com/agronholm/anyio |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| beautifulsoup4 | 4.15.0 | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| soupsieve | 2.10 | MIT | https://github.com/facelessuser/soupsieve |
| lxml (libxml2, libxslt) | 6.1.3 | BSD-3-Clause (libxml2/libxslt: MIT) | https://lxml.de |
| python-docx | 1.2.0 | MIT | https://github.com/python-openxml/python-docx |
| python-pptx | 1.0.2 | MIT | https://github.com/scanny/python-pptx |
| XlsxWriter | 3.2.9 | BSD-2-Clause | https://github.com/jmcnamara/XlsxWriter |
| Pillow | 12.3.0 | MIT-CMU (HPND) | https://python-pillow.org |
| olefile | 0.47 | BSD-2-Clause | https://github.com/decalage2/olefile |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | https://github.com/python-greenlet/greenlet |
| pyee | 13.0.1 | MIT | https://github.com/jfhbrook/pyee |
| typing-extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |

Build-time only (not part of the source licence): PyInstaller (GPL-2.0-or-later with a bootloader exception that permits distributing the built application under any license).

## Other components

| Component | License | Notes |
| --- | --- | --- |
| Chromium (downloaded by Playwright) | BSD-3-Clause plus the licenses of its bundled third-party code | Downloaded by `setup.bat`; optionally bundled in the release under `browser_data\browsers`. Its own license/credits files are included in that folder. |
| Node.js runtime (inside Playwright's driver) | MIT | Bundled in the Playwright package. |
| Microsoft Edge / Google Chrome | Proprietary | Not distributed. Used only if already installed on the user's PC. |
| LibreOffice | MPL-2.0 (with parts under other licenses) | **Not distributed** by this project. Users install it themselves from https://www.libreoffice.org. |
| Python | PSF License | Not distributed with the source version; the standalone build bundles the Python runtime. |

## Notes for redistributors

- **PyMuPDF is AGPL-3.0.** Distributing Website Collector (source or binary) therefore requires complying with the AGPL — which is why this project uses the AGPL as well. Anyone who wants to distribute it under different terms needs a commercial PyMuPDF license from Artifex or must replace PyMuPDF.
- **Qt/PySide6 is LGPL-3.0.** The standalone build uses PyInstaller's one-folder mode, so the Qt DLLs remain separate, replaceable files in `_internal\`. Keep them that way and keep the license files.
- Keep `LICENSE`, this file and the license files shipped inside each package when you redistribute the app.
- Website content, screenshots and documents collected with the app belong to their respective owners and are not covered by this project's license.

This list was prepared from the package metadata on PyPI for the pinned versions. If you change dependency versions, re-check their licenses.
