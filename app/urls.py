from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

DOCUMENT_TYPES = {"pdf", "ppt", "pptx", "doc", "docx"}
IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff", "svg", "avif"}


def normalize_url(value: str, base: str = "") -> str:
    value = value.strip()
    if not value or re.search(r"[\x00-\x20\x7f]", value):
        raise ValueError("URL is empty or contains spaces/control characters")
    if base:
        value = urljoin(base, value)
    elif "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Only HTTP and HTTPS website URLs are supported")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URLs with embedded credentials are not supported")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    if port and not (scheme == "http" and port == 80 or scheme == "https" and port == 443):
        host += f":{port}"
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    path = re.sub(r"%([0-9a-fA-F]{2})", lambda m: chr(int(m[1], 16))
                  if chr(int(m[1], 16)) in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
                  else "%" + m[1].upper(), path)
    # Ordinary anchors do not identify a different resource; hash-router paths do.
    fragment = parts.fragment if parts.fragment.startswith(("/", "!")) else ""
    return urlunsplit((scheme, host, path, parts.query, fragment))


def parse_urls(text: str) -> tuple[list[str], list[str]]:
    urls, errors, seen = [], [], set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            url = normalize_url(line)
            if url not in seen:
                seen.add(url)
                urls.append(url)
        except ValueError as exc:
            errors.append(f"Line {line_number}: {exc}")
    return urls, errors


def classify(url: str) -> str:
    ext = PurePosixPath(unquote(urlsplit(url).path)).suffix.lower().lstrip(".")
    if ext in DOCUMENT_TYPES:
        return ext
    if ext in IMAGE_TYPES:
        return "image"
    if ext == "zip":
        return "zip"
    if ext and ext not in {"html", "htm", "php", "aspx", "asp", "jsp"}:
        return "other"
    return "webpage"


def same_origin(a: str, b: str) -> bool:
    x, y = urlsplit(a), urlsplit(b)
    return (x.scheme, x.netloc) == (y.scheme, y.netloc)
