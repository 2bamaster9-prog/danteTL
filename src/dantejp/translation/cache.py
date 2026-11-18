"""Worker-owned bounded memory/SQLite cache; disk failure degrades to memory only."""

import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from pathlib import Path

logger = logging.getLogger(__name__)
# WAL/schema initialization must not race when two category owners start together.
_schema_lock = threading.Lock()


def translation_key(identity: str, source: str) -> str:
    payload = json.dumps(["ja", "en", identity, source], ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class TranslationCache:
    def __init__(self, path: Path, *, memory_limit: int = 512, disk_limit: int = 20_000) -> None:
        if min(memory_limit, disk_limit) < 1:
            raise ValueError("Cache limits must be positive.")
        self._memory: OrderedDict[str, str] = OrderedDict()
        self._memory_limit, self._disk_limit = memory_limit, disk_limit
        self._touched: OrderedDict[str, None] = OrderedDict()
        self._touches = 0
        self._flushed_at = time.monotonic()
        self._db: sqlite3.Connection | None = None
        self._pending: dict[str, str | None] = {}
        self._data_version: int | None = None
        self.warning = ""
        try:
            with _schema_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(path, timeout=1)
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("PRAGMA synchronous=NORMAL")
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS translations "
                    "(key TEXT PRIMARY KEY, english TEXT NOT NULL, used INTEGER NOT NULL)"
                )
                self._db.execute(
                    "CREATE INDEX IF NOT EXISTS recent_translation ON translations(used)"
                )
                # One transactional count is shared by all category owners. Count
                # existing rows on initialization, not on each put.
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS cache_size "
                    "(id INTEGER PRIMARY KEY CHECK(id=1), rows INTEGER NOT NULL)"
                )
                self._db.execute(
                    "INSERT OR IGNORE INTO cache_size SELECT 1, COUNT(*) FROM translations"
                )
                self._db.execute(
                    "CREATE TRIGGER IF NOT EXISTS translation_insert AFTER INSERT ON translations "
                    "BEGIN UPDATE cache_size SET rows=rows+1 WHERE id=1; END"
                )
                self._db.execute(
                    "CREATE TRIGGER IF NOT EXISTS translation_delete AFTER DELETE ON translations "
                    "BEGIN UPDATE cache_size SET rows=rows-1 WHERE id=1; END"
                )
                self._db.commit()
        except (OSError, sqlite3.Error) as error:
            self._disable_disk(error)

    def _disable_disk(self, error: Exception) -> None:
        self.warning = "Translation cache is using memory only; disk cache is unavailable."
        logger.warning("Translation disk cache unavailable: %s", error)
        self._close_connection()

    def _touch(self, key: str) -> None:
        if self._db is None:
            return
        self._touched[key] = None
        self._touched.move_to_end(key)
        self._touches += 1
        if self._touches >= 64 or time.monotonic() - self._flushed_at >= 1:
            self._flush()

    def _flush(self, entry: tuple[str, str] | None = None) -> None:
        if self._db is None or (not self._touched and entry is None):
            return
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                # Windows wall-clock reads can tie across many accesses. Allocate
                # strictly ordered recency within this transaction, using the
                # indexed maximum so independently owned connections agree.
                latest = self._db.execute("SELECT MAX(used) FROM translations").fetchone()[0] or 0
                used = max(latest, time.time_ns())
                self._db.executemany(
                    "UPDATE translations SET used=? WHERE key=?",
                    ((used + index, key) for index, key in enumerate(self._touched, 1)),
                )
                if entry is not None:
                    self._db.execute(
                        "INSERT INTO translations VALUES (?, ?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET english=excluded.english, "
                        "used=MAX(translations.used, excluded.used)",
                        (*entry, used + len(self._touched) + 1),
                    )
                count = self._db.execute("SELECT rows FROM cache_size WHERE id=1").fetchone()[0]
                if count > self._disk_limit:
                    self._db.execute(
                        "DELETE FROM translations WHERE key IN "
                        "(SELECT key FROM translations ORDER BY used LIMIT ?)",
                        (count - self._disk_limit,),
                    )
            self._touched.clear()
            self._touches = 0
            self._flushed_at = time.monotonic()
        except sqlite3.Error as error:
            self._disable_disk(error)

    def _remember(self, key: str, english: str) -> None:
        self._memory[key] = english
        self._memory.move_to_end(key)
        while len(self._memory) > self._memory_limit:
            self._memory.popitem(last=False)

    def get(self, key: str) -> str | None:
        if key in self._memory:
            self._memory.move_to_end(key)
            self._touch(key)
            return self._memory[key]
        if self._db is not None:
            try:
                row = self._db.execute(
                    "SELECT english FROM translations WHERE key=?", (key,)
                ).fetchone()
                if row is not None:
                    self._remember(key, row[0])
                    self._touch(key)
                    return row[0]
            except sqlite3.Error as error:
                self._disable_disk(error)
        return None

    def put(self, key: str, english: str) -> None:
        self._remember(key, english)
        if key in self._pending:
            self._pending[key] = english
        self._flush((key, english))

    def lookup_pending(self, keys: Iterable[str], *, reset: bool) -> Mapping[str, str | None]:
        """Remember lookup results only for the scheduler's current bounded demand."""
        version = None
        if self._db is not None:
            try:
                # This connection's own commits do not change data_version. Sample before
                # the sweep so a concurrent writer cannot leave a remembered miss stale.
                version = self._db.execute("PRAGMA data_version").fetchone()[0]
            except sqlite3.Error as error:
                self._disable_disk(error)
        previous = {} if reset else self._pending
        changed = version != self._data_version
        self._pending = {
            key: previous[key]
            if key in previous and (previous[key] is not None or not changed)
            else self.get(key)
            for key in keys
        }
        self._data_version = version
        return self._pending

    def close(self) -> None:
        self._flush()
        self._close_connection()

    def _close_connection(self) -> None:
        self._touched.clear()
        if self._db is not None:
            connection = self._db
            self._db = None
            try:
                connection.close()
            except sqlite3.Error:
                logger.exception("Translation disk cache cleanup failed")
