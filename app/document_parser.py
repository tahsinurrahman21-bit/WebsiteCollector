from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from threading import Event

import olefile
import pymupdf
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pptx import Presentation

from .models import DocumentResult, Options, checkpoint
from .network import Download, DownloadError


def detect_document(path: Path) -> str:
    with path.open("rb") as handle:
        signature = handle.read(1024)
    if b"%PDF-" in signature:
        return "pdf"
    if signature.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as archive:
                items = archive.infolist()
                if len(items) > 20000 or sum(item.file_size for item in items) > 512 * 1048576:
                    raise DownloadError("Office archive is too large after decompression (512 MB limit)")
                if any(item.file_size > max(1048576, item.compress_size * 1000) for item in items):
                    raise DownloadError("Office archive has an unsafe compression ratio")
                names = {item.filename for item in items}
                if "word/document.xml" in names:
                    return "docx"
                if "ppt/presentation.xml" in names:
                    return "pptx"
        except zipfile.BadZipFile as exc:
            raise DownloadError("Invalid Office ZIP container") from exc
    if signature.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        with olefile.OleFileIO(path) as compound:
            if compound.exists("WordDocument"):
                return "doc"
            if compound.exists("PowerPoint Document"):
                return "ppt"
            if compound.exists("EncryptedPackage"):
                raise DownloadError("Password-protected Office document; skipped")
    return ""


def find_libreoffice(explicit: str = "") -> str:
    if explicit:
        return explicit if Path(explicit).is_file() else ""
    # The project-local installation keeps the converter and its dependencies on G:.
    local = Path(__file__).resolve().parents[1] / "tools" / "LibreOffice" / "program"
    candidates = [str(local / "soffice.com"), str(local / "soffice.exe"),
                  shutil.which("soffice.com"), shutil.which("soffice")]
    for base in (os.environ.get("ProgramFiles", "C:/Program Files"),
                 os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"), "G:/Program Files"):
        candidates.extend([str(Path(base) / "LibreOffice/program/soffice.com"),
                           str(Path(base) / "LibreOffice/program/soffice.exe")])
    return next((path for path in candidates if path and Path(path).is_file()), "")


class DocumentParser:
    def __init__(self, temp: Path, options: Options, stop: Event, log):
        self.temp, self.options, self.stop, self.log = temp, options, stop, log
        self.soffice = find_libreoffice(options.libreoffice)

    def parse(self, download: Download, name: str = "") -> DocumentResult:
        checkpoint(self.stop)
        kind = detect_document(download.path)
        if not kind:
            raise DownloadError("Resource is not a supported PDF, Word or PowerPoint document")
        path = download.path.with_suffix("." + kind)
        download.path.rename(path)
        result = DocumentResult(name or path.name, download.url, kind, path)
        if kind == "pdf":
            with pymupdf.open(path) as document:
                if document.needs_pass:
                    raise DownloadError("Password-protected PDF; skipped")
                result.text = self.pdf_text(document)
                result.visual_pdf = path
            if not result.text.strip():
                result.warnings.append("Text could not be extracted; document pages are still included visually. OCR is not enabled.")
            return result
        try:
            if kind == "docx":
                document = Document(path)
                pieces = []
                for child in document.element.body.iterchildren():
                    checkpoint(self.stop)
                    if child.tag == qn("w:p"):
                        paragraph = Paragraph(child, document)
                        value = paragraph.text.strip()
                        if value:
                            style = paragraph.style.name if paragraph.style else ""
                            match = re.match(r"Heading (\d)", style)
                            pieces.append(("#" * int(match[1]) + " " if match else "") + value)
                    elif child.tag == qn("w:tbl"):
                        table = Table(child, document)
                        pieces.append("\n".join(" | ".join(cell.text for cell in row.cells) for row in table.rows))
                result.text = "\n\n".join(pieces)
            elif kind == "pptx":
                presentation = Presentation(path)
                pieces = []
                def shape_text(shape):
                    if getattr(shape, "has_text_frame", False):
                        return shape.text
                    if getattr(shape, "has_table", False):
                        return "\n".join(" | ".join(cell.text for cell in row.cells) for row in shape.table.rows)
                    if hasattr(shape, "shapes"):
                        return "\n".join(shape_text(nested) for nested in shape.shapes)
                    return ""
                for number, slide in enumerate(presentation.slides, 1):
                    checkpoint(self.stop)
                    pieces.append(f"Slide {number}\n" + "\n".join(filter(None, (shape_text(s) for s in slide.shapes))))
                    if slide.has_notes_slide:
                        notes = slide.notes_slide.notes_text_frame
                        if notes and notes.text.strip():
                            pieces.append("Speaker notes\n" + notes.text)
                result.text = "\n\n".join(pieces)
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
            result.warnings.append(f"Native text extraction failed: {exc}")
        if not self.soffice:
            result.warnings.append("LibreOffice is unavailable; visual conversion was not performed." +
                                   (" Legacy DOC/PPT text also needs LibreOffice." if kind in {"doc", "ppt"} else " Native text was retained."))
            return result
        try:
            result.visual_pdf = self.convert(path)
            if not result.text.strip():
                with pymupdf.open(result.visual_pdf) as document:
                    result.text = self.pdf_text(document)
        except (OSError, RuntimeError) as exc:
            result.warnings.append(f"LibreOffice conversion failed: {exc}")
        return result

    def pdf_text(self, document) -> str:
        pieces = []
        for number, page in enumerate(document, 1):
            checkpoint(self.stop)
            text = page.get_text("text", sort=True).strip()
            if text:
                pieces.append(f"Page {number}\n{text}")
        return "\n\n".join(pieces)

    def convert(self, path: Path) -> Path:
        checkpoint(self.stop)
        job = self.temp / "office" / uuid.uuid4().hex
        profile = job / "profile"
        (profile / "user").mkdir(parents=True)
        # A fresh profile has no trusted locations. Very-high macro security prevents
        # document macros from running; external link updates are disabled.
        (profile / "user" / "registrymodifications.xcu").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
</oor:items>''', encoding="utf-8")
        command = [self.soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo",
                   "--nodefault", "--nofirststartwizard", "--norestore", "--convert-to", "pdf", "--outdir", str(job), str(path)]
        logfile = job / "conversion.log"
        process = None
        try:
            with logfile.open("wb") as output:
                process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                deadline = time.monotonic() + self.options.conversion_timeout
                while process.poll() is None:
                    checkpoint(self.stop)
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"Conversion timed out after {self.options.conversion_timeout} seconds")
                    self.stop.wait(0.2)
            converted = job / (path.stem + ".pdf")
            if process.returncode != 0 or not converted.is_file():
                detail = logfile.read_text(encoding="utf-8", errors="replace")[-1500:]
                raise RuntimeError(detail or "No PDF was produced")
            return converted
        finally:
            if process and process.poll() is None:
                if os.name == "nt":
                    # Terminate only the conversion process tree we launched.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                else:
                    process.kill()
                process.wait(timeout=10)
