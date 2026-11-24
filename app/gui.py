from __future__ import annotations

import traceback
import os
import time
from dataclasses import asdict
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal, Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QDoubleSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .config import Storage
from .crawler import Collector
from .document_parser import find_libreoffice
from .models import Options
from .urls import parse_urls


STYLE = """
QMainWindow, QWidget#central { background: #f1f5f7; color: #20313d; }
QWidget { font-family: 'Segoe UI'; font-size: 10pt; }
QLabel#title { font-size: 25pt; font-weight: 650; color: #133940; }
QLabel#subtitle { color: #52636f; font-size: 11pt; }
QLabel#badge { color: #0b6257; background: #dcefe7; border-radius: 10px; padding: 7px 12px; }
QTabWidget::pane { border: 1px solid #d5dfe4; background: white; border-radius: 6px; }
QTabBar::tab { background: #e8eff2; padding: 11px 24px; border: 0; }
QTabBar::tab:selected { background: white; color: #087b78; font-weight: 600; }
QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox { background: white; color: #20313d; border: 1px solid #c4d1d8; border-radius: 5px; padding: 7px; selection-background-color: #b3e2df; }
QPushButton { padding: 9px 16px; border: 1px solid #bfcdd3; border-radius: 5px; background: white; color: #294653; }
QPushButton:hover { background: #e7f3f2; }
QPushButton#start { background: #087b78; color: white; border: 0; font-weight: 600; padding: 11px 25px; }
QPushButton#start:hover { background: #096b68; }
QPushButton:disabled { background: #e6ecef; color: #88959c; }
QProgressBar { background: #dde7ec; border: 0; border-radius: 5px; min-height: 15px; text-align: center; }
QProgressBar::chunk { background: #159b91; border-radius: 5px; }
QCheckBox { spacing: 9px; padding: 5px; }
QLabel#hint { color: #61747d; }
"""


class CollectionWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, storage, options, urls, parent=None):
        super().__init__(parent)
        self.storage, self.options, self.urls = storage, options, urls
        self.stop = Event()

    def run(self):
        try:
            result = Collector(self.storage, self.options, self.stop, self.log.emit, self.progress.emit).run(self.urls)
            self.completed.emit(result)
        except Exception as exc:
            self.log.emit(traceback.format_exc())
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage):
        super().__init__()
        # Explicit registration also supports offscreen checks and machines where Qt's
        # platform font discovery does not enumerate the Windows UI fonts.
        if not getattr(MainWindow, "_fonts_loaded", False):
            font_folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            for filename in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"):
                font = font_folder / filename
                if font.is_file():
                    QFontDatabase.addApplicationFont(str(font))
            MainWindow._fonts_loaded = True
        self.storage = storage
        self.worker = None
        self.closing = False
        self.latest_folder = None
        self.run_started = None
        self.current_activity = ""
        self.setWindowTitle("Website Collector 1.1.1 · Fast + GPU")
        self.resize(1080, 900)
        self.setMinimumSize(760, 650)
        self.setStyleSheet(STYLE)
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(13)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Website Collector", objectName="title"))
        heading.addStretch()
        heading.addWidget(QLabel("LOCAL PROCESSING  ·  ZERO AI TOKENS", objectName="badge"))
        layout.addLayout(heading)
        subtitle = QLabel("Collect website text, screenshots and linked documents into one TXT and one PDF.", objectName="subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 3)
        self.checks = {}
        self.spins = {}
        self.paths = {}
        self.build_urls_tab()
        self.build_options_tab()
        self.build_storage_tab()
        actions = QHBoxLayout()
        self.start_button = QPushButton("Start collection", objectName="start")
        self.start_button.clicked.connect(self.start_collection)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_collection)
        self.open_button = QPushButton("Open output folder")
        self.open_button.clicked.connect(self.open_output)
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.open_button)
        layout.addLayout(actions)
        self.status = QLabel("Ready. Paste URLs to begin.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("%v / %m websites")
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.activity_bar = QProgressBar()
        self.activity_bar.setTextVisible(False)
        self.activity_bar.setFixedHeight(7)
        self.activity_bar.setRange(0, 1)
        self.activity_bar.setValue(0)
        layout.addWidget(self.activity_bar)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Activity log"))
        log_header.addStretch()
        clear = QPushButton("Clear log")
        clear.clicked.connect(lambda: self.log_panel.clear())
        log_header.addWidget(clear)
        layout.addLayout(log_header)
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(3000)
        self.log_panel.setMinimumHeight(110)
        layout.addWidget(self.log_panel, 1)
        self.load_settings()
        saved_urls = self.storage.root / "last_urls.txt"
        if saved_urls.is_file():
            try:
                self.urls.setPlainText(saved_urls.read_text(encoding="utf-8"))
            except OSError:
                pass
        self.update_url_count()
        self.ticker = QTimer(self)
        self.ticker.setInterval(1000)
        self.ticker.timeout.connect(self.refresh_activity)

    def build_urls_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(QLabel("Website URLs · one per line"))
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText("https://example.com/article\nhttps://example.org/course/materials\n\nBlank lines and duplicate URLs are ignored.")
        self.urls.setMinimumHeight(170)
        self.urls.textChanged.connect(self.update_url_count)
        layout.addWidget(self.urls, 1)
        self.url_count = QLabel("0 unique URLs", objectName="hint")
        layout.addWidget(self.url_count)
        speed_row = QHBoxLayout()
        for name, label in (("fast_mode", "Fast mode"), ("use_gpu", "Use GPU for browser rendering")):
            check = QCheckBox(label)
            check.setChecked(True)
            self.checks[name] = check
            speed_row.addWidget(check)
        speed_row.addStretch()
        layout.addLayout(speed_row)
        speed_hint = QLabel("Fast mode skips guessing whether ordinary links hide documents. Direct document downloads and webpage captures stay enabled.", objectName="hint")
        speed_hint.setWordWrap(True)
        layout.addWidget(speed_hint)
        note = QLabel("Use content you have permission to collect. The app checks robots.txt and stops at access restrictions, login gates and verification challenges.", objectName="hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs.addTab(tab, "Websites")

    def build_options_tab(self):
        content = QWidget()
        outer = QVBoxLayout(content)
        checks = QGridLayout()
        entries = [("include_images", "Include website images in PDF"), ("download_pdf", "Download linked PDFs"),
                   ("download_ppt", "Download linked PPT / PPTX"), ("download_doc", "Download linked DOC / DOCX"),
                   ("follow_pages", "Follow linked webpages (same website only)"), ("show_browser", "Show browser while processing")]
        defaults = Options()
        for index, (name, label) in enumerate(entries):
            check = QCheckBox(label)
            check.setChecked(getattr(defaults, name))
            self.checks[name] = check
            checks.addWidget(check, index // 2, index % 2)
        outer.addLayout(checks)
        form = QFormLayout()
        settings = [("timeout", "Page / connection timeout (seconds)", 5, 180),
                    ("download_workers", "Concurrent resource downloads", 1, 8),
                    ("settle_seconds", "Extra wait for page content (seconds)", 0, 30),
                    ("max_file_mb", "Maximum individual download (MB)", 1, 2048),
                    ("min_image_width", "Minimum image width (pixels)", 32, 4000),
                    ("min_image_height", "Minimum image height (pixels)", 32, 4000),
                    ("max_images", "Image candidates per website", 0, 500),
                    ("max_documents", "Linked documents per website", 0, 500),
                    ("max_link_probes", "Check untyped links for documents (limit)", 0, 500),
                    ("max_followed", "Extra webpages for the whole batch", 1, 500),
                    ("follow_depth", "Linked webpage depth", 1, 5),
                    ("max_capture_sections", "Maximum capture sections per website", 1, 500),
                    ("conversion_timeout", "Document conversion timeout (seconds)", 15, 600)]
        for name, label, low, high in settings:
            spin = QDoubleSpinBox() if name == "settle_seconds" else QSpinBox()
            spin.setRange(low, high)
            spin.setValue(getattr(defaults, name))
            self.spins[name] = spin
            form.addRow(label, spin)
        self.office_path = QLineEdit()
        self.office_path.setPlaceholderText("Auto-detect LibreOffice, or browse to soffice.exe")
        office_row = QHBoxLayout()
        office_row.addWidget(self.office_path)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.select_office)
        office_row.addWidget(browse)
        form.addRow("LibreOffice (optional)", office_row)
        office_note = QLabel("LibreOffice renders Word and PowerPoint pages. Without it, DOCX/PPTX text still works; legacy DOC/PPT needs it for text too.", objectName="hint")
        office_note.setWordWrap(True)
        outer.addLayout(form)
        outer.addWidget(office_note)
        outer.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, "Collection options")

    def build_storage_tab(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        intro = QLabel("All defaults use G:. Choose any writable location below. Every collection gets a new subfolder, so existing outputs remain safe.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        for name, label in [("output", "Final output"), ("cache", "Downloads and captures"),
                            ("temp", "Temporary conversion files"), ("browser", "Browser profiles and cache"), ("logs", "Logs")]:
            entry = QLineEdit(str(getattr(self.storage, name)))
            self.paths[name] = entry
            row = QHBoxLayout()
            row.addWidget(entry)
            button = QPushButton("Browse…")
            button.clicked.connect(lambda checked=False, target=entry: self.select_folder(target))
            row.addWidget(button)
            form.addRow(label, row)
        layout.addLayout(form)
        hint = QLabel(f"Project and browser installation: {self.storage.root}\n\nFiles are kept after collection. The app never automatically cleans your folders or deletes earlier outputs.", objectName="hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        self.tabs.addTab(content, "Storage")

    def select_folder(self, target):
        result = QFileDialog.getExistingDirectory(self, "Choose storage folder", target.text())
        if result:
            target.setText(result)

    def select_office(self):
        result, _ = QFileDialog.getOpenFileName(self, "Choose LibreOffice executable", "G:/", "LibreOffice (soffice.exe soffice.com);;All files (*)")
        if result:
            self.office_path.setText(result)

    def update_url_count(self):
        urls, errors = parse_urls(self.urls.toPlainText())
        self.url_count.setText(f"{len(urls)} unique URL{'s' if len(urls) != 1 else ''}" + (f" · {len(errors)} invalid lines will be skipped" if errors else ""))
        if hasattr(self, "progress_bar") and not (self.worker and self.worker.isRunning()):
            self.progress_bar.setRange(0, max(1, len(urls)))
            self.progress_bar.setFormat("%v / %m websites" if urls else "Ready")
            self.progress_bar.setValue(0)

    def load_settings(self):
        data = self.storage.settings()
        for name, path in data.get("storage", {}).items():
            if name in self.paths and isinstance(path, str):
                self.paths[name].setText(path)
        for name, value in data.get("options", {}).items():
            if name in self.checks and isinstance(value, bool):
                self.checks[name].setChecked(value)
            elif name in self.spins and isinstance(value, (int, float)):
                self.spins[name].setValue(value)
            elif name == "libreoffice" and isinstance(value, str):
                self.office_path.setText(value)

    def start_collection(self):
        if self.worker and self.worker.isRunning():
            return
        urls, errors = parse_urls(self.urls.toPlainText())
        if not urls:
            QMessageBox.information(self, "Add website URLs", "Paste at least one valid HTTP or HTTPS website URL, one per line.")
            return
        try:
            for name, entry in self.paths.items():
                if not entry.text().strip() or not Path(entry.text()).is_absolute():
                    raise ValueError(f"Choose an absolute folder path for {name}.")
                setattr(self.storage, name, Path(entry.text()))
            self.storage.prepare()
            values = {name: check.isChecked() for name, check in self.checks.items()}
            values.update({name: spin.value() for name, spin in self.spins.items()})
            values["libreoffice"] = self.office_path.text().strip()
            options = Options(**values)
            self.storage.save_settings(asdict(options))
            (self.storage.root / "last_urls.txt").write_text(self.urls.toPlainText(), encoding="utf-8")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Storage is unavailable", str(exc))
            return
        self.log_panel.clear()
        for error in errors:
            self.log_panel.appendPlainText("Skipped " + error)
        if not find_libreoffice(options.libreoffice):
            self.log_panel.appendPlainText("LibreOffice was not found. Office visuals and legacy DOC/PPT text will be reported as unavailable.")
        self.worker = CollectionWorker(self.storage, options, urls, self)
        self.worker.log.connect(self.on_log)
        self.worker.progress.connect(self.on_progress)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.on_finished)
        self.tabs.setEnabled(False)
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, len(urls))
        self.progress_bar.setFormat("%v / %m websites")
        self.progress_bar.setValue(0)
        self.activity_bar.setRange(0, 0)
        self.run_started = time.monotonic()
        self.current_activity = "Starting collection…"
        self.ticker.start()
        self.status.setText("Starting collection…")
        self.worker.start()

    def cancel_collection(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop.set()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling… finishing the current operation and saving collected results.")
            self.log_panel.appendPlainText("Cancel requested. The current browser call or PDF save may need time to finish.")

    def on_progress(self, done, total, message):
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(done)
        if self.worker and not self.worker.stop.is_set():
            self.current_activity = message
            self.refresh_activity()

    def on_log(self, message):
        self.log_panel.appendPlainText(message)
        if self.worker and not self.worker.stop.is_set():
            self.current_activity = message[:240]
            self.refresh_activity()

    def refresh_activity(self):
        if self.run_started is None:
            return
        elapsed = time.monotonic() - self.run_started
        clock = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        if self.worker and self.worker.stop.is_set():
            self.status.setText(f"Elapsed {clock} · Cancelling and saving partial results…")
        else:
            self.status.setText(f"Elapsed {clock} · {self.current_activity}")

    def on_completed(self, result):
        self.ticker.stop()
        self.latest_folder = result.folder
        prefix = "Cancelled · partial files saved" if result.cancelled else "Collection complete"
        elapsed = time.monotonic() - self.run_started if self.run_started else 0
        self.status.setText(f"{prefix} in {elapsed:.1f}s. {result.processed} websites · {result.failed} failed · {result.warnings} notes.\n{result.folder}")
        if not result.cancelled:
            self.progress_bar.setValue(self.progress_bar.maximum())

    def on_failed(self, message):
        self.ticker.stop()
        self.status.setText("Collection could not finish: " + message)
        if not self.closing:
            QMessageBox.critical(self, "Collection could not finish", message + "\n\nCheck the activity log. Earlier outputs have not been overwritten.")

    def on_finished(self):
        self.ticker.stop()
        self.run_started = None
        self.activity_bar.setRange(0, 1)
        self.activity_bar.setValue(1)
        self.tabs.setEnabled(True)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if self.closing:
            self.close()

    def open_output(self):
        folder = self.latest_folder or Path(self.paths["output"].text())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.closing = True
            self.cancel_collection()
            event.ignore()
        else:
            event.accept()
