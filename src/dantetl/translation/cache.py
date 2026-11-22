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

from dantetl.i18n import tr
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.languages.target import ENGLISH, TargetLanguage
from dantetl.translation.cache_values import CacheInventory

logger = logging.getLogger(__name__)
# WAL/schema initialization must not race when two category owners start together.
_schema_lock = threading.Lock()
DISK_LIMIT = 100_000


def translation_key(
    identity: str,
    source: str,
    *,
    language: SourceLanguage = DEFAULT_SOURCE,
    target: TargetLanguage = ENGLISH,
) -> str:
    # Backends fingerprint their default prompt once. The actual output is a per-request key.
    payload = json.dumps([language.code, target.code, identity, source], ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def _game_id(db: sqlite3.Connection, game: str) -> int:
    db.execute("INSERT OR IGNORE INTO cache_games(name) VALUES (?)", (game,))
    return db.execute("SELECT id FROM cache_games WHERE name=?", (game,)).fetchone()[0]


class TranslationCache:
    def __init__(
        self, path: Path, *, memory_limit: int = 512, disk_limit: int = DISK_LIMIT
    ) -> None:
        if min(memory_limit, disk_limit) < 1:
            raise ValueError(tr("Cache limits must be positive."))
        self._memory: OrderedDict[str, str] = OrderedDict()
        self._memory_limit, self._disk_limit = memory_limit, disk_limit
        self._touched: OrderedDict[str, None] = OrderedDict()
        self._touches = 0
        self._flushed_at = time.monotonic()
        self._db: sqlite3.Connection | None = None
        self._pending: dict[str, str | None] = {}
        self._data_version: int | None = None
        self._revision = 0
        self._game = ""
        self.scope: int | None = None
        self.warning = ""
        try:
            with _schema_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(path, timeout=10)
                self._db.execute("PRAGMA foreign_keys=ON")
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
                # Insert/delete triggers maintain one count across all owners.
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS cache_size "
                    "(id INTEGER PRIMARY KEY CHECK(id=1), rows INTEGER NOT NULL)"
                )
                # Older caches can lack the count or have a count seeded from zero
                # after translations already existed. Repair once under the write lock.
                if self._db.execute("PRAGMA user_version").fetchone()[0] == 0:
                    self._db.execute(
                        "INSERT OR REPLACE INTO cache_size SELECT 1, COUNT(*) FROM translations"
                    )
                    self._db.execute("PRAGMA user_version=1")
                self._db.execute(
                    "CREATE TRIGGER IF NOT EXISTS translation_insert AFTER INSERT ON translations "
                    "BEGIN UPDATE cache_size SET rows=rows+1 WHERE id=1; END"
                )
                self._db.execute(
                    "CREATE TRIGGER IF NOT EXISTS translation_delete AFTER DELETE ON translations "
                    "BEGIN UPDATE cache_size SET rows=rows-1 WHERE id=1; END"
                )
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS cache_games "
                    "(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)"
                )
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS game_entries "
                    "(game INTEGER NOT NULL REFERENCES cache_games ON DELETE CASCADE, "
                    "key TEXT NOT NULL REFERENCES translations ON DELETE CASCADE, "
                    "PRIMARY KEY(game,key)) WITHOUT ROWID"
                )
                self._db.execute("CREATE INDEX IF NOT EXISTS entries_by_key ON game_entries(key)")
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS cache_changes (revision INTEGER NOT NULL)"
                )
                self._db.execute(
                    "INSERT INTO cache_changes SELECT 0 "
                    "WHERE NOT EXISTS (SELECT 1 FROM cache_changes)"
                )
                self._revision = self._db.execute("SELECT revision FROM cache_changes").fetchone()[
                    0
                ]
                self._db.commit()
        except (OSError, sqlite3.Error) as error:
            self._disable_disk(error)

    def _disable_disk(self, error: Exception) -> None:
        self.warning = tr("Translation cache is using memory only; disk cache is unavailable.")
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

    def _flush(self, entry: tuple[str, str] | None = None, scope: int | None = None) -> bool:
        if self._db is None or (not self._touched and entry is None):
            return True
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                if (
                    scope is not None
                    and not self._db.execute(
                        "SELECT 1 FROM cache_games WHERE id=?", (scope,)
                    ).fetchone()
                ):
                    return False  # A clear retired the game while inference was running.
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
                    self._db.execute(
                        "INSERT OR IGNORE INTO game_entries(game,key) VALUES (?,?)",
                        (scope if scope is not None else _game_id(self._db, ""), entry[0]),
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
        return True

    def _remember(self, key: str, english: str) -> None:
        self._memory[key] = english
        self._memory.move_to_end(key)
        while len(self._memory) > self._memory_limit:
            self._memory.popitem(last=False)

    def get(self, key: str) -> str | None:
        if key in self._memory and self._db is not None:
            try:
                if (
                    self._db.execute("SELECT revision FROM cache_changes").fetchone()[0]
                    != self._revision
                ):
                    self._memory.clear()
            except sqlite3.Error as error:
                self._disable_disk(error)
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

    def put(self, key: str, english: str, *, scope: int | None = None) -> None:
        if not self._flush((key, english), scope):
            return
        self._remember(key, english)
        if key in self._pending:
            self._pending[key] = english

    def lookup_pending(
        self, keys: Iterable[str], *, reset: bool, game: str = ""
    ) -> Mapping[str, str | None]:
        """Remember lookup results only for the scheduler's current bounded demand."""
        version = None
        keys = tuple(keys)
        if self._db is not None:
            try:
                # This connection's own commits do not change data_version. Sample before
                # the sweep so a concurrent writer cannot leave a remembered miss stale.
                version = self._db.execute("PRAGMA data_version").fetchone()[0]
                if self._data_version != version:
                    revision = self._db.execute("SELECT revision FROM cache_changes").fetchone()[0]
                    if revision != self._revision:
                        self._revision = revision
                        self._memory.clear()
                        self._pending = {}
                        self._touched.clear()
                        self.scope = None
                if keys and (self.scope is None or self._game != game):
                    with self._db:
                        self.scope = _game_id(self._db, game)
                    self._game = game
                    reset = True
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
        if self._db is not None and self.scope is not None:
            hits = [
                (self.scope, key)
                for key, value in self._pending.items()
                if value is not None and previous.get(key) is None
            ]
            if hits:
                try:
                    with self._db:
                        self._db.executemany(
                            "INSERT OR IGNORE INTO game_entries SELECT g.id,t.key FROM "
                            "cache_games g,translations t WHERE g.id=? AND t.key=?",
                            hits,
                        )
                except sqlite3.Error as error:
                    self._disable_disk(error)
        return self._pending

    def inventory(self, *, clear: bool = False, game: str | None = None) -> CacheInventory:
        """Apply a confirmed deletion and read one consistent disk snapshot. None selects all."""
        db = self._db
        if db is None:
            raise OSError(self.warning)
        with db:
            db.execute("BEGIN IMMEDIATE" if clear else "BEGIN")
            if clear:
                if game is None:
                    db.execute("DELETE FROM translations")
                    db.execute("DELETE FROM cache_games")
                else:
                    db.execute(
                        "DELETE FROM translations WHERE key IN (SELECT e.key FROM game_entries e "
                        "JOIN cache_games g ON e.game=g.id WHERE g.name=? AND NOT EXISTS "
                        "(SELECT 1 FROM game_entries other "
                        "WHERE other.key=e.key AND other.game<>e.game))",
                        (game,),
                    )
                    db.execute("DELETE FROM cache_games WHERE name=?", (game,))
                db.execute("UPDATE cache_changes SET revision=revision+1")
                self._memory.clear()
                self._pending = {}
                self._touched.clear()
                self.scope = None
            total = db.execute("SELECT rows FROM cache_size WHERE id=1").fetchone()[0]
            games = tuple(
                db.execute(
                    "SELECT g.name,COUNT(*) FROM cache_games g JOIN game_entries e "
                    "ON e.game=g.id GROUP BY g.id ORDER BY g.name COLLATE NOCASE,g.name"
                )
            )
        return CacheInventory(total, games)

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
