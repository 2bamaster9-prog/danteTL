"""Worker-owned bounded memory/SQLite cache; disk failure degrades to memory only."""

import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
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
        self._db: sqlite3.Connection | None = None
        self.warning = ""
        try:
            with _schema_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(path, timeout=1)
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("PRAGMA synchronous=NORMAL")
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS translations "
                    "(key TEXT PRIMARY KEY, english TEXT NOT NULL, used INTEGER NOT NULL)"
                )
                self._db.execute(
                    "CREATE INDEX IF NOT EXISTS recent_translation ON translations(used)"
                )
                self._db.commit()
        except (OSError, sqlite3.Error) as error:
            self._disable_disk(error)

    def _disable_disk(self, error: Exception) -> None:
        self.warning = "Translation cache is using memory only; disk cache is unavailable."
        logger.warning("Translation disk cache unavailable: %s", error)
        self.close()

    def _remember(self, key: str, english: str) -> None:
        self._memory[key] = english
        self._memory.move_to_end(key)
        while len(self._memory) > self._memory_limit:
            self._memory.popitem(last=False)

    def get(self, key: str) -> str | None:
        if key in self._memory:
            self._memory.move_to_end(key)
            return self._memory[key]
        if self._db is not None:
            try:
                row = self._db.execute(
                    "SELECT english FROM translations WHERE key=?", (key,)
                ).fetchone()
                if row is not None:
                    self._db.execute(
                        "UPDATE translations SET used=? WHERE key=?", (time.time_ns(), key)
                    )
                    self._db.commit()
                    self._remember(key, row[0])
                    return row[0]
            except sqlite3.Error as error:
                self._disable_disk(error)
        return None

    def put(self, key: str, english: str) -> None:
        self._remember(key, english)
        if self._db is not None:
            try:
                self._db.execute(
                    "INSERT OR REPLACE INTO translations VALUES (?, ?, ?)",
                    (key, english, time.time_ns()),
                )
                self._db.execute(
                    "DELETE FROM translations WHERE key IN "
                    "(SELECT key FROM translations ORDER BY used DESC LIMIT -1 OFFSET ?)",
                    (self._disk_limit,),
                )
                self._db.commit()
            except sqlite3.Error as error:
                self._disable_disk(error)

    def close(self) -> None:
        if self._db is not None:
            connection = self._db
            self._db = None
            try:
                connection.close()
            except sqlite3.Error:
                logger.exception("Translation disk cache cleanup failed")
