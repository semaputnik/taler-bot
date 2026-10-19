# Deploying taler-bot

The bot runs on a Linux server (x86_64 or arm64) with Docker. The image is built by GitHub Actions on a
green `main` and published to `ghcr.io/semaputnik/taler-bot` (tags `latest` and `sha-<short>`; a
release tag `vX.Y.Z` adds `vX.Y.Z` and `X.Y`).
The server only pulls it. The stack is `postgres`, `redis`, a one-shot `migrate` and `bot`
(`docker-compose.prod.yml`). Nothing is published on the server's network interfaces, and all
data lives in directories under one `DATA_DIR`.

## Prerequisites

- Docker with the compose plugin; the deploying user is in the `docker` group.
- The GHCR package `taler-bot` is public, so the server needs no registry login. A package
  created by CI is private at first: after the first successful `publish` job, set it once in
  GitHub (profile, Packages, `taler-bot`, Package settings, Danger Zone, Change visibility,
  Public) and check from a machine without a GHCR login: `docker pull ghcr.io/semaputnik/taler-bot:latest`.

## The two bot tokens

One Telegram token has one consumer: two processes polling with the same token break each
other. Therefore:

- **Production** keeps the current `@taler_money_bot` token. It goes into the server's `.env` and
  must be removed from the laptop's `.env` once the server runs.
- **Development** uses its own bot: create one with BotFather and put its token into the local
  `.env` (`BOT__TOKEN`).
- The Casa Receipts and Casa Mail tokens stay with n8n; never use them here.

## First install

```bash
sudo mkdir -p /srv/taler-bot/{postgres,redis,receipts}
sudo chown 1000:1000 /srv/taler-bot/receipts      # the container runs as uid 1000 (user `app`)
mkdir ~/taler-bot && cd ~/taler-bot
# copy docker-compose.prod.yml and .env.prod.template here (from the repository), then:
cp .env.prod.template .env
chmod 600 .env
```

Edit `.env`: set `BOT__TOKEN`, `LLM__API_KEY`, `POSTGRES_PASSWORD` (letters and digits only) and
`DATA_DIR` (an absolute path, `/srv/taler-bot` above). `TALER_TAG` is `latest` or a release
tag such as `v0.2.0`.

Compose reads this `.env` twice: to fill `${...}` in the compose file, and as the bot's
environment (`env_file`). Compose does **not** interpolate `${POSTGRES_PASSWORD}` inside
`env_file` values, so `docker-compose.prod.yml` builds `DATABASE__URL` itself in `environment:`
(together with `REDIS__URL` and `STORAGE__RECEIPTS_DIR`). Do not put those three in `.env`.

Check, then start:

```bash
docker compose -f docker-compose.prod.yml config > /dev/null    # fails on a missing variable
docker compose -f docker-compose.prod.yml up -d --wait
docker compose -f docker-compose.prod.yml logs migrate           # alembic ran, exit 0
```

To avoid typing `-f` every time, `export COMPOSE_FILE=docker-compose.prod.yml` or rename the file
to `docker-compose.yml` on the server; the commands below assume one of these.

The bot drops messages from users who are not allowed. Allow yourself by your numeric Telegram
user id. The first message from anyone creates their `users` row as not allowed, so send `/start`
first (no reply comes), then:

```bash
docker compose exec postgres psql -U taler -d taler \
  -c "UPDATE users SET is_allowed = true WHERE id = 123456789;"
```

`users.id` is the Telegram user id. If `UPDATE 0` is printed, the user has not sent anything yet.

## Deploy

```bash
docker compose pull && docker compose up -d
```

`migrate` runs `alembic upgrade head` first; if it fails the bot is not started, and the old bot
container keeps running until the new one replaces it.

## Roll back

Pin an older image in `.env` (`TALER_TAG=v0.2.0` or `TALER_TAG=sha-abc1234`; the tags are listed
on the GitHub package page) and run the same command. Migrations are not reversed automatically; a rollback across a
schema change needs `docker compose run --rm migrate alembic downgrade <revision>` first.

```bash
docker compose pull && docker compose up -d
```

## Logs and status

```bash
docker compose ps
docker compose logs -f bot
```

Set `LOG_LEVEL=DEBUG` in `.env` and run `docker compose up -d` to get debug output (no rebuild).

## Stop

`docker compose stop` sends SIGINT to the bot. It waits up to 10 s for receipts being read, marks
the rest for recovery at the next start, closes its clients and exits; the grace period is 30 s.

## Backup and restore

Everything is under `DATA_DIR`. Cold backup (a few seconds of downtime):

```bash
docker compose stop
sudo tar -C /srv -czf taler-bot-$(date +%F).tar.gz taler-bot
docker compose start
```

Online, database only:

```bash
docker compose exec -T postgres pg_dump -U taler taler | gzip > taler-$(date +%F).sql.gz
```

Restore a cold backup: `docker compose down`, replace the directory with the unpacked copy
(keep ownership: `receipts` is uid 1000), `docker compose up -d`. Restore a dump into an empty
database: `gunzip -c taler-DATE.sql.gz | docker compose exec -T postgres psql -U taler taler`.
Backups contain receipt photos and personal data; keep them off public storage.

## Import the n8n history

A one-off import of the Receipts Bot history (n8n data tables) for one user. The user must
already exist (send `/start` to the bot first); the import never creates or allows users.

1. Export the n8n tables as JSON into a directory on the server, for example `./import/`
   (git-ignored in the repository; it never enters git):

   ```
   import/
     receipt_payments.json   # a list of row objects with the n8n column names
     store_products.json
   ```

   The other n8n tables (`product_prices`, `receipt_issues`, `telegram_whitelist`) may be
   present; they are ignored.

   To bring the photos too, download the Google Drive folder `receipts` by hand and put its
   files into `import/photos/`, next to the JSON files (no sub-folders; the files keep their
   names, `receipt_<date>_<message id>.<ext>`). Each file is matched to its payment by the
   message id at the end of the name; the date in the name is ignored. Without `photos/` the
   import works as before.
2. Run it in the bot container, with the Telegram id of the user:

   ```bash
   docker compose run --rm -v ./import:/import bot python -m src.tools.import_n8n /import --user-id 41512748
   ```

3. Read the summary: counts of added and skipped payees, products, receipts and expenses, the
   number of photos stored (the bot container already mounts the receipts volume, so the
   command is the same), the photo files that were not imported (no payment has their message
   id, an unknown file type, or the payment was imported by an earlier run), then
   one line for every field where the port's receipt key, purchase time, payee key, total or
   status differs from the n8n columns (a column n8n left empty is not compared).

Rerunning is safe: a payment or product that was imported is skipped, so after a fresh export
only the new rows are added. The import stops at the first failing payment and names it; the
payments before it stay committed, so fix the cause and run it again. An unknown user id exits
with an error before anything is written. A photo file is stored together with its new receipt only, so a rerun
never stores a photo twice. The Drive id and link are always kept; a receipt without a file in
`photos/` has no stored photo, and its Photo button shows the "photo could not be loaded" notice.

## Building the image locally

```bash
docker build --build-arg REVISION=$(git rev-parse HEAD) -t taler-bot:dev .
docker run --rm taler-bot:dev ls -a /app      # .venv alembic alembic.ini src, nothing else
```
