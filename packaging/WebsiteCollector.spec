# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the standalone Windows build of Website Collector.
# Build with:  build_release.ps1   (or: pyinstaller packaging/WebsiteCollector.spec)
#
# Produces a one-folder app in dist/WebsiteCollector/ containing
# WebsiteCollector.exe and an _internal/ folder.  One-folder mode is used on
# purpose: it starts faster than one-file mode, keeps the Playwright driver
# (node.exe) as a normal file, and keeps the LGPL Qt libraries as separate,
# replaceable DLLs.

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project = Path(SPECPATH).resolve().parent

hiddenimports = collect_submodules("app") + collect_submodules("playwright")

# Playwright ships its Node.js driver as package data; it must be bundled.
datas = collect_data_files("playwright", include_py_files=False)

excludes = [
    "tkinter", "pydoc_data",
    # Qt modules the app does not use (it only needs QtCore/QtGui/QtWidgets)
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtLocation",
    "PySide6.QtPositioning", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtWebSockets", "PySide6.QtDesigner",
]

a = Analysis(
    [str(project / "packaging" / "launcher.py")],
    pathex=[str(project)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WebsiteCollector",
    console=False,          # GUI app: no black console window
    disable_windowed_traceback=False,
    upx=False,              # UPX often triggers antivirus false positives
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="WebsiteCollector",
)
