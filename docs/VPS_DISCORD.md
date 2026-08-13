# VPS and Discord deployment

This deployment runs one Archive Scout operation at a time. Project databases, downloaded
captures, and reports live in the Docker volume `archive-scout-data` and survive image rebuilds
and container restarts.
Interrupted Archive Scout queues remain resumable with `/scout run project:NAME mode:resume`.

## 1. Create the Discord application

1. Open the Discord Developer Portal and create an application.
2. Open **Bot**, create/reset the token, and copy it into `.env` on the VPS.
3. In **OAuth2 > URL Generator**, select `bot` and `applications.commands`.
4. Grant only **View Channels**, **Send Messages**, and **Attach Files** in the bot's channel.
5. Use the generated URL to install the bot in your server.
6. Enable Discord Developer Mode and copy the server, user, and/or operator-role IDs.

The bot does not need Message Content Intent or administrator permission.

## 2. Prepare an Ubuntu VPS

Install Docker Engine and its Compose plugin using Docker's instructions for your Ubuntu release.
Then clone your fork and create its private configuration:

```bash
git clone https://github.com/CocoaCockatiel/archive-scout-VPS.git
cd archive-scout-VPS
cp .env.example .env
nano .env
chmod 600 .env
```

Set `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, and either `DISCORD_ALLOWED_USER_IDS` or
`DISCORD_ALLOWED_ROLE_IDS`. Never commit `.env`.

## 3. Start it 24/7

```bash
docker compose up -d --build
docker compose logs -f archive-scout-bot
```

The Compose restart policy starts the bot again after a crash or VPS reboot, provided Docker is
enabled at boot. Verify that with `sudo systemctl enable --now docker`.

Updates are applied with:

```bash
git pull --ff-only
docker compose up -d --build
```

Back up the `archive-scout-data` Docker volume; it contains all durable project state and
downloaded material. For example:

```bash
docker compose exec -T archive-scout-bot tar -C /data -czf - projects > archive-scout-backup.tar.gz
```

## Commands

- `/scout create` creates a project with one target and comma-separated keyword rules.
- `/scout projects` lists available projects.
- `/scout run` starts an operation such as `all`, `resume`, `report`, or `integrity`.
- `/scout status` shows the latest progress event.
- `/scout stop` requests a safe stop after the current network operation.
- `/scout reports` lists generated report files.
- `/scout get-report` uploads a small report file to Discord.

Long jobs announce completion with a normal channel message rather than relying on the temporary
slash-command interaction token.

## Operational notes

- Run the bot in a private channel when project targets or results are sensitive.
- Archive Scout respects Wayback exclusions and rate limits; do not increase concurrency simply to
  work around archive restrictions.
- `import_folder` and `merge_project` are intentionally unavailable from Discord because they
  accept server filesystem paths. Run those from an authenticated VPS shell when needed.
- A container restart safely interrupts the current process, but it does not automatically restart
  the operation. Use the project's `resume` mode after the bot reconnects.
