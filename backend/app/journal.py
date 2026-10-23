"""Append-only CSV trade journal.

trade_history in store.json keeps the latest 100 events for the dashboard; the
CSV keeps everything so it can be exported or opened in a spreadsheet.
"""

import csv
import io
import os
import threading
from pathlib import Path

JOURNAL_FIELDS = ("timestamp", "type", "symbol", "side", "exposure", "note")
_LOCK = threading.Lock()


def journal_path() -> Path:
    log_dir = os.getenv("COMMUNITY_LOG_DIR")
    base = Path(log_dir).expanduser() if log_dir else Path(__file__).resolve().parents[2] / "logs"
    return base / "trade_log.csv"


def append_entry(entry: dict) -> bool:
    path = journal_path()
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            new_file = not path.exists() or path.stat().st_size == 0
            with path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=JOURNAL_FIELDS, extrasaction="ignore")
                if new_file:
                    writer.writeheader()
                writer.writerow({field: entry.get(field, "") for field in JOURNAL_FIELDS})
        return True
    except OSError:
        return False


def export_csv(fallback_rows: list) -> str:
    """The full journal, or the in-memory history if no CSV has been written yet."""
    path = journal_path()
    if path.exists() and path.stat().st_size:
        return path.read_text(encoding="utf-8")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=JOURNAL_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in reversed(fallback_rows or []):
        writer.writerow({field: row.get(field, "") for field in JOURNAL_FIELDS})
    return buffer.getvalue()
