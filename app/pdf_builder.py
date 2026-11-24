from __future__ import annotations

import html
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from .models import SiteResult


class PdfBuilder:
    def __init__(self):
        self.document = pymupdf.open()
        self.bookmarks = []

    def note(self, heading: str, lines: list[str], level: int = 1) -> None:
        page = self.document.new_page(width=595, height=842)
        page.draw_rect(pymupdf.Rect(0, 0, 595, 15), fill=(0.06, 0.40, 0.43), color=None)
        escaped = "".join(f"<p>{html.escape(value)}</p>" for value in lines)
        page.insert_htmlbox(pymupdf.Rect(42, 55, 553, 790),
                            f"<h1>{html.escape(heading)}</h1>{escaped}",
                            css="body {font-family: sans-serif; font-size: 12px; color: #23323e} h1 {font-size: 27px; color: #10666e} p {overflow-wrap: anywhere; margin-bottom: 14px}")
        self.bookmarks.append([level, heading[:160], len(self.document)])

    def add_image(self, path: Path, caption: str) -> None:
        with Image.open(path) as source:
            width, height = source.size
            # Captures and downloaded images have already been normalized. Reuse
            # those bytes instead of decoding and PNG-compressing every image again.
            image_args = {"filename": str(path)}
            if source.getexif().get(274, 1) != 1:
                import io
                image = ImageOps.exif_transpose(source)
                width, height = image.size
                buffer = io.BytesIO()
                image.convert("RGBA").save(buffer, format="PNG")
                image_args = {"stream": buffer.getvalue()}
        landscape = width > height * 1.25
        page = self.document.new_page(width=842 if landscape else 595, height=595 if landscape else 842)
        rect = pymupdf.Rect(24, 24, page.rect.width - 24, page.rect.height - 62)
        page.insert_image(rect, keep_proportion=True, **image_args)
        page.insert_htmlbox(pymupdf.Rect(24, page.rect.height - 48, page.rect.width - 24, page.rect.height - 12),
                            html.escape(caption[:500]), css="body {font-size: 9px; font-family: sans-serif; color: #445563}")

    def append_site(self, site: SiteResult) -> None:
        self.note(f"WEBSITE {site.index}", [site.content.title, site.url,
                  "Retrieved: " + site.retrieved, "Status: " + site.status])
        self.bookmarks[-1][1] = f"{site.index}. {site.content.title[:140]}"
        if not site.captures:
            self.note("Website capture unavailable", ["Text and links, when available, are in website_content.txt.",
                      *site.warnings[:8]], level=2)
        for number, path in enumerate(site.captures, 1):
            try:
                self.add_image(path, f"{site.content.title} | Website capture {number}/{len(site.captures)}")
            except Exception as exc:
                site.warnings.append(f"Could not include capture {path.name}: {exc}")
        for path, caption in site.images:
            try:
                self.add_image(path, caption)
            except Exception as exc:
                site.warnings.append(f"Could not include image {path.name}: {exc}")
        for resource in site.documents:
            self.note("DOCUMENT: " + resource.name, [resource.source, "Type: " + resource.kind.upper(), *resource.warnings], level=2)
            if resource.visual_pdf:
                try:
                    with pymupdf.open(resource.visual_pdf) as source:
                        # Retain page order and vector content; omit interactive annotations/forms.
                        self.document.insert_pdf(source, links=False, annots=False, widgets=False)
                except Exception as exc:
                    resource.warnings.append(f"Could not include document pages: {exc}")
                    self.note("Document pages unavailable", [str(exc)], level=2)
        if site.warnings:
            # Full diagnostics remain in TXT; this page makes partial captures explicit.
            self.note("Collection notes", site.warnings[:15] + (["More details are in website_content.txt."] if len(site.warnings) > 15 else []), level=2)

    def save(self, path: Path, cancelled: bool, processed: int) -> None:
        self.note("Collection cancelled" if cancelled else "Collection complete",
                  [f"{processed} website sections collected.",
                   "Cancelled runs contain partial results." if cancelled else "Text and resource details are in website_content.txt."])
        self.document.set_toc(self.bookmarks)
        self.document.set_metadata({"title": "Website content collection", "creator": "Website Collector (local)",
                                    "subject": "Partial collection" if cancelled else "Website captures and document pages"})
        self.document.save(path, garbage=3, deflate=True)

    def close(self):
        self.document.close()


def site_text(site: SiteResult) -> str:
    lines = ["=" * 72, f"WEBSITE {site.index}", f"Title: {site.content.title}", f"URL: {site.url}",
             f"Retrieved: {site.retrieved}", f"Status: {site.status}"]
    if site.final_url and site.final_url != site.url:
        lines.append("Final URL: " + site.final_url)
    if site.content.canonical:
        lines.append("Canonical: " + site.content.canonical)
    if site.content.description:
        lines.extend(["", "Description: " + site.content.description])
    lines.extend(["", "PAGE TEXT", "", site.content.text or "No page text extracted.", "", "LINKS", ""])
    for index, link in enumerate(site.content.links, 1):
        lines.extend([f"{index}. {link.text} [{link.kind.upper()}]", "   " + link.url])
    if not site.content.links:
        lines.append("No content links found.")
    lines.extend(["", "DOWNLOADED DOCUMENTS", ""])
    if not site.documents:
        lines.append("No documents downloaded.")
    for document in site.documents:
        lines.extend(["-" * 60, "DOCUMENT", "Name: " + document.name, "Source: " + document.source,
                      "Type: " + document.kind.upper(), "Cached file: " + str(document.local_path), "",
                      document.text or "No text extracted.", ""])
        lines.extend("Note: " + warning for warning in document.warnings)
    if site.images:
        lines.extend(["", "INCLUDED IMAGES"])
        lines.extend(caption for _, caption in site.images)
    if site.warnings:
        lines.extend(["", "COLLECTION NOTES", *site.warnings])
    return "\n".join(lines) + "\n\n"
