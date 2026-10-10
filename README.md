# Bibit Transaction Visualizer

An editable monthly cash-flow ledger for investment tracking, with a chart that
redraws as you type. It imports Bibit transaction exports, but it is not limited
to them — you add rows for anything else you hold (crypto, gold, a second broker)
and everything rolls up into the same monthly view.

- **Just want to use it?** Follow [1. Install the app](#1-install-the-app) — build
  a standalone `BibitVisualizer.exe` once, then double-click it; no Python needed
  to run it afterwards.
- **Want to work on the code?** Follow [2. Start developing](#2-start-developing).

## 1. Install the app

Releases are not published as downloads, so the app is built from source once.
The result is a single `BibitVisualizer.exe` (Windows, ~55 MB) that runs on any
machine without Python.

1. **Install Python 3.10 or newer** from [python.org](https://www.python.org/downloads/).
   On the first installer screen tick **"Add python.exe to PATH"**. Tkinter is
   included by default.
2. **Install Git** from [git-scm.com](https://git-scm.com/download/win) (or click
   *Code → Download ZIP* on GitHub and unzip it instead of step 3).
3. **Get the code** — open *PowerShell* or *Command Prompt*:

   ```bash
   git clone https://github.com/Fortissible/bibit-invest-visualizer.git
   cd bibit-invest-visualizer
   ```

4. **Install the dependencies and the builder:**

   ```bash
   python -m pip install -r requirements.txt pyinstaller
   ```

5. **Build the app:**

   ```bash
   python packaging/build.py
   ```

   It takes a minute or two and ends with the path of the result:
   **`dist\BibitVisualizer.exe`**.
6. **Install it** — copy `BibitVisualizer.exe` anywhere you like (e.g.
   `C:\Users\<you>\Apps\`), then right-click it → *Send to → Desktop (create
   shortcut)*. The cloned folder is no longer needed to run it.
7. **Run it** — double-click. A splash shows immediately; the window follows in
   about five seconds. Windows SmartScreen may warn about an unrecognised app the
   first time, since the build is not code-signed: *More info → Run anyway*.
8. **Load your data** — in Bibit, export your transaction history (PDF, or the
   older CSV/XLSX), then in the app press `Ctrl+I` and select the file(s). Save
   your ledger with `Ctrl+S`; next launch reopens it automatically. `F1` opens the
   built-in help.

Build variants:

| Command | Produces |
|---|---|
| `python packaging/build.py` | `dist\BibitVisualizer.exe` — one file, windowed (recommended) |
| `python packaging/build.py --onedir` | `dist\BibitVisualizer\` — a folder; not measurably faster, twice the disk |
| `python packaging/build.py --console` | a build that keeps a terminal, for the `--no-gui` CLI output |
| `python packaging/build.py --clean` | clears PyInstaller's cache first — use if a build behaves oddly |

Because a packaged build has no console, unhandled errors are shown in a dialog
and appended to `%APPDATA%\bibitviz\error.log` rather than disappearing, and a
remembered ledger that has been moved or damaged just starts you empty instead
of refusing to open.

To **update**, `git pull` in the cloned folder and repeat step 5. To **uninstall**,
delete the `.exe` and the `%APPDATA%\bibitviz` folder (it holds only the
recent-files list and error log; your `.bviz` ledgers live wherever you saved them).

## 2. Start developing

1. **Prerequisites** — Python 3.10+ and Git (see steps 1–2 above).
   - Windows / macOS: Tkinter ships with the python.org installer.
   - Debian / Ubuntu: `sudo apt install python3-tk python3-venv`.
2. **Clone the repository:**

   ```bash
   git clone https://github.com/Fortissible/bibit-invest-visualizer.git
   cd bibit-invest-visualizer
   ```

3. **Create a virtual environment** so the project's libraries stay separate
   from the rest of your system:

   ```bash
   python -m venv .venv
   ```

4. **Activate it** (do this in every new terminal you work in):

   ```bash
   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   # Windows Command Prompt
   .venv\Scripts\activate.bat
   # macOS / Linux
   source .venv/bin/activate
   ```

   If PowerShell refuses with *"running scripts is disabled"*, run
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.
5. **Install the libraries:**

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

   | Library | Why |
   |---|---|
   | `matplotlib` | the charts |
   | `pdfplumber` | reading Bibit's PDF transaction history |
   | `openpyxl` | reading `.xlsx` exports |

   `pdfplumber` and `openpyxl` are imported lazily, so the app still runs without
   them if you only use the other formats. Nothing else is required — the `.xlsx`
   reader uses openpyxl directly rather than pulling in pandas.
6. **Check it works:**

   ```bash
   python main.py --help        # lists every CLI option
   python main.py               # opens the window
   python main.py --fresh       # opens with an empty ledger
   ```

7. **Make your changes** — see [Layout](#layout) for which file does what. The
   GUI is plain Tkinter (`bibitviz/app.py`); parsing and the data model have no GUI
   dependency, so they can be exercised headless:

   ```bash
   python main.py --import my-report.pdf --png chart.png --no-gui
   ```

8. **(Optional) Build the app** to test the packaged version:

   ```bash
   python -m pip install pyinstaller
   python packaging/build.py --console
   ```

   `build/` and `dist/` are git-ignored, as are `.bviz` ledgers and any
   `.pdf`/`.csv`/`.xlsx` reports — keep your real transaction files in the project
   folder if convenient; they will not be committed.

## What it does

**A month holds as many rows as you need.** Importing a Bibit report seeds each
month with one row per direction per kind — so a month arrives as a *Fund Buy*
row, a *Coupon* row and a *Fund Sell* row rather than one opaque total. Add your
own rows beside them and they all add up.

**Two starting categories, `Bibit` and `Crypto`**, and you can type any new name
into a category cell to create another. Category colours are fixed by position,
so filtering a category out never repaints the others.

**Save and open your own ledger files** (`.bviz`, plain JSON). This is a separate
thing from importing a Bibit export: the export is read-only source data, the
`.bviz` file is your working document, including everything you typed by hand.

**Every Out row can say what it was spent on** — eat, holiday, game, transport,
electricity, bill, anything you type. See *Spending breakdown* below.

**Imports PDF, CSV and XLSX**, and stitches several files into one history — see
below, because Bibit's PDF report is capped at one year.

## Spending breakdown

Every row has a **Purpose** alongside its Category. They are two different
questions: *category* is which pot the money moved through (Bibit, Crypto),
*purpose* is what it actually went on (Eat, Holiday, Bill, Transport). It is free
text — type anything and it joins the list, which is remembered in the file.

An import lands one summarised Out row per month, so **Split row** (`Ctrl+K`) is
how a month gets broken down: peel `2,000,000` off January's outflow and label it
*Holiday*, then split the remainder again for the next purpose. The month's total
never changes, only how it is described. To tag a batch of rows at once, select
them and press `Ctrl+T`.

The **Outflow by purpose** view then shows each month's outflow stacked by
purpose, with a ranked total for the whole window underneath — so "where did my
money actually go" has an answer. Whatever is not yet tagged is shown as
**Untagged** in a neutral grey rather than being quietly dropped; the KPI row
tells you what percentage of outflow is accounted for.

## Projection

**View → Projection…** (`Ctrl+P`) carries the ledger forward for as many months
as you ask. Enter your monthly salary for the years you know — `11.5jt`,
`11.500.000` or just `11.5` all work — and set:

- a **yearly raise** (%), and the month it lands in;
- a **yearly bonus**, as a multiple of that month's salary, and the month it is paid;
- the share of **salary** and of **bonus** you save;
- an optional **return** on the balance. It defaults to 0, so the line stays
  comparable to the main chart, which tracks capital put in rather than market value.

The projection starts from the ledger's closing balance, so the dashed line
continues the solid one. A table underneath shows past years (salary earned
against what the ledger actually deployed) beside the projected years, so the
savings rate you assume can be checked against the one you have actually had.
**Use actual** fills in the last 12 months' rate. Next to the raise field, the
window shows the raise your own salary timeline implies. The assumptions are
saved in the `.bviz` file.

## Stitching multi-year history

Bibit's transaction history is now a PDF covering **at most one year**, so a
longer history is several files whose ranges overlap. Select them all at once
(`Ctrl+I`, or `--import a.pdf b.pdf c.pdf`) and they are joined into one run.

The join works on **per-day authority**: for each day, exactly one report is the
source. Not row-level deduplication — that would be wrong here. Selling the same
number of units of the same fund at the same NAV *twice* in one day really
happens, and any scheme that hashes rows and keeps the distinct ones silently
deletes the second.
Since each report is complete for every day inside its own range, a day never
needs assembling from two files; it only needs taking from the right one.

Among the reports covering a day, the winner is the one that states its own range
(a PDF prints it; a spreadsheet export does not, so its range is inferred from its
rows) and then the one holding the day furthest from its own edges, since an edge
day is the one at risk of being partial. That gives three useful properties:

- duplicate transactions survive, because a day's rows are never merged;
- overlaps cannot double-count, because a day comes from exactly one file;
- **an old CSV export mixes with new PDFs**, because the rule needs only a date
  range, not a shared transaction id — which the PDFs no longer print.

Anything the rule cannot settle is shown rather than hidden. **Gaps** ("nothing
covers 01 Jan 2024 to 31 Dec 2025 — export that range too") and **conflicts**
(two reports that both claim a day and disagree about it) are put in front of you
before the import lands. Reports from two different SIDs are refused outright.

## What the PDF contains

The PDF holds five separate tables, all of which are read:

| Section | Becomes |
|---|---|
| Mutual Fund - IDR | `Fund Buy` / `Fund Sell` / `Fund Instant Redeem` |
| FR Bonds - Transaction | `Bond Maturity`, buys and sells |
| FR Bonds - Coupon Disbursed | `Coupon` |
| Stocks - Transaction | `Stock Buy`, `Stock Buy IPO`, `Stock Refund IPO` |
| Stocks - Cash Dividend | `Dividend` |

Columns are cut from the page geometry rather than by splitting text, because
fund names ("Manulife Dana Kas Syariah") and transaction types ("Instant Redeem",
"Buy IPO") both contain spaces. Each section's printed `Total` line is parsed too
and checked against the sum of the rows, so a misparse becomes a loud warning
instead of a quietly wrong chart.

## The window

```
Filters:  From / To · Last 12 · Categories · In-vs-Out or By-category · Units · Theme
KPIs:     Total in · Total out · Net deployed · Months · Ledger rows
Left:     the ledger, grouped by month - In rows green, Out rows red;
          double-click any cell to edit in place
Right:    the chart - every month is a point on both panels, hover for detail
```

| | |
|---|---|
| `Ctrl+N` / `Ctrl+O` | new / open ledger |
| `Ctrl+S` / `Ctrl+Shift+S` | save / save as |
| `Ctrl+I` | import Bibit report(s) — `.pdf`, `.csv`, `.xlsx`; select several to stitch |
| `Ctrl+Enter` | add row |
| `Ctrl+K` | split a row, to break a month's outflow into purposes |
| `Ctrl+T` | set the purpose on every selected row |
| `Ctrl+D` / `Delete` | duplicate / delete row |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo |

Amounts accept Indonesian formatting — typing `13.690.000` or `13690000` both
work, in the table and in the add-row dialog.

## The chart

Two panels sharing one x-axis: monthly flow on top (In and Out bars with the net
line over them), cumulative capital deployed underneath. They are separate
because the running total grows to roughly twice the largest monthly bar — drawn
together on one scale the bars flatten out, and putting the total on a second
y-axis would imply a relationship that is not in the data.

*By category* mode stacks In above the zero line and Out below it, coloured by
category, so you can see how much of a month was Bibit and how much was crypto.
*Outflow by purpose* stacks the month's spending by what it was for, with a
ranked total for the whole window in the lower panel.

Every month is a point on both panels and both answer to hover: the top gives
that month's In, Out, Net and the split behind them; the cumulative line gives
the running total, what the month added, and what it stood at before.

Colours are validated for colour-vision deficiency in both light and dark themes,
and values are direct-labelled selectively (the extremes and the endpoint) rather
than on every bar — the ledger table beside the chart is the complete table view.

## Headless use

```bash
# stitch a multi-year history and render it, without opening a window
python main.py --import 2023-2024.pdf 2024-2025.pdf 2025-2026.pdf --png chart.png --no-gui

# mix the old spreadsheet export with the new PDFs
python main.py --import old-export.csv 2025-2026.pdf --save ledger.bviz --no-gui

# monthly totals as CSV, in millions, dark theme
python main.py ledger.bviz --csv monthly.csv --scale million --theme dark --no-gui

# just print the totals
python main.py ledger.bviz --no-gui
```

`--mode category`, `--size WxH`, and `--keep-transactions` (import every
transaction instead of summarising by month) are also available;
`python main.py --help` lists everything.

## Two notes on the data

**Coupons and dividends.** Bibit's coupon rows (`Kupon` in the old CSV, `Coupon`
in the PDF) and stock dividends are cash a holding pays out. They are imported as
**In**, matching how this project has always counted them — money staying in the
portfolio, reinvested. They arrive as their own row, so if you would rather treat
a coupon as a withdrawal, flip that row's direction and the chart follows.

**In is green, Out is red** in the ledger, and a month's own row takes the
colour of its net. The chart keeps blue/red instead: there the colour *is* the
only channel, and green/red is the pair colour-blind readers most often lose,
whereas the table writes "In" or "Out" beside every row anyway. Both row colours
clear 4.5:1 against every background they sit on, in light and dark.

**Empty months are drawn.** A month with no activity shows as a gap on the axis
rather than being dropped, so the time axis stays honest.

**Your work is not lost between sessions.** Purposes and their tags live in the
`.bviz` file, and launching with no arguments reopens the ledger you last saved
(`File > Open recent` lists the rest; `--fresh` starts empty instead). Files
written before this feature existed still open — their rows simply arrive
untagged.

## Layout

| File | |
|---|---|
| `main.py` | entry point and CLI |
| `bibitviz/model.py` | entries, the ledger, monthly aggregation, undo |
| `bibitviz/records.py` | the shape every source parses into (`Report`, `RawRow`) |
| `bibitviz/importer.py` | CSV/XLSX parsing, and turning rows into ledger entries |
| `bibitviz/pdf_report.py` | PDF parsing — sections, column geometry, total checks |
| `bibitviz/stitch.py` | joining several reports into one history |
| `bibitviz/storage.py` | `.bviz` save/open, CSV export |
| `bibitviz/chart.py` | the matplotlib figures, main chart and projection |
| `bibitviz/projection.py` | salary timeline, raises, bonus, and the month-by-month projection |
| `bibitviz/projection_window.py` | the projection window |
| `bibitviz/app.py` | the Tkinter window |
| `bibitviz/theme.py` | the validated light and dark palettes |
| `packaging/build.py` | builds the standalone app |
