from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .models import checkpoint
from .urls import normalize_url

USER_AGENT = "WebsiteCollector/1.0 (local desktop content collector)"


class AccessError(RuntimeError):
    pass


class DownloadError(RuntimeError):
    pass


@dataclass
class Download:
    path: Path
    url: str
    content_type: str
    disposition: str = ""


class Fetcher:
    """Bounded, streamed HTTP downloads. Every redirect is checked before fetching."""

    def __init__(self, timeout: int, stop: Event, log):
        self.timeout = timeout
        self.stop = stop
        self.log = log
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT},
                                   timeout=httpx.Timeout(timeout, read=min(timeout, 5)),
                                   follow_redirects=False)
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self._locks_guard = Lock()
        self._origin_locks: dict[str, Lock] = {}

    def close(self) -> None:
        self.client.close()

    @contextmanager
    def _stream(self, method: str, url: str, retry_hook=None, **kwargs):
        """Retry one failed connection, never HTTP restrictions or a partial body."""
        for attempt in range(2):
            checkpoint(self.stop)
            manager = self.client.stream(method, url, **kwargs)
            try:
                response = manager.__enter__()
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                detail = str(exc)
                # Certificate failures are not transient and must not be bypassed.
                if any(value in detail.lower() for value in ("certificate_verify_failed", "certificate verify failed")):
                    raise
                host = urlsplit(url).hostname or url
                if attempt == 0:
                    self.log(f"Temporary connection/DNS problem contacting {host}. Retrying once in 1 second.")
                    self.stop.wait(1)
                    checkpoint(self.stop)
                    if retry_hook:
                        retry_hook()
                    continue
                dns_failure = any(value in detail.lower() for value in ("getaddrinfo", "name resolution", "name or service not known", "11001"))
                reason = "Network/DNS lookup failed" if dns_failure else "Network connection failed"
                raise DownloadError(f"{reason} for {host} after 2 attempts. Check the internet connection/DNS and try again. Details: {detail}") from exc
            try:
                yield response
            finally:
                manager.__exit__(None, None, None)
            return

    def _read_robots(self, origin: str) -> RobotFileParser:
        parser = RobotFileParser(origin + "/robots.txt")
        url = origin + "/robots.txt"
        try:
            for _ in range(6):
                checkpoint(self.stop)
                with self._stream("GET", url) as response:
                    if response.is_redirect:
                        url = normalize_url(urljoin(url, response.headers.get("location", "")))
                        continue
                    if response.status_code in {404, 410}:
                        parser.parse([])
                    elif response.status_code in {401, 403}:
                        parser.parse(["User-agent: *", "Disallow: /"])
                    else:
                        response.raise_for_status()
                        data = bytearray()
                        deadline = time.monotonic() + self.timeout
                        for chunk in response.iter_bytes():
                            checkpoint(self.stop)
                            data.extend(chunk)
                            if len(data) > 1024 * 1024 or time.monotonic() > deadline:
                                raise AccessError("robots.txt exceeded its size/time limit")
                        parser.parse(data.decode("utf-8", errors="replace").splitlines())
                    return parser
            raise AccessError("Too many robots.txt redirects")
        except (httpx.HTTPError, AccessError, DownloadError, ValueError) as exc:
            raise AccessError(f"Could not verify robots.txt for {origin}; skipped ({exc})") from exc

    def check_access(self, url: str, pace: bool = True) -> None:
        checkpoint(self.stop)
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._locks_guard:
            lock = self._origin_locks.setdefault(origin, Lock())
        while not lock.acquire(timeout=0.1):
            checkpoint(self.stop)
        try:
            self._check_origin(origin, url, pace)
        finally:
            lock.release()

    def _check_origin(self, origin: str, url: str, pace: bool) -> None:
        if origin not in self.robots:
            self.robots[origin] = self._read_robots(origin)
        parser = self.robots[origin]
        if not parser.can_fetch(USER_AGENT, url):
            raise AccessError(f"robots.txt does not allow this URL: {url}")
        if pace:
            delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0.3
            rate = parser.request_rate(USER_AGENT) or parser.request_rate("*")
            if rate and rate.requests:
                delay = max(delay, rate.seconds / rate.requests)
            remaining = delay - (time.monotonic() - self.last_request.get(origin, 0))
            if remaining > 0:
                if remaining > 1:
                    self.log(f"Waiting {remaining:.1f}s for the site's crawl delay: {origin}")
                self.stop.wait(remaining)
                checkpoint(self.stop)
            self.last_request[origin] = time.monotonic()

    def fetch(self, url: str, folder: Path, max_bytes: int, referer: str = "") -> Download:
        folder.mkdir(parents=True, exist_ok=True)
        checkpoint(self.stop)
        url = normalize_url(url)
        for _ in range(11):
            self.check_access(url)
            self.log("Fetching: " + url)
            headers = {"Referer": referer} if referer else {}
            with self._stream("GET", url, headers=headers, retry_hook=lambda: self.check_access(url)) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise DownloadError("Redirect has no destination")
                    url = normalize_url(location, url)
                    continue
                if response.status_code in {401, 403, 407, 429}:
                    raise AccessError(f"HTTP {response.status_code}: access is restricted or rate limited; no bypass attempted")
                response.raise_for_status()
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > max_bytes:
                    raise DownloadError(f"Download exceeds the {max_bytes / 1048576:g} MB limit")
                path = folder / (uuid.uuid4().hex + ".download")
                total = 0
                began = last_report = time.monotonic()
                # A slow but responsive large file is allowed, with a finite total deadline.
                deadline = time.monotonic() + max(self.timeout, min(600, max_bytes / 262144))
                try:
                    with path.open("xb") as output:
                        for chunk in response.iter_bytes():
                            checkpoint(self.stop)
                            total += len(chunk)
                            if total > max_bytes:
                                raise DownloadError(f"Download exceeds the {max_bytes / 1048576:g} MB limit")
                            if time.monotonic() > deadline:
                                raise DownloadError("Download exceeded its total time limit")
                            output.write(chunk)
                            now = time.monotonic()
                            if now - last_report >= 1:
                                expected = f" / {int(length) / 1048576:.1f} MB" if length.isdigit() else " MB"
                                self.log(f"Downloading {total / 1048576:.1f}{expected} at {total / max(0.1, now - began) / 1048576:.1f} MB/s: {url}")
                                last_report = now
                except BaseException:
                    path.unlink(missing_ok=True)  # Only the unique file this call created.
                    raise
                return Download(path, str(response.url), response.headers.get("content-type", "").lower(),
                                response.headers.get("content-disposition", ""))
        raise DownloadError("Too many redirects")

    def fetch_html(self, url: str, folder: Path) -> tuple[str, Download]:
        downloaded = self.fetch(url, folder, 10 * 1048576)
        return decode_html(downloaded), downloaded

    def inspect_link(self, url: str) -> str:
        """Check headers without following the webpage body or downloading a file."""
        from .urls import classify
        import re
        mime_types = {"application/pdf": "pdf", "application/msword": "doc",
                      "application/vnd.ms-powerpoint": "ppt",
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                      "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx"}
        for _ in range(6):
            self.check_access(url)
            with self._stream("HEAD", url, timeout=httpx.Timeout(min(self.timeout, 5)), retry_hook=lambda: self.check_access(url)) as response:
                response.read()
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return ""
                url = normalize_url(location, url)
                continue
            if response.status_code in {405, 501}:
                return ""  # Servers need not implement HEAD; do not GET an arbitrary page.
            if response.status_code in {401, 403, 407, 429}:
                raise AccessError(f"HTTP {response.status_code} while checking linked resource")
            response.raise_for_status()
            kind = mime_types.get(response.headers.get("content-type", "").split(";")[0].strip().lower(), "")
            if kind:
                return kind
            disposition = response.headers.get("content-disposition", "")
            match = re.search(r"\.(pdf|pptx?|docx?)(?:[\"';\s]|$)", disposition, re.I)
            return match[1].lower() if match else ""
        return ""


def decode_html(download: Download) -> str:
    # httpx honours HTTP charset; BeautifulSoup handles HTML meta charset if absent.
    from bs4 import UnicodeDammit
    import re
    data = download.path.read_bytes()
    charset = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", download.content_type)
    if charset:
        try:
            return data.decode(charset[1], errors="replace")
        except LookupError:
            pass
    return UnicodeDammit(data, is_html=True).unicode_markup or data.decode("utf-8", errors="replace")
