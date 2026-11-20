import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

from dantetl.translation.cache import TranslationCache, translation_key


def test_cache_key_separates_backend_settings_and_exact_source() -> None:
    assert translation_key("v1", "猫") != translation_key("v2", "猫")
    assert translation_key("v1", "猫") != translation_key("v1", "犬")
    assert translation_key("v1:beam2", "猫") != translation_key("v1:beam5", "猫")


def test_memory_and_sqlite_limits_and_persistence(tmp_path) -> None:
    path = tmp_path / "cache.sqlite3"
    cache = TranslationCache(path, memory_limit=2, disk_limit=3)
    for index in range(10):
        cache.put(str(index), f"Translation {index}")
    assert len(cache._memory) == 2
    cache.close()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM translations").fetchone()[0] == 3
    restored = TranslationCache(path)
    assert restored.get("9") == "Translation 9"
    assert restored.get("0") is None
    restored.close()


def test_corrupt_disk_cache_keeps_translation_usable_without_deleting_user_file(tmp_path) -> None:
    path = tmp_path / "bad.sqlite3"
    path.write_bytes(b"not a database")
    cache = TranslationCache(path)
    assert cache.warning
    cache.put("key", "English")
    assert cache.get("key") == "English"
    cache.close()
    assert path.read_bytes() == b"not a database"


def test_memory_hits_update_disk_recency_before_eviction_and_close(tmp_path):
    path = tmp_path / "cache.sqlite3"
    cache = TranslationCache(path, disk_limit=2)
    cache.put("hot", "Often read")
    cache.put("cold", "Never read")
    assert cache.get("hot") == "Often read"
    cache.put("new", "New result")
    cache.close()
    reopened = TranslationCache(path, disk_limit=2)
    assert reopened.get("hot") == "Often read"
    assert reopened.get("cold") is None
    reopened.close()
    # The read immediately before close must also survive a later owner's write.
    writer = TranslationCache(path, disk_limit=2)
    writer.put("next", "Next result")
    writer.close()
    reopened = TranslationCache(path, disk_limit=2)
    assert reopened.get("hot") == "Often read" and reopened.get("new") is None
    reopened.close()


def test_two_owners_account_for_updates_and_evictions_in_one_transaction(tmp_path):
    path = tmp_path / "cache.sqlite3"
    first = TranslationCache(path, disk_limit=3)
    second = TranslationCache(path, disk_limit=3)
    try:
        for index in range(30):
            owner = first if index % 2 else second
            owner.put(str(index), f"English {index}")
            owner.put(str(index), f"English {index} updated")
            with sqlite3.connect(path) as db:
                assert db.execute("SELECT COUNT(*) FROM translations").fetchone()[0] == min(
                    index + 1, 3
                )
        assert first.get("29") == "English 29 updated"
        assert second.get("28") == "English 28 updated"
    finally:
        first.close()
        second.close()


def test_concurrent_owner_writes_keep_capacity_and_latest_values(tmp_path):
    path = tmp_path / "shared.sqlite3"
    ready = threading.Barrier(2)

    def write(lane):
        cache = TranslationCache(path, disk_limit=12)
        try:
            ready.wait(timeout=5)
            for index in range(50):
                cache.put(f"{lane}/{index}", f"{lane} English {index}")
                cache.put(f"{lane}/{index}", f"{lane} revised {index}")
                with sqlite3.connect(path) as db:
                    assert db.execute("SELECT COUNT(*) FROM translations").fetchone()[0] <= 12
            assert not cache.warning
        finally:
            cache.close()

    with ThreadPoolExecutor(max_workers=2) as owners:
        list(owners.map(write, ("short", "long")))
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT key, english FROM translations").fetchall()
    assert len(rows) == 12
    assert all(
        english == f"{key.split('/')[0]} revised {key.split('/')[1]}" for key, english in rows
    )
