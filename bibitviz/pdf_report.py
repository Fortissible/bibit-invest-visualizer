"""Read Bibit's PDF transaction history.

Bibit replaced the spreadsheet export with a PDF that covers **at most one year**,
so a longer history arrives as several files -- see stitch.py for joining them.

A report is a stack of independent tables, each with its own columns:

    Mutual Fund - IDR          Txn. Date  Name  Type  Unit  NAV  Buy Value  Sell Value
    FR Bonds - Transaction     Txn. Date  Settle Date  Name  Type  Unit  Price  Buy Value  Net Sell Value
    FR Bonds - Coupon ...      Txn. Date  Name  Type  Unit  Coupon Rate  Net Value
    Stocks - Transaction       Txn. Date  Name  Type  Lot  Price  Net Buy Value  Net Sell Value
    Stocks - Cash Dividend     Txn. Date  Name  Lot  Cash Dividend  Net Value

Two things make naive text parsing unsafe: fund names contain spaces ("Manulife
Dana Kas Syariah") and so do transaction types ("Instant Redeem", "Buy IPO",
"Refund IPO"). So columns are cut from the *geometry* instead.

Header positions alone are not enough either -- the "Name" header is a short word
sitting at the left of a wide column, so a midpoint between headers slices
"Syariah" off the end of the fund name. What is reliable is the whitespace: over
a whole section no word ever falls in the gutter between two columns. So the
columns are found by projecting every word in the section onto the x-axis and
reading off the empty corridors. The result is checked -- each header must land
wholly inside its own column -- and falls back to header midpoints with a warning
if the layout ever stops looking like a table.

A section header is also its own fingerprint, so sections are identified by their
column signature rather than by the title text above them. That matters because
a table continuing onto the next page reprints its columns but not its title.

Each section ends with a "Total" line. Those are parsed too and checked against
the sum of the rows, so a silent misparse becomes a loud warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .importer import parse_amount, parse_date
from .records import RawRow, Report

#: Money moves *into* the portfolio unless a section says otherwise. Coupons and
#: dividends are cash the holding pays out; they are counted as In to match how
#: this project has always treated Bibit's "Kupon" rows -- money staying in,
#: reinvested. They import as their own rows, so flipping one is a single edit.


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    short: str
    headers: tuple
    name_column: str
    in_column: str = ""
    out_column: str = ""
    kind_column: str = ""
    default_kind: str = ""


SECTIONS = (
    Section(
        key="mutual_fund", short="Fund", label="Mutual fund",
        headers=("Txn. Date", "Name", "Type", "Unit", "NAV", "Buy Value", "Sell Value"),
        name_column="Name", kind_column="Type",
        in_column="Buy Value", out_column="Sell Value",
    ),
    Section(
        key="bond", short="Bond", label="FR bonds",
        headers=("Txn. Date", "Settle Date", "Name", "Type", "Unit", "Price",
                 "Buy Value", "Net Sell Value"),
        name_column="Name", kind_column="Type",
        in_column="Buy Value", out_column="Net Sell Value",
    ),
    Section(
        key="bond_coupon", short="Coupon", label="FR bond coupons",
        headers=("Txn. Date", "Name", "Type", "Unit", "Coupon Rate", "Net Value"),
        name_column="Name", kind_column="Type",
        in_column="Net Value", default_kind="Coupon",
    ),
    Section(
        key="stock", short="Stock", label="Stocks",
        headers=("Txn. Date", "Name", "Type", "Lot", "Price", "Net Buy Value", "Net Sell Value"),
        name_column="Name", kind_column="Type",
        in_column="Net Buy Value", out_column="Net Sell Value",
    ),
    Section(
        key="stock_dividend", short="Dividend", label="Stock dividends",
        headers=("Txn. Date", "Name", "Lot", "Cash Dividend", "Net Value"),
        name_column="Name",
        in_column="Net Value", default_kind="Dividend",
    ),
)
_BY_SIGNATURE = {" ".join(section.headers): section for section in SECTIONS}

_DATE_START = re.compile(r"^\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b")
_PERIOD = re.compile(
    r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*[^\w\s]?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
)
_SID = re.compile(r"SID\s*:\s*([A-Za-z0-9]+)")
_ROW_TOLERANCE = 4.0  # points; words within this vertical distance are one line


class PdfReportError(ValueError):
    """Raised when a PDF is not a Bibit transaction history we can read."""


# --------------------------------------------------------------------------- geometry


def _lines(page):
    """Group a page's words into visual lines, each sorted left to right."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    grouped = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if grouped and abs(word["top"] - grouped[-1][0]) <= _ROW_TOLERANCE:
            grouped[-1][1].append(word)
        else:
            grouped.append((word["top"], [word]))
    return [sorted(items, key=lambda w: w["x0"]) for _top, items in grouped]


def _text(line) -> str:
    return " ".join(word["text"] for word in line)


def _match_section(line):
    """If this line is a column header, return (section, its header spans)."""
    section = _BY_SIGNATURE.get(_text(line))
    if section is None:
        return None, None

    # Walk the schema's column names, consuming as many header words as each
    # name has tokens, to recover where every column's title starts and ends.
    spans, cursor = [], 0
    for column in section.headers:
        size = len(column.split())
        words = line[cursor:cursor + size]
        if len(words) != size:
            return None, None
        spans.append((words[0]["x0"], words[-1]["x1"]))
        cursor += size
    return section, spans


_MIN_GUTTER = 8.0  # points; real column gutters here are 24pt+, word gaps ~2pt


def _corridors(lines):
    """Every x range in which no word from any of these lines appears."""
    intervals = sorted((w["x0"], w["x1"]) for line in lines for w in line)
    if not intervals:
        return []
    gaps = []
    reach = intervals[0][1]
    for start, end in intervals[1:]:
        if start - reach >= _MIN_GUTTER:
            gaps.append((reach, start))
        reach = max(reach, end)
    return gaps


def _boundaries(section, spans, lines):
    """Column cut positions for a section, read off the whitespace between columns.

    Returns (bounds, note). `note` is non-empty when the whitespace did not look
    like a table and header midpoints were used instead.
    """
    wanted = len(section.headers) - 1
    midpoints = [(spans[i][1] + spans[i + 1][0]) / 2.0 for i in range(wanted)]
    if wanted == 0:
        return [], ""

    gaps = _corridors(lines)
    if len(gaps) < wanted:
        return midpoints, f"only {len(gaps)} column gutters for {wanted + 1} columns"

    widest = sorted(gaps, key=lambda gap: gap[1] - gap[0], reverse=True)[:wanted]
    bounds = [(start + end) / 2.0 for start, end in sorted(widest)]

    # Sanity check: every column title must sit wholly inside its own column.
    edges = [float("-inf")] + bounds + [float("inf")]
    for index, (left, right) in enumerate(spans):
        if not (edges[index] < left and right < edges[index + 1]):
            return midpoints, f"column {section.headers[index]!r} straddles a detected gutter"
    return bounds, ""


def _cells(line, section, bounds):
    """Bucket a line's words into the section's columns."""
    cells = {column: [] for column in section.headers}
    for word in line:
        centre = (word["x0"] + word["x1"]) / 2.0
        index = 0
        while index < len(bounds) and centre > bounds[index]:
            index += 1
        cells[section.headers[index]].append(word["text"])
    return {column: " ".join(parts).strip() for column, parts in cells.items()}


# --------------------------------------------------------------------------- parsing


def _money(cell) -> float:
    value = parse_amount(cell)
    return 0.0 if value is None else abs(value)


def _read_metadata(report, line_text):
    if report.period_start is None and line_text.startswith("Transaction History"):
        match = _PERIOD.search(line_text)
        if match:
            report.period_start = parse_date(match.group(1))
            report.period_end = parse_date(match.group(2))
    if not report.sid:
        match = _SID.search(line_text)
        if match:
            report.sid = match.group(1)


def parse_report(path) -> Report:
    """Parse one Bibit PDF transaction history."""
    try:
        import pdfplumber
    except ImportError:
        raise PdfReportError(
            "Reading Bibit PDF reports needs the 'pdfplumber' package - run:\n"
            "    pip install pdfplumber"
        ) from None

    path = Path(path)
    if not path.exists():
        raise PdfReportError(f"No such file: {path}")

    report = Report(path=path, kind="pdf")

    try:
        opened = pdfplumber.open(str(path))
    except Exception as error:
        raise PdfReportError(f"{path.name} could not be opened as a PDF: {error}") from error

    # --- pass 1: read every line, and group them by the section they belong to.
    # A table continuing onto the next page reprints its columns but not its
    # title, so the same section key collects lines from every page it spans --
    # which also gives the column detector the whole section to work with.
    blocks = {}
    order = []
    section = None
    with opened as pdf:
        report.pages = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            for line in _lines(page):
                text = _text(line)
                _read_metadata(report, text)

                matched, spans = _match_section(line)
                if matched is not None:
                    section = matched
                    if section.key not in blocks:
                        blocks[section.key] = {"section": section, "spans": spans,
                                               "lines": [], "rows": [], "totals": []}
                        order.append(section.key)
                    blocks[section.key]["lines"].append(line)
                    continue
                if text.startswith("Txn."):
                    # A table we do not know -- say so rather than misreading it.
                    report.warnings.append(f"page {number}: unrecognised table columns - {text}")
                    section = None
                    continue
                if section is None:
                    continue

                block = blocks[section.key]
                if text.startswith("Total"):
                    block["lines"].append(line)
                    block["totals"].append(line)
                    section = None  # a section ends at its total
                elif _DATE_START.match(text):
                    block["lines"].append(line)
                    block["rows"].append((number, line))
                # anything else (footnotes, page furniture) is not part of the table

    # --- pass 2: find the columns from the section's own whitespace, then read it.
    totals = {}
    summed = {}
    for key in order:
        block = blocks[key]
        section = block["section"]
        bounds, note = _boundaries(section, block["spans"], block["lines"])
        if note:
            report.warnings.append(f"{key}: falling back to header positions - {note}")

        for line in block["totals"]:
            cells = _cells(line, section, bounds)
            totals[key] = (
                _money(cells.get(section.in_column, "")),
                _money(cells.get(section.out_column, "")) if section.out_column else 0.0,
            )

        for number, line in block["rows"]:
            cells = _cells(line, section, bounds)
            when = parse_date(cells.get("Txn. Date", ""))
            if when is None:
                report.warnings.append(f"page {number}: unreadable date in {_text(line)!r}")
                continue

            inflow = _money(cells.get(section.in_column, "")) if section.in_column else 0.0
            outflow = _money(cells.get(section.out_column, "")) if section.out_column else 0.0
            if not inflow and not outflow:
                report.warnings.append(f"page {number}: no amount in {_text(line)!r}")
                continue

            report.rows.append(RawRow(
                date=when,
                section=key,
                section_label=section.label,
                short_label=section.short,
                name=cells.get(section.name_column, "").strip(),
                kind=(cells.get(section.kind_column, "").strip()
                      if section.kind_column else "") or section.default_kind,
                inflow=inflow,
                outflow=outflow,
                page=number,
            ))
            running = summed.setdefault(key, [0.0, 0.0])
            running[0] += inflow
            running[1] += outflow

    report.rows.sort(key=lambda row: (row.date, row.section, row.name))

    if report.period_start is None or report.period_end is None:
        raise PdfReportError(
            f"{path.name} has no 'Transaction History <from> - <to>' heading, so it does "
            "not look like a Bibit transaction history."
        )
    if report.period_end < report.period_start:
        report.period_start, report.period_end = report.period_end, report.period_start

    _check_totals(report, totals, summed)
    return report


def _check_totals(report, declared, parsed):
    """Compare each section's printed Total against what we actually read."""
    for key, (total_in, total_out) in declared.items():
        got_in, got_out = parsed.get(key, (0.0, 0.0))
        for what, expected, actual in (("buy", total_in, got_in), ("sell", total_out, got_out)):
            if abs(expected - actual) > 1.0:  # the PDF rounds to whole rupiah
                report.warnings.append(
                    f"{key}: {what} total does not reconcile - the PDF says "
                    f"{expected:,.0f} but the rows add up to {actual:,.0f}"
                )
    for key in parsed:
        if key not in declared:
            report.warnings.append(f"{key}: no Total line found, so the rows could not be checked")


def parse_reports(paths):
    """Parse several PDFs, keeping going when one of them fails."""
    reports, failures = [], []
    for path in paths:
        try:
            reports.append(parse_report(path))
        except PdfReportError as error:
            failures.append(str(error))
    return reports, failures
