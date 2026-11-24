from __future__ import annotations

import re
from bs4 import BeautifulSoup, NavigableString, Tag

from .models import ImageCandidate, Link, PageContent
from .urls import classify, normalize_url

NOISE = re.compile(r"(?:^|[-_\s])(cookie|consent|advert|advertisement|social-share|share-buttons|tracking|breadcrumb)(?:$|[-_\s])", re.I)
DECORATION = re.compile(r"(?:logo|favicon|tracking|pixel|spacer|social[-_]?icon|avatar)", re.I)


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_html(html: str, url: str) -> PageContent:
    soup = BeautifulSoup(html, "lxml")
    result = PageContent(title=compact(soup.title.get_text(" ")) if soup.title else url)
    canonical = soup.select_one('link[rel~="canonical"][href]')
    if canonical:
        try:
            result.canonical = normalize_url(canonical["href"], url)
        except ValueError:
            pass
    description = soup.select_one('meta[name="description"], meta[property="og:description"]')
    if description:
        result.description = compact(description.get("content", ""))
    base_tag = soup.find("base", href=True)
    base = url
    if base_tag:
        try:
            base = normalize_url(base_tag["href"], url)
        except ValueError:
            pass
    for element in list(soup.find_all(True)):
        if element.parent is None or element.attrs is None:
            continue
        style = re.sub(r"\s+", "", element.get("style", "")).lower()
        signature = " ".join([element.get("id", ""), *element.get("class", [])])
        if (element.name in {"script", "style", "noscript", "nav", "footer", "aside", "template"}
                or element.has_attr("hidden") or element.get("aria-hidden") == "true"
                or element.get("data-collector-hidden") == "1"
                or "display:none" in style or "visibility:hidden" in style
                or element.get("role") in {"navigation", "banner", "contentinfo"}
                or NOISE.search(signature)):
            element.decompose()
    # A semantic main is preferred, with all article blocks retained when no main exists.
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    seen_links = set()
    for anchor in root.find_all("a", href=True):
        raw = anchor["href"]
        if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        try:
            target = normalize_url(raw, base)
        except ValueError:
            continue
        if target in seen_links:
            continue
        seen_links.add(target)
        label = compact(anchor.get_text(" ")) or anchor.get("title", "") or target
        hint = bool(anchor.has_attr("download") or re.search(r"\b(pdf|pptx?|docx?)\b", label, re.I)
                    or any(x in anchor.get("type", "") for x in ("pdf", "officedocument", "msword", "powerpoint")))
        result.links.append(Link(target, label, classify(target), hint))
    seen_images = set()
    for img in root.find_all("img"):
        alt = compact(img.get("alt", ""))
        raw = img.get("data-collector-src") or img.get("data-src") or img.get("src", "")
        if not raw or raw.startswith(("data:", "blob:")) or DECORATION.search(raw + " " + alt):
            continue
        try:
            target = normalize_url(raw, base)
        except ValueError:
            continue
        if target in seen_images:
            continue
        seen_images.add(target)
        figure = img.find_parent("figure")
        caption = figure.find("figcaption") if figure else None
        label = compact(caption.get_text(" ")) if caption else alt
        def dimension(name: str) -> int:
            value = str(img.get("data-collector-" + name) or img.get(name, "0"))
            return int(value) if value.isdigit() else 0
        result.images.append(ImageCandidate(target, label, dimension("width"), dimension("height")))
    chunks: list[str] = []
    inline: list[str] = []
    blocks = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "figcaption", "dt", "dd", "blockquote", "label"}

    def flush() -> None:
        value = compact(" ".join(inline))
        inline.clear()
        if value:
            chunks.append(value)

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                inline.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name
            if name == "table":
                flush()
                rows = []
                for row in child.find_all("tr"):
                    cells = row.find_all(["td", "th"], recursive=False)
                    rows.append(" | ".join(compact(cell.get_text(" ")) for cell in cells))
                chunks.append("\n".join(row for row in rows if row))
            elif name in blocks:
                flush()
                if name == "li":
                    value = compact(" ".join(str(c) if isinstance(c, NavigableString) else c.get_text(" ")
                                             for c in child.contents if not isinstance(c, Tag) or c.name not in {"ul", "ol"}))
                    parent = child.parent
                    prefix = "- "
                    if parent.name == "ol":
                        prefix = f"{len(child.find_previous_siblings('li')) + 1}. "
                    if value:
                        chunks.append(prefix + value)
                    for nested in child.find_all(["ul", "ol"], recursive=False):
                        walk(nested)
                elif name == "pre":
                    chunks.append(child.get_text().strip())
                else:
                    value = compact(child.get_text(" "))
                    if value:
                        chunks.append(("#" * int(name[1]) + " " if re.fullmatch(r"h[1-6]", name) else "") + value)
            elif name == "img":
                if child.get("alt"):
                    flush()
                    chunks.append("[Image: " + compact(child["alt"]) + "]")
            elif name == "br":
                flush()
            else:
                if name in {"div", "section", "article", "header", "ul", "ol"}:
                    flush()
                walk(child)
                if name in {"div", "section", "article", "header", "ul", "ol"}:
                    flush()
    walk(root)
    flush()
    result.text = "\n\n".join(chunk for chunk in chunks if chunk)
    descriptions = [image.caption for image in result.images if image.caption and image.caption not in result.text]
    if descriptions:
        result.text += "\n\nIMAGE DESCRIPTIONS\n\n" + "\n".join(dict.fromkeys(descriptions))
    return result


def needs_javascript(html: str, content: PageContent) -> bool:
    return (len(content.text) < 300 or bool(re.search(r"enable javascript|__NEXT_DATA__|id=[\"'](?:root|app)[\"']", html, re.I)))


def restricted_page(html: str, title: str = "") -> bool:
    sample = (title + " " + BeautifulSoup(html[:150000], "lxml").get_text(" ")).lower()
    return bool(re.search(r"verify you are human|checking your browser|just a moment\.\.\.|access denied|complete the captcha|sign in to continue|log in to continue|subscribe to continue reading", sample[:12000]))
