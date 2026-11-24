from __future__ import annotations

import copy
import json
import logging
import re
import uuid
import warnings
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime
from pathlib import Path
from threading import Event
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageOps

from .browser import BrowserRenderer
from .config import Storage
from .document_parser import DocumentParser, detect_document
from .extract import extract_html, needs_javascript, restricted_page
from .models import BatchResult, Cancelled, Options, SiteResult, checkpoint
from .network import AccessError, Download, Fetcher, decode_html
from .pdf_builder import PdfBuilder, site_text
from .urls import DOCUMENT_TYPES, classify, normalize_url, same_origin


def document_name(download: Download) -> str:
    match = re.search(r"filename\*?\s*=\s*(?:UTF-8''|\")?([^\";]+)", download.disposition, re.I)
    name = unquote(match[1].strip()) if match else unquote(Path(urlsplit(download.url).path).name)
    return (name.replace("\\", "/").split("/")[-1] or "Downloaded document")[:180]


class Collector:
    def __init__(self, storage: Storage, options: Options, stop: Event, log=lambda text: None,
                 progress=lambda done, total, message: None):
        self.storage, self.options, self.stop = storage, options, stop
        self.notify, self.progress = log, progress
        self.run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:8]
        self.document_cache = {}
        self.image_cache = {}
        self.file_logger = None
        self.started = time.monotonic()

    def log(self, message):
        elapsed = time.monotonic() - self.started
        self.notify(f"[{int(elapsed // 60):02d}:{int(elapsed % 60):02d}] {message}")
        if self.file_logger:
            self.file_logger.info(message)

    def run(self, urls: list[str]) -> BatchResult:
        self.storage.prepare()
        folder = self.storage.output / self.run_id
        folder.mkdir(exist_ok=False)
        logfile = self.storage.logs / f"collection-{self.run_id}.log"
        logger = logging.getLogger("collector." + self.run_id)
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(logfile, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        self.file_logger = logger
        fetcher = Fetcher(min(self.options.timeout, 15) if self.options.fast_mode else self.options.timeout, self.stop, self.log)
        renderer = BrowserRenderer(self.storage, self.options, self.stop, fetcher, self.run_id, self.log)
        parser = DocumentParser(self.storage.temp / self.run_id, self.options, self.stop, self.log)
        builder = PdfBuilder()
        pending = deque((url, 0) for url in dict.fromkeys(urls))
        seen = set(urls)
        processed = failed = warning_count = followed = 0
        summary = []
        text_file, pdf_file = folder / "website_content.txt", folder / "website_content.pdf"
        self.log(f"Saving this run to {folder}")
        if self.options.fast_mode:
            self.log("Fast mode: skipping speculative link checks; direct documents, images and all capture sections remain enabled.")
        try:
            with text_file.open("x", encoding="utf-8", newline="\n") as output:
                output.write("WEBSITE CONTENT COLLECTION\nLocal extraction. No AI services or API tokens.\n\n")
                output.flush()
                while pending and not self.stop.is_set():
                    url, depth = pending.popleft()
                    self.progress(processed, processed + len(pending) + 1, "Collecting " + url)
                    site = SiteResult(processed + 1, url, datetime.now().astimezone().isoformat(timespec="seconds"))
                    site.content.title = url
                    try:
                        self.collect_site(site, fetcher, renderer, parser)
                    except Cancelled:
                        site.status = "Cancelled (partial results)"
                        site.warnings.append("Cancelled by the user. This website may be incomplete.")
                    except Exception as exc:
                        site.status = "Failed"
                        site.warnings.append(str(exc))
                        failed += 1
                        self.log(f"Failed: {url} — {exc}")
                    # Finish writing the material already collected before respecting Cancel.
                    self.progress(processed, processed + len(pending) + 1, "Adding website section to outputs")
                    if site.warnings or any(doc.warnings for doc in site.documents):
                        if site.status == "Complete":
                            site.status = "Complete with notes"
                    self.log(f"Building PDF section for website {site.index}: {len(site.captures)} captures, {len(site.images)} images, {len(site.documents)} documents.")
                    builder.append_site(site)
                    if site.warnings and site.status == "Complete":
                        site.status = "Complete with notes"
                    output.write(site_text(site))
                    output.flush()
                    processed += 1
                    warning_count += len(site.warnings) + sum(len(d.warnings) for d in site.documents)
                    for note in site.warnings:
                        self.log("Note: " + note)
                    for document in site.documents:
                        for note in document.warnings:
                            self.log(f"{document.name}: {note}")
                    summary.append({"url": url, "title": site.content.title, "status": site.status,
                                    "captures": len(site.captures), "documents": len(site.documents), "images": len(site.images)})
                    if self.options.follow_pages and depth < self.options.follow_depth and site.status != "Failed":
                        for link in site.content.links:
                            if (followed >= self.options.max_followed or link.kind != "webpage"
                                    or link.document_hint or link.url in seen
                                    or not same_origin(link.url, site.final_url or site.url)
                                    or re.search(r"/(?:logout|signout|login|signin|cart|checkout|delete)(?:[/?]|$)", link.url, re.I)):
                                continue
                            seen.add(link.url)
                            followed += 1
                            pending.append((link.url, depth + 1))
                    self.progress(processed, processed + len(pending), f"Collected {processed} website sections")
                cancelled = self.stop.is_set()
                output.write(f"\nBATCH STATUS: {'CANCELLED — PARTIAL RESULTS' if cancelled else 'COMPLETE'}\n")
                output.write(f"Websites processed: {processed}\nFailed websites: {failed}\nCollection notes: {warning_count}\n")
                if cancelled:
                    output.write(f"Unprocessed queued URLs: {len(pending)}\n")
            self.log("Saving combined PDF. Large collections may take a moment.")
            builder.save(pdf_file, cancelled, processed)
            (self.storage.logs / f"collection-{self.run_id}.json").write_text(json.dumps({"cancelled": cancelled, "sites": summary,
                "elapsed_seconds": round(time.monotonic() - self.started, 2), "gpu": renderer.gpu_info,
                "log": str(logfile), "warning_count": warning_count}, ensure_ascii=False, indent=2), encoding="utf-8")
            self.log(f"{'Cancelled; partial outputs saved' if cancelled else 'Finished'}: {processed} websites, {failed} failed, {warning_count} notes.")
            return BatchResult(folder, text_file, pdf_file, processed, failed, cancelled, warning_count)
        finally:
            try:
                renderer.close()
            finally:
                fetcher.close()
                builder.close()
                handler.close()
                logger.removeHandler(handler)

    def collect_site(self, site, fetcher, renderer, parser):
        checkpoint(self.stop)
        web_folder = self.storage.cache / "websites" / self.run_id / f"website-{site.index:03d}"
        document_folder = self.storage.cache / "documents" / self.run_id
        image_folder = self.storage.cache / "images" / self.run_id
        byte_limit = self.options.max_file_mb * 1048576
        kind = classify(site.url)
        downloaded = fetcher.fetch(site.url, document_folder if kind in DOCUMENT_TYPES else web_folder,
                                   byte_limit if kind in DOCUMENT_TYPES else min(byte_limit, 10 * 1048576))
        site.final_url = downloaded.url
        actual_kind = detect_document(downloaded.path)
        if actual_kind:
            site.content.title = document_name(downloaded)
            if self.options.documents_enabled(actual_kind):
                site.documents.append(parser.parse(downloaded, site.content.title))
            else:
                site.warnings.append(f"{actual_kind.upper()} document processing is disabled.")
            return
        html = decode_html(downloaded)
        if "html" not in downloaded.content_type and not re.search(r"<(?:html|body|head|!doctype)\b", html[:5000], re.I):
            raise RuntimeError("URL did not return a supported HTML page or document")
        site.content = extract_html(html, site.final_url)
        if restricted_page(html, site.content.title):
            site.content.text, site.content.links, site.content.images = "", [], []
            raise AccessError("Page shows a login, access restriction or human-verification challenge; skipped")
        self.log("Rendering website and capturing readable sections: " + site.final_url)
        try:
            rendered_html, rendered_url = renderer.render(site.final_url, web_folder, site.captures, site.warnings, initial=downloaded)
            rendered_content = extract_html(rendered_html, rendered_url)
            # Rendered HTML is authoritative for visibility. HTTP remains the fallback
            # if rendering fails; the heuristic is also recorded in the run log.
            if needs_javascript(html, site.content):
                self.log("Using JavaScript-rendered page content.")
            site.content = rendered_content
            site.final_url = rendered_url
        except Cancelled:
            raise
        except AccessError:
            site.content.text, site.content.links, site.content.images = "", [], []
            raise  # A restriction is never treated as permission to collect via another path.
        except Exception as exc:
            site.warnings.append(f"Website capture/rendering unavailable; retained HTTP text. {exc}")
        checkpoint(self.stop)
        self.log(f"Page captured. Found {len(site.content.links)} links and {len(site.content.images)} content image candidates.")
        document_count = 0
        probe_count = 0
        limit_noted = False
        document_links = []
        for link in site.content.links:
            checkpoint(self.stop)
            if (not self.options.fast_mode and link.kind in {"webpage", "other"} and not link.document_hint
                    and probe_count < self.options.max_link_probes
                    and any((self.options.download_pdf, self.options.download_ppt, self.options.download_doc, self.options.follow_pages))):
                probe_count += 1
                self.log(f"Checking optional link {probe_count}/{self.options.max_link_probes}: {link.url}")
                try:
                    detected = fetcher.inspect_link(link.url)
                    if detected:
                        link.kind = detected
                except Cancelled:
                    raise
                except Exception as exc:
                    self.log(f"Could not inspect link headers: {link.url} — {exc}")
            candidate = self.options.documents_enabled(link.kind) or (
                link.document_hint and link.kind not in DOCUMENT_TYPES and
                any((self.options.download_pdf, self.options.download_ppt, self.options.download_doc)))
            if not candidate:
                continue
            if document_count >= self.options.max_documents:
                if not limit_noted:
                    site.warnings.append(f"Document limit reached ({self.options.max_documents} per website); remaining document links are listed in TXT.")
                    limit_noted = True
                continue
            document_count += 1
            document_links.append(link)
        for link, resource, error in self.prefetch(document_links, document_folder, byte_limit, site.final_url, fetcher, self.document_cache):
            checkpoint(self.stop)
            try:
                if error:
                    raise error
                if link.url in self.document_cache:
                    cached = self.document_cache[link.url]
                    link.kind = cached.kind
                    if self.options.documents_enabled(cached.kind):
                        site.documents.append(copy.deepcopy(cached))
                    continue
                self.log("Extracting downloaded document: " + link.url)
                resource_kind = detect_document(resource.path)
                if not resource_kind:
                    raise RuntimeError("Downloaded data is not a supported document; it may be a login or preview page")
                link.kind = resource_kind
                if not self.options.documents_enabled(resource_kind):
                    site.warnings.append(f"Skipped {link.url}: detected {resource_kind.upper()} is disabled.")
                    continue
                result = parser.parse(resource, document_name(resource))
                self.document_cache[link.url] = result
                self.document_cache[resource.url] = result
                site.documents.append(copy.deepcopy(result))
            except Cancelled:
                raise
            except Exception as exc:
                site.warnings.append(f"Document failed: {link.url} — {exc}")
        if self.options.include_images:
            candidates = site.content.images
            eligible = [candidate for candidate in candidates[:self.options.max_images]
                        if not ((candidate.width and candidate.width < self.options.min_image_width)
                                or (candidate.height and candidate.height < self.options.min_image_height))]
            if eligible:
                self.log(f"Collecting {len(eligible)} images with up to {self.options.download_workers} concurrent downloads.")
            for index, (candidate, resource, error) in enumerate(self.prefetch(eligible, image_folder, byte_limit, site.final_url, fetcher, self.image_cache), 1):
                checkpoint(self.stop)
                try:
                    if error:
                        raise error
                    self.log(f"Preparing image {index}/{len(eligible)}: {candidate.url}")
                    if candidate.url in self.image_cache:
                        path = self.image_cache[candidate.url]
                    else:
                        with warnings.catch_warnings():
                            warnings.simplefilter("error", Image.DecompressionBombWarning)
                            with Image.open(resource.path) as original:
                                if original.width < self.options.min_image_width or original.height < self.options.min_image_height:
                                    continue
                                original.load()
                                image = ImageOps.exif_transpose(original).convert("RGBA")
                                path = resource.path.with_suffix(".png")
                                image.save(path, "PNG")
                        self.image_cache[candidate.url] = path
                    site.images.append((path, (candidate.caption + "\n" if candidate.caption else "") + candidate.url))
                except Cancelled:
                    raise
                except Exception as exc:
                    site.warnings.append(f"Image skipped: {candidate.url} — {exc}")
            if len(candidates) > self.options.max_images:
                site.warnings.append(f"Image candidate limit reached ({self.options.max_images} per website).")

    def prefetch(self, items, folder, byte_limit, referer, fetcher, cache):
        """Overlap network I/O; parse documents and assemble PDFs on one worker thread.

        The shared Fetcher serializes robots/rate-limit decisions per origin. PDF
        libraries are deliberately kept out of these download threads.
        """
        if not items:
            return
        pool = ThreadPoolExecutor(max_workers=max(1, min(8, self.options.download_workers)), thread_name_prefix="collector-download")
        futures = {}
        try:
            for item in items:
                if item.url not in cache and item.url not in futures:
                    futures[item.url] = pool.submit(fetcher.fetch, item.url, folder, byte_limit, referer)
            for item in items:
                checkpoint(self.stop)
                if item.url in cache:
                    yield item, None, None
                    continue
                future = futures[item.url]
                while True:
                    checkpoint(self.stop)
                    try:
                        downloaded = future.result(timeout=0.1)
                        yield item, downloaded, None
                        break
                    except FutureTimeout:
                        continue
                    except Cancelled:
                        raise
                    except Exception as exc:
                        yield item, None, exc
                        break
        finally:
            for future in futures.values():
                future.cancel()
            pool.shutdown(wait=True, cancel_futures=True)
