from pathlib import Path

import pytest
from archive_scout.discord_bot import parse_snowflakes, safe_project_dir


def test_parse_snowflakes() -> None:
    assert parse_snowflakes("123, 456") == frozenset({123, 456})
    assert parse_snowflakes("") == frozenset()
    with pytest.raises(ValueError):
        parse_snowflakes("123,nope")


def test_safe_project_dir_stays_inside_root(tmp_path: Path) -> None:
    assert safe_project_dir(tmp_path, "case-01") == tmp_path.resolve() / "case-01"
    for unsafe in ("../outside", "two/levels", "", "."):
        with pytest.raises(ValueError):
            safe_project_dir(tmp_path, unsafe)
