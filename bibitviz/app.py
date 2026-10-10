"""The desktop app: an editable monthly ledger on the left, the chart on the right.

The ledger is a tree -- one node per month, one child row per entry -- because a
month genuinely holds several things: the month's purchases, its sales, a bond
coupon, a crypto buy you typed in yourself. Double-click any cell to edit it in
place; the chart redraws as you go.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from . import chart as chart_module  # noqa: E402
from . import storage, theme as theme_module  # noqa: E402
from .projection import ProjectionSettings, default_settings  # noqa: E402
from .importer import DEFAULT_CATEGORY, ImportError_, import_paths, parse_amount  # noqa: E402
from .model import (  # noqa: E402
    IN,
    OUT,
    DIRECTION_LABEL,
    Entry,
    History,
    Ledger,
    LedgerError,
    normalize_month,
    shift_month,
)

APP_NAME = "Bibit Transaction Visualizer"
BIBIT_FILETYPES = [
    ("Bibit report", "*.pdf *.csv *.xlsx *.xls"),
    ("PDF transaction history", "*.pdf"),
    ("CSV", "*.csv"),
    ("Excel", "*.xlsx *.xls"),
    ("All files", "*.*"),
]
_COLUMNS = ("month", "direction", "amount", "purpose", "category", "label", "note")
_HEADINGS = {
    "month": "Month",
    "direction": "In / Out",
    "amount": "Amount (IDR)",
    "purpose": "Purpose",
    "category": "Category",
    "label": "Label",
    "note": "Note",
}
_WIDTHS = {"month": 74, "direction": 58, "amount": 116, "purpose": 104,
           "category": 92, "label": 128, "note": 140}


# --------------------------------------------------------------------------- formatting


def format_idr(value: float) -> str:
    """Indonesian grouping: 13.690.000 (dots for thousands)."""
    sign = "-" if value < 0 else ""
    return sign + f"{abs(value):,.0f}".replace(",", ".")


def format_idr_compact(value: float) -> str:
    sign = "-" if value < 0 else ""
    size = abs(value)
    for cut, suffix, places in ((1e12, "T", 2), (1e9, "M", 2), (1e6, "jt", 1), (1e3, "rb", 0)):
        if size >= cut:
            number = f"{size / cut:.{places}f}".replace(".", ",")
            return f"{sign}Rp {number} {suffix}"
    return f"{sign}Rp {size:,.0f}".replace(",", ".")


# --------------------------------------------------------------------------- dialogs


class EntryDialog(tk.Toplevel):
    """Add or edit one ledger row."""

    def __init__(self, parent, ledger: Ledger, entry=None, default_month=None):
        super().__init__(parent)
        self.title("Edit row" if entry else "Add row")
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self._ledger = ledger

        month = entry.month if entry else (default_month or "")
        self.var_month = tk.StringVar(value=month)
        self.var_direction = tk.StringVar(value=DIRECTION_LABEL[entry.direction if entry else IN])
        self.var_amount = tk.StringVar(value=format_idr(entry.amount) if entry else "")
        self.var_category = tk.StringVar(value=entry.category if entry else (ledger.categories[0] if ledger.categories else DEFAULT_CATEGORY))
        self.var_purpose = tk.StringVar(value=entry.purpose if entry else "")
        self.var_label = tk.StringVar(value=entry.label if entry else "")
        self.var_note = tk.StringVar(value=entry.note if entry else "")

        body = ttk.Frame(self, padding=14)
        body.grid(row=0, column=0, sticky="nsew")

        rows = [
            ("Month (YYYY-MM)", ttk.Entry(body, textvariable=self.var_month, width=28)),
            ("Direction", ttk.Combobox(body, textvariable=self.var_direction, width=26,
                                       state="readonly", values=[DIRECTION_LABEL[IN], DIRECTION_LABEL[OUT]])),
            ("Amount (IDR)", ttk.Entry(body, textvariable=self.var_amount, width=28)),
            ("Purpose", ttk.Combobox(body, textvariable=self.var_purpose, width=26, values=list(ledger.purposes))),
            ("Category", ttk.Combobox(body, textvariable=self.var_category, width=26, values=list(ledger.categories))),
            ("Label", ttk.Entry(body, textvariable=self.var_label, width=28)),
            ("Note", ttk.Entry(body, textvariable=self.var_note, width=28)),
        ]
        for index, (caption, widget) in enumerate(rows):
            ttk.Label(body, text=caption).grid(row=index, column=0, sticky="w", pady=4, padx=(0, 10))
            widget.grid(row=index, column=1, sticky="ew", pady=4)
        ttk.Label(
            body,
            text="Purpose is what an Out row was spent on - eat, holiday, bill.\n"
                 "Type any new purpose or category name to create it.",
            foreground="#898781",
        ).grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Save", command=self._save).pack(side="right")

        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())
        rows[0][1].focus_set()
        self.grab_set()
        self.wait_window(self)

    def _save(self):
        amount = parse_amount(self.var_amount.get())
        if amount is None:
            messagebox.showerror("Add row", "Amount is not a number I can read.", parent=self)
            return
        try:
            self.result = {
                "month": normalize_month(self.var_month.get()),
                "direction": IN if self.var_direction.get() == DIRECTION_LABEL[IN] else OUT,
                "amount": abs(amount),
                "category": self.var_category.get().strip() or DEFAULT_CATEGORY,
                "purpose": self.var_purpose.get().strip(),
                "label": self.var_label.get().strip(),
                "note": self.var_note.get().strip(),
            }
        except LedgerError as error:
            messagebox.showerror("Add row", str(error), parent=self)
            return
        self.destroy()


HELP_TEXT = """\
GETTING STARTED

  1.  File > Import Bibit report...   (Ctrl+I)
      Select every file that makes up your history. You can pick several at
      once - hold Ctrl and click - and they are joined into one run.
  2.  File > Save   (Ctrl+S)
      From then on the app reopens this ledger by itself when you start it.
      File > Open recent lists the others.

  Nothing is sent anywhere. Your ledger is a plain JSON file on your disk.


IMPORTING, AND WHY SEVERAL FILES

  Bibit's PDF transaction history covers at most one year, so a longer history
  arrives as several files whose date ranges overlap. Select them all together
  and the app stitches them: for each day it takes the rows from exactly one
  report, so an overlap can never be counted twice, and identical transactions
  on the same day are preserved rather than deduplicated away.

  Old spreadsheet exports (.csv / .xlsx) can be mixed in with new PDFs the same
  way. If the files leave a gap in time, or two of them disagree about a day,
  you are told before the import lands.

  The import reads all five tables in the PDF - mutual funds, FR bonds, bond
  coupons, stocks and dividends - and checks each section against the "Total"
  line the PDF prints, so a misread shows up as a warning rather than a wrong
  chart.


THE LEDGER

  Each month holds as many rows as you need. An import gives a month one row
  per kind - a Fund Buy row, a Coupon row, a Fund Sell row - and you add your
  own beside them for anything Bibit does not know about (crypto, gold, another
  broker). Double-click any cell to edit it in place.

  In  = money into the portfolio (buys, deposits, coupons)   - green
  Out = money taken back out (sales, withdrawals)            - red

  A month's own row is bold and takes the colour of its net, so a month that
  gave back more than it took in reads red at a glance. The In / Out column
  always spells the direction out as well, so the colour never has to be
  relied on alone.

  Category is which pot the money moved through - Bibit, Crypto, anything you
  type. Its colour is fixed once created, so hiding one never recolours the rest.


BREAKING A MONTH'S SPENDING DOWN

  Purpose is what an Out row was actually spent on: eat, holiday, transport,
  electricity, bill - free text, type anything.

  An import lands one summarised Out row per month, so to break a month down:

    1.  Click the Out row.
    2.  Ctrl+K (Split row). Take an amount off it and give that part a purpose.
    3.  Repeat on what is left for the next purpose.

  The month's total never changes, only how it is described. To tag several
  rows at once, select them and press Ctrl+T.

  Then set the View dropdown to "Outflow by purpose". Anything not yet tagged
  shows as Untagged in grey - it is never quietly dropped - and the "Outflow
  tagged" figure at the top tells you how much is accounted for.


THE CHART

  In vs Out            monthly money in and out, with the net line over it,
                       and the running total of capital underneath
  By category          In above the line, Out below, coloured by category
  Outflow by purpose   each month's spending stacked by what it was for, with
                       a ranked total for the whole window underneath

  From / To and the Categories menu narrow what is charted. "Last 12" jumps to
  the last year; "All" clears everything. Units switches between rupiah,
  thousands and millions.

  Both panels carry a point per month and both respond to hover: over the top
  one you get that month's In, Out, Net and the split behind them; over the
  cumulative line you get the running total, what that month added, and what it
  stood at before.


PROJECTION

  View > Projection... (Ctrl+P) carries the ledger forward month by month.

  Enter your monthly salary for the years you know - "2024: 10jt",
  "2026: 11.5jt". After the last year the salary rises by the yearly raise,
  from the month you choose, and a bonus (a multiple of that month's salary)
  arrives once a year. A share of each is saved and added to the balance.

  It starts from the ledger's closing balance, so it continues the
  cumulative line of the main chart. The table underneath puts past years -
  salary earned against what the ledger actually deployed - beside the
  projected ones, so the savings rate you assume can be checked against the
  one you have had. "Use actual" fills in the last 12 months' rate.

  The assumptions are saved in the ledger file.


SAVING AND EXPORTING

  Ledgers are saved as .bviz - plain JSON you can read in a text editor. That
  is a different thing from a Bibit export: the export is read-only source
  data, the .bviz file is your working document including everything you typed.

  File > Export writes the chart as a PNG, the ledger as a CSV, or the monthly
  totals as a CSV.


KEYBOARD

  Ctrl+N   new ledger              Ctrl+O   open ledger
  Ctrl+S   save                    Ctrl+Shift+S  save as
  Ctrl+I   import Bibit report(s)
  Ctrl+Enter  add row              Ctrl+K   split a row
  Ctrl+T   set purpose on selection
  Ctrl+D   duplicate row           Delete   remove row
  Ctrl+Z   undo                    Ctrl+Y   redo
  Ctrl+P   projection
"""


class HelpWindow(tk.Toplevel):
    """Everything needed to use the app, since a packaged build has no README."""

    def __init__(self, parent, palette):
        super().__init__(parent)
        self.title(f"{APP_NAME} - How to use")
        self.transient(parent)
        self.geometry("720x620")
        self.minsize(520, 380)

        frame = ttk.Frame(self, padding=2)
        frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical")
        text = tk.Text(
            frame, wrap="none", font=("Consolas", 9), relief="flat",
            background=palette["ui_field"], foreground=palette["ui_text"],
            insertbackground=palette["ui_text"], padx=16, pady=12,
            yscrollcommand=scroll.set,
        )
        scroll.config(command=text.yview)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.insert("1.0", HELP_TEXT)
        text.config(state="disabled")

        ttk.Button(self, text="Close", command=self.destroy).pack(pady=8)
        self.bind("<Escape>", lambda _e: self.destroy())
        text.focus_set()


class SplitDialog(tk.Toplevel):
    """Carve an amount off a row and give it its own purpose.

    An import lands one summarised Out row per month, so this is how a month's
    outflow gets broken down: peel off "2,000,000 for Holiday", then split the
    remainder again for the next purpose. The month's total never changes.
    """

    def __init__(self, parent, ledger: Ledger, entry):
        super().__init__(parent)
        self.title("Split row")
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.entry = entry

        self.var_amount = tk.StringVar()
        self.var_purpose = tk.StringVar()
        self.var_note = tk.StringVar(value=entry.note)

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text=f"{entry.month}   {DIRECTION_LABEL[entry.direction]}   "
                 f"{format_idr(entry.amount)} IDR   ({entry.label or entry.category})",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body, text="Take part of this row and label it. The rest stays where it is.",
            foreground="#898781",
        ).pack(anchor="w", pady=(2, 12))

        grid = ttk.Frame(body)
        grid.pack(fill="x")
        fields = [
            ("Amount to split off", ttk.Entry(grid, textvariable=self.var_amount, width=26)),
            ("Purpose", ttk.Combobox(grid, textvariable=self.var_purpose, width=24,
                                     values=list(ledger.purposes))),
            ("Note", ttk.Entry(grid, textvariable=self.var_note, width=26)),
        ]
        for index, (caption, widget) in enumerate(fields):
            ttk.Label(grid, text=caption).grid(row=index, column=0, sticky="w", pady=4, padx=(0, 10))
            widget.grid(row=index, column=1, sticky="ew", pady=4)

        self.preview = ttk.Label(body, text="", foreground="#898781")
        self.preview.pack(anchor="w", pady=(10, 0))
        self.var_amount.trace_add("write", lambda *_a: self._update_preview())

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Split", command=self._accept).pack(side="right")

        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        fields[0][1].focus_set()
        self.grab_set()
        self.wait_window(self)

    def _update_preview(self):
        amount = parse_amount(self.var_amount.get())
        if amount is None or not 0 < amount < self.entry.amount:
            self.preview.config(text="")
            return
        self.preview.config(
            text=f"leaves {format_idr(self.entry.amount - amount)} on the original row"
        )

    def _accept(self):
        amount = parse_amount(self.var_amount.get())
        if amount is None:
            messagebox.showerror("Split row", "That amount is not a number I can read.", parent=self)
            return
        if not 0 < amount < self.entry.amount:
            messagebox.showerror(
                "Split row",
                f"Split off something between 0 and {format_idr(self.entry.amount)}.\n\n"
                "To label the whole row, set its purpose directly instead.",
                parent=self,
            )
            return
        self.result = {
            "amount": amount,
            "purpose": self.var_purpose.get().strip(),
            "note": self.var_note.get().strip(),
        }
        self.destroy()


class ImportDialog(tk.Toplevel):
    """How to fold a Bibit export into the ledger."""

    def __init__(self, parent, has_existing: bool, file_count: int = 1):
        super().__init__(parent)
        self.title("Import Bibit report")
        self.transient(parent)
        self.resizable(False, False)
        self.result = None

        self.var_summarize = tk.BooleanVar(value=True)
        self.var_split = tk.BooleanVar(value=False)
        self.var_category = tk.StringVar(value=DEFAULT_CATEGORY)
        self.var_merge = tk.StringVar(value="merge" if has_existing else "replace")

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)

        if file_count > 1:
            ttk.Label(
                body,
                text=f"{file_count} files will be joined into one history - overlapping\n"
                     "days are taken from a single report, so nothing is counted twice.",
            ).pack(anchor="w", pady=(0, 10))

        group = ttk.LabelFrame(body, text="Rows", padding=10)
        group.pack(fill="x")
        ttk.Radiobutton(
            group, text="One row per month, per direction, per kind  (recommended)",
            variable=self.var_summarize, value=True,
        ).pack(anchor="w")
        ttk.Label(
            group, text="A month arrives as e.g. a Fund Buy row, a Coupon row and a Fund Sell row.",
            foreground="#898781",
        ).pack(anchor="w", padx=(22, 0))
        ttk.Radiobutton(
            group, text="Keep every individual transaction", variable=self.var_summarize, value=False,
        ).pack(anchor="w", pady=(6, 0))

        group = ttk.LabelFrame(body, text="Category", padding=10)
        group.pack(fill="x", pady=(10, 0))
        line = ttk.Frame(group)
        line.pack(fill="x")
        ttk.Label(line, text="Name").pack(side="left")
        ttk.Entry(line, textvariable=self.var_category, width=22).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(
            group, text="Separate category per product type (Reksadana, Obligasi FR, ...)",
            variable=self.var_split,
        ).pack(anchor="w", pady=(8, 0))

        if has_existing:
            group = ttk.LabelFrame(body, text="This ledger already has rows", padding=10)
            group.pack(fill="x", pady=(10, 0))
            ttk.Radiobutton(
                group, text="Merge - replace only the months the import covers",
                variable=self.var_merge, value="merge",
            ).pack(anchor="w")
            ttk.Radiobutton(
                group, text="Replace everything", variable=self.var_merge, value="replace",
            ).pack(anchor="w", pady=(4, 0))
            ttk.Radiobutton(
                group, text="Append - keep existing rows and add these alongside",
                variable=self.var_merge, value="append",
            ).pack(anchor="w", pady=(4, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Import", command=self._accept).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()
        self.wait_window(self)

    def _accept(self):
        self.result = {
            "summarize": self.var_summarize.get(),
            "split_by_product_type": self.var_split.get(),
            "category": self.var_category.get().strip() or DEFAULT_CATEGORY,
            "merge": self.var_merge.get(),
        }
        self.destroy()


# --------------------------------------------------------------------------- app


class App(tk.Tk):
    def __init__(self, ledger=None, path=None, settings=None):
        super().__init__()
        self.ledger = ledger or Ledger()
        self.history = History()
        self.path = Path(path) if path else None
        self.dirty = False
        self._editor = None
        self._resize_job = None
        self._render = None
        self._hover = {}
        #: The projection's assumptions as saved in the file, or None until the
        #: projection is first opened for this ledger.
        self._projection = (settings or {}).get("projection")
        self._projection_window = None

        self.options = chart_module.ChartOptions()
        self.var_mode = tk.StringVar(value="In vs Out")
        self.var_scale = tk.StringVar(value="Millions (jt)")
        self.var_theme = tk.StringVar(value="Light")
        self.var_cumulative = tk.BooleanVar(value=True)
        self.var_label_all = tk.BooleanVar(value=False)
        self.var_from = tk.StringVar(value="All")
        self.var_to = tk.StringVar(value="All")
        self.var_status = tk.StringVar(value="Ready.")
        self._category_vars = {}

        self.title(APP_NAME)
        self.geometry("1500x900")
        self.minsize(1080, 660)

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._bind_keys()
        self._rebuild_recent_menu()
        self.apply_theme()
        self.refresh(rebuild_filters=True)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # -- chrome ------------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New ledger", accelerator="Ctrl+N", command=self.on_new)
        file_menu.add_command(label="Open ledger...", accelerator="Ctrl+O", command=self.on_open)
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open recent", menu=self.recent_menu)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.on_save)
        file_menu.add_command(label="Save as...", accelerator="Ctrl+Shift+S", command=self.on_save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Import Bibit report...", accelerator="Ctrl+I", command=self.on_import)
        file_menu.add_separator()
        file_menu.add_command(label="Export chart as PNG...", command=self.on_export_png)
        file_menu.add_command(label="Export ledger as CSV...", command=self.on_export_csv)
        file_menu.add_command(label="Export monthly totals as CSV...", command=self.on_export_monthly)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.on_undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.on_redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Add row...", accelerator="Ctrl+Enter", command=self.on_add)
        edit_menu.add_command(label="Split row...", accelerator="Ctrl+K", command=self.on_split)
        edit_menu.add_command(label="Duplicate row", accelerator="Ctrl+D", command=self.on_duplicate)
        edit_menu.add_command(label="Delete row", accelerator="Delete", command=self.on_delete)
        edit_menu.add_separator()
        edit_menu.add_command(label="Set purpose on selected rows...", accelerator="Ctrl+T",
                              command=self.on_tag_selected)
        edit_menu.add_command(label="Rename purpose...", command=self.on_rename_purpose)
        edit_menu.add_command(label="Rename category...", command=self.on_rename_category)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(
            label="Cumulative panel", variable=self.var_cumulative, command=self.refresh_chart
        )
        view_menu.add_checkbutton(
            label="Label every month", variable=self.var_label_all, command=self.refresh_chart
        )
        view_menu.add_separator()
        view_menu.add_command(label="Projection...", accelerator="Ctrl+P", command=self.on_projection)
        view_menu.add_separator()
        view_menu.add_command(label="Reset filters", command=self.on_reset_filters)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="How to use", accelerator="F1", command=self.on_help)
        help_menu.add_command(label="Keyboard shortcuts", command=self.on_shortcuts)
        help_menu.add_separator()
        help_menu.add_command(label=f"About {APP_NAME}", command=self.on_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(12, 10, 12, 6))
        bar.pack(fill="x")
        self.toolbar = bar

        ttk.Label(bar, text="From").pack(side="left")
        self.combo_from = ttk.Combobox(bar, textvariable=self.var_from, width=9, state="readonly")
        self.combo_from.pack(side="left", padx=(6, 12))
        ttk.Label(bar, text="To").pack(side="left")
        self.combo_to = ttk.Combobox(bar, textvariable=self.var_to, width=9, state="readonly")
        self.combo_to.pack(side="left", padx=(6, 8))
        for combo in (self.combo_from, self.combo_to):
            combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_chart())

        ttk.Button(bar, text="Last 12", width=8, command=lambda: self.on_quick_range(12)).pack(side="left")
        ttk.Button(bar, text="All", width=5, command=self.on_reset_filters).pack(side="left", padx=(4, 16))

        self.category_button = ttk.Menubutton(bar, text="Categories", width=13)
        self.category_menu = tk.Menu(self.category_button, tearoff=0)
        self.category_button.config(menu=self.category_menu)
        self.category_button.pack(side="left", padx=(0, 16))

        for caption, variable, values, width in (
            ("View", self.var_mode, ["In vs Out", "By category", "Outflow by purpose"], 17),
            ("Units", self.var_scale, ["Rupiah", "Thousands (rb)", "Millions (jt)"], 15),
            ("Theme", self.var_theme, ["Light", "Dark"], 7),
        ):
            ttk.Label(bar, text=caption).pack(side="left")
            combo = ttk.Combobox(bar, textvariable=variable, width=width, state="readonly", values=values)
            combo.pack(side="left", padx=(6, 14))
            combo.bind(
                "<<ComboboxSelected>>",
                (lambda _e: self.apply_theme()) if caption == "Theme" else (lambda _e: self.refresh_chart()),
            )

        ttk.Button(bar, text="Projection...", command=self.on_projection).pack(side="right")

    def _build_body(self):
        self.kpi_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        self.kpi_frame.pack(fill="x")
        self.kpi_labels = {}
        for key, caption in (
            ("in", "Total in"), ("out", "Total out"), ("net", "Net deployed"),
            ("tagged", "Outflow tagged"), ("months", "Months"), ("rows", "Ledger rows"),
        ):
            tile = ttk.Frame(self.kpi_frame)
            tile.pack(side="left", padx=(0, 34))
            ttk.Label(tile, text=caption, style="Caption.TLabel").pack(anchor="w")
            value = ttk.Label(tile, text="-", style="Figure.TLabel")
            value.pack(anchor="w")
            self.kpi_labels[key] = value

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        left = ttk.Frame(panes)
        panes.add(left, weight=2)

        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=(0, 6))
        # Visible, not just in the File menu: importing is the first thing
        # anyone does, and a packaged app has no instructions beside it.
        ttk.Button(actions, text="Import report...", command=self.on_import).pack(side="left")
        ttk.Button(actions, text="+ Add row", command=self.on_add).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Split", command=self.on_split).pack(side="left", padx=6)
        ttk.Button(actions, text="Duplicate", command=self.on_duplicate).pack(side="left")
        ttk.Button(actions, text="Delete", command=self.on_delete).pack(side="left", padx=(6, 0))
        ttk.Label(actions, text="Double-click a cell to edit it", style="Caption.TLabel").pack(side="right")

        holder = ttk.Frame(left)
        holder.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(holder, columns=_COLUMNS, show="tree headings", selectmode="extended")
        self.tree.column("#0", width=26, minwidth=26, stretch=False)
        self.tree.heading("#0", text="")
        for name in _COLUMNS:
            self.tree.heading(name, text=_HEADINGS[name])
            self.tree.column(
                name, width=_WIDTHS[name], minwidth=56,
                anchor="e" if name == "amount" else "w",
                stretch=name in ("label", "note"),
            )
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_cell_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._close_editor())

        right = ttk.Frame(panes)
        panes.add(right, weight=3)
        self.figure = Figure(figsize=(9, 7), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        widget = self.canvas.get_tk_widget()
        widget.pack(fill="both", expand=True)
        widget.bind("<Configure>", self._on_canvas_resize)
        self.canvas.mpl_connect("motion_notify_event", self._on_chart_hover)
        self.canvas.mpl_connect("figure_leave_event", lambda _e: self._clear_hover())

        status = ttk.Frame(self, padding=(12, 4))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.var_status, style="Caption.TLabel").pack(side="left")

    def _bind_keys(self):
        bindings = {
            "<Control-n>": self.on_new, "<Control-o>": self.on_open,
            "<Control-s>": self.on_save, "<Control-S>": self.on_save_as,
            "<Control-i>": self.on_import, "<Control-z>": self.on_undo,
            "<Control-y>": self.on_redo, "<Control-d>": self.on_duplicate,
            "<Control-Return>": self.on_add, "<Delete>": self.on_delete,
            "<Control-k>": self.on_split, "<Control-t>": self.on_tag_selected,
            "<Control-p>": self.on_projection, "<F1>": self.on_help,
        }
        for sequence, handler in bindings.items():
            self.bind_all(sequence, lambda _e, fn=handler: (fn(), "break")[1])

    def report_callback_exception(self, exc_type, value, traceback_obj):
        """Show errors instead of losing them.

        A packaged, windowed build has no console, so an unhandled exception
        would otherwise vanish and the app would just look frozen.
        """
        import traceback

        detail = "".join(traceback.format_exception(exc_type, value, traceback_obj))
        try:
            log = storage.settings_path().with_name("error.log")
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"\n--- {APP_NAME} ---\n{detail}")
            where = f"\n\nWritten to:\n{log}"
        except OSError:
            where = ""
        messagebox.showerror(
            "Something went wrong",
            f"{exc_type.__name__}: {value}\n\nYour ledger is unchanged - save it "
            f"under a new name if you want to be safe.{where}",
            parent=self,
        )

    # -- theming -----------------------------------------------------------

    def apply_theme(self):
        name = "dark" if self.var_theme.get() == "Dark" else "light"
        palette = theme_module.theme(name)
        self.options.theme = name

        style = ttk.Style(self)
        style.theme_use("clam")
        background, field, ink, border = (
            palette["ui_bg"], palette["ui_field"], palette["ui_text"], palette["ui_border"]
        )
        self.configure(background=background)
        style.configure(".", background=background, foreground=ink, fieldbackground=field,
                        bordercolor=border, lightcolor=background, darkcolor=background)
        style.configure("TFrame", background=background)
        style.configure("TLabel", background=background, foreground=ink)
        style.configure("TLabelframe", background=background, foreground=ink, bordercolor=border)
        style.configure("TLabelframe.Label", background=background, foreground=palette["muted"])
        style.configure("Caption.TLabel", background=background, foreground=palette["muted"], font=("Segoe UI", 8))
        style.configure("Figure.TLabel", background=background, foreground=ink, font=("Segoe UI", 14, "bold"))
        style.configure("TButton", background=field, foreground=ink, bordercolor=border, focuscolor=background)
        style.map("TButton", background=[("active", border)])
        style.configure("TCheckbutton", background=background, foreground=ink)
        style.configure("TRadiobutton", background=background, foreground=ink)
        style.configure("TMenubutton", background=field, foreground=ink, bordercolor=border)
        style.configure("TCombobox", fieldbackground=field, background=field, foreground=ink,
                        arrowcolor=palette["muted"], bordercolor=border)
        style.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", ink)])
        style.configure("TEntry", fieldbackground=field, foreground=ink, bordercolor=border, insertcolor=ink)
        # Set the row font explicitly so the bold tags differ only in weight,
        # not in size, and every row keeps the same height.
        style.configure("Treeview", background=field, fieldbackground=field, foreground=ink,
                        bordercolor=border, rowheight=23, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=background, foreground=palette["muted"],
                        bordercolor=border, relief="flat")
        style.map("Treeview", background=[("selected", palette["inflow"])], foreground=[("selected", "#ffffff")])
        style.configure("TPanedwindow", background=background)
        style.configure("TScrollbar", background=field, troughcolor=background, bordercolor=border,
                        arrowcolor=palette["muted"])

        # Each tag owns a different option -- direction sets the text colour,
        # month rows set weight and background, tagging state sets a tint -- so
        # a row can carry several and Tk never has to resolve a conflict.
        self.tree.tag_configure("in", foreground=palette["row_in"])
        self.tree.tag_configure("out", foreground=palette["row_out"])
        self.tree.tag_configure("month", font=("Segoe UI", 9, "bold"), background=background)
        # Out rows still waiting for a purpose get a faint tint, so the work left
        # to do is visible at a glance.
        self.tree.tag_configure("untagged", background=palette["ui_bg"])
        self.refresh_chart()

    # -- state -------------------------------------------------------------

    def mark_dirty(self, dirty=True):
        self.dirty = dirty
        self._update_title()

    def _update_title(self):
        name = self.path.name if self.path else "Untitled"
        self.title(f"{'* ' if self.dirty else ''}{name} - {APP_NAME}")

    def record(self):
        """Snapshot before a mutation, so Ctrl+Z can walk it back."""
        self.history.record(self.ledger)

    def status(self, message):
        self.var_status.set(message)

    # -- rendering ---------------------------------------------------------

    def refresh(self, rebuild_filters=False):
        self._close_editor()
        if rebuild_filters:
            self._rebuild_filters()
        self._fill_tree()
        self.refresh_chart()
        self._update_title()

    def _rebuild_filters(self):
        months = self.ledger.months()
        values = ["All"] + months
        self.combo_from.configure(values=values)
        self.combo_to.configure(values=values)
        if self.var_from.get() not in values:
            self.var_from.set("All")
        if self.var_to.get() not in values:
            self.var_to.set("All")

        self.category_menu.delete(0, "end")
        existing = dict(self._category_vars)
        self._category_vars = {}
        for name in self.ledger.categories:
            variable = existing.get(name) or tk.BooleanVar(value=True)
            self._category_vars[name] = variable
            self.category_menu.add_checkbutton(label=name, variable=variable, command=self.refresh_chart)
        if not self.ledger.categories:
            self.category_menu.add_command(label="(none yet)", state="disabled")

    def _selected_categories(self):
        chosen = [name for name, variable in self._category_vars.items() if variable.get()]
        return None if len(chosen) == len(self._category_vars) else chosen

    def _window(self):
        start = self.var_from.get()
        stop = self.var_to.get()
        return (None if start == "All" else start, None if stop == "All" else stop)

    def _fill_tree(self):
        selected = set(self.tree.selection())
        expanded = {item for item in self.tree.get_children("") if self.tree.item(item, "open")}
        self.tree.delete(*self.tree.get_children(""))

        by_month = {}
        for entry in self.ledger.sorted_entries():
            by_month.setdefault(entry.month, []).append(entry)

        for month, entries in by_month.items():
            inflow = sum(e.amount for e in entries if e.direction == IN)
            outflow = sum(e.amount for e in entries if e.direction == OUT)
            node = f"m:{month}"
            untagged = sum(e.amount for e in entries if e.direction == OUT and not e.purpose)
            # The month row carries the same colours by the sign of its net, so a
            # month that gave back more than it took in reads red at a glance.
            net = inflow - outflow
            self.tree.insert(
                "", "end", iid=node, tags=("month", IN if net >= 0 else OUT),
                values=(
                    month, "", format_idr(net),
                    f"{format_idr_compact(untagged)} untagged" if untagged else "all tagged",
                    "", f"{len(entries)} row{'s' if len(entries) != 1 else ''}",
                    f"in {format_idr_compact(inflow)}  |  out {format_idr_compact(outflow)}",
                ),
            )
            for entry in entries:
                tags = [entry.direction]
                if entry.direction == OUT and not entry.purpose:
                    tags.append("untagged")
                self.tree.insert(
                    node, "end", iid=entry.id, tags=tuple(tags),
                    values=(
                        entry.month, DIRECTION_LABEL[entry.direction], format_idr(entry.amount),
                        entry.purpose, entry.category, entry.label, entry.note,
                    ),
                )
            self.tree.item(node, open=node in expanded or not expanded)

        restored = [item for item in selected if self.tree.exists(item)]
        if restored:
            self.tree.selection_set(restored)

    def refresh_chart(self):
        self.options.mode = {
            "By category": chart_module.MODE_CATEGORY,
            "Outflow by purpose": chart_module.MODE_PURPOSE,
        }.get(self.var_mode.get(), chart_module.MODE_FLOW)
        self.options.scale = {
            "Rupiah": "raw", "Thousands (rb)": "thousand", "Millions (jt)": "million",
        }.get(self.var_scale.get(), "million")
        self.options.show_cumulative = self.var_cumulative.get()
        self.options.label_every_month = self.var_label_all.get()

        month_from, month_to = self._window()
        self._hover = {}   # the old annotations died with the cleared figure
        self._render = chart_module.render(
            self.figure, self.ledger, self.options,
            month_from=month_from, month_to=month_to, categories=self._selected_categories(),
        )
        self.canvas.draw_idle()
        self._update_kpis(self._render.summary)
        # the projection starts from the ledger's balance, so it follows every edit
        if self._projection_alive():
            self._projection_window.schedule()

    def _update_kpis(self, summary):
        self.kpi_labels["in"].config(text=format_idr_compact(summary.total_in))
        self.kpi_labels["out"].config(text=format_idr_compact(summary.total_out))
        self.kpi_labels["net"].config(text=format_idr_compact(summary.total_net))
        self.kpi_labels["tagged"].config(
            text=f"{summary.tagged_fraction:.0%}" if summary.total_out else "-"
        )
        self.kpi_labels["months"].config(text=str(len(summary.months)))
        self.kpi_labels["rows"].config(text=str(len(self.ledger.entries)))

    def _on_canvas_resize(self, _event):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(180, self._do_resize)

    def _do_resize(self):
        self._resize_job = None
        self.refresh_chart()

    # -- chart hover -------------------------------------------------------

    def _clear_hover(self):
        shown = [note for note in self._hover.values() if note.get_visible()]
        for note in shown:
            note.set_visible(False)
            note.set_zorder(20)
        if shown:
            self.canvas.draw_idle()

    def _hover_note(self, axes, palette):
        """One reusable annotation per panel. They die with the figure on redraw."""
        note = self._hover.get(axes)
        if note is None:
            note = axes.annotate(
                "", xy=(0, 0), xytext=(14, 14), textcoords="offset points",
                fontsize=8, color=palette["ink"], family="monospace", zorder=20,
                annotation_clip=False,
                # The box is anchored by its left or right edge depending on
                # which side of the point it lands, but the lines inside always
                # stay left-aligned so the columns line up either way.
                multialignment="left",
                bbox={"boxstyle": "round,pad=0.5", "facecolor": palette["surface"],
                      "edgecolor": palette["axis"], "linewidth": 0.8},
            )
            self._hover[axes] = note
        return note

    def _hover_lines(self, render, axes, index):
        summary = render.summary
        scale, unit = render.scale, render.unit
        month = summary.months[index]

        if axes is render.cumulative_axes:
            change = summary.net[index] / scale
            previous = summary.cumulative[index - 1] / scale if index else 0.0
            return [
                month,
                f"Total      {summary.cumulative[index] / scale:,.2f}  ({unit})",
                f"Month      {change:+,.2f}",
                f"Was        {previous:,.2f}",
            ]

        lines = [
            month,
            f"In   {summary.inflow[index] / scale:,.2f}",
            f"Out  {summary.outflow[index] / scale:,.2f}",
            f"Net  {summary.net[index] / scale:,.2f}   ({unit})",
        ]
        for name in summary.categories:
            got_in = summary.inflow_by_category[name][index]
            got_out = summary.outflow_by_category[name][index]
            if got_in or got_out:
                lines.append(f"  {name}: +{got_in / scale:,.2f} / -{got_out / scale:,.2f}")
        if self.options.mode == chart_module.MODE_PURPOSE:
            lines = [line for line in lines if not line.startswith("  ")]
            for name in summary.purposes:
                spent = summary.outflow_by_purpose[name][index]
                if spent:
                    lines.append(f"  {name}: {spent / scale:,.2f}")
        return lines

    def _on_chart_hover(self, event):
        render = self._render
        axes = event.inaxes
        if render is None or axes not in render.month_axes or event.xdata is None:
            self._clear_hover()
            return
        summary = render.summary
        if not summary.months:
            return
        index = int(round(event.xdata))
        if not 0 <= index < len(summary.months):
            self._clear_hover()
            return

        palette = theme_module.theme(self.options.theme)
        note = self._hover_note(axes, palette)
        for other, existing in self._hover.items():
            if other is not axes:
                existing.set_visible(False)

        # On the cumulative panel the tooltip hangs off the month's own point,
        # so it reads as a label for that marker rather than for the pointer.
        if axes is render.cumulative_axes:
            anchor = summary.cumulative[index] / render.scale
        else:
            anchor = event.ydata
        note.set_visible(True)
        note.xy = (index, anchor)
        note.set_text("\n".join(self._hover_lines(render, axes, index)))
        self._place_note(note, axes, index, anchor)
        self.canvas.draw_idle()

    _NOTE_GAP = 14  # px between the point and its tooltip
    #: get_window_extent() measures the text, not the rounded box drawn around
    #: it, so the fit test allows for that padding on every side.
    _NOTE_PAD = 8

    def _place_note(self, note, axes, index, anchor):
        """Flip the tooltip to whichever side of the point it actually fits.

        Left as-is it always sat up and to the right, so on the last months of a
        window it ran off the canvas and got clipped -- by over 200px at the
        final point. Rather than guess from a fraction of the axis, the box is
        measured and put on the side with room for it.
        """
        gap = self._NOTE_GAP
        note.set_ha("left")
        note.set_va("bottom")
        note.xyann = (gap, gap)

        try:
            renderer = self.canvas.get_renderer()
            box = note.get_window_extent(renderer)
            width = box.width + 2 * self._NOTE_PAD
            height = box.height + 2 * self._NOTE_PAD
            point_x, point_y = axes.transData.transform((index, anchor))
            canvas_w, canvas_h = self.canvas.get_width_height()
        except Exception:
            return  # no renderer yet; the default corner is fine

        # Prefer the usual side, take the other when it does not fit, and when
        # neither does, take the roomier one so the clipping is as small as
        # possible rather than always on the same edge.
        room_right, room_left = canvas_w - point_x - gap, point_x - gap
        if width > room_right and (width <= room_left or room_left > room_right):
            note.set_ha("right")
            note.xyann = (-gap, note.xyann[1])

        room_up, room_down = canvas_h - point_y - gap, point_y - gap
        if height > room_up and (height <= room_down or room_down > room_up):
            note.set_va("top")
            note.xyann = (note.xyann[0], -gap)

    # -- inline editing ----------------------------------------------------

    def _close_editor(self):
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None

    def _on_cell_double_click(self, event):
        self._close_editor()
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item or column == "#0":
            return
        if item.startswith("m:"):
            return  # month rows are a read-only roll-up of their children
        field = _COLUMNS[int(column[1:]) - 1]
        box = self.tree.bbox(item, column)
        if not box:
            return

        entry = self.ledger.get(item)
        if entry is None:
            return
        current = {
            "month": entry.month, "direction": DIRECTION_LABEL[entry.direction],
            "amount": format_idr(entry.amount), "purpose": entry.purpose,
            "category": entry.category, "label": entry.label, "note": entry.note,
        }[field]

        if field == "direction":
            widget = ttk.Combobox(self.tree, state="readonly",
                                  values=[DIRECTION_LABEL[IN], DIRECTION_LABEL[OUT]])
        elif field == "category":
            widget = ttk.Combobox(self.tree, values=list(self.ledger.categories))
        elif field == "purpose":
            # editable, not readonly: the list is a set of suggestions, and
            # anything typed becomes a new purpose
            widget = ttk.Combobox(self.tree, values=list(self.ledger.purposes))
        else:
            widget = ttk.Entry(self.tree)
        widget.place(x=box[0], y=box[1], width=box[2], height=box[3])
        if isinstance(widget, ttk.Combobox):
            widget.set(current)
        else:
            widget.insert(0, current)
        widget.focus_set()
        if isinstance(widget, ttk.Entry):
            widget.select_range(0, "end")

        def commit(_event=None):
            value = widget.get()
            self._close_editor()
            self._commit_cell(item, field, value)

        widget.bind("<Return>", commit)
        widget.bind("<FocusOut>", commit)
        widget.bind("<<ComboboxSelected>>", commit)
        widget.bind("<Escape>", lambda _e: self._close_editor())
        self._editor = widget

    def _commit_cell(self, entry_id, field, raw):
        entry = self.ledger.get(entry_id)
        if entry is None:
            return
        try:
            if field == "amount":
                value = parse_amount(raw)
                if value is None:
                    raise LedgerError(f"{raw!r} is not a number I can read.")
                changes = {"amount": abs(value)}
            elif field == "direction":
                changes = {"direction": IN if raw == DIRECTION_LABEL[IN] else OUT}
            elif field == "month":
                changes = {"month": normalize_month(raw)}
            else:
                changes = {field: raw.strip()}
            if getattr(entry, field, None) == changes.get(field):
                return
            self.record()
            self.ledger.update(entry_id, **changes)
        except LedgerError as error:
            messagebox.showerror("Edit row", str(error), parent=self)
            return
        self.mark_dirty()
        self.refresh(rebuild_filters=True)
        self.status(f"Updated {field}.")

    # -- row actions -------------------------------------------------------

    def _selected_entry_ids(self):
        return [item for item in self.tree.selection() if not item.startswith("m:")]

    def _default_month(self):
        for item in self.tree.selection():
            return item[2:] if item.startswith("m:") else self.ledger.get(item).month
        months = self.ledger.months()
        return months[-1] if months else ""

    def on_add(self):
        dialog = EntryDialog(self, self.ledger, default_month=self._default_month())
        if not dialog.result:
            return
        self.record()
        entry = self.ledger.add(Entry(source="manual", **dialog.result))
        self.mark_dirty()
        self.refresh(rebuild_filters=True)
        if self.tree.exists(entry.id):
            self.tree.see(entry.id)
            self.tree.selection_set(entry.id)
        self.status(f"Added a row in {entry.month}.")

    def on_split(self):
        ids = self._selected_entry_ids()
        if len(ids) != 1:
            self.status("Select exactly one row to split.")
            return
        entry = self.ledger.get(ids[0])
        if entry is None:
            return
        dialog = SplitDialog(self, self.ledger, entry)
        if not dialog.result:
            return
        try:
            self.record()
            piece = self.ledger.split(
                entry.id, dialog.result["amount"],
                purpose=dialog.result["purpose"], note=dialog.result["note"],
            )
        except LedgerError as error:
            messagebox.showerror("Split row", str(error), parent=self)
            return
        self.mark_dirty()
        self.refresh(rebuild_filters=True)
        if self.tree.exists(piece.id):
            self.tree.see(piece.id)
            self.tree.selection_set(piece.id)
        self.status(
            f"Split off {format_idr(piece.amount)} as {piece.purpose or 'untagged'}."
        )

    def on_tag_selected(self):
        """Give every selected row the same purpose -- the fast way to tag a batch."""
        ids = self._selected_entry_ids()
        if not ids:
            self.status("Select the rows you want to tag.")
            return
        from tkinter.simpledialog import askstring

        known = ", ".join(self.ledger.purposes[:12]) or "none yet"
        purpose = askstring(
            "Set purpose",
            f"Purpose for {len(ids)} selected row(s)?\n\nAlready in use: {known}\n"
            "(leave blank to clear)",
            parent=self,
        )
        if purpose is None:
            return
        self.record()
        for entry_id in ids:
            self.ledger.update(entry_id, purpose=purpose.strip())
        self.mark_dirty()
        self.refresh(rebuild_filters=True)
        self.status(f"Tagged {len(ids)} row(s) as {purpose.strip() or 'untagged'}.")

    def on_rename_purpose(self):
        if not self.ledger.purposes:
            return
        from tkinter.simpledialog import askstring

        old = askstring(
            "Rename purpose",
            "Which purpose?\n\n" + ", ".join(self.ledger.purposes), parent=self,
        )
        if not old or old not in self.ledger.purposes:
            return
        new = askstring("Rename purpose", f"New name for {old!r}:", parent=self, initialvalue=old)
        if not new or new == old:
            return
        try:
            self.record()
            self.ledger.rename_purpose(old, new)
        except LedgerError as error:
            messagebox.showerror("Rename purpose", str(error), parent=self)
            return
        self.mark_dirty()
        self.refresh(rebuild_filters=True)
        self.status(f"Renamed {old!r} to {new!r}.")

    def on_duplicate(self):
        ids = self._selected_entry_ids()
        if not ids:
            self.status("Select a row to duplicate.")
            return
        self.record()
        for entry_id in ids:
            self.ledger.duplicate(entry_id)
        self.mark_dirty()
        self.refresh()
        self.status(f"Duplicated {len(ids)} row(s).")

    def on_delete(self):
        ids = self._selected_entry_ids()
        if not ids:
            return
        if len(ids) > 1 and not messagebox.askyesno("Delete rows", f"Delete {len(ids)} rows?", parent=self):
            return
        self.record()
        for entry_id in ids:
            self.ledger.remove(entry_id)
        self.mark_dirty()
        self.refresh(rebuild_filters=True)
        self.status(f"Deleted {len(ids)} row(s).")

    def on_rename_category(self):
        if not self.ledger.categories:
            return
        from tkinter.simpledialog import askstring

        current = self.ledger.categories
        old = askstring("Rename category", f"Which category?\n\n{', '.join(current)}", parent=self)
        if not old or old not in current:
            return
        new = askstring("Rename category", f"New name for {old!r}:", parent=self, initialvalue=old)
        if not new or new == old:
            return
        try:
            self.record()
            self.ledger.rename_category(old, new)
        except LedgerError as error:
            messagebox.showerror("Rename category", str(error), parent=self)
            return
        self.mark_dirty()
        self.refresh(rebuild_filters=True)

    # -- filters -----------------------------------------------------------

    def on_quick_range(self, months):
        available = self.ledger.months()
        if not available:
            return
        self.var_to.set(available[-1])
        self.var_from.set(shift_month(available[-1], -(months - 1)) if len(available) >= months else available[0])
        if self.var_from.get() not in available:
            self.var_from.set(available[0])
        self.refresh_chart()

    def on_reset_filters(self):
        self.var_from.set("All")
        self.var_to.set("All")
        for variable in self._category_vars.values():
            variable.set(True)
        self.refresh_chart()

    # -- file --------------------------------------------------------------

    def _confirm_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            APP_NAME, "Save changes to the current ledger first?", parent=self
        )
        if answer is None:
            return False
        return self.on_save() if answer else True

    def on_new(self):
        if not self._confirm_discard():
            return
        self._close_projection()
        self.ledger = Ledger()
        self._projection = None
        self.history.clear()
        self.path = None
        self.mark_dirty(False)
        self.on_reset_filters()
        self.refresh(rebuild_filters=True)
        self.status("New ledger.")

    def _rebuild_recent_menu(self):
        self.recent_menu.delete(0, "end")
        items = storage.recent_files()
        if not items:
            self.recent_menu.add_command(label="(nothing yet)", state="disabled")
            return
        for path in items:
            self.recent_menu.add_command(
                label=path.name, command=lambda p=path: self.open_path(p)
            )

    def on_open(self):
        path = filedialog.askopenfilename(
            title="Open ledger", filetypes=storage.FILETYPES, parent=self
        )
        if path:
            self.open_path(path)

    def open_path(self, path):
        """Open a ledger file, guarding unsaved work first."""
        if not self._confirm_discard():
            return
        try:
            ledger, settings = storage.load(path)
        except storage.StorageError as error:
            messagebox.showerror("Open ledger", str(error), parent=self)
            return
        self._close_projection()
        self.ledger = ledger
        self._projection = settings.get("projection")
        self.history.clear()
        self.path = Path(path)
        if settings.get("theme") in theme_module.THEMES:
            self.var_theme.set(settings["theme"].capitalize())
        if settings.get("scale_label"):
            self.var_scale.set(settings["scale_label"])
        if settings.get("mode_label"):
            self.var_mode.set(settings["mode_label"])
        self.mark_dirty(False)
        self.on_reset_filters()
        self.refresh(rebuild_filters=True)
        self.apply_theme()
        storage.remember_recent(self.path, theme=self.options.theme)
        self._rebuild_recent_menu()
        self.status(f"Opened {Path(path).name} - {len(ledger.entries)} rows.")

    def _settings(self):
        return {
            "theme": self.options.theme,
            "scale_label": self.var_scale.get(),
            "mode_label": self.var_mode.get(),
            "show_cumulative": self.var_cumulative.get(),
            **({"projection": self._projection} if self._projection is not None else {}),
        }

    def on_save(self):
        if self.path is None:
            return self.on_save_as()
        try:
            storage.save(self.path, self.ledger, self._settings())
        except OSError as error:
            messagebox.showerror("Save", f"Could not write the file:\n{error}", parent=self)
            return False
        self.mark_dirty(False)
        # Remembered so the next launch reopens this ledger instead of an empty one.
        storage.remember_recent(self.path, theme=self.options.theme)
        self._rebuild_recent_menu()
        self.status(f"Saved {self.path.name}.")
        return True

    def on_save_as(self):
        path = filedialog.asksaveasfilename(
            title="Save ledger as", defaultextension=storage.EXTENSION,
            filetypes=storage.FILETYPES, parent=self,
            initialfile=self.path.name if self.path else "ledger.bviz",
        )
        if not path:
            return False
        self.path = Path(path)
        return self.on_save()

    def on_import(self):
        # Plural: a PDF report covers at most a year, so a full history is
        # several files. They get stitched into one continuous run.
        paths = filedialog.askopenfilenames(
            title="Import Bibit report(s) - select every file that makes up the history",
            filetypes=BIBIT_FILETYPES, parent=self,
        )
        if not paths:
            return
        paths = list(paths)
        dialog = ImportDialog(self, has_existing=bool(self.ledger.entries), file_count=len(paths))
        if not dialog.result:
            return
        choice = dialog.result
        try:
            result = import_paths(
                paths,
                summarize=choice["summarize"],
                split_by_product_type=choice["split_by_product_type"],
                category=choice["category"],
            )
        except (ImportError_, OSError) as error:
            messagebox.showerror("Import", str(error), parent=self)
            return
        if not result.entries:
            messagebox.showwarning(
                "Import", "Nothing usable in those files.\n\n" + "\n".join(result.warnings[:8]), parent=self
            )
            return
        if not self._confirm_stitch(result):
            return

        self.record()
        mode = choice["merge"]
        if mode == "replace" or not self.ledger.entries:
            self.ledger = Ledger(categories=list(self.ledger.categories))
            self.ledger.extend(result.entries)
            note = "replaced the ledger"
        elif mode == "merge":
            removed = self.ledger.replace_months(result.months, result.entries)
            note = f"merged, replacing {removed} row(s) in the imported months"
        else:
            self.ledger.extend(result.entries)
            note = "appended"

        self.mark_dirty()
        self.on_reset_filters()
        self.refresh(rebuild_filters=True)
        self.status(f"{result.describe()} ({note})")
        if result.warnings:
            messagebox.showinfo(
                "Import finished",
                f"{result.describe()}\n\nNotes:\n" + "\n".join(f"- {w}" for w in result.warnings[:10]),
                parent=self,
            )

    def _confirm_stitch(self, result):
        """Show what joining the files produced, and stop if it looks incomplete.

        A gap or a disagreement between reports is exactly the thing that would
        otherwise turn into a quietly wrong chart, so it is put in front of the
        user as a decision rather than a line in a log.
        """
        joined = result.stitch
        if joined is None or (len(joined.reports) < 2 and joined.ok):
            return True

        lines = [f"- {report.describe()}" for report in joined.reports]
        body = "Files read:\n" + "\n".join(lines) + "\n\n" + joined.describe()
        if joined.ok:
            messagebox.showinfo("Stitched reports", body, parent=self)
            return True
        return messagebox.askokcancel(
            "Stitched reports - check this",
            body + "\n\nImport anyway?",
            parent=self, icon="warning", default="cancel",
        )

    # -- export ------------------------------------------------------------

    def on_export_png(self):
        path = filedialog.asksaveasfilename(
            title="Export chart", defaultextension=".png",
            filetypes=[("PNG image", "*.png")], parent=self, initialfile="cash-flow.png",
        )
        if not path:
            return
        self.figure.savefig(path, dpi=200, facecolor=self.figure.get_facecolor())
        self.status(f"Chart written to {Path(path).name}.")

    def on_export_csv(self):
        path = filedialog.asksaveasfilename(
            title="Export ledger", defaultextension=".csv",
            filetypes=[("CSV", "*.csv")], parent=self, initialfile="ledger.csv",
        )
        if path:
            storage.export_csv(path, self.ledger)
            self.status(f"Ledger written to {Path(path).name}.")

    def on_export_monthly(self):
        if self._render is None:
            return
        path = filedialog.asksaveasfilename(
            title="Export monthly totals", defaultextension=".csv",
            filetypes=[("CSV", "*.csv")], parent=self, initialfile="monthly.csv",
        )
        if path:
            storage.export_monthly_csv(path, self._render.summary)
            self.status(f"Monthly totals written to {Path(path).name}.")

    # -- history -----------------------------------------------------------

    def on_undo(self):
        if self.history.undo(self.ledger):
            self.mark_dirty()
            self.refresh(rebuild_filters=True)
            self.status("Undone.")
        else:
            self.status("Nothing to undo.")

    def on_redo(self):
        if self.history.redo(self.ledger):
            self.mark_dirty()
            self.refresh(rebuild_filters=True)
            self.status("Redone.")
        else:
            self.status("Nothing to redo.")

    # -- projection --------------------------------------------------------

    def projection_settings(self) -> ProjectionSettings:
        if self._projection is not None:
            return ProjectionSettings.from_dict(self._projection)
        return default_settings(self.ledger)

    def store_projection_settings(self, settings: ProjectionSettings) -> None:
        """Keep the window's assumptions with the ledger, so they save with it.

        The first store only records the defaults the window opened with --
        just opening the projection is not an edit, so it does not mark the
        ledger unsaved. Every real change after that does.
        """
        stored = settings.to_dict()
        if stored == self._projection:
            return
        first = self._projection is None
        self._projection = stored
        if not first:
            self.mark_dirty()

    def _projection_alive(self) -> bool:
        window = self._projection_window
        return window is not None and bool(window.winfo_exists())

    def _close_projection(self):
        """Its form belongs to the current ledger, so it must not outlive it."""
        if self._projection_alive():
            self._projection_window.destroy()
        self._projection_window = None

    def on_projection(self):
        if self._projection_alive():
            self._projection_window.deiconify()
            self._projection_window.lift()
            self._projection_window.focus_set()
            return
        from .projection_window import ProjectionWindow

        self._projection_window = ProjectionWindow(self)

    # -- misc --------------------------------------------------------------

    def on_help(self):
        HelpWindow(self, theme_module.theme(self.options.theme))

    def on_about(self):
        from . import __version__

        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME}  v{__version__}\n\n"
            "An editable monthly cash-flow ledger for Bibit exports.\n"
            "Reads .pdf, .csv and .xlsx reports and stitches several\n"
            "into one continuous history.\n\n"
            f"Settings and recent files:\n{storage.settings_path()}\n\n"
            "Everything stays on this computer.",
            parent=self,
        )

    def on_shortcuts(self):
        messagebox.showinfo(
            "Keyboard shortcuts",
            "Ctrl+N  new ledger\n"
            "Ctrl+O  open ledger (.bviz)\n"
            "Ctrl+S  save        Ctrl+Shift+S  save as\n"
            "Ctrl+I  import a Bibit report (.csv / .xlsx)\n"
            "Ctrl+Enter  add row     Ctrl+D  duplicate     Delete  remove\n"
            "Ctrl+Z / Ctrl+Y  undo / redo\n"
            "Ctrl+P  projection\n\n"
            "Double-click any cell in the ledger to edit it in place.\n"
            "A month can hold as many rows as you like - add one per\n"
            "source (Bibit, Crypto, ...) and the chart adds them up.",
            parent=self,
        )

    def on_close(self):
        if self._confirm_discard():
            self.destroy()


def close_splash():
    """Dismiss the packaged build's splash screen. A no-op when running from source."""
    try:
        import pyi_splash  # only exists inside a PyInstaller one-file build

        pyi_splash.close()
    except Exception:
        pass


def launch(ledger=None, path=None):
    app = App(ledger=ledger, path=path)
    app.after(80, close_splash)
    app.mainloop()
