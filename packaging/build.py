"""Build the standalone app.

    python packaging/build.py              -> dist/BibitVisualizer.exe (one file)
    python packaging/build.py --onedir     -> dist/BibitVisualizer/  (starts faster)
    python packaging/build.py --console    -> keeps a console, for the --no-gui CLI

The result needs no Python installed. Double-click it and everything -- opening
the last ledger, importing PDFs and spreadsheets, the help -- happens inside.

Notes on the options below:

* pdfplumber reaches pdfminer.six, which loads CMap tables from data files at
  runtime, and pypdfium2, which loads a bundled DLL. Neither survives a plain
  bytecode scan, so both are collected wholesale.
* pandas is excluded on purpose. Nothing imports it any more (the .xlsx reader
  uses openpyxl directly), and leaving it out keeps ~55 MB out of the build.
* The GUI toolkit backends are excluded so matplotlib cannot drag in Qt or wx.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "BibitVisualizer"

COLLECT_WHOLE = ("pdfplumber", "pdfminer", "pypdfium2")
EXCLUDE = (
    "pandas", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "IPython", "jupyter", "notebook", "pytest", "sphinx",
    "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_wx",
    "matplotlib.backends.backend_webagg", "matplotlib.backends.backend_gtk3agg",
)


def build(onedir=False, console=False, clean=False):
    try:
        import PyInstaller.__main__ as pyinstaller
    except ImportError:
        sys.exit("PyInstaller is not installed. Run:  pip install pyinstaller")

    icon = ROOT / "packaging" / "icon.ico"
    args = [
        str(ROOT / "main.py"),
        "--name", NAME,
        "--noconfirm",
        "--onedir" if onedir else "--onefile",
        "--console" if console else "--windowed",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT),
        "--hidden-import", "bibitviz.pdf_report",   # imported lazily, on demand
        "--hidden-import", "bibitviz.projection_window",   # likewise, on first Ctrl+P
        "--hidden-import", "openpyxl",
    ]
    if icon.exists():
        args += ["--icon", str(icon)]
    # Startup is ~5s, nearly all of it matplotlib importing, so show something
    # immediately. The app closes the splash once its window is ready.
    splash = ROOT / "packaging" / "splash.png"
    if splash.exists() and not onedir:
        args += ["--splash", str(splash)]
    if clean:
        args.append("--clean")
    for module in COLLECT_WHOLE:
        args += ["--collect-all", module]
    for module in EXCLUDE:
        args += ["--exclude-module", module]

    print(f"Building {NAME} ({'folder' if onedir else 'single file'}, "
          f"{'console' if console else 'windowed'})...\n")
    pyinstaller.run(args)

    target = ROOT / "dist" / (NAME if onedir else f"{NAME}.exe")
    if target.exists():
        size = (
            sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
            if target.is_dir() else target.stat().st_size
        )
        print(f"\nBuilt {target}  ({size / 1e6:.0f} MB)")
    else:
        sys.exit("Build finished but the output is missing - check the log above.")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the standalone app.")
    parser.add_argument("--onedir", action="store_true",
                        help="a folder instead of one file; starts noticeably faster")
    parser.add_argument("--console", action="store_true",
                        help="keep a console window, so --no-gui prints where you can see it")
    parser.add_argument("--clean", action="store_true", help="discard PyInstaller's cache first")
    args = parser.parse_args(argv)

    if args.clean:
        for junk in (ROOT / "build", ROOT / "dist"):
            shutil.rmtree(junk, ignore_errors=True)
    build(onedir=args.onedir, console=args.console, clean=args.clean)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
