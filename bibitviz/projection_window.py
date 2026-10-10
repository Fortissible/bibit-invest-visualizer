"""The projection window: assumptions on the left, the chart and a by-year table on the right.

Every field re-runs the projection as you type. The assumptions belong to the
ledger -- they are saved in its .bviz file -- so changing one marks the ledger
unsaved, the same as editing a row.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import chart as chart_module
from . import theme as theme_module
from .importer import parse_amount
from .projection import (
    MONTH_NAMES,
    ProjectionSettings,
    actual_years,
    implied_raises,
    project,
    suggest_save_pct,
)

_SUFFIX_RE = re.compile(r"^\s*(.*?)\s*(jt|juta|m|rb|ribu|k)\s*$", re.IGNORECASE)
_MULTIPLIER = {"jt": 1e6, "juta": 1e6, "m": 1e6, "rb": 1e3, "ribu": 1e3, "k": 1e3}


def parse_salary(raw):
    """A monthly salary as typed: '11.500.000', '11.5jt', '11,5 juta', or just '11.5'.

    A bare number under 1,000 is read as millions -- nobody's monthly salary is
    Rp 11 -- so the timeline can be typed the way it is spoken.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    multiplier = 1.0
    match = _SUFFIX_RE.match(text)
    if match:
        text, multiplier = match.group(1), _MULTIPLIER[match.group(2).lower()]
    value = parse_amount(text)
    if value is None or value < 0:
        return None
    if multiplier == 1.0 and value < 1000:
        multiplier = 1e6
    return value * multiplier


def _parse_number(raw):
    return parse_amount(str(raw).replace("%", "").replace("x", "").strip())


class ProjectionWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Projection - Bibit Transaction Visualizer")
        self.geometry("1420x860")
        self.minsize(1100, 680)
        self.configure(background=theme_module.theme(app.options.theme)["ui_bg"])

        settings = app.projection_settings()
        self._job = None
        self._render = None
        self._note = None
        self._salary_rows = []

        self.var_months = tk.StringVar(value=str(settings.months))
        self.var_raise = tk.StringVar(value=f"{settings.raise_pct:g}")
        self.var_raise_month = tk.StringVar(value=MONTH_NAMES[settings.raise_month - 1])
        self.var_bonus = tk.StringVar(value=f"{settings.bonus_months:g}")
        self.var_bonus_month = tk.StringVar(value=MONTH_NAMES[settings.bonus_month - 1])
        self.var_save = tk.StringVar(value=f"{settings.save_pct:g}")
        self.var_bonus_save = tk.StringVar(value=f"{settings.bonus_save_pct:g}")
        self.var_return = tk.StringVar(value=f"{settings.return_pct:g}")
        self.var_history = tk.BooleanVar(value=True)
        self.var_message = tk.StringVar()

        self._build(settings)
        for variable in (self.var_months, self.var_raise, self.var_raise_month, self.var_bonus,
                         self.var_bonus_month, self.var_save, self.var_bonus_save, self.var_return):
            variable.trace_add("write", lambda *_a: self.schedule())

        self.bind("<Escape>", lambda _e: self.destroy())
        self.recompute()

    # -- layout ------------------------------------------------------------

    def _build(self, settings):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        side = ttk.Frame(outer, width=330)
        side.pack(side="left", fill="y", padx=(0, 14))

        # -- salary timeline
        group = ttk.LabelFrame(side, text="Monthly salary by year", padding=10)
        group.pack(fill="x")
        self.salary_frame = ttk.Frame(group)
        self.salary_frame.pack(fill="x")
        for year, amount in sorted(settings.salary.items()):
            self._add_salary_row(year, amount)
        line = ttk.Frame(group)
        line.pack(fill="x", pady=(6, 0))
        ttk.Button(line, text="+ Year", command=self._on_add_year).pack(side="left")
        ttk.Label(line, text="e.g. 11.5jt or 11.500.000", style="Caption.TLabel").pack(side="right")

        # -- assumptions
        group = ttk.LabelFrame(side, text="Assumptions", padding=10)
        group.pack(fill="x", pady=(10, 0))
        group.columnconfigure(1, weight=1)
        row = 0

        def field(caption, widget, hint_var=None):
            nonlocal row
            ttk.Label(group, text=caption).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
            widget.grid(row=row, column=1, sticky="ew", pady=3)
            row += 1
            if hint_var is not None:
                ttk.Label(group, textvariable=hint_var, style="Caption.TLabel", wraplength=300,
                          justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
                row += 1

        months = ttk.Frame(group)
        ttk.Spinbox(months, from_=1, to=600, increment=12, width=6,
                    textvariable=self.var_months).pack(side="left")
        for count in (12, 36, 60, 120):
            ttk.Button(months, text=f"{count // 12}y", width=4,
                       command=lambda c=count: self.var_months.set(str(c))).pack(side="left", padx=(4, 0))
        field("Months ahead", months)

        self.raise_hint = tk.StringVar()
        field("Yearly raise %", ttk.Entry(group, textvariable=self.var_raise, width=10), self.raise_hint)
        field("Raise lands in", ttk.Combobox(group, textvariable=self.var_raise_month, values=MONTH_NAMES,
                                             state="readonly", width=8))
        field("Yearly bonus (x salary)", ttk.Entry(group, textvariable=self.var_bonus, width=10))
        field("Bonus paid in", ttk.Combobox(group, textvariable=self.var_bonus_month, values=MONTH_NAMES,
                                            state="readonly", width=8))

        self.save_hint = tk.StringVar()
        save = ttk.Frame(group)
        ttk.Entry(save, textvariable=self.var_save, width=10).pack(side="left")
        self.use_actual = ttk.Button(save, text="Use actual", command=self._on_use_actual)
        self.use_actual.pack(side="left", padx=(6, 0))
        field("Save from salary %", save, self.save_hint)
        field("Save from bonus %", ttk.Entry(group, textvariable=self.var_bonus_save, width=10))
        self.return_hint = tk.StringVar(
            value="0 keeps it comparable to the main chart, which tracks capital put in, "
                  "not market value."
        )
        field("Return % per year", ttk.Entry(group, textvariable=self.var_return, width=10), self.return_hint)

        ttk.Checkbutton(side, text="Show actual history before the projection",
                        variable=self.var_history, command=self.recompute).pack(anchor="w", pady=(10, 0))
        ttk.Label(side, textvariable=self.var_message, style="Caption.TLabel", wraplength=320,
                  justify="left").pack(anchor="w", pady=(8, 0))

        # -- right: KPIs, chart, by-year table
        main = ttk.Frame(outer)
        main.pack(side="left", fill="both", expand=True)

        kpis = ttk.Frame(main)
        kpis.pack(fill="x", pady=(0, 6))
        self.kpi = {}
        for key, caption in (("closing", "Balance at end"), ("salary", "Saved from salary"),
                             ("bonus", "Saved from bonus"), ("growth", "Growth"),
                             ("pay", "Salary by then")):
            tile = ttk.Frame(kpis)
            tile.pack(side="left", padx=(0, 30))
            caption_label = ttk.Label(tile, text=caption, style="Caption.TLabel")
            caption_label.pack(anchor="w")
            value = ttk.Label(tile, text="-", style="Figure.TLabel")
            value.pack(anchor="w")
            self.kpi[key] = (caption_label, value)

        panes = ttk.PanedWindow(main, orient="vertical")
        panes.pack(fill="both", expand=True)

        holder = ttk.Frame(panes)
        panes.add(holder, weight=4)
        self.figure = Figure(figsize=(9, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=holder)
        widget = self.canvas.get_tk_widget()
        widget.pack(fill="both", expand=True)
        widget.bind("<Configure>", lambda _e: self.schedule(180))
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        self.canvas.mpl_connect("figure_leave_event", lambda _e: self._hide_note())

        table = ttk.Frame(panes)
        panes.add(table, weight=1)
        columns = ("year", "kind", "salary", "income", "saved", "rate", "closing")
        headings = {"year": "Year", "kind": "", "salary": "Salary / month", "income": "Income",
                    "saved": "Saved", "rate": "Rate", "closing": "Balance at year end"}
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=7)
        for name in columns:
            self.tree.heading(name, text=headings[name])
            self.tree.column(name, width=150 if name in ("closing", "income") else 100,
                             anchor="w" if name in ("year", "kind") else "e", stretch=True)
        self.tree.column("year", width=60)
        self.tree.column("kind", width=150)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=(6, 0))
        scroll.pack(side="right", fill="y", pady=(6, 0))

    def _add_salary_row(self, year="", amount=None):
        from .app import format_idr

        frame = ttk.Frame(self.salary_frame)
        frame.pack(fill="x", pady=2)
        year_var = tk.StringVar(value=str(year))
        amount_var = tk.StringVar(value=format_idr(amount) if amount else "")
        ttk.Entry(frame, textvariable=year_var, width=6).pack(side="left")
        ttk.Entry(frame, textvariable=amount_var, width=18).pack(side="left", padx=(6, 0))
        row = (frame, year_var, amount_var)
        ttk.Button(frame, text="x", width=2,
                   command=lambda: self._remove_salary_row(row)).pack(side="left", padx=(6, 0))
        for variable in (year_var, amount_var):
            variable.trace_add("write", lambda *_a: self.schedule())
        self._salary_rows.append(row)
        return row

    def _remove_salary_row(self, row):
        row[0].destroy()
        self._salary_rows.remove(row)
        self.schedule()

    def _on_add_year(self):
        years = []
        for _frame, year_var, _amount in self._salary_rows:
            try:
                years.append(int(year_var.get()))
            except ValueError:
                pass
        if years:
            self._add_salary_row(max(years) + 1)
        else:
            from datetime import date

            self._add_salary_row(date.today().year)
        self.schedule()

    def _on_use_actual(self):
        settings = self._read()
        if settings is None:
            return
        suggested = suggest_save_pct(self.app.ledger, settings, categories=self.app._selected_categories())
        if suggested is not None:
            self.var_save.set(f"{suggested:g}")

    # -- reading the form --------------------------------------------------

    def _read(self):
        """The form as settings, or None (with the reason shown) if a field is unreadable."""
        problems = []
        salary = {}
        for _frame, year_var, amount_var in self._salary_rows:
            year_text, amount_text = year_var.get().strip(), amount_var.get().strip()
            if not year_text and not amount_text:
                continue
            try:
                year = int(year_text)
                if not 1900 <= year <= 2200:
                    raise ValueError
            except ValueError:
                problems.append(f"'{year_text}' is not a year.")
                continue
            amount = parse_salary(amount_text)
            if amount is None:
                problems.append(f"The {year} salary is not a number I can read.")
                continue
            salary[year] = amount

        def number(variable, caption):
            value = _parse_number(variable.get())
            if value is None:
                problems.append(f"{caption} is not a number.")
                return 0.0
            return value

        settings = ProjectionSettings(
            months=int(number(self.var_months, "Months ahead")),
            salary=salary,
            raise_pct=number(self.var_raise, "Yearly raise"),
            raise_month=MONTH_NAMES.index(self.var_raise_month.get()) + 1,
            bonus_months=number(self.var_bonus, "Bonus"),
            bonus_month=MONTH_NAMES.index(self.var_bonus_month.get()) + 1,
            save_pct=number(self.var_save, "Save from salary"),
            bonus_save_pct=number(self.var_bonus_save, "Save from bonus"),
            return_pct=number(self.var_return, "Return"),
        )
        if problems:
            self.var_message.set("  ".join(problems))
            return None
        settings.clamp()
        return settings

    # -- recompute ---------------------------------------------------------

    def schedule(self, delay=250):
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(delay, self.recompute)

    def recompute(self):
        self._job = None
        if not self.winfo_exists():
            return
        settings = self._read()
        if settings is None:
            return
        self.app.store_projection_settings(settings)

        ledger = self.app.ledger
        categories = self.app._selected_categories()
        result = project(ledger, settings, categories=categories)
        scope = "all categories" if categories is None else ", ".join(categories) or "no categories"
        self.var_message.set(
            f"Starts {result.start_month} from the ledger's balance of "
            f"{self._money(result.start_balance)} ({scope})."
            if settings.salary else
            "Add your monthly salary for at least one year above to start the projection."
        )
        self._update_hints(settings, ledger, categories)

        self._hide_note()
        self._note = None
        palette = theme_module.theme(self.app.options.theme)
        self.configure(background=palette["ui_bg"])
        if not settings.salary:
            self.figure.clear()
            self.figure.patch.set_facecolor(palette["plane"])
            chart_module._draw_empty(self.figure, palette,
                                     "Enter your monthly salary by year on the left.")
            self._render = None
        else:
            self._render = chart_module.render_projection(
                self.figure, result, theme=self.app.options.theme,
                scale_name=self.app.options.scale, show_history=self.var_history.get(),
            )
        self.canvas.draw_idle()
        self._update_kpis(result, settings)
        self._fill_table(ledger, settings, result, categories)

    def _update_hints(self, settings, ledger, categories):
        raises = implied_raises(settings.salary)
        self.raise_hint.set(
            "Your timeline: " + ", ".join(f"{rate:+.1f}%/yr since {year}" for year, _last, rate in raises)
            if raises else ""
        )
        actual = suggest_save_pct(ledger, settings, categories=categories)
        self.save_hint.set(
            f"The last 12 months actually saved {actual:g}% of income." if actual is not None else ""
        )

    @staticmethod
    def _money(value):
        from .app import format_idr_compact

        return format_idr_compact(value)

    def _update_kpis(self, result, settings):
        empty = not settings.salary or not result
        end = result.months[-1] if result.months else ""
        values = {
            "closing": (f"Balance at {end}", result.closing),
            "salary": ("Saved from salary", result.total_saved_salary),
            "bonus": ("Saved from bonus", result.total_saved_bonus),
            "growth": (f"Growth at {settings.return_pct:g}%/yr", result.total_growth),
            "pay": (f"Salary by {end}", result.salary[-1] if result.salary else 0.0),
        }
        for key, (caption, value) in values.items():
            caption_label, value_label = self.kpi[key]
            caption_label.config(text=caption)
            value_label.config(text="-" if empty else self._money(value))

    def _fill_table(self, ledger, settings, result, categories):
        from .app import format_idr_compact

        palette = theme_module.theme(self.app.options.theme)
        self.tree.tag_configure("projected", foreground=palette["inflow"])
        self.tree.tag_configure("actual", foreground=palette["ui_text"])
        self.tree.delete(*self.tree.get_children(""))
        if not settings.salary:
            return
        rows = [r for r in actual_years(ledger, settings, categories) if r.year <= int(result.start_month[:4])]
        rows += result.years()
        for row in rows:
            if row.projected:
                kind = "projected" + (f" ({row.months} mo)" if row.months != 12 else "")
            else:
                kind = "actual" + (f" ({row.months} mo)" if row.months != 12 else "")
            self.tree.insert(
                "", "end", tags=("projected" if row.projected else "actual",),
                values=(row.year, kind, format_idr_compact(row.salary), format_idr_compact(row.income),
                        format_idr_compact(row.saved), f"{row.rate:.0%}" if row.income else "-",
                        format_idr_compact(row.closing)),
            )

    # -- hover -------------------------------------------------------------

    def _hide_note(self):
        if self._note is not None and self._note.get_visible():
            self._note.set_visible(False)
            self.canvas.draw_idle()

    def _on_hover(self, event):
        render = self._render
        if render is None or event.inaxes not in (render.flow_axes, render.balance_axes) or event.xdata is None:
            self._hide_note()
            return
        index = int(round(event.xdata))
        if not 0 <= index < len(render.months):
            self._hide_note()
            return

        projection, scale, unit = render.projection, render.scale, render.unit
        month = render.months[index]
        if index < render.split:
            offset = len(projection.history_months) - render.split + index
            lines = [
                f"{month}  actual",
                f"Salary   {projection.history_salary[offset] / scale:,.2f}",
                f"Net      {projection.history_net[offset] / scale:,.2f}",
                f"Balance  {projection.history_balance[offset] / scale:,.2f}   ({unit})",
            ]
            anchor = projection.history_balance[offset] / scale
        else:
            i = index - render.split
            lines = [
                f"{month}  projected",
                f"Salary   {projection.salary[i] / scale:,.2f}",
                f"Saved    {projection.saved_salary[i] / scale:,.2f}",
            ]
            if projection.bonus[i]:
                lines.append(f"Bonus    {projection.bonus[i] / scale:,.2f}  "
                             f"(saved {projection.saved_bonus[i] / scale:,.2f})")
            if projection.growth[i]:
                lines.append(f"Growth   {projection.growth[i] / scale:,.2f}")
            lines.append(f"Balance  {projection.balance[i] / scale:,.2f}   ({unit})")
            anchor = projection.balance[i] / scale

        axes = render.balance_axes
        palette = theme_module.theme(self.app.options.theme)
        if self._note is None or self._note.axes is not axes:
            self._note = axes.annotate(
                "", xy=(0, 0), xytext=(14, 14), textcoords="offset points",
                fontsize=8, color=palette["ink"], family="monospace", zorder=20,
                annotation_clip=False, multialignment="left",
                bbox={"boxstyle": "round,pad=0.5", "facecolor": palette["surface"],
                      "edgecolor": palette["axis"], "linewidth": 0.8},
            )
        note = self._note
        note.xy = (index, anchor)
        note.set_text("\n".join(lines))
        # flip left over the second half and down over the upper half, so the
        # box always opens towards the middle of the panel and never off its edge
        right_half = index > len(render.months) / 2
        low, high = axes.get_ylim()
        upper_half = anchor > (low + high) / 2
        note.set_ha("right" if right_half else "left")
        note.set_va("top" if upper_half else "bottom")
        note.xyann = (-14 if right_half else 14, -14 if upper_half else 14)
        note.set_visible(True)
        self.canvas.draw_idle()
