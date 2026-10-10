"""The ledger: month-granular in/out entries, plus the monthly roll-up the chart reads.

A month holds any number of entries. Importing a Bibit report seeds one entry per
(month, direction, category, kind) -- so a month that had purchases, sales and a
bond coupon starts as three editable rows rather than one opaque total.

Amounts are stored as raw IDR. Display scaling is a view setting, never baked in.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace

IN = "in"
OUT = "out"
DIRECTIONS = (IN, OUT)
DIRECTION_LABEL = {IN: "In", OUT: "Out"}
DIRECTION_HELP = {
    IN: "In - money moved into the portfolio (buys, deposits, coupons)",
    OUT: "Out - money taken back out (sales, withdrawals)",
}

DEFAULT_CATEGORIES = ("Bibit", "Crypto")

#: Shown in the breakdown for outflow that has not been given a purpose yet.
UNTAGGED = "Untagged"

#: Offered in the purpose dropdown on a fresh ledger. Only suggestions -- the
#: field is free text, so anything can be typed and it joins the list.
SUGGESTED_PURPOSES = (
    "Eat", "Transport", "Bill", "Electricity", "Holiday", "Game",
    "Shopping", "Health", "Family", "Savings",
)

_MONTH_RE = re.compile(r"^\s*(\d{4})[-/](\d{1,2})\s*$")


class LedgerError(ValueError):
    """Raised for input the ledger refuses to store."""


# --------------------------------------------------------------------------- months


def normalize_month(value) -> str:
    """Return 'YYYY-MM' from a string, a date/datetime, or anything with .year/.month."""
    if value is None:
        raise LedgerError("month is required")
    if hasattr(value, "year") and hasattr(value, "month"):
        return f"{int(value.year):04d}-{int(value.month):02d}"
    match = _MONTH_RE.match(str(value))
    if not match:
        raise LedgerError(f"month must look like YYYY-MM (got {value!r})")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise LedgerError(f"month {month} is out of range in {value!r}")
    return f"{year:04d}-{month:02d}"


def month_ordinal(month: str) -> int:
    year, mon = month.split("-")
    return int(year) * 12 + int(mon) - 1


def month_from_ordinal(ordinal: int) -> str:
    return f"{ordinal // 12:04d}-{ordinal % 12 + 1:02d}"


def month_span(first: str, last: str) -> list:
    """Every month from first to last inclusive.

    Empty months are included on purpose: a time axis that silently drops the
    months with no activity compresses the gaps and misreads as a steady cadence.
    """
    start, end = month_ordinal(first), month_ordinal(last)
    if end < start:
        return []
    return [month_from_ordinal(n) for n in range(start, end + 1)]


def shift_month(month: str, delta: int) -> str:
    return month_from_ordinal(month_ordinal(month) + delta)


# --------------------------------------------------------------------------- entry


@dataclass
class Entry:
    """One line of the ledger.

    amount is always non-negative; direction carries the sign.
    """

    month: str
    direction: str = IN
    amount: float = 0.0
    category: str = "Bibit"
    #: What the money was for -- "eat", "holiday", "transport", "electricity".
    #: Free text, and a second dimension to `category`: category says which pot
    #: the money moved through, purpose says what it went on. Mostly meaningful
    #: on Out rows, which is what the breakdown chart reads, but nothing stops
    #: you tagging an In row with where it came from.
    purpose: str = ""
    label: str = ""
    note: str = ""
    source: str = "manual"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        self.month = normalize_month(self.month)
        direction = str(self.direction).strip().lower()
        if direction not in DIRECTIONS:
            raise LedgerError(f"direction must be 'in' or 'out' (got {self.direction!r})")
        self.direction = direction
        try:
            amount = float(self.amount)
        except (TypeError, ValueError):
            raise LedgerError(f"amount must be a number (got {self.amount!r})") from None
        if amount != amount:  # NaN
            raise LedgerError("amount must be a number, not NaN")
        if amount < 0:
            raise LedgerError(
                "amount cannot be negative - use the In/Out direction to say which way it moved"
            )
        self.amount = amount
        self.category = str(self.category).strip() or "Uncategorised"
        self.purpose = " ".join(str(self.purpose).split())
        self.label = str(self.label).strip()
        self.note = str(self.note).strip()

    @property
    def signed(self) -> float:
        return self.amount if self.direction == IN else -self.amount

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "month": self.month,
            "direction": self.direction,
            "amount": self.amount,
            "category": self.category,
            "purpose": self.purpose,
            "label": self.label,
            "note": self.note,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        known = {"id", "month", "direction", "amount", "category", "purpose",
                 "label", "note", "source"}
        return cls(**{k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------------- summary


@dataclass
class Summary:
    """What the chart draws: one value per month, already filtered and sliced."""

    months: list
    inflow: list
    outflow: list
    net: list
    cumulative: list
    categories: list
    inflow_by_category: dict
    outflow_by_category: dict
    #: Outflow split by what it was spent on. Rows with no purpose land in
    #: UNTAGGED, which is deliberately shown rather than hidden -- how much of
    #: the spending is still unaccounted for is part of the answer.
    purposes: list = field(default_factory=list)
    outflow_by_purpose: dict = field(default_factory=dict)

    def __bool__(self):
        return bool(self.months)

    @property
    def tagged_out(self) -> float:
        return sum(
            sum(values) for name, values in self.outflow_by_purpose.items() if name != UNTAGGED
        )

    @property
    def tagged_fraction(self) -> float:
        return self.tagged_out / self.total_out if self.total_out else 0.0

    def purpose_totals(self):
        """Total per purpose over the whole window, biggest first, UNTAGGED last."""
        totals = [(name, sum(values)) for name, values in self.outflow_by_purpose.items()]
        totals = [row for row in totals if row[1]]
        totals.sort(key=lambda row: (row[0] == UNTAGGED, -row[1]))
        return totals

    @property
    def total_in(self) -> float:
        return sum(self.inflow)

    @property
    def total_out(self) -> float:
        return sum(self.outflow)

    @property
    def total_net(self) -> float:
        return self.total_in - self.total_out

    @property
    def closing_cumulative(self) -> float:
        return self.cumulative[-1] if self.cumulative else 0.0


# --------------------------------------------------------------------------- ledger


class Ledger:
    """An ordered set of entries plus the category order that fixes chart colours."""

    def __init__(self, entries=None, categories=None, meta=None, purposes=None):
        self.entries = list(entries or [])
        self.categories = []
        self.purposes = []
        for name in (categories if categories is not None else DEFAULT_CATEGORIES):
            self.register_category(name)
        for name in (purposes if purposes is not None else SUGGESTED_PURPOSES):
            self.register_purpose(name)
        for entry in self.entries:
            self.register_category(entry.category)
            self.register_purpose(entry.purpose)
        self.meta = dict(meta or {})

    # -- categories --------------------------------------------------------

    def register_category(self, name: str) -> str:
        """Append an unseen category. Position is permanent, so its colour is too."""
        name = str(name).strip() or "Uncategorised"
        if name not in self.categories:
            self.categories.append(name)
        return name

    def rename_category(self, old: str, new: str) -> None:
        new = str(new).strip()
        if not new:
            raise LedgerError("category name cannot be empty")
        if old not in self.categories:
            raise LedgerError(f"no such category: {old!r}")
        if new in self.categories and new != old:
            raise LedgerError(f"category {new!r} already exists")
        self.categories[self.categories.index(old)] = new
        for entry in self.entries:
            if entry.category == old:
                entry.category = new

    def used_categories(self) -> list:
        used = {entry.category for entry in self.entries}
        return [name for name in self.categories if name in used]

    # -- purposes ----------------------------------------------------------

    def register_purpose(self, name: str) -> str:
        """Remember a spending purpose. Position is permanent, so its colour is too."""
        name = " ".join(str(name or "").split())
        if name and name != UNTAGGED and name not in self.purposes:
            self.purposes.append(name)
        return name

    def rename_purpose(self, old: str, new: str) -> None:
        new = " ".join(str(new).split())
        if not new:
            raise LedgerError("purpose cannot be empty")
        if old not in self.purposes:
            raise LedgerError(f"no such purpose: {old!r}")
        if new in self.purposes and new != old:
            # Merge instead of refusing -- renaming "Food" to "Eat" when both
            # exist is how you tidy up, not a mistake.
            self.purposes.remove(old)
        else:
            self.purposes[self.purposes.index(old)] = new
        for entry in self.entries:
            if entry.purpose == old:
                entry.purpose = new

    def used_purposes(self) -> list:
        used = {entry.purpose for entry in self.entries if entry.purpose}
        return [name for name in self.purposes if name in used]

    # -- entries -----------------------------------------------------------

    def add(self, entry: Entry) -> Entry:
        self.register_category(entry.category)
        self.register_purpose(entry.purpose)
        self.entries.append(entry)
        return entry

    def get(self, entry_id: str):
        return next((e for e in self.entries if e.id == entry_id), None)

    def update(self, entry_id: str, **changes) -> Entry:
        current = self.get(entry_id)
        if current is None:
            raise LedgerError(f"no entry with id {entry_id!r}")
        updated = replace(current, **changes)
        updated.__post_init__()
        self.register_category(updated.category)
        self.register_purpose(updated.purpose)
        self.entries[self.entries.index(current)] = updated
        return updated

    def remove(self, entry_id: str) -> bool:
        current = self.get(entry_id)
        if current is None:
            return False
        self.entries.remove(current)
        return True

    def duplicate(self, entry_id: str):
        current = self.get(entry_id)
        if current is None:
            return None
        copy = replace(current, id=uuid.uuid4().hex[:12], source="manual")
        self.entries.insert(self.entries.index(current) + 1, copy)
        return copy

    def split(self, entry_id: str, amount: float, purpose="", **overrides) -> Entry:
        """Carve `amount` off an entry into a new row, usually to give it a purpose.

        This is what makes an imported month breakable: an import lands one
        "Fund Sell (8x)" row for the month, and splitting peels off "2,000,000
        for Holiday" while the remainder stays where it was. Split again to keep
        going. The month's total is unchanged either way.
        """
        current = self.get(entry_id)
        if current is None:
            raise LedgerError(f"no entry with id {entry_id!r}")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise LedgerError(f"amount must be a number (got {amount!r})") from None
        if amount <= 0:
            raise LedgerError("split off an amount greater than zero")
        if amount >= current.amount:
            raise LedgerError(
                f"that is the whole row ({current.amount:,.0f}). To label all of it, "
                "set the purpose on the row itself instead of splitting."
            )

        piece = replace(
            current, id=uuid.uuid4().hex[:12], amount=amount,
            purpose=purpose or current.purpose, source="manual", **overrides,
        )
        piece.__post_init__()
        self.register_purpose(piece.purpose)
        self.register_category(piece.category)
        index = self.entries.index(current)
        self.entries[index] = replace(current, amount=current.amount - amount)
        self.entries.insert(index + 1, piece)
        return piece

    def extend(self, entries) -> int:
        count = 0
        for entry in entries:
            self.add(entry)
            count += 1
        return count

    def replace_months(self, months, entries) -> int:
        """Drop everything in the given months, then add entries. Used by import-merge."""
        months = set(months)
        removed = sum(1 for e in self.entries if e.month in months)
        self.entries = [e for e in self.entries if e.month not in months]
        self.extend(entries)
        return removed

    # -- shape -------------------------------------------------------------

    def months(self) -> list:
        if not self.entries:
            return []
        found = [e.month for e in self.entries]
        return month_span(min(found), max(found))

    def sorted_entries(self) -> list:
        order = {IN: 0, OUT: 1}
        return sorted(
            self.entries,
            key=lambda e: (month_ordinal(e.month), order[e.direction], -e.amount, e.label),
        )

    def month_entries(self, month: str) -> list:
        month = normalize_month(month)
        return [e for e in self.sorted_entries() if e.month == month]

    # -- aggregation -------------------------------------------------------

    def summarize(self, month_from=None, month_to=None, categories=None) -> Summary:
        """Roll entries up to one value per month.

        categories=None means all. The cumulative line is always accumulated from
        the first month of the *filtered* history and only then sliced to the
        requested window -- so zooming to the last 12 months does not reset the
        running total to zero.
        """
        selected = self.entries
        if categories is not None:
            wanted = set(categories)
            selected = [e for e in selected if e.category in wanted]
        if not selected:
            return Summary([], [], [], [], [], [], {}, {}, [], {})

        found = [e.month for e in selected]
        span = month_span(min(found), max(found))
        index = {month: i for i, month in enumerate(span)}
        size = len(span)

        inflow = [0.0] * size
        outflow = [0.0] * size
        present = [name for name in self.categories if any(e.category == name for e in selected)]
        in_by_cat = {name: [0.0] * size for name in present}
        out_by_cat = {name: [0.0] * size for name in present}

        # Tagged purposes keep their registration order (so colours are stable);
        # UNTAGGED is appended last so it stacks on top of what is accounted for.
        spent = {e.purpose for e in selected if e.direction == OUT and e.purpose}
        purposes = [name for name in self.purposes if name in spent]
        if any(e.direction == OUT and not e.purpose for e in selected):
            purposes.append(UNTAGGED)
        out_by_purpose = {name: [0.0] * size for name in purposes}

        for entry in selected:
            slot = index[entry.month]
            if entry.direction == IN:
                inflow[slot] += entry.amount
                in_by_cat[entry.category][slot] += entry.amount
            else:
                outflow[slot] += entry.amount
                out_by_cat[entry.category][slot] += entry.amount
                out_by_purpose[entry.purpose or UNTAGGED][slot] += entry.amount

        net = [i - o for i, o in zip(inflow, outflow)]
        cumulative = []
        running = 0.0
        for value in net:
            running += value
            cumulative.append(running)

        start = index.get(normalize_month(month_from), 0) if month_from else 0
        stop = index.get(normalize_month(month_to), size - 1) + 1 if month_to else size
        start = max(0, min(start, size - 1))
        stop = min(size, max(stop, start + 1))

        return Summary(
            months=span[start:stop],
            inflow=inflow[start:stop],
            outflow=outflow[start:stop],
            net=net[start:stop],
            cumulative=cumulative[start:stop],
            categories=present,
            inflow_by_category={k: v[start:stop] for k, v in in_by_cat.items()},
            outflow_by_category={k: v[start:stop] for k, v in out_by_cat.items()},
            purposes=purposes,
            outflow_by_purpose={k: v[start:stop] for k, v in out_by_purpose.items()},
        )

    # -- history -----------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "categories": list(self.categories),
            "purposes": list(self.purposes),
        }

    def restore(self, snapshot: dict) -> None:
        self.entries = [Entry.from_dict(d) for d in snapshot["entries"]]
        self.categories = list(snapshot["categories"])
        self.purposes = list(snapshot.get("purposes", []))


class History:
    """Snapshot undo/redo. Cheap enough at this scale to just copy the whole ledger."""

    def __init__(self, limit: int = 60):
        self.limit = limit
        self._undo = []
        self._redo = []

    def record(self, ledger: Ledger) -> None:
        self._undo.append(ledger.snapshot())
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, ledger: Ledger) -> bool:
        if not self._undo:
            return False
        self._redo.append(ledger.snapshot())
        ledger.restore(self._undo.pop())
        return True

    def redo(self, ledger: Ledger) -> bool:
        if not self._redo:
            return False
        self._undo.append(ledger.snapshot())
        ledger.restore(self._redo.pop())
        return True
