import sqlite3

from jp_overlay.translation_cache import TranslationCache, translation_key


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
