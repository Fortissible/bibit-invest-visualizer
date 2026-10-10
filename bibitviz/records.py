"""The shape every source file is reduced to before it becomes ledger entries.

A CSV export, an XLSX export and a PDF report all parse into the same thing: a
Report covering a date range, holding RawRows. That is what lets stitch.py treat
them uniformly -- including the case that matters most here, an old spreadsheet
export and a new PDF whose date ranges overlap.

This module deliberately imports nothing from the parsers, so they can all import
it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

#: Bibit writes the same transaction as "Pembelian" in the old CSV and "Buy" in
#: the new PDF. Normalising to one vocabulary keeps a stitched ledger consistent
#: and lets the overlap check compare rows that came from different formats.
KIND_ALIASES = {
    "pembelian": "Buy",
    "subscription": "Buy",
    "top up": "Buy",
    "topup": "Buy",
    "buy": "Buy",
    "penjualan": "Sell",
    "redemption": "Sell",
    "penarikan": "Sell",
    "withdrawal": "Sell",
    "sell": "Sell",
    "instant redeem": "Instant Redeem",
    "kupon": "Coupon",
    "coupon": "Coupon",
    "dividen": "Dividend",
    "dividend": "Dividend",
    "maturity": "Maturity",
    "jatuh tempo": "Maturity",
    "switch in": "Switch In",
    "switch out": "Switch Out",
}


def normalize_kind(kind: str) -> str:
    text = " ".join(str(kind or "").split())
    return KIND_ALIASES.get(text.lower(), text)


@dataclass
class RawRow:
    """One transaction, before it is rolled up into a ledger entry."""

    date: date
    section: str = "mutual_fund"
    section_label: str = "Mutual fund"
    short_label: str = "Fund"
    name: str = ""
    kind: str = ""
    inflow: float = 0.0
    outflow: float = 0.0
    page: int = 0

    def __post_init__(self):
        self.kind = normalize_kind(self.kind)

    @property
    def fingerprint(self):
        """Full identity of a row, source file and page excluded."""
        return (self.date, self.section, self.name, self.kind,
                round(self.inflow, 2), round(self.outflow, 2))

    @property
    def money_fingerprint(self):
        """Identity for asking whether two reports agree about a day.

        The product name is left out on purpose: the formats spell the same
        holding differently -- the CSV export writes "Obligasi FR (FR0086)"
        where the PDF writes "FR0086" -- and that is a naming convention, not a
        disagreement about what happened. What must match is the money.
        """
        return (self.date, self.section, self.kind,
                round(self.inflow, 2), round(self.outflow, 2))

    @property
    def label(self) -> str:
        """How the row is named in the ledger: 'Fund Buy', 'Coupon', 'Bond Maturity'."""
        if not self.kind:
            return self.short_label
        return self.kind if self.kind == self.short_label else f"{self.short_label} {self.kind}"


@dataclass
class Report:
    """One source file: what it covers, and what it says happened."""

    path: Path
    period_start: date = None
    period_end: date = None
    sid: str = ""
    holder: str = ""
    kind: str = "report"          # "pdf" / "csv" / "xlsx"
    rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    pages: int = 0
    #: True when the period was inferred from the rows rather than printed in the
    #: file. Inferred ranges are treated as slightly less trustworthy at the edges.
    period_inferred: bool = False

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def period(self):
        return (self.period_start, self.period_end)

    def covers(self, day: date) -> bool:
        return bool(self.period_start and self.period_start <= day <= self.period_end)

    def interiority(self, day: date) -> int:
        """How far a day sits from this report's edges, in days.

        The tie-breaker when several sources cover the same day: prefer the one
        holding it well inside its window, since a day sitting on the very edge
        of a range is the one most at risk of being clipped or partial.
        """
        if not self.covers(day):
            return -1
        return min((day - self.period_start).days, (self.period_end - day).days)

    def days_with_rows(self):
        return {row.date for row in self.rows}

    def describe(self) -> str:
        if not self.rows:
            return f"{self.name}: no transactions found"
        span = f"{self.period_start:%d %b %Y} to {self.period_end:%d %b %Y}"
        kinds = sorted({row.section_label for row in self.rows})
        suffix = " (range inferred from the rows)" if self.period_inferred else ""
        return f"{self.name}: {len(self.rows)} rows, {span}{suffix} [{', '.join(kinds)}]"
