# PyInstaller spec for 83 MEN'S WEAR POS.  Build from the repository root:
#     pyinstaller packaging/83mw.spec --noconfirm
# Output: dist/83MensWear/83MensWear.exe  (a folder build: starts faster than --onefile)
from pathlib import Path

root = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is provided by PyInstaller)

a = Analysis(  # noqa: F821
    [str(root / "main.py")],
    pathex=[str(root)],
    datas=[(str(root / "assets" / "app.ico"), "assets")],
    hiddenimports=["win32print", "win32api", "pywintypes"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtNetwork",
              "pytest", "zxingcpp"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="83MensWear",
    console=False,
    icon=str(root / "assets" / "app.ico"),
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="83MensWear")  # noqa: F821
