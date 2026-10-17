# taler-bot

[![CI](https://github.com/semaputnik/taler-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/semaputnik/taler-bot/actions/workflows/ci.yml)

Telegram bot for household receipts: send a photo, get the items read, stored and summarised.

Development: see [CLAUDE.md](CLAUDE.md) (stack, commands, architecture).

## Deploy

The bot runs from a Docker image on a Linux server (`docker-compose.prod.yml`: Postgres, Redis,
a migration step and the bot; data in one directory):

```bash
cp .env.prod.template .env      # fill in the tokens, POSTGRES_PASSWORD and DATA_DIR
docker compose -f docker-compose.prod.yml up -d --wait
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d   # deploy
```

Install, rollback, backup and the bot tokens are in [docs/deploy.md](docs/deploy.md).
