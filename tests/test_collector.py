from __future__ import annotations

import io
import os
import subprocess
import threading
import time
import unittest
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "tests" / uuid.uuid4().hex
WORK.mkdir(parents=True)
os.environ["TEMP"] = str(ROOT / "temp")
os.environ["TMP"] = str(ROOT / "temp")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "browser_data" / "browsers")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PIL import Image, ImageDraw
from docx import Document
from pptx import Presentation
from pptx.util import Inches

from app.config import Storage
from app.crawler import Collector
from app.document_parser import DocumentParser, detect_document, find_libreoffice
from app.extract import extract_html
from app.models import Cancelled, Options
from app.network import AccessError, Download, DownloadError, Fetcher
from app.urls import classify, normalize_url, parse_urls


def make_fixtures():
    image = Image.new("RGB", (720, 420), "#e8f5f3")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 80, 150, 360), fill="#11877e")
    draw.rectangle((210, 160, 320, 360), fill="#236c9a")
    draw.rectangle((380, 40, 490, 360), fill="#eaae40")
    draw.text((40, 15), "Local sample chart", fill="#17393f")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    pdf = pymupdf.open()
    for label in ("Fixture PDF page one", "Fixture PDF page two"):
        page = pdf.new_page()
        page.insert_text((50, 100), label, fontsize=20)
    pdf_bytes = pdf.tobytes()
    pdf.close()
    doc = Document()
    doc.add_heading("DOCX local heading", 1)
    doc.add_paragraph("Bangla: বাংলা লেখা. Hindi: हिन्दी पाठ.")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Table left"
    table.cell(0, 1).text = "Table right"
    word = io.BytesIO()
    doc.save(word)
    presentation = Presentation()
    for label in ("First slide text", "Second slide text"):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2))
        box.text_frame.text = label
    slides = io.BytesIO()
    presentation.save(slides)
    return buffer.getvalue(), pdf_bytes, word.getvalue(), slides.getvalue()


IMAGE, PDF, DOCX, PPTX = make_fixtures()
REQUESTS = Counter()
ACTIVE_DOWNLOADS = 0
MAX_ACTIVE_DOWNLOADS = 0
ACTIVE_LOCK = threading.Lock()


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_HEAD(self):
        if urlsplit(self.path).path == "/untyped":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        else:
            self.send_response(405)
        self.end_headers()

    def do_GET(self):
        global ACTIVE_DOWNLOADS, MAX_ACTIVE_DOWNLOADS
        path = urlsplit(self.path).path
        REQUESTS[path] += 1
        status = 200
        content_type = "text/html; charset=utf-8"
        headers = {}
        if path == "/robots.txt":
            data = b"User-agent: *\nDisallow: /blocked\n"
            content_type = "text/plain"
        elif path == "/alpha":
            data = '''<!doctype html><html><head><title>Local lesson · বাংলা</title>
<style>body{font:20px 'Segoe UI';margin:40px;color:#17393f} .hidden{display:none} main{max-width:900px} section{margin:30px 0}</style>
<meta name="description" content="A deterministic local integration fixture."></head><body>
<nav>Navigation noise</nav><main><h1>Local learning materials</h1><p>English text. বাংলা লেখা। हिन्दी पाठ।</p>
<p class="hidden">COMPUTED_HIDDEN_NOISE</p><script>window.scriptNoise='DO_NOT_DUMP_SCRIPTS';</script>
<h2>Resources</h2><ul><li>First useful item</li><li>Second useful item</li></ul>
<table><tr><th>Topic</th><th>Value</th></tr><tr><td>Physics</td><td>42</td></tr></table>
<figure><img src="/chart.png" alt="A chart with three columns"><figcaption>Example lesson figure</figcaption></figure>
<p><a href="/notes.pdf">Lecture PDF</a> · <a href="/notes.docx">Lecture Word document</a> · <a href="/slides.pptx">Slides</a></p>
<p><a href="/download?kind=pdf" download>Download PDF without extension</a></p>
<p><a href="/untyped">Resource without type hint</a></p>
<p><a href="/blocked/secret.pdf">Blocked PDF</a> · <a href="/fake.pdf">Broken PDF</a></p>
<p><a href="/beta">Related webpage</a></p></main><footer>Footer noise</footer></body></html>'''.encode("utf-8")
        elif path == "/beta":
            data = b"<!doctype html><html><head><title>Second website</title></head><body><main><h1>Second website</h1><p>Batch continuation succeeded.</p></main></body></html>"
        elif path == "/js":
            data = b"<!doctype html><html><head><title>JS fixture</title></head><body><main id='app'></main><script>setTimeout(()=>{document.getElementById('app').innerHTML='<h1>Rendered JavaScript heading</h1><p>Dynamic lesson content</p>';},200)</script></body></html>"
        elif path == "/long":
            blocks = "".join(f'<section style="height:1100px"><h2>Long section {i}</h2><p>Readable content for section {i}.</p></section>' for i in range(1, 5))
            data = f"<!doctype html><html><head><title>Long fixture</title></head><body style='margin:40px;font:24px sans-serif'><main>{blocks}</main></body></html>".encode()
        elif path in {"/notes.pdf", "/download", "/untyped"}:
            data, content_type = PDF, "application/pdf"
        elif path == "/notes.docx":
            data, content_type = DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif path == "/slides.pptx":
            data, content_type = PPTX, "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        elif path == "/chart.png":
            data, content_type = IMAGE, "image/png"
        elif path == "/fake.pdf":
            data = b"<html><body>Not a PDF</body></html>"
        elif path == "/redirect-blocked":
            data, status, headers = b"", 302, {"Location": "/blocked/secret.pdf"}
        elif path == "/huge":
            data, content_type = b"X" * 20000, "application/octet-stream"
        elif path == "/chunked-big":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(b"X" * 20000)
            return
        elif path.startswith("/parallel/"):
            with ACTIVE_LOCK:
                ACTIVE_DOWNLOADS += 1
                MAX_ACTIVE_DOWNLOADS = max(MAX_ACTIVE_DOWNLOADS, ACTIVE_DOWNLOADS)
            try:
                time.sleep(0.8)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(IMAGE)))
                self.end_headers()
                self.wfile.write(IMAGE)
            finally:
                with ACTIVE_LOCK:
                    ACTIVE_DOWNLOADS -= 1
            return
        elif path == "/slow":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", "50000")
            self.end_headers()
            try:
                for _ in range(50):
                    self.wfile.write(b"X" * 1000)
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        elif path == "/restricted":
            data, status = b"Access denied", 403
        else:
            data, status = b"Missing", 404
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)


class BasicTests(unittest.TestCase):
    def test_normalization_dedup_and_unicode(self):
        urls, errors = parse_urls("HTTPS://EXAMPLE.COM:443/%7euser#top\nhttps://example.com/~user\n\nexample.org/বাংলা?q=1\nftp://example.com/a\n")
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0], "https://example.com/~user")
        self.assertIn("%E0", urls[1])
        self.assertEqual(len(errors), 1)
        self.assertNotEqual(normalize_url("https://example.com/?x=1"), normalize_url("https://example.com/?x=2"))
        self.assertEqual(normalize_url("https://example.com/#/lesson"), "https://example.com/#/lesson")
        with self.assertRaises(ValueError):
            normalize_url("https://user:password@example.com/")

    def test_semantic_extraction_and_noise(self):
        content = extract_html('''<html><head><title>Lesson</title></head><body><nav>NOISE_NAV</nav><main><h1>বাংলা</h1><p>Hello हिन्दी</p><script>NOISE_JS</script><style>NOISE_STYLE</style><div hidden>NOISE_HIDDEN</div><p style="display: none">NOISE_INLINE</p><ul><li>Point</li></ul><table><tr><td>A</td><td>B</td></tr></table><a href="/f.PDF?q=1">Notes</a></main><footer>NOISE_FOOTER</footer></body></html>''', "https://example.com/")
        self.assertIn("# বাংলা", content.text)
        self.assertIn("Hello हिन्दी", content.text)
        self.assertIn("A | B", content.text)
        self.assertNotIn("NOISE", content.text)
        self.assertEqual(content.links[0].kind, "pdf")

    def test_documents_extract_unicode_and_order_without_office(self):
        parser = DocumentParser(WORK / "office-temp", Options(), threading.Event(), print)
        parser.soffice = ""
        for data, kind in ((PDF, "pdf"), (DOCX, "docx"), (PPTX, "pptx")):
            path = WORK / (uuid.uuid4().hex + ".download")
            path.write_bytes(data)
            self.assertEqual(detect_document(path), kind)
            result = parser.parse(Download(path, "https://example.com/resource", "application/octet-stream"), "Lesson." + kind)
            if kind == "docx":
                self.assertIn("বাংলা লেখা", result.text)
                self.assertIn("हिन्दी पाठ", result.text)
                self.assertIn("Table left | Table right", result.text)
                self.assertIsNone(result.visual_pdf)
                self.assertTrue(result.warnings)
            elif kind == "pptx":
                self.assertLess(result.text.index("First slide"), result.text.index("Second slide"))
            else:
                self.assertLess(result.text.index("page one"), result.text.index("page two"))

    def test_image_only_pdf_and_invalid_type(self):
        path = WORK / "scanned.download"
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_image(page.rect, stream=IMAGE)
            document.save(path)
        result = DocumentParser(WORK, Options(), threading.Event(), print).parse(Download(path, "https://example.com/scanned.pdf", "application/pdf"))
        self.assertEqual(result.text, "")
        self.assertIsNotNone(result.visual_pdf)
        self.assertIn("OCR", result.warnings[0])
        fake = WORK / "fake.pdf"
        fake.write_text("<html>not a document</html>", encoding="utf-8")
        self.assertEqual(detect_document(fake), "")

    def test_libreoffice_visuals_and_legacy_text(self):
        office = find_libreoffice()
        if not office:
            self.skipTest("Optional LibreOffice is not installed")
        folder = WORK / "office-validation"
        folder.mkdir()
        parser = DocumentParser(folder / "temp", Options(), threading.Event(), print)
        cases = []
        for data, modern, legacy, export_filter, expected, pages in (
            (DOCX, "docx", "doc", "MS Word 97", "DOCX local heading", 1),
            (PPTX, "pptx", "ppt", "MS PowerPoint 97", "First slide text", 2),
        ):
            source = folder / ("fixture." + modern)
            source.write_bytes(data)
            profile = folder / ("export-profile-" + legacy)
            completed = subprocess.run(
                [office, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo",
                 "--nofirststartwizard", "--convert-to", f"{legacy}:{export_filter}",
                 "--outdir", str(folder), str(source)], capture_output=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            legacy_path = source.with_suffix("." + legacy)
            self.assertTrue(legacy_path.is_file(), completed.stdout + completed.stderr)
            self.assertEqual(detect_document(legacy_path), legacy)
            cases.extend([(source, modern, expected, pages), (legacy_path, legacy, expected, pages)])
        for source, kind, expected, pages in cases:
            with self.subTest(format=kind):
                downloaded = folder / (kind + ".download")
                downloaded.write_bytes(source.read_bytes())
                result = parser.parse(Download(downloaded, "https://example.com/fixture." + kind,
                                               "application/octet-stream"), "Fixture." + kind)
                self.assertFalse(result.warnings, result.warnings)
                self.assertIn(expected, result.text)
                self.assertIsNotNone(result.visual_pdf)
                with pymupdf.open(result.visual_pdf) as document:
                    self.assertEqual(len(document), pages)
                    self.assertIn(expected, document[0].get_text())
                    if kind in {"ppt", "pptx"}:
                        self.assertIn("Second slide text", document[1].get_text())
                    document[0].get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2)).save(
                        ROOT / "work" / ("libreoffice-" + kind + "-preview.png"))

    def test_missing_drive_is_explicit(self):
        if os.name != "nt":
            self.skipTest("Windows drive validation")
        missing = next((letter for letter in "ZYXWVUTSRQ" if not Path(letter + ":/").exists()), None)
        if not missing:
            self.skipTest("No unused drive letter")
        with self.assertRaisesRegex(OSError, "unavailable"):
            Storage.defaults(Path(missing + ":/WebsiteCollector")).prepare()


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def storage(self):
        storage = Storage.defaults(WORK / uuid.uuid4().hex)
        storage.prepare()
        # Tests have isolated storage, while installed browser binaries remain at the project root.
        storage.root = ROOT
        return storage

    def test_robots_redirect_size_and_cancel(self):
        stop = threading.Event()
        fetcher = Fetcher(5, stop, lambda _: None)
        folder = WORK / "network"
        try:
            before = REQUESTS["/blocked/secret.pdf"]
            for path in ("/blocked/secret.pdf", "/redirect-blocked"):
                with self.assertRaises(AccessError):
                    fetcher.fetch(self.base + path, folder, 10000)
            self.assertEqual(REQUESTS["/blocked/secret.pdf"], before)
            for path in ("/huge", "/chunked-big"):
                with self.assertRaises(DownloadError):
                    fetcher.fetch(self.base + path, folder, 1000)
            self.assertFalse(list(folder.glob("*.download")))
            stop.set()
            with self.assertRaises(Cancelled):
                fetcher.fetch(self.base + "/beta", folder, 10000)
        finally:
            fetcher.close()

    def test_batch_documents_unicode_visuals_and_error_isolation(self):
        storage = self.storage()
        options = Options(settle_seconds=0.4, timeout=10, fast_mode=False)
        result = Collector(storage, options, threading.Event()).run([self.base + "/alpha", self.base + "/restricted", self.base + "/beta"])
        text = result.text_file.read_text(encoding="utf-8")
        self.assertEqual(result.processed, 3)
        self.assertEqual(result.failed, 1)
        for value in ("বাংলা লেখা", "हिन्दी पाठ", "DOCX local heading", "First slide text", "Batch continuation succeeded.", "WEBSITE 3", "robots.txt"):
            self.assertIn(value, text)
        self.assertNotIn("COMPUTED_HIDDEN_NOISE", text)
        self.assertNotIn("DO_NOT_DUMP_SCRIPTS", text)
        self.assertIn("Resource without type hint [PDF]", text)
        self.assertEqual({p.name for p in result.folder.iterdir()}, {"website_content.txt", "website_content.pdf"})
        with pymupdf.open(result.pdf_file) as document:
            self.assertGreaterEqual(len(document), 12)
            combined = "\n".join(page.get_text() for page in document)
            self.assertIn("Fixture PDF page one", combined)
            if find_libreoffice():
                for value in ("DOCX local heading", "First slide text", "Second slide text"):
                    self.assertIn(value, combined)
                self.assertNotIn("LibreOffice conversion failed", text)
            self.assertLess(combined.index("page one"), combined.index("page two"))
            self.assertTrue(any(page.get_images() for page in document))
            self.assertGreaterEqual(len(document.get_toc()), 3)
            # Keep a preview from a real generated PDF for visual inspection.
            document[0].get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2)).save(ROOT / "work" / "pdf-separator-preview.png")
            document[1].get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2)).save(ROOT / "work" / "pdf-capture-preview.png")
        (ROOT / "work" / "sample-output-path.txt").write_text(str(result.folder), encoding="utf-8")

    def test_cancel_during_stream_removes_only_own_partial_download(self):
        folder = WORK / "cancel-stream"
        folder.mkdir()
        sentinel = folder / "original-user-file.txt"
        sentinel.write_text("keep me", encoding="utf-8")
        stop = threading.Event()
        fetcher = Fetcher(5, stop, lambda _: None)
        timer = threading.Timer(0.35, stop.set)
        started = time.monotonic()
        timer.start()
        try:
            with self.assertRaises(Cancelled):
                fetcher.fetch(self.base + "/slow", folder, 100000)
        finally:
            timer.cancel()
            fetcher.close()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me")
        self.assertFalse(list(folder.glob("*.download")))

    def test_javascript_long_pages_and_follow_limits(self):
        storage = self.storage()
        result = Collector(storage, Options(settle_seconds=0.5, timeout=10, max_capture_sections=3), threading.Event()).run([self.base + "/js", self.base + "/long"])
        text = result.text_file.read_text(encoding="utf-8")
        self.assertIn("Rendered JavaScript heading", text)
        self.assertIn("visual capture stopped at 3", text)
        import json
        report = json.loads((storage.logs / f"collection-{result.folder.name}.json").read_text(encoding="utf-8"))
        self.assertEqual(report["sites"][1]["captures"], 3)
        result2 = Collector(self.storage(), Options(settle_seconds=0, timeout=10, follow_pages=True, fast_mode=False,
                    max_followed=1, include_images=False, download_pdf=False, download_doc=False,
                    download_ppt=False), threading.Event()).run([self.base + "/alpha"])
        self.assertEqual(result2.processed, 2)
        self.assertIn("Second website", result2.text_file.read_text(encoding="utf-8"))

    def test_cancellation_saves_partial_pair_without_overwriting(self):
        storage = self.storage()
        stop = threading.Event()
        def progress(done, total, message):
            if done >= 1:
                stop.set()
        result = Collector(storage, Options(settle_seconds=0, timeout=10), stop, progress=progress).run([self.base + "/beta", self.base + "/alpha"])
        self.assertTrue(result.cancelled)
        self.assertEqual(result.processed, 1)
        self.assertTrue(result.pdf_file.is_file())
        original = result.text_file.read_bytes()
        self.assertIn("CANCELLED", original.decode("utf-8"))
        again = Collector(storage, Options(settle_seconds=0, timeout=10), threading.Event()).run([self.base + "/beta"])
        self.assertNotEqual(result.folder, again.folder)
        self.assertEqual(result.text_file.read_bytes(), original)

    def test_browser_failure_retains_http_and_finishes(self):
        with patch("app.browser.BrowserRenderer.start", side_effect=RuntimeError("Browser deliberately unavailable")):
            result = Collector(self.storage(), Options(download_pdf=False, download_doc=False, download_ppt=False, include_images=False), threading.Event()).run([self.base + "/beta"])
        self.assertIn("Batch continuation", result.text_file.read_text(encoding="utf-8"))
        self.assertTrue(result.pdf_file.exists())
        self.assertGreater(result.warnings, 0)

    def test_fast_mode_skips_speculative_checks_and_reuses_html(self):
        before = REQUESTS["/alpha"]
        messages = []
        with patch("app.network.Fetcher.inspect_link", side_effect=AssertionError("Fast mode must not probe ordinary links")) as inspect:
            result = Collector(self.storage(), Options(settle_seconds=0, timeout=10, fast_mode=True),
                               threading.Event(), log=messages.append).run([self.base + "/alpha"])
        inspect.assert_not_called()
        self.assertEqual(REQUESTS["/alpha"] - before, 1)
        text = result.text_file.read_text(encoding="utf-8")
        self.assertIn("First slide text", text)
        self.assertIn("Fixture PDF page one", text)
        self.assertTrue(any("Capturing page section" in message for message in messages))
        self.assertTrue(any("Browser GPU:" in message for message in messages))

    def test_resource_downloads_overlap_and_keep_input_order(self):
        global MAX_ACTIVE_DOWNLOADS
        from app.models import ImageCandidate
        MAX_ACTIVE_DOWNLOADS = 0
        stop = threading.Event()
        fetcher = Fetcher(5, stop, lambda _: None)
        collector = Collector(self.storage(), Options(download_workers=3), stop)
        items = [ImageCandidate(self.base + f"/parallel/{number}") for number in range(3)]
        robots_before = REQUESTS["/robots.txt"]
        try:
            results = list(collector.prefetch(items, WORK / "parallel-downloads", 1000000, self.base, fetcher, {}))
        finally:
            fetcher.close()
        self.assertEqual([item.url for item, _, _ in results], [item.url for item in items])
        self.assertTrue(all(error is None and resource.path.is_file() for _, resource, error in results))
        self.assertGreaterEqual(MAX_ACTIVE_DOWNLOADS, 2)
        self.assertEqual(REQUESTS["/robots.txt"] - robots_before, 1)


class NetworkRetryTests(unittest.TestCase):
    def test_dns_failure_then_recovery(self):
        import httpx
        calls = []
        def handler(request):
            calls.append(str(request.url))
            if len(calls) == 1:
                raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        messages = []
        fetcher = Fetcher(5, threading.Event(), messages.append)
        fetcher.client.close()
        fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            fetcher.check_access("https://example.test/", pace=False)
        finally:
            fetcher.close()
        self.assertEqual(len(calls), 2)
        self.assertTrue(any("Retrying once" in message for message in messages))

    def test_repeated_dns_failure_has_clear_error_and_bounded_attempts(self):
        import httpx
        calls = []
        def handler(request):
            calls.append(str(request.url))
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)
        fetcher = Fetcher(5, threading.Event(), lambda _: None)
        fetcher.client.close()
        fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaisesRegex(AccessError, "Network/DNS lookup failed.*after 2 attempts"):
                fetcher.check_access("https://example.test/", pace=False)
        finally:
            fetcher.close()
        self.assertEqual(len(calls), 2)

    def test_cancel_during_retry_wait(self):
        import httpx
        calls = []
        stop = threading.Event()
        def handler(request):
            calls.append(str(request.url))
            raise httpx.ConnectError("DNS lookup failed", request=request)
        fetcher = Fetcher(5, stop, lambda message: stop.set())
        fetcher.client.close()
        fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
        started = time.monotonic()
        try:
            with self.assertRaises(Cancelled):
                fetcher.check_access("https://example.test/", pace=False)
        finally:
            fetcher.close()
        self.assertEqual(len(calls), 1)
        self.assertLess(time.monotonic() - started, 0.5)


class GuiTests(unittest.TestCase):
    def test_interface_renders(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from app.gui import MainWindow
        application = QApplication.instance() or QApplication([])
        storage = Storage.defaults(WORK / "gui")
        storage.prepare()
        window = MainWindow(storage)
        window.urls.setPlainText("https://example.com/article\nhttps://example.org/course/materials\nhttps://example.com/article#top")
        self.assertIn("2 unique", window.url_count.text())
        window.show()
        application.processEvents()
        self.assertTrue(window.grab().save(str(ROOT / "work" / "interface-preview.png")))
        window.close()

    def test_worker_keeps_event_loop_responsive_and_accepts_cancel(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from app.gui import CollectionWorker
        application = QApplication.instance() or QApplication([])
        ticks = []
        def simulated_run(collector, urls):
            deadline = time.monotonic() + 3
            while not collector.stop.is_set() and time.monotonic() < deadline:
                collector.stop.wait(0.02)
            return None
        worker = CollectionWorker(Storage.defaults(ROOT), Options(), [])
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        with patch("app.gui.Collector.run", simulated_run):
            worker.start()
            timer.start()
            QTimer.singleShot(200, worker.stop.set)
            deadline = time.monotonic() + 4
            while worker.isRunning() and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(0.005)
            timer.stop()
            self.assertTrue(worker.wait(1000))
        self.assertTrue(worker.stop.is_set())
        self.assertGreaterEqual(len(ticks), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
