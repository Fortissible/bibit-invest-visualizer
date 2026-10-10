"""Save and open the app's own ledger files.

A .bviz file is plain JSON -- readable, diffable, and greppable -- and is a
different thing from a Bibit export: the export is read-only source data you
import, this is your working document, including the rows you typed yourself.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .model import Entry, Ledger

FORMAT = "bibit-transaction-visualizer"
#: v2 added per-entry `purpose` and the ledger's purpose list. v1 files still
#: open -- their entries simply arrive untagged - so nothing written by an
#: earlier build has to be redone.
VERSION = 2
EXTENSION = ".bviz"
FILETYPES = [("Ledger file", "*.bviz"), ("JSON", "*.json"), ("All files", "*.*")]


class StorageError(ValueError):
    """Raised when a file is not a ledger this version can open."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_document(ledger: Ledger, settings=None) -> dict:
    meta = dict(ledger.meta)
    meta.setdefault("created", _now())
    meta["modified"] = _now()
    return {
        "format": FORMAT,
        "version": VERSION,
        "meta": meta,
        "settings": dict(settings or {}),
        "categories": list(ledger.categories),
        "purposes": list(ledger.purposes),
        "entries": [entry.to_dict() for entry in ledger.entries],
    }


def from_document(document: dict):
    if not isinstance(document, dict):
        raise StorageError("File is not a ledger document.")
    if document.get("format") != FORMAT:
        raise StorageError(
            "This is not a ledger file. To read a Bibit report, use File > Import Bibit report."
        )
    version = document.get("version", 0)
    if not isinstance(version, int) or version > VERSION:
        raise StorageError(
            f"This file was written by a newer version (v{version}); this app reads up to v{VERSION}."
        )
    try:
        entries = [Entry.from_dict(row) for row in document.get("entries", [])]
    except Exception as error:
        raise StorageError(f"Ledger rows are malformed: {error}") from error

    ledger = Ledger(
        entries=entries,
        categories=document.get("categories") or None,
        purposes=document.get("purposes"),   # absent in v1: fall back to the suggestions
        meta=document.get("meta") or {},
    )
    return ledger, dict(document.get("settings") or {})


def save(path, ledger: Ledger, settings=None) -> Path:
    """Write atomically, so an interrupted save never truncates the previous file."""
    path = Path(path)
    if not path.suffix:
        path = path.with_suffix(EXTENSION)
    payload = json.dumps(to_document(ledger, settings), indent=2, ensure_ascii=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=path.name + ".", suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return path


def load(path):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise StorageError(f"Could not read {path}: {error}") from error
    except UnicodeDecodeError:
        raise StorageError(f"{path.name} is not a text file, so it is not a ledger.") from None

    if not text.lstrip().startswith("{"):
        raise StorageError(
            f"{path.name} is not a ledger file. If it is a Bibit export, "
            "use File > Import Bibit report instead of Open."
        )
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise StorageError(f"{path.name} is damaged - the JSON does not parse: {error}") from error
    ledger, settings = from_document(document)
    ledger.meta.setdefault("path", str(path))
    return ledger, settings


# --------------------------------------------------------------------------- app settings


_MAX_RECENT = 8


def settings_path() -> Path:
    """Where the app remembers which ledger you had open, per platform."""
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) / "bibitviz" if base else Path.home() / ".bibitviz"
    return root / "settings.json"


def load_app_settings() -> dict:
    """Never raises: a missing or damaged settings file just means no memory."""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_app_settings(data: dict) -> None:
    """Best effort. Failing to remember a preference must never break the app."""
    try:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def recent_files(settings=None) -> list:
    """Recently opened ledgers, newest first, skipping any that have gone away."""
    settings = load_app_settings() if settings is None else settings
    seen, alive = set(), []
    for item in settings.get("recent", []):
        path = Path(item)
        if str(path) not in seen and path.exists():
            seen.add(str(path))
            alive.append(path)
    return alive[:_MAX_RECENT]


def remember_recent(path, **extra) -> None:
    """Push a ledger to the top of the recent list, so it reopens next time."""
    settings = load_app_settings()
    resolved = str(Path(path).resolve())
    recent = [item for item in settings.get("recent", []) if item != resolved]
    settings["recent"] = [resolved] + recent[: _MAX_RECENT - 1]
    settings.update(extra)
    save_app_settings(settings)


def export_csv(path, ledger: Ledger) -> Path:
    """Every ledger row as CSV -- the table view, portable."""
    import csv

    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Month", "Direction", "Amount (IDR)", "Category", "Purpose",
                         "Label", "Note", "Source"])
        for entry in ledger.sorted_entries():
            writer.writerow([
                entry.month, entry.direction, f"{entry.amount:.2f}",
                entry.category, entry.purpose, entry.label, entry.note, entry.source,
            ])
    return path


def export_monthly_csv(path, summary) -> Path:
    """The monthly roll-up behind the chart."""
    import csv

    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Month", "In (IDR)", "Out (IDR)", "Net (IDR)", "Cumulative (IDR)"])
        for row in zip(summary.months, summary.inflow, summary.outflow, summary.net, summary.cumulative):
            writer.writerow([row[0]] + [f"{value:.2f}" for value in row[1:]])
    return path
