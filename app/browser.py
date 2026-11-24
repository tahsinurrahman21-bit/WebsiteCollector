from __future__ import annotations

import math
import os
from urllib.parse import urlsplit
from pathlib import Path
from threading import Event

from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

from .config import Storage
from .extract import restricted_page
from .models import Cancelled, Options, checkpoint
from .network import AccessError, Download, Fetcher, USER_AGENT


# Computed visibility, responsive image URLs and natural dimensions come from the rendered DOM.
SNAPSHOT_JS = """() => {
  const copy = document.documentElement.cloneNode(true);
  const originals = document.documentElement.querySelectorAll('*');
  const clones = copy.querySelectorAll('*');
  for (let i = 0; i < originals.length; i++) {
    const el = originals[i], target = clones[i], style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')
      target.setAttribute('data-collector-hidden', '1');
    if (el.tagName === 'IMG') {
      target.setAttribute('data-collector-src', el.currentSrc || el.src);
      target.setAttribute('data-collector-width', el.naturalWidth);
      target.setAttribute('data-collector-height', el.naturalHeight);
    }
  }
  return '<!DOCTYPE html>' + copy.outerHTML;
}"""


def installed_browser() -> str:
    for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for base in (os.environ.get("ProgramFiles", "C:/Program Files"),
                     os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            path = Path(base) / relative
            if path.is_file():
                return str(path)
    return ""


class BrowserRenderer:
    WIDTH = 1100
    HEIGHT = 1450

    def __init__(self, storage: Storage, options: Options, stop: Event, fetcher: Fetcher, run_id: str, log):
        self.storage, self.options, self.stop = storage, options, stop
        self.fetcher, self.run_id, self.log = fetcher, run_id, log
        self.playwright = None
        self.context = None
        self.start_error = ""
        self.gpu_info = {}

    def start(self) -> None:
        if self.context:
            return
        if self.start_error:
            raise RuntimeError(self.start_error)
        checkpoint(self.stop)
        try:
            self.playwright = sync_playwright().start()
            browser_args = {}
            acceleration_args = []
            if self.options.use_gpu:
                acceleration_args = ["--enable-gpu", "--enable-gpu-rasterization", "--force-high-performance-gpu"]
                if os.name == "nt":
                    acceleration_args.append("--use-angle=d3d11")
                browser_args["ignore_default_args"] = ["--enable-unsafe-swiftshader"]
            if not Path(self.playwright.chromium.executable_path).is_file():
                fallback = installed_browser()
                if fallback:
                    browser_args["executable_path"] = fallback
                    self.log("Using installed Chromium-based browser with a separate local profile: " + fallback)
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.storage.browser / "profiles" / self.run_id),
                headless=not self.options.show_browser,
                channel="chromium",
                downloads_path=str(self.storage.temp / self.run_id / "browser-downloads"),
                viewport={"width": self.WIDTH, "height": self.HEIGHT},
                device_scale_factor=1.5, user_agent=USER_AGENT,
                accept_downloads=False, service_workers="block",
                timeout=self.options.timeout * 1000,
                args=[f"--disk-cache-dir={self.storage.browser / 'http-cache' / self.run_id}",
                      "--disable-background-networking", "--disable-component-update", *acceleration_args],
                **browser_args,
            )
            self.context.set_default_timeout(self.options.timeout * 1000)
            self.report_gpu()
        except Exception as exc:
            self.start_error = f"Chromium could not start. Run setup.bat to install/repair it. {exc}"
            self.close()
            raise RuntimeError(self.start_error) from exc

    def report_gpu(self) -> None:
        try:
            session = self.context.browser.new_browser_cdp_session()
            try:
                self.gpu_info = session.send("SystemInfo.getInfo").get("gpu", {})
            finally:
                session.detach()
            renderer = self.gpu_info.get("auxAttributes", {}).get("glRenderer", "")
            features = self.gpu_info.get("featureStatus", {})
            if not renderer:
                renderer = ", ".join(device.get("deviceString", "") for device in self.gpu_info.get("devices", []))
            self.log(f"Browser GPU: {renderer or 'not reported'}; compositing={features.get('gpu_compositing', 'unknown')}; rasterization={features.get('rasterization', 'unknown')}")
        except Exception as exc:
            self.log(f"GPU acceleration {'requested' if self.options.use_gpu else 'automatic'}; browser did not report its renderer ({exc}).")

    def render(self, url: str, folder: Path, captures: list[Path], warnings: list[str], initial: Download | None = None) -> tuple[str, str]:
        self.start()
        checkpoint(self.stop)
        folder.mkdir(parents=True, exist_ok=True)
        page = self.context.new_page()
        page.on("dialog", lambda dialog: dialog.dismiss())
        navigation_errors = []
        initial_body = initial

        def route_request(route):
            nonlocal initial_body
            request = route.request
            if self.stop.is_set() or request.method not in {"GET", "HEAD"} or request.resource_type == "media":
                route.abort()
                return
            if self.options.fast_mode and not request.is_navigation_request():
                host = urlsplit(request.url).hostname or ""
                trackers = ("doubleclick.net", "googlesyndication.com", "google-analytics.com",
                            "googletagmanager.com", "googletagservices.com", "adnxs.com", "hotjar.com", "clarity.ms")
                if any(host == suffix or host.endswith("." + suffix) for suffix in trackers):
                    route.abort()
                    return
            if request.is_navigation_request():
                if request.frame != page.main_frame:
                    route.abort()
                    return
                try:
                    # Serve only a verified navigation body. Manual HTTP redirects in Fetcher
                    # apply robots checks before every hop, including JS-triggered navigations.
                    if initial_body and request.url.split("#", 1)[0] == initial_body.url.split("#", 1)[0]:
                        downloaded, initial_body = initial_body, None
                    else:
                        downloaded = self.fetcher.fetch(request.url, folder, 10 * 1048576)
                    if "html" not in downloaded.content_type and not downloaded.path.read_bytes()[:500].lstrip().lower().startswith((b"<!doctype html", b"<html")):
                        raise AccessError("Browser navigation did not return an HTML page")
                    if downloaded.url != request.url:
                        route.fulfill(status=302, headers={"location": downloaded.url}, body="")
                    else:
                        route.fulfill(status=200, content_type=downloaded.content_type or "text/html", body=downloaded.path.read_bytes())
                except Cancelled:
                    route.abort()
                except Exception as exc:
                    navigation_errors.append(str(exc))
                    route.abort()
            else:
                route.continue_()

        page.route("**/*", route_request)
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.options.timeout * 1000)
            except BrowserTimeout:
                warnings.append("Page loading reached the timeout; captured the available content.")
            checkpoint(self.stop)
            if navigation_errors:
                raise AccessError(navigation_errors[0])
            self.log("Page loaded. Waiting briefly for visible content.")
            waited = 0.0
            settle = min(self.options.settle_seconds, 0.8) if self.options.fast_mode else self.options.settle_seconds
            while waited < settle:
                checkpoint(self.stop)
                page.wait_for_timeout(200)
                waited += 0.2
            if restricted_page(page.content(), page.title()):
                raise AccessError("Page shows a login, access restriction or human-verification challenge; skipped")
            # Scroll in bounded steps to load lazy content. Infinite feeds stop at the section cap.
            max_height = self.HEIGHT * self.options.max_capture_sections
            position = 0
            self.log("Preparing page sections and lazy-loaded images.")
            while position < min(page.evaluate("document.documentElement.scrollHeight"), max_height):
                checkpoint(self.stop)
                page.evaluate("y => window.scrollTo(0, y)", position)
                page.wait_for_timeout(50 if self.options.fast_mode else 100)
                position += self.HEIGHT
            page.evaluate("window.scrollTo(0, 0)")
            html = page.evaluate(SNAPSHOT_JS)
            height = max(self.HEIGHT, page.evaluate("document.documentElement.scrollHeight"))
            if height > max_height:
                warnings.append(f"Very long page: visual capture stopped at {self.options.max_capture_sections} sections. Increase the limit to capture more.")
            count = min(self.options.max_capture_sections, math.ceil(height / self.HEIGHT))
            # Small pages use one full-page image; long pages are clipped directly, never
            # assembled into a giant image that would exhaust memory or become unreadable.
            if count == 1:
                self.log("Capturing page section 1 of 1.")
                path = folder / "capture-001.png"
                page.screenshot(path=str(path), full_page=True, animations="disabled", timeout=self.options.timeout * 1000)
                captures.append(path)
            else:
                page.add_style_tag(content="html {scroll-behavior:auto!important} * {animation:none!important; transition:none!important}")
                for index in range(count):
                    checkpoint(self.stop)
                    self.log(f"Capturing page section {index + 1} of {count}.")
                    y = index * self.HEIGHT
                    path = folder / f"capture-{index + 1:03d}.png"
                    page.screenshot(path=str(path), full_page=True, clip={"x": 0, "y": y, "width": self.WIDTH,
                                    "height": min(self.HEIGHT, height - y)},
                                    animations="disabled", timeout=self.options.timeout * 1000)
                    captures.append(path)
            return html, page.url
        finally:
            page.close()

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
        finally:
            self.context = None
            if self.playwright:
                self.playwright.stop()
                self.playwright = None
