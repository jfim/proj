from pathlib import Path

import pytest

from proj.cache import Cache


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


def test_store_and_lookup_text(cache):
    cache.store("foo", "size", "k1", 12345)
    assert cache.lookup("foo", "size", "k1") == 12345


def test_lookup_miss_returns_none(cache):
    assert cache.lookup("foo", "size", "k1") is None


def test_different_keys_isolated(cache):
    cache.store("foo", "size", "k1", 1)
    cache.store("foo", "size", "k2", 2)
    assert cache.lookup("foo", "size", "k1") == 1
    assert cache.lookup("foo", "size", "k2") == 2


def test_store_overwrites_same_key(cache):
    cache.store("foo", "size", "k1", 1)
    cache.store("foo", "size", "k1", 2)
    assert cache.lookup("foo", "size", "k1") == 2


def test_store_none_value_is_lookup_miss(cache):
    cache.store("foo", "size", "k1", None)
    assert cache.lookup("foo", "size", "k1") is None


def test_preserves_types(cache):
    cache.store("p", "c", "k", 42)
    cache.store("p", "c2", "k", "hello")
    cache.store("p", "c3", "k", True)
    cache.store("p", "c4", "k", 3.14)
    assert cache.lookup("p", "c", "k") == 42
    assert cache.lookup("p", "c2", "k") == "hello"
    assert cache.lookup("p", "c3", "k") is True
    assert cache.lookup("p", "c4", "k") == 3.14


def test_persists_across_instances(tmp_path):
    db = tmp_path / "cache.db"
    c1 = Cache(db)
    c1.store("foo", "size", "k", 99)
    c2 = Cache(db)
    assert c2.lookup("foo", "size", "k") == 99


def test_command_hash_is_stable():
    assert Cache.command_hash("echo hi") == Cache.command_hash("echo hi")
    assert Cache.command_hash("a") != Cache.command_hash("b")
