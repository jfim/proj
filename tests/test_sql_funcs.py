import time

import pytest

from proj.sql_funcs import ago, gb, kb, mb


def test_kb():
    assert kb(1) == 1024
    assert kb(2) == 2048


def test_mb():
    assert mb(1) == 1024 * 1024


def test_gb():
    assert gb(1) == 1024 * 1024 * 1024


def test_ago_seconds():
    now = int(time.time())
    result = ago("60s", now=now)
    assert result == now - 60


def test_ago_minutes():
    now = 1_000_000
    assert ago("5m", now=now) == now - 5 * 60


def test_ago_hours():
    now = 1_000_000
    assert ago("3h", now=now) == now - 3 * 3600


def test_ago_days():
    now = 1_000_000
    assert ago("7d", now=now) == now - 7 * 86400


def test_ago_months():
    now = 1_000_000
    # 1 month = 30 days
    assert ago("2mo", now=now) == now - 2 * 30 * 86400


def test_ago_years():
    now = 1_000_000
    # 1 year = 365 days
    assert ago("1y", now=now) == now - 365 * 86400


def test_ago_invalid_format_raises():
    with pytest.raises(ValueError):
        ago("garbage")
