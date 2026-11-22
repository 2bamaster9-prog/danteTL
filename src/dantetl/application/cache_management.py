"""On-demand cache inspection and deletion, each on its own SQLite connection."""

import sqlite3
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from dantetl.translation.cache import TranslationCache
from dantetl.translation.cache_values import CacheView


class CacheManagement:
    def __init__(self, path: Path, notify: Callable[[], None]) -> None:
        self._path, self._notify = path, notify
        self._lock = threading.Lock()
        self._view = CacheView()

    def snapshot(self) -> CacheView:
        with self._lock:
            return self._view

    def refresh(self) -> None:
        self._start(False, None)

    def clear(self, game: str | None) -> None:
        self._start(True, game)

    def _start(self, clear: bool, game: str | None) -> None:
        with self._lock:
            if self._view.busy:
                return
            self._view = replace(self._view, busy=True, error="")
        threading.Thread(target=self._run, args=(clear, game), name="cache-maintenance").start()

    def _run(self, clear: bool, game: str | None) -> None:
        try:
            cache = TranslationCache(self._path)
            try:
                view = CacheView(cache.inventory(clear=clear, game=game))
            finally:
                cache.close()
        except (sqlite3.Error, OSError) as error:
            view = CacheView(error=str(error))
        with self._lock:
            self._view = view
        self._notify()
