from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import DEFAULT_ROOT, Storage


def main() -> int:
    parser = argparse.ArgumentParser(description="Website Collector desktop app")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Explicitly select an installation/storage root; default G:/WebsiteCollector")
    args = parser.parse_args()
    storage = Storage.defaults(args.root)
    error = None
    try:
        storage.prepare()
    except OSError as exc:
        error = str(exc)
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    application = QApplication(sys.argv[:1])
    application.setApplicationName("Website Collector")
    application.setOrganizationName("Local tools")
    if error:
        QMessageBox.critical(None, "Storage unavailable", error)
        selected = QFileDialog.getExistingDirectory(None, "Select another storage location (Cancel to exit)")
        if not selected:
            return 1
        storage = Storage.defaults(Path(selected))
        try:
            storage.prepare()
        except OSError as exc:
            QMessageBox.critical(None, "Storage unavailable", str(exc))
            return 1
    from .gui import MainWindow
    window = MainWindow(storage)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
