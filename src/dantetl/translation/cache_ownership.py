"""Transactional ownership of cached translations and revocation of in-flight writes."""

import hashlib
import sqlite3
from dataclasses import dataclass

from dantetl.translation.cache_values import CacheInventory


@dataclass(frozen=True, slots=True)
class CacheScope:
    game: str
    revision: int


# Only explicit user clears enter this log. Older writes without a provable
# scope can still be displayed, but cannot repopulate persistent storage.
_CLEAR_HISTORY = 256


def _digest(game: str) -> bytes:
    return hashlib.sha256(game.encode("utf-8")).digest()


class CacheOwnership:
    """Every method participates in the caller's existing SQLite transaction."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        db.execute(
            "CREATE TABLE IF NOT EXISTS cache_games "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS game_entries "
            "(game INTEGER NOT NULL REFERENCES cache_games ON DELETE CASCADE, "
            "key TEXT NOT NULL REFERENCES translations ON DELETE CASCADE, "
            "PRIMARY KEY(game,key)) WITHOUT ROWID"
        )
        db.execute("CREATE INDEX IF NOT EXISTS entries_by_key ON game_entries(key)")
        db.execute("CREATE TABLE IF NOT EXISTS cache_changes (revision INTEGER NOT NULL)")
        db.execute(
            "INSERT INTO cache_changes SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM cache_changes)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS cache_clears (revision INTEGER PRIMARY KEY, game BLOB)"
        )
        db.execute(
            "CREATE TRIGGER IF NOT EXISTS retire_empty_game AFTER DELETE ON game_entries "
            "BEGIN DELETE FROM cache_games WHERE id=OLD.game AND NOT EXISTS "
            "(SELECT 1 FROM game_entries WHERE game=OLD.game); END"
        )
        if db.execute("PRAGMA user_version").fetchone()[0] == 1:
            db.execute(
                "DELETE FROM cache_games WHERE NOT EXISTS "
                "(SELECT 1 FROM game_entries WHERE game=cache_games.id)"
            )
            db.execute("PRAGMA user_version=2")

    def revision(self) -> int:
        return self.db.execute("SELECT revision FROM cache_changes").fetchone()[0]

    def permits(self, scope: CacheScope) -> bool:
        current = self.revision()
        if current == scope.revision:
            return True
        elapsed = current - scope.revision
        if elapsed > _CLEAR_HISTORY:
            return False
        # An older app sharing this database may have cleared entries without a
        # journal record. Only a complete history can authorize a late write.
        recorded, revoked = self.db.execute(
            "SELECT COUNT(*), MAX(game IS NULL OR game=?) FROM cache_clears WHERE revision>?",
            (_digest(scope.game), scope.revision),
        ).fetchone()
        return recorded == elapsed and not revoked

    def associate(self, game: str, keys: tuple[str, ...]) -> None:
        row = self.db.execute("SELECT id FROM cache_games WHERE name=?", (game,)).fetchone()
        if row is None:
            game_id = self.db.execute("INSERT INTO cache_games(name) VALUES (?)", (game,)).lastrowid
        else:
            game_id = row[0]
        self.db.executemany(
            "INSERT OR IGNORE INTO game_entries SELECT ?,key FROM translations WHERE key=?",
            ((game_id, key) for key in keys),
        )
        # A remembered memory hit may already have been evicted by another owner.
        self.db.execute(
            "DELETE FROM cache_games WHERE id=? AND NOT EXISTS "
            "(SELECT 1 FROM game_entries WHERE game=?)",
            (game_id, game_id),
        )

    def clear(self, game: str | None) -> None:
        if game is None:
            self.db.execute("DELETE FROM translations")
            self.db.execute("DELETE FROM cache_games")
            self.db.execute("DELETE FROM cache_clears")
        else:
            self.db.execute(
                "DELETE FROM translations WHERE key IN (SELECT e.key FROM game_entries e "
                "JOIN cache_games g ON e.game=g.id WHERE g.name=? AND NOT EXISTS "
                "(SELECT 1 FROM game_entries other WHERE other.key=e.key AND other.game<>e.game))",
                (game,),
            )
            self.db.execute("DELETE FROM cache_games WHERE name=?", (game,))
        self.db.execute("UPDATE cache_changes SET revision=revision+1")
        revision = self.revision()
        self.db.execute(
            "INSERT INTO cache_clears VALUES (?,?)",
            (revision, _digest(game) if game is not None else None),
        )
        self.db.execute("DELETE FROM cache_clears WHERE revision<=?", (revision - _CLEAR_HISTORY,))

    def inventory(self) -> CacheInventory:
        total = self.db.execute("SELECT rows FROM cache_size WHERE id=1").fetchone()[0]
        games = tuple(
            self.db.execute(
                "SELECT g.name,COUNT(*) FROM cache_games g JOIN game_entries e "
                "ON e.game=g.id GROUP BY g.id ORDER BY g.name COLLATE NOCASE,g.name"
            )
        )
        return CacheInventory(total, games)
