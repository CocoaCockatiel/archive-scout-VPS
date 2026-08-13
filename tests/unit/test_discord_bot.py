import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from archive_scout.discord_bot import JobManager, parse_snowflakes, parse_targets, safe_project_dir


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


def test_parse_multiple_targets() -> None:
    assert parse_targets("example.com/*", "www.example.com/*; forum.example.com/*\nexample.com/*") == [
        "example.com/*",
        "www.example.com/*",
        "forum.example.com/*",
    ]


def test_job_manager_allows_distinct_projects_up_to_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        for name in ("alpha", "beta", "gamma"):
            folder = tmp_path / name
            folder.mkdir()
            (folder / "project.json").write_text("{}", encoding="utf-8")

        bot = SimpleNamespace(
            settings=SimpleNamespace(projects_root=tmp_path, max_concurrent_jobs=2)
        )
        manager = JobManager(bot)
        release = asyncio.Event()

        async def hold_job(job, project_file) -> None:
            await release.wait()

        manager._run = hold_job
        first, _ = await manager.start("alpha", "all", 1, 10)
        second, _ = await manager.start("beta", "all", 1, 10)
        duplicate, duplicate_message = await manager.start("alpha", "resume", 1, 10)
        over_limit, limit_message = await manager.start("gamma", "all", 1, 10)

        assert first and second
        assert not duplicate and "already has" in duplicate_message
        assert not over_limit and "concurrency limit" in limit_message

        stopped, _ = await manager.stop("alpha")
        assert stopped
        assert manager.active["alpha"].stop_event.is_set()

        release.set()
        await asyncio.gather(*(job.task for job in manager.active.values() if job.task))

    asyncio.run(scenario())
