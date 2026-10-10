"""Join several Bibit reports into one continuous history.

Bibit caps a PDF report at one year, so a longer history arrives as a stack of
files whose ranges overlap -- the 2024-2025 report and the 2025-2026 report both
contain 29 Aug 2025. Joining them means answering one question per day: which
file is the authority for it?

**Why not dedupe row by row.** Genuinely identical transactions happen: selling
the same number of units of the same fund at the same NAV twice in one day.
Any scheme that hashes rows and keeps the distinct ones silently deletes the
second one. Counting occurrences instead would fix that but still breaks the
moment a report is regenerated with a rounding change.

**What this does instead: per-day authority.** Each report is complete for every
day inside its own range, so a day never needs to be assembled from two files --
it only needs to be taken from the right one. For each day, among the reports
covering it, the winner is the one holding that day furthest from its own edges
(see Report.interiority), because an edge day is the one at risk of being partial.
Ties go to the report with the later end date, which is the fresher download.

That gives three properties worth having:

  * duplicate transactions survive, because a day's rows are never merged;
  * overlaps cannot double-count, because a day comes from exactly one file;
  * old CSV exports and new PDFs join cleanly, because the rule needs only a
    date range, not a shared transaction id -- and the PDFs no longer print one.

Anything the rule cannot settle is reported rather than hidden: gaps between
ranges, and days where two reports that both claim to cover them disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

ONE_DAY = timedelta(days=1)


class StitchError(ValueError):
    """Raised when the reports cannot honestly be joined at all."""


@dataclass
class StitchResult:
    rows: list = field(default_factory=list)
    reports: list = field(default_factory=list)
    period_start: object = None
    period_end: object = None
    gaps: list = field(default_factory=list)          # (start, end) not covered by any report
    overlap_days: int = 0
    conflicts: list = field(default_factory=list)     # human-readable disagreements
    warnings: list = field(default_factory=list)
    rows_in: int = 0                                  # rows read across all reports

    @property
    def rows_dropped(self) -> int:
        """Rows discarded because another report was the authority for their day."""
        return self.rows_in - len(self.rows)

    @property
    def ok(self) -> bool:
        return not self.gaps and not self.conflicts

    def describe(self) -> str:
        if not self.rows:
            return "Nothing to stitch - no transactions in any of those files."
        lines = [
            f"{len(self.reports)} report(s) -> {len(self.rows)} transactions, "
            f"{self.period_start:%d %b %Y} to {self.period_end:%d %b %Y}"
        ]
        if self.overlap_days:
            lines.append(
                f"{self.overlap_days} day(s) appeared in more than one report; "
                f"{self.rows_dropped} duplicate row(s) dropped."
            )
        for start, end in self.gaps:
            lines.append(
                f"GAP: nothing covers {start:%d %b %Y} to {end:%d %b %Y} "
                f"({(end - start).days + 1} days) - export that range too."
            )
        for note in self.conflicts:
            lines.append(f"CONFLICT: {note}")
        return "\n".join(lines)


def _check_same_account(reports):
    seen = {report.sid for report in reports if report.sid}
    if len(seen) > 1:
        listing = ", ".join(
            f"{report.name} ({report.sid})" for report in reports if report.sid
        )
        raise StitchError(
            "These reports are for different accounts, so joining them would mix "
            f"two portfolios: {listing}"
        )
    return next(iter(seen), "")


def _find_gaps(reports):
    """Uncovered stretches between the reports' date ranges."""
    spans = sorted(
        (r.period_start, r.period_end) for r in reports if r.period_start and r.period_end
    )
    gaps = []
    if not spans:
        return gaps
    reach = spans[0][1]
    for start, end in spans[1:]:
        if start > reach + ONE_DAY:
            gaps.append((reach + ONE_DAY, start - ONE_DAY))
        reach = max(reach, end)
    return gaps


def _rank(report, day):
    """How much a report deserves to own a day. Higher wins.

    A PDF prints the range it covers; a spreadsheet export does not, so its range
    is inferred from its own first and last transaction and its edges could sit
    anywhere. A stated range therefore outranks an inferred one -- which also
    means a new PDF wins where it overlaps an old CSV, and that is the right way
    round: the PDF carries sections (stocks, dividends) the CSV never had.

    Among sources of equal standing, prefer the one holding the day furthest from
    its own edges, then the one whose range ends latest (the fresher download).
    """
    return (not report.period_inferred, report.interiority(day), report.period_end)


def _authority(day, reports):
    """The report that owns a day."""
    covering = [report for report in reports if report.covers(day)]
    if not covering:
        # A row dated outside its own report's stated range. Trust whoever has it.
        covering = [report for report in reports if day in report.days_with_rows()]
    if not covering:
        return None
    return max(covering, key=lambda report: _rank(report, day))


def _describe_disagreement(day, holders, owner):
    """Explain how two reports differ about one day, in terms a person can act on."""
    if len(holders) < 2:
        return None
    seen = {tuple(sorted(row.money_fingerprint for row in rows)) for _report, rows in holders}
    if len(seen) == 1:
        return None
    detail = ", ".join(
        f"{report.name} has {len(rows) or 'no'} row(s)" for report, rows in holders
    )
    return (
        f"{day:%d %b %Y} is covered by {len(holders)} reports that do not agree "
        f"({detail}). Used {owner.name}."
    )


def stitch(reports) -> StitchResult:
    """Join reports into one history, taking each day from a single authority."""
    reports = [report for report in reports if report.period_start and report.period_end]
    result = StitchResult(reports=list(reports))
    if not reports:
        return result

    _check_same_account(reports)
    reports = sorted(reports, key=lambda r: (r.period_start, r.period_end))
    result.reports = reports
    result.rows_in = sum(len(report.rows) for report in reports)
    for report in reports:
        result.warnings.extend(f"{report.name}: {note}" for note in report.warnings)

    result.period_start = min(report.period_start for report in reports)
    result.period_end = max(report.period_end for report in reports)
    result.gaps = _find_gaps(reports)

    # Index every report's rows by day once, then let one report own each day.
    by_day = []
    for report in reports:
        index = {}
        for row in report.rows:
            index.setdefault(row.date, []).append(row)
        by_day.append((report, index))

    days = sorted({day for _report, index in by_day for day in index})
    for day in days:
        # A report that covers a day is making a claim about it even when it lists
        # nothing -- it is asserting the day was quiet. So covering-but-empty
        # counts as a holder, which is how a report missing a day gets caught.
        holders = [
            (report, index.get(day, []))
            for report, index in by_day
            if report.covers(day) or day in index
        ]
        owner = _authority(day, reports)
        if sum(1 for report, _rows in holders if report.covers(day)) > 1:
            result.overlap_days += 1
            note = _describe_disagreement(day, holders, owner)
            if note:
                result.conflicts.append(note)

        chosen = next((rows for report, rows in holders if report is owner), [])
        if not chosen:
            # The authority has nothing for this day but somebody else does. Keep
            # those rows rather than losing them; the conflict above says why.
            chosen = next((rows for _report, rows in holders if rows), [])
        result.rows.extend(chosen)

    result.rows.sort(key=lambda row: (row.date, row.section, row.name, row.kind))
    return result
