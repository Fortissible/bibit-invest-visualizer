"""Bibit Transaction Visualizer.

Run with no arguments for the app:

    python main.py
    python main.py my-ledger.bviz

Bibit's PDF transaction history covers at most one year, so a longer history is
several files. Pass them all and they are stitched into one continuous run --
overlapping days are taken from exactly one report, so nothing is double-counted.
Old CSV/XLSX exports can be mixed in the same way.

    python main.py --import 2023-2024.pdf 2024-2025.pdf 2025-2026.pdf
    python main.py --import old-export.csv 2025-2026.pdf

Or headless, to render a chart without opening a window:

    python main.py --import *.pdf --png chart.png --no-gui
    python main.py --import report.pdf --save ledger.bviz --no-gui
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bibitviz import storage
from bibitviz.chart import SCALE_ORDER, ChartOptions
from bibitviz.importer import ImportError_, import_paths
from bibitviz.model import Ledger


def build_parser():
    parser = argparse.ArgumentParser(
        prog="bibit-transaction-visualizer",
        description="Edit a monthly in/out ledger and chart it. Imports Bibit CSV/XLSX exports.",
    )
    parser.add_argument("ledger", nargs="?", help="a .bviz ledger file to open")
    parser.add_argument("--import", dest="import_paths", metavar="FILE", nargs="+", default=None,
                        help="Bibit report(s) to import: .pdf, .csv or .xlsx. Pass several "
                             "and they are stitched into one history, since a PDF report "
                             "covers at most a year")
    parser.add_argument("--fresh", action="store_true",
                        help="start empty instead of reopening the last ledger")
    parser.add_argument("--keep-transactions", action="store_true",
                        help="import every transaction instead of one row per month/direction/kind")
    parser.add_argument("--save", metavar="FILE", help="write the ledger to a .bviz file")
    parser.add_argument("--png", metavar="FILE", help="render the chart to a PNG")
    parser.add_argument("--csv", metavar="FILE", help="write the monthly totals to a CSV")
    parser.add_argument("--no-gui", action="store_true", help="do the above and exit, without a window")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--scale", choices=SCALE_ORDER, default="million")
    parser.add_argument("--mode", choices=("flow", "category", "purpose"), default="flow")
    parser.add_argument("--size", default="13x7.5", metavar="WxH", help="PNG size in inches (default 13x7.5)")
    return parser


def load_startup_ledger(args):
    """Open the given ledger, import the given report, or reopen the last one.

    With no arguments the app comes back to the ledger you were last working on,
    rather than an empty one. `--fresh` opts out.
    """
    ledger, path, settings = Ledger(), None, {}
    target = args.ledger
    reopened = False
    if target is None and not args.import_paths and not args.fresh:
        recent = storage.recent_files()
        if recent:
            target, reopened = str(recent[0]), True
    if target:
        try:
            ledger, settings = storage.load(target)
            path = Path(target)
        except storage.StorageError:
            if not reopened:
                raise
            # The remembered ledger has been moved or damaged. Start empty
            # rather than refusing to open at all.
            ledger, path, target, settings = Ledger(), None, None, {}
    if args.import_paths:
        result = import_paths(args.import_paths, summarize=not args.keep_transactions)
        if target:
            ledger.replace_months(result.months, result.entries)
        else:
            ledger.extend(result.entries)
        print(result.describe(), file=sys.stderr)
        if result.stitch is not None and len(result.stitch.reports) > 1:
            for report in result.stitch.reports:
                print(f"  - {report.describe()}", file=sys.stderr)
            for line in result.stitch.describe().splitlines():
                print(f"  {line}", file=sys.stderr)
        for warning in result.warnings[:10]:
            print(f"  note: {warning}", file=sys.stderr)
    return ledger, path, settings


def run_headless(ledger, args):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from bibitviz import chart as chart_module

    if args.save:
        storage.save(args.save, ledger, {"theme": args.theme})
        print(f"Wrote {args.save}")

    if args.png or args.csv:
        try:
            width, height = (float(part) for part in args.size.lower().split("x"))
        except ValueError:
            width, height = 13.0, 7.5
        figure = plt.figure(figsize=(width, height), dpi=110)
        options = ChartOptions(theme=args.theme, mode=args.mode, scale=args.scale)
        result = chart_module.render(figure, ledger, options)
        if args.png:
            figure.savefig(args.png, facecolor=figure.get_facecolor())
            print(f"Wrote {args.png}")
        if args.csv:
            storage.export_monthly_csv(args.csv, result.summary)
            print(f"Wrote {args.csv}")
        plt.close(figure)

    if not (args.save or args.png or args.csv):
        summary = ledger.summarize()
        print(f"{len(ledger.entries)} rows over {len(summary.months)} months")
        print(f"  in  {summary.total_in:>18,.0f} IDR")
        print(f"  out {summary.total_out:>18,.0f} IDR")
        print(f"  net {summary.total_net:>18,.0f} IDR")


def _report_startup_error(message, windowed):
    """A packaged build has no console, so say it in a dialog instead of vanishing."""
    print(f"error: {message}", file=sys.stderr)
    if not windowed:
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Bibit Transaction Visualizer", str(message))
        root.destroy()
    except Exception:
        pass


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ledger, path, settings = load_startup_ledger(args)
    except (ImportError_, storage.StorageError) as error:
        _report_startup_error(error, windowed=not args.no_gui)
        return 2

    if args.no_gui:
        run_headless(ledger, args)
        return 0

    from bibitviz.app import App, close_splash

    app = App(ledger=ledger, path=path, settings=settings)
    app.var_theme.set(args.theme.capitalize())
    app.apply_theme()
    if args.import_paths and path is None:
        app.mark_dirty(True)
    app.after(80, close_splash)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
