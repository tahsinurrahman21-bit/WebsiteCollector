from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event


class Cancelled(Exception):
    """Cooperative cancellation; completed work is retained."""


def checkpoint(stop: Event) -> None:
    if stop.is_set():
        raise Cancelled("Cancelled by the user")


@dataclass
class Options:
    include_images: bool = True
    download_pdf: bool = True
    download_ppt: bool = True
    download_doc: bool = True
    follow_pages: bool = False
    show_browser: bool = False
    fast_mode: bool = True
    use_gpu: bool = True
    download_workers: int = 4
    timeout: int = 30
    settle_seconds: float = 2
    max_file_mb: int = 250
    min_image_width: int = 250
    min_image_height: int = 150
    max_images: int = 30
    max_documents: int = 40
    max_link_probes: int = 50
    max_followed: int = 20
    follow_depth: int = 1
    max_capture_sections: int = 60
    conversion_timeout: int = 120
    libreoffice: str = ""

    def documents_enabled(self, kind: str) -> bool:
        return {"pdf": self.download_pdf, "ppt": self.download_ppt,
                "pptx": self.download_ppt, "doc": self.download_doc,
                "docx": self.download_doc}.get(kind, False)


@dataclass
class Link:
    url: str
    text: str
    kind: str = "webpage"
    document_hint: bool = False


@dataclass
class ImageCandidate:
    url: str
    caption: str = ""
    width: int = 0
    height: int = 0


@dataclass
class PageContent:
    title: str = "Untitled page"
    text: str = ""
    canonical: str = ""
    description: str = ""
    links: list[Link] = field(default_factory=list)
    images: list[ImageCandidate] = field(default_factory=list)


@dataclass
class DocumentResult:
    name: str
    source: str
    kind: str
    local_path: Path
    text: str = ""
    visual_pdf: Path | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class SiteResult:
    index: int
    url: str
    retrieved: str
    final_url: str = ""
    content: PageContent = field(default_factory=PageContent)
    captures: list[Path] = field(default_factory=list)
    images: list[tuple[Path, str]] = field(default_factory=list)
    documents: list[DocumentResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "Complete"


@dataclass
class BatchResult:
    folder: Path
    text_file: Path
    pdf_file: Path
    processed: int
    failed: int
    cancelled: bool
    warnings: int
