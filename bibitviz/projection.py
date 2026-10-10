"""Project the ledger forward from a salary, a yearly raise and a yearly bonus.

The ledger only knows what moved into and out of the portfolio. A projection
needs the other side too -- what was earned -- so the salary is entered as a
short timeline ("2023: 5.5 jt, 2024: 10 jt, ...") and everything else is derived:

  * past years: salary income against the net the ledger actually deployed, which
    gives the real savings rate, year by year
  * future months: the last known salary, raised once a year, with a bonus in one
    month of the year; a share of each is saved and added to the balance

The projection starts from the ledger's closing cumulative balance, so it carries
on the line the main chart already draws rather than starting from zero.

Nothing here touches Tk or matplotlib, so it can be checked headless.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import IN, Ledger, month_ordinal, month_span, shift_month

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class ProjectionSettings:
    """The assumptions. Saved in the .bviz file's settings, so they reopen with it."""

    months: int = 36
    #: Monthly take-home salary by calendar year. A year missing from the middle
    #: carries the previous one forward; years after the last one get raises.
    salary: dict = field(default_factory=dict)
    raise_pct: float = 7.0
    #: Month (1-12) the raise lands in. Before it, a year still pays last year's rate.
    raise_month: int = 1
    #: Bonus as a multiple of that month's salary, paid once a year.
    bonus_months: float = 1.0
    bonus_month: int = 12
    save_pct: float = 30.0
    bonus_save_pct: float = 50.0
    #: Yearly return on the balance. 0 keeps the line comparable to the main
    #: chart, which tracks capital deployed, not market value.
    return_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "months": self.months,
            "salary": {str(year): amount for year, amount in sorted(self.salary.items())},
            "raise_pct": self.raise_pct,
            "raise_month": self.raise_month,
            "bonus_months": self.bonus_months,
            "bonus_month": self.bonus_month,
            "save_pct": self.save_pct,
            "bonus_save_pct": self.bonus_save_pct,
            "return_pct": self.return_pct,
        }

    @classmethod
    def from_dict(cls, data) -> "ProjectionSettings":
        settings = cls()
        if not isinstance(data, dict):
            return settings
        for name in ("raise_pct", "bonus_months", "save_pct", "bonus_save_pct", "return_pct"):
            try:
                setattr(settings, name, float(data[name]))
            except (KeyError, TypeError, ValueError):
                pass
        for name in ("months", "raise_month", "bonus_month"):
            try:
                setattr(settings, name, int(data[name]))
            except (KeyError, TypeError, ValueError):
                pass
        salary = {}
        for year, amount in (data.get("salary") or {}).items():
            try:
                salary[int(year)] = float(amount)
            except (TypeError, ValueError):
                continue
        settings.salary = salary
        settings.clamp()
        return settings

    def clamp(self) -> None:
        self.months = max(1, min(int(self.months), 600))
        self.raise_month = max(1, min(int(self.raise_month), 12))
        self.bonus_month = max(1, min(int(self.bonus_month), 12))
        self.bonus_months = max(0.0, self.bonus_months)
        self.save_pct = max(0.0, min(self.save_pct, 100.0))
        self.bonus_save_pct = max(0.0, min(self.bonus_save_pct, 100.0))
        self.salary = {year: amount for year, amount in self.salary.items() if amount > 0}


# --------------------------------------------------------------------------- salary


def salary_for(month: str, settings: ProjectionSettings) -> float:
    """Monthly salary in force in `month` (YYYY-MM).

    A year that is in the timeline pays its own figure all year -- that is how it
    was entered ("2024: 10 jt"). After the last entered year the raise compounds
    once a year, from `raise_month` on. Before the first entered year there is no
    salary to speak of, so it is 0.
    """
    if not settings.salary:
        return 0.0
    year, mon = int(month[:4]), int(month[5:7])
    known = sorted(settings.salary)
    if year < known[0]:
        return 0.0
    if year in settings.salary:
        return settings.salary[year]
    if year < known[-1]:
        # a gap in the timeline: carry the last stated year forward
        return settings.salary[max(y for y in known if y < year)]
    raises = year - known[-1] - (1 if mon < settings.raise_month else 0)
    return settings.salary[known[-1]] * (1 + settings.raise_pct / 100.0) ** raises


def bonus_for(month: str, settings: ProjectionSettings) -> float:
    if int(month[5:7]) != settings.bonus_month:
        return 0.0
    return salary_for(month, settings) * settings.bonus_months


def implied_raises(salary: dict) -> list:
    """(from_year, last_year, compounded yearly %) from each earlier year to the latest.

    Shown beside the raise field, so the raise can be judged against what the
    timeline itself says: a big early jump and a slow recent climb give very
    different answers, and only the person knows which one will continue.
    """
    years = sorted(salary)
    if len(years) < 2:
        return []
    last = years[-1]
    return [
        (year, last, ((salary[last] / salary[year]) ** (1 / (last - year)) - 1) * 100)
        for year in years[:-1]
        if salary[year] > 0
    ]


# --------------------------------------------------------------------------- history


@dataclass
class YearRow:
    year: int
    months: int
    salary: float          # monthly salary that year (or the latest, for projected)
    income: float          # salary x months + bonus, over the months counted
    saved: float           # net deployed (actual) or contributions (projected)
    closing: float         # balance at the end of the year (or of the window)
    projected: bool

    @property
    def rate(self) -> float:
        return self.saved / self.income if self.income else 0.0


def actual_years(ledger: Ledger, settings: ProjectionSettings, categories=None) -> list:
    """Per calendar year: what was earned against what the ledger actually deployed.

    Only months the ledger covers are counted, so a history that starts in July
    compares six months of salary with six months of saving, not twelve with six.
    """
    summary = ledger.summarize(categories=categories)
    rows = {}
    for month, net, cumulative in zip(summary.months, summary.net, summary.cumulative):
        year = int(month[:4])
        row = rows.get(year)
        if row is None:
            row = rows[year] = YearRow(year, 0, 0.0, 0.0, 0.0, 0.0, projected=False)
        row.months += 1
        row.salary = salary_for(month, settings)
        row.income += salary_for(month, settings) + bonus_for(month, settings)
        row.saved += net
        row.closing = cumulative
    return [rows[year] for year in sorted(rows)]


def trailing_save_rate(ledger: Ledger, settings: ProjectionSettings, months=12, categories=None):
    """Share of income deployed over the last `months` months, or None if unknown."""
    summary = ledger.summarize(categories=categories)
    if not summary.months:
        return None
    window = list(zip(summary.months, summary.net))[-months:]
    income = sum(salary_for(m, settings) + bonus_for(m, settings) for m, _net in window)
    if income <= 0:
        return None
    return sum(net for _m, net in window) / income * 100.0


# --------------------------------------------------------------------------- projection


@dataclass
class Projection:
    """One value per projected month, plus the actual history it continues from."""

    months: list
    salary: list
    bonus: list
    saved_salary: list
    saved_bonus: list
    growth: list
    balance: list
    #: what the balance would be with no return -- the deployed-capital line
    contributed: list
    start_month: str
    start_balance: float
    history_months: list = field(default_factory=list)
    history_net: list = field(default_factory=list)
    history_balance: list = field(default_factory=list)
    history_salary: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.months)

    @property
    def total_saved_salary(self) -> float:
        return sum(self.saved_salary)

    @property
    def total_saved_bonus(self) -> float:
        return sum(self.saved_bonus)

    @property
    def total_growth(self) -> float:
        return sum(self.growth)

    @property
    def closing(self) -> float:
        return self.balance[-1] if self.balance else self.start_balance

    def years(self) -> list:
        rows = {}
        for i, month in enumerate(self.months):
            year = int(month[:4])
            row = rows.get(year)
            if row is None:
                row = rows[year] = YearRow(year, 0, 0.0, 0.0, 0.0, 0.0, projected=True)
            row.months += 1
            row.salary = self.salary[i]
            row.income += self.salary[i] + self.bonus[i]
            row.saved += self.saved_salary[i] + self.saved_bonus[i]
            row.closing = self.balance[i]
        return [rows[year] for year in sorted(rows)]


def project(ledger: Ledger, settings: ProjectionSettings, categories=None, start_month=None) -> Projection:
    """Run the projection forward from the month after the ledger's last one.

    `start_month` overrides where it begins (the first projected month); the
    starting balance is still the ledger's closing cumulative, since that is the
    only balance there is.
    """
    settings.clamp()
    summary = ledger.summarize(categories=categories)
    start_balance = summary.closing_cumulative
    if start_month is None:
        if summary.months:
            start_month = shift_month(summary.months[-1], 1)
        else:
            from datetime import date

            today = date.today()
            start_month = f"{today.year:04d}-{today.month:02d}"

    months = month_span(start_month, shift_month(start_month, settings.months - 1))
    monthly_return = (1 + settings.return_pct / 100.0) ** (1 / 12) - 1

    out = Projection([], [], [], [], [], [], [], [], start_month, start_balance)
    balance = contributed = start_balance
    for month in months:
        salary = salary_for(month, settings)
        bonus = bonus_for(month, settings)
        from_salary = salary * settings.save_pct / 100.0
        from_bonus = bonus * settings.bonus_save_pct / 100.0
        # Growth is earned on the balance carried into the month; this month's
        # saving goes in at the end of it.
        growth = balance * monthly_return
        balance += growth + from_salary + from_bonus
        contributed += from_salary + from_bonus

        out.months.append(month)
        out.salary.append(salary)
        out.bonus.append(bonus)
        out.saved_salary.append(from_salary)
        out.saved_bonus.append(from_bonus)
        out.growth.append(growth)
        out.balance.append(balance)
        out.contributed.append(contributed)

    # Only the history that comes before the projection is context for it.
    for month, net, cumulative in zip(summary.months, summary.net, summary.cumulative):
        if month_ordinal(month) < month_ordinal(start_month):
            out.history_months.append(month)
            out.history_net.append(net)
            out.history_balance.append(cumulative)
            out.history_salary.append(salary_for(month, settings))
    return out


def suggest_save_pct(ledger: Ledger, settings: ProjectionSettings, categories=None):
    """The last twelve months' actual savings rate, clamped to 0-100, or None.

    Needs a salary to divide by, so with an empty timeline there is no suggestion.
    """
    rate = trailing_save_rate(ledger, settings, categories=categories)
    if rate is None:
        return None
    return float(round(max(0.0, min(rate, 100.0))))


def default_settings(ledger: Ledger, salary=None) -> ProjectionSettings:
    """Assumptions for a ledger that has none saved yet.

    The savings rate starts at what the ledger actually shows rather than a
    round guess, once there is a salary to measure it against.
    """
    settings = ProjectionSettings(salary=dict(salary or {}))
    suggested = suggest_save_pct(ledger, settings)
    if suggested is not None:
        settings.save_pct = suggested
    return settings
