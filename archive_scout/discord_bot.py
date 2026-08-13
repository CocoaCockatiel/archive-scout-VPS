from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from .config import KeywordSetConfig, ProjectConfig, save_project_config
from .events import ProgressEvent, Stopped
from .operations import SUPPORTED_MODES, run_project

LOG = logging.getLogger("archive_scout.discord")
PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
DISCORD_MODES = tuple(sorted(SUPPORTED_MODES - {"import_folder", "merge_project"}))


def parse_snowflakes(value: str | None) -> frozenset[int]:
    if not value:
        return frozenset()
    try:
        return frozenset(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("Discord ID lists must contain comma-separated numbers") from exc


def safe_project_dir(root: Path, name: str) -> Path:
    if not PROJECT_NAME_RE.fullmatch(name):
        raise ValueError("Project names may contain only letters, numbers, underscores, and hyphens")
    resolved_root = root.expanduser().resolve()
    candidate = (resolved_root / name).resolve()
    if candidate.parent != resolved_root:
        raise ValueError("Invalid project name")
    return candidate


def parse_targets(primary: str, additional: str = "") -> list[str]:
    values = [primary, *re.split(r"[;\n]+", additional)]
    targets = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    if not targets:
        raise ValueError("Provide at least one target")
    return targets


@dataclass(frozen=True, slots=True)
class BotSettings:
    token: str
    projects_root: Path
    guild_id: int | None
    allowed_user_ids: frozenset[int]
    allowed_role_ids: frozenset[int]
    max_upload_bytes: int
    max_concurrent_jobs: int

    @classmethod
    def from_environment(cls) -> BotSettings:
        token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("DISCORD_BOT_TOKEN is required")
        guild = os.environ.get("DISCORD_GUILD_ID", "").strip()
        root = Path(os.environ.get("ARCHIVE_SCOUT_PROJECTS_ROOT", "/data/projects"))
        upload_mb = max(1, int(os.environ.get("DISCORD_MAX_UPLOAD_MB", "8")))
        max_jobs = min(16, max(1, int(os.environ.get("ARCHIVE_SCOUT_MAX_CONCURRENT_JOBS", "3"))))
        return cls(
            token=token,
            projects_root=root.expanduser().resolve(),
            guild_id=int(guild) if guild else None,
            allowed_user_ids=parse_snowflakes(os.environ.get("DISCORD_ALLOWED_USER_IDS")),
            allowed_role_ids=parse_snowflakes(os.environ.get("DISCORD_ALLOWED_ROLE_IDS")),
            max_upload_bytes=upload_mb * 1024 * 1024,
            max_concurrent_jobs=max_jobs,
        )


@dataclass(slots=True)
class ActiveJob:
    project: str
    mode: str
    requester_id: int
    channel_id: int
    stop_event: threading.Event = field(default_factory=threading.Event)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    progress: str = "Starting"
    current: int | None = None
    total: int | None = None
    task: asyncio.Task[None] | None = None

    def summary(self) -> str:
        elapsed = datetime.now(UTC) - self.started_at
        progress = f" ({self.current:,}/{self.total:,})" if self.current is not None and self.total else ""
        return (
            f"**{self.project}** is running `{self.mode}` for {str(elapsed).split('.')[0]}.\n"
            f"{self.progress[:1500]}{progress}"
        )


class JobManager:
    def __init__(self, bot: ArchiveScoutBot) -> None:
        self.bot = bot
        self.active: dict[str, ActiveJob] = {}
        self._guard = asyncio.Lock()

    def running(self) -> list[ActiveJob]:
        return [job for job in self.active.values() if job.task and not job.task.done()]

    async def start(
        self,
        project: str,
        mode: str,
        requester_id: int,
        channel_id: int,
    ) -> tuple[bool, str]:
        async with self._guard:
            running = self.running()
            key = project.casefold()
            if key in self.active and self.active[key] in running:
                return False, f"**{project}** already has a running operation."
            if len(running) >= self.bot.settings.max_concurrent_jobs:
                names = ", ".join(f"`{job.project}`" for job in running)
                return False, (
                    f"The {self.bot.settings.max_concurrent_jobs}-job concurrency limit is full: "
                    f"{names}. Wait for one to finish or stop one."
                )
            project_file = safe_project_dir(self.bot.settings.projects_root, project) / "project.json"
            if not project_file.is_file():
                return False, f"Project `{project}` does not exist. Use `/scout create` first."
            if mode not in DISCORD_MODES:
                return False, "That operation is not available through Discord."
            job = ActiveJob(project, mode, requester_id, channel_id)
            self.active[key] = job
            job.task = asyncio.create_task(self._run(job, project_file), name=f"scout:{project}:{mode}")
            return True, (
                f"Started `{mode}` for **{project}** "
                f"({len(running) + 1}/{self.bot.settings.max_concurrent_jobs} slots in use). "
                "Use `/scout status` for progress."
            )

    async def _run(self, job: ActiveJob, project_file: Path) -> None:
        def progress(event: ProgressEvent) -> None:
            job.progress = event.message
            job.current = event.current
            job.total = event.total

        try:
            paths = await asyncio.to_thread(
                self._run_sync, project_file, job.mode, job.stop_event, progress
            )
            details = "\n".join(f"• `{name}`: `{Path(path).name}`" for name, path in paths.items())
            message = f"<@{job.requester_id}> **{job.project}** finished `{job.mode}`."
            if details:
                message += f"\n{details[:1500]}"
        except Stopped:
            message = f"<@{job.requester_id}> **{job.project}** stopped safely. Use `resume` to continue."
        except Exception as exc:  # the operation layer records the failure in SQLite
            LOG.exception("Archive Scout job failed")
            message = f"<@{job.requester_id}> **{job.project}** failed: `{type(exc).__name__}: {str(exc)[:1200]}`"
        try:
            await self.bot.send_job_message(job.channel_id, message)
        finally:
            async with self._guard:
                key = job.project.casefold()
                if self.active.get(key) is job:
                    self.active.pop(key, None)

    @staticmethod
    def _run_sync(project_file: Path, mode: str, stop_event: threading.Event, callback) -> dict:
        from .config import load_project_config

        return run_project(load_project_config(project_file), mode, stop_event, callback)

    async def stop(self, project: str = "") -> tuple[bool, str]:
        async with self._guard:
            running = self.running()
            if not running:
                return False, "No Archive Scout jobs are running."
            if project:
                job = self.active.get(project.casefold())
                if not job or job not in running:
                    return False, f"Project `{project}` is not running."
            elif len(running) == 1:
                job = running[0]
            else:
                names = ", ".join(f"`{item.project}`" for item in running)
                return False, f"More than one job is running. Specify a project: {names}."
            job.stop_event.set()
            job.progress = "Stop requested; waiting for the current network request to finish"
            return True, f"Stop requested for **{job.project}**. Saved work will remain resumable."


class ScoutCog(commands.Cog):
    scout = app_commands.Group(name="scout", description="Run Archive Scout projects")

    def __init__(self, bot: ArchiveScoutBot) -> None:
        self.bot = bot

    async def authorized(self, interaction: discord.Interaction) -> bool:
        settings = self.bot.settings
        if settings.guild_id and interaction.guild_id != settings.guild_id:
            await interaction.response.send_message("This bot is not enabled in this server.", ephemeral=True)
            return False
        if interaction.user.id in settings.allowed_user_ids:
            return True
        role_ids = {role.id for role in getattr(interaction.user, "roles", [])}
        if role_ids & settings.allowed_role_ids:
            return True
        if not settings.allowed_user_ids and not settings.allowed_role_ids:
            permissions = getattr(interaction.user, "guild_permissions", None)
            if permissions and permissions.administrator:
                return True
        await interaction.response.send_message("You are not allowed to run Archive Scout.", ephemeral=True)
        return False

    @scout.command(name="create", description="Create a new Archive Scout project")
    @app_commands.describe(
        name="Short project name",
        target="Site, URL prefix, or exact URL to search",
        keywords="Comma-separated search terms",
        additional_targets="Optional extra targets separated by semicolons",
        from_date="Beginning archive date or year, for example 2001",
        to_date="Ending archive date or year, for example 2004",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        target: str,
        keywords: str,
        additional_targets: str = "",
        from_date: str = "2000",
        to_date: str = "",
    ) -> None:
        if not await self.authorized(interaction):
            return
        try:
            project_dir = safe_project_dir(self.bot.settings.projects_root, name)
            project_file = project_dir / "project.json"
            if project_file.exists():
                await interaction.response.send_message(f"Project `{name}` already exists.", ephemeral=True)
                return
            rules = [item.strip() for item in keywords.split(",") if item.strip()]
            if not rules:
                raise ValueError("Provide at least one keyword")
            targets = parse_targets(target, additional_targets)
            config = ProjectConfig(
                output_dir=project_dir,
                targets=targets,
                keywords=rules,
                keyword_sets=[KeywordSetConfig("Discord keywords", rules)],
                from_date=from_date,
                to_date=to_date,
            ).normalized()
            project_dir.mkdir(parents=True, exist_ok=False)
            save_project_config(config)
        except (OSError, ValueError) as exc:
            await interaction.response.send_message(f"Could not create project: `{exc}`", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Created **{name}** with {len(targets)} target(s) and {len(rules)} keyword(s).",
            ephemeral=True,
        )

    @scout.command(name="projects", description="List available projects")
    async def projects(self, interaction: discord.Interaction) -> None:
        if not await self.authorized(interaction):
            return
        root = self.bot.settings.projects_root
        names = sorted(path.parent.name for path in root.glob("*/project.json")) if root.exists() else []
        text = "\n".join(f"• `{name}`" for name in names[:50]) or "No projects yet."
        await interaction.response.send_message(text, ephemeral=True)

    @scout.command(name="run", description="Start or resume a project operation")
    @app_commands.describe(project="Project name", mode="Archive Scout operation")
    async def run(self, interaction: discord.Interaction, project: str, mode: str = "all") -> None:
        if not await self.authorized(interaction):
            return
        if not interaction.channel_id:
            await interaction.response.send_message("Run this command in a server channel.", ephemeral=True)
            return
        ok, message = await self.bot.jobs.start(project, mode, interaction.user.id, interaction.channel_id)
        await interaction.response.send_message(message, ephemeral=not ok)

    @run.autocomplete("mode")
    async def mode_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=mode, value=mode)
            for mode in DISCORD_MODES
            if current.casefold() in mode.casefold()
        ][:25]

    @scout.command(name="status", description="Show running jobs and their latest progress")
    async def status(self, interaction: discord.Interaction, project: str = "") -> None:
        if not await self.authorized(interaction):
            return
        running = self.bot.jobs.running()
        if project:
            job = self.bot.jobs.active.get(project.casefold())
            message = (
                job.summary()
                if job and job in running
                else f"Project `{project}` is not currently running."
            )
        elif running:
            summaries = [job.summary() for job in running]
            message = (
                f"Running {len(running)}/{self.bot.settings.max_concurrent_jobs} jobs:\n\n"
                + "\n\n".join(summaries)
            )[:1900]
        else:
            message = "No Archive Scout jobs are running."
        await interaction.response.send_message(message, ephemeral=True)

    @scout.command(name="stop", description="Safely stop a running project")
    async def stop(self, interaction: discord.Interaction, project: str = "") -> None:
        if not await self.authorized(interaction):
            return
        _, message = await self.bot.jobs.stop(project)
        await interaction.response.send_message(message, ephemeral=True)

    @scout.command(name="reports", description="List generated report files for a project")
    async def reports(self, interaction: discord.Interaction, project: str) -> None:
        if not await self.authorized(interaction):
            return
        try:
            folder = safe_project_dir(self.bot.settings.projects_root, project) / "reports"
            files = sorted(path for path in folder.rglob("*") if path.is_file())
            lines = [f"• `{path.relative_to(folder)}` ({path.stat().st_size / 1024:.1f} KiB)" for path in files[:40]]
            text = "\n".join(lines) or "No reports have been generated."
        except ValueError as exc:
            text = str(exc)
        await interaction.response.send_message(text[:1900], ephemeral=True)

    @scout.command(name="get-report", description="Upload one generated report to Discord")
    async def get_report(self, interaction: discord.Interaction, project: str, report: str) -> None:
        if not await self.authorized(interaction):
            return
        try:
            reports_dir = (safe_project_dir(self.bot.settings.projects_root, project) / "reports").resolve()
            path = (reports_dir / report).resolve()
            if reports_dir not in path.parents or not path.is_file():
                raise ValueError("Report not found")
            if path.stat().st_size > self.bot.settings.max_upload_bytes:
                raise ValueError("Report is too large for the configured Discord upload limit")
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(file=discord.File(path), ephemeral=True)


class ArchiveScoutBot(commands.Bot):
    def __init__(self, settings: BotSettings) -> None:
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.none())
        self.settings = settings
        self.jobs = JobManager(self)

    async def setup_hook(self) -> None:
        self.settings.projects_root.mkdir(parents=True, exist_ok=True)
        await self.add_cog(ScoutCog(self))
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        LOG.info("Synced %d application commands", len(synced))

    async def on_ready(self) -> None:
        LOG.info("Connected to Discord as %s", self.user)

    async def send_job_message(self, channel_id: int, message: str) -> None:
        try:
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            await channel.send(
                message,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=True, replied_user=False
                ),
            )
        except Exception:
            LOG.exception("Could not send job completion message to channel %s", channel_id)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = BotSettings.from_environment()
    ArchiveScoutBot(settings).run(settings.token, log_handler=None)


if __name__ == "__main__":
    main()
