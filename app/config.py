from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path("G:/WebsiteCollector")


def ensure_writable(folder: Path) -> Path:
    folder = folder.expanduser().absolute()
    if os.name == "nt" and not Path(folder.anchor).exists():
        raise OSError(f"Local volume {folder.drive} is unavailable. Please connect or mount the drive, or select another storage location.")
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # Request directory create-file/subdirectory rights without creating or
        # deleting a probe file outside the program's cache/temp directories.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(str(folder), 0x0002 | 0x0004, 7, None, 3, 0x02000000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.CloseHandle(handle)
    elif not os.access(folder, os.W_OK):
        raise PermissionError(f"Storage folder is not writable: {folder}")
    return folder


@dataclass
class Storage:
    root: Path
    cache: Path
    temp: Path
    output: Path
    browser: Path
    logs: Path

    @classmethod
    def defaults(cls, root: Path = DEFAULT_ROOT) -> "Storage":
        return cls(root, root / "cache", root / "temp", root / "output",
                   root / "browser_data", root / "logs")

    def prepare(self) -> None:
        for name in ("root", "cache", "temp", "output", "browser", "logs"):
            setattr(self, name, ensure_writable(getattr(self, name)))
        for sub in ("websites", "images", "documents"):
            (self.cache / sub).mkdir(exist_ok=True)
        self.configure_environment()

    def configure_environment(self) -> None:
        for key in ("TEMP", "TMP", "TMPDIR"):
            os.environ[key] = str(self.temp)
        tempfile.tempdir = str(self.temp)
        # Browser binaries stay in the installation even when the profile location changes.
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self.root / "browser_data" / "browsers")
        os.environ["PIP_CACHE_DIR"] = str(self.root / "cache" / "pip")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    def settings(self) -> dict:
        try:
            return json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_settings(self, options: dict) -> None:
        data = {"storage": {key: str(getattr(self, key)) for key in
                            ("cache", "temp", "output", "browser", "logs")},
                "options": options}
        target = self.root / "settings.json"
        temporary = self.root / f".settings-{uuid.uuid4().hex}.json"
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, target)
