# taler-bot

Telegram bot for household receipts. It replaces the **Receipts Bot** workflow in n8n
(workflow id `macYuhowbTG2gdRo`) and adds more features. The first goal is parity with
that workflow. New features come after.

**Planned features, dialogs and the multi-photo design are in [docs/features.md](docs/features.md).**
Read it before working on any user-facing flow. Key decisions:
- All data is scoped by the Telegram user (`user_id` on every table). There is no
  shared or household view yet.
- The UI is in English. All user-facing text goes through fluentogram (`.ftl` files).
- A repeat photo of a known receipt **refines** that receipt (all photos are re-parsed
  together and the result is applied at once, with undo). It is no longer trashed as a
  duplicate. This intentionally differs from n8n step 7 below.

## Stack

| concern | choice |
|---|---|
| runtime | Python 3.14, managed with **uv** (`uv run`, `uv add`). No build backend: the code is the `src` package, run with `python -m src` |
| Telegram | **aiogram 3**, using **long polling** (no webhook) |
| bot UI (menus, multi-step flows) | **aiogram-dialog** |
| database | **PostgreSQL**, accessed through **SQLAlchemy 2 async** + **asyncpg**. Migrations use **Alembic** |
| models / validation | **pydantic v2** |
| config | **pydantic-settings**: nested models, `env_nested_delimiter="__"` |
| i18n / texts | **fluentogram**, `.ftl` files, `en` locale |
| LLM | **pydantic-ai** (`pydantic-ai-slim[openai]`), OpenAI, the same model as n8n (`gpt-6-luna`). The model name is a setting |
| receipt photos | files on the server, in a mounted volume (not Google Drive) |
| dialog / FSM state | **Redis** (`RedisStorage` with `DefaultKeyBuilder(with_destiny=True)`, required by aiogram-dialog) |
| deploy | **docker compose**: `bot` + `postgres` + `redis`, plus volumes for photos, the DB and Redis |
| dev tools | pytest, pytest-asyncio, ruff |

Add a new dependency only after asking the user. Record each decision here.

> **Status:** the code written so far (`src/taler_bot/`, `migrations/`) still uses the
> old layout and is waiting to be moved into the structure below. Don't add new code
> to the old layout.

```bash
cp src/config/envs/.env.template src/config/envs/.env   # fill in the bot token and the OpenAI key
docker compose up -d --wait     # postgres on localhost:5447, redis on localhost:6390
uv sync
uv run alembic upgrade head
uv run python -m src
uv run pytest                   # creates and migrates its own <db>_test database
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "..."   # then review it, see Database
uv run alembic check
```

## Architecture

The layout follows the user's earlier project `~/Documents/Projects/paper-work-bot`,
including the layered DB design that its CLAUDE.MD describes.

```
src/
  __main__.py              # App(settings).run()
  exception.py             # AppException → DatabaseException, IntegrationException, …
  config/                  # settings.py (root Settings) + database.py, redis.py, llm.py,
                           # storage.py (nested models); envs/.env.template, envs/.env
  bot/                     # everything that knows about aiogram
    app.py                 # App: Bot, Dispatcher, RedisStorage, TranslatorHub, usecases, lifespan
    middlewares/           # access (users.is_allowed), i18n, usecases injection
    handlers/
      command/             # one module per command, each exposes register_xxx(dp)
      message/photo.py     # photo intake, works in any state
      dialog/<name>/       # one folder per aiogram-dialog dialog (see Dialogs)
    states/                # StatesGroup classes
    locales/en/LC_MESSAGES/  # button.ftl, view.ftl, error.ftl
  database/
    models/                # SQLAlchemy ORM; never leaves database/
    dto/                   # pydantic DTOs: the only thing repositories return
    interfaces/            # Protocols for repositories and the UoW (typing)
    repositories/          # SQLAlchemy implementations
    uow/                   # SqlAlchemyUnitOfWork
  usecases/                # one class per user action, no aiogram imports
    user/  receipt/
  domain/                  # pure business rules, no I/O
    enums.py
    normalize/             # port of n8n "Normalize Receipt"; also diff, edit overlay, near-match
  integration/             # adapters to external systems, behind interfaces
    llm/                   # ReceiptParser: pydantic-ai agent, schema models, prompt
    storage/               # PhotoStorage: RECEIPTS_DIR, atomic writes, .trash
alembic/                   # migrations (alembic.ini at the repo root)
tests/
```

### Layers and dependencies

`bot → usecases → (domain, database via UoW, integration)`. Nothing imports `bot`, and
`domain` imports nothing from the other layers.

- **domain**: functions and value objects with no DB, network or filesystem access.
  Normalization takes the raw LLM output plus context (message time, the user's known
  products and cards) and returns a normalized receipt and issues. Test it with real
  receipt JSON fixtures.
- **integration**: one package per external system. It maps external errors to
  `IntegrationException` subclasses. Usecases depend on its interfaces, so tests can stub
  the LLM.
- **database**:
  - Use `async with uow:` to get repositories (`uow.receipts`, `uow.stores`,
    `uow.products`, …).
  - Commit only explicitly with `await uow.commit()`. Leaving the block without a
    commit rolls back.
  - Repositories never commit, and they return DTOs, never ORM objects.
- **usecases**: a class per action (`SaveReceiptPhoto`, `ParseReceipt`, `RefineReceipt`,
  `UndoRefinement`, `EditItem`, `ResolveIssue`, `ListReceipts`, `EnsureUser`, …).
  - Dependencies (UoW factory, `ReceiptParser`, `PhotoStorage`) come in through
    `__init__`.
  - It is called as `await usecase(input_dto) -> result_dto`.
  - The bot passes in plain data (photo bytes, ids), never aiogram objects.
- **bot**:
  - Handlers and getters only call usecases and render the results through i18n.
  - `App` builds the usecases once, and a middleware puts them into handler data, so
    getters receive them as arguments. There is no DI library.
- **Business logic services** (a `services/` package) were considered and postponed. Use
  `domain` + `usecases` for now.

### Code rules

- **Never hold a DB transaction across an LLM call** (up to 120 s). Photo intake is two
  usecases:
  1. `SaveReceiptPhoto` saves the file and a `pending` row, commits, and the bot replies
     "✅ Saved, reading…";
  2. `ParseReceipt` runs as a background task (`asyncio.create_task`, with a reference
     kept and errors logged). It calls the LLM with no transaction open, then writes the
     result in a new UoW and sends the summary.
- Everything is async. Never block the event loop: no `time.sleep` (use `asyncio.sleep`),
  and file I/O goes through `asyncio.to_thread`.
- Getters must not query in a loop (N+1). Load what a window needs in one repository
  call.
- Config, not code: no whitelist ids or tokens in source. Access is `users.is_allowed`
  in the DB.
- Long-lived clients (the LLM agent, the HTTP sessions, `PhotoStorage`) are created once
  in `App` and closed in its lifespan, never per update.
- The pydantic-ai agent uses `output_type` = a pydantic model that mirrors
  `docs/n8n-reference/receipt_schema.json`. Images go in as `BinaryContent`. The system
  prompt is ported verbatim from `docs/n8n-reference/system_prompt.md`.

### Dialogs (aiogram-dialog)

As in paper-work-bot, each dialog is a folder in `bot/handlers/dialog/<name>/`:

| file | contents |
|---|---|
| `dialog.py` | `Dialog(Window(...), ...)`, `on_start` |
| `getters.py` | window data; calls usecases |
| `click_event.py` | button and input handlers |
| `common.py` | key constants: `DialogDataKeys` (dialog_data), `PreviewDataKeys` (getter output) |
| `model.py` | pydantic preview models for `Select`/`ScrollingGroup` items |

Keys passed between dialogs through `start_data` live in one shared `TransferKeys`
class. State groups live in `bot/states/`. Every text comes from `.ftl`, and there are
no string literals in windows.

### Tests

- Repositories and usecases are tested against a real Postgres (a separate `<db>_test`
  database, each test rolled back). There is no fake UoW: it would double the code and
  could not check SQL constraints.
- The LLM is stubbed behind the `ReceiptParser` interface. `domain` is tested with JSON
  fixtures.

### Database

Models: `src/database/models/`. Enums: `src/domain/enums.py`. The design
rationale is in `docs/features.md` (multi-photo).

- A `receipts` row is one **receipt**, not one photo. Each new photo first gets its own
  receipt (`pending`) and is parsed alone. Then one of three things happens:
  - it matches a known receipt, so its photo and parse move there, it becomes `merged`
    (with `merged_into_id`), and the target is re-parsed from all photos;
  - it is a near match, so it becomes `awaiting_match` until the user answers;
  - otherwise it ends up `parsed`.
- Receipt header columns are the current parse (`current_parse_id`) with `receipt_edits`
  applied. `receipt_items` are rebuilt from `receipt_parses.normalized` whenever the
  current parse changes. Active issues are those of the current parse.
- Product name and category edits go to `store_products`, never to `receipt_edits`.
  A parse never overwrites `store_products` or `stores.name`.
- Deleting a receipt is soft (`deleted_at`). Every list, stats query and uniqueness check
  must filter `deleted_at IS NULL`.
- Money is `numeric(12,2)` and unit prices/quantities are `numeric(12,4)`, both `Decimal`
  in Python. Timestamps are `timestamptz`.
- Statuses and categories are `varchar` + `StrEnum` + `CHECK` (built with `enum_check`
  in `database/models/base.py`), not PG enums. When you add an enum value, write a migration that
  recreates the CHECK.
- `source_ref = 'n8n:<id>'` marks imported rows, so the import can be rerun.
- **Review every autogenerated migration.** Alembic silently drops `use_alter` FKs inside
  `create_table`; the `receipts.current_parse_id` FK had to be added by hand. Partial
  indexes and CHECKs must be checked too. Run `alembic check` and a down/up round trip.
- DB tests run against a real Postgres. Each test is rolled back (`tests/conftest.py`).
  Add a constraint test for every new constraint.

### Photo storage

- Root directory: the `RECEIPTS_DIR` setting, mounted as a docker volume.
- Layout: `RECEIPTS_DIR/yyyy/mm/receipt_<yyyy-MM-dd_HH-mm-ss>_<message_id>.<ext>`. The
  DB stores the path relative to `RECEIPTS_DIR`.
- Write to a temp file in the same directory, then rename it, so a crash never leaves a
  half-written photo.
- Never delete photos. A deleted receipt's photos move to `RECEIPTS_DIR/.trash/`.
  Repeat photos are kept and attached to their receipt (`receipt_photos`).

## What the n8n workflow does (the spec for parity)

Trigger: a Telegram `message` update to the **Casa Receipts bot**.

1. **Whitelist.** Look up `message.from.id` (as a string) in `telegram_whitelist.userId`.
   Unknown senders are dropped silently, with no reply.
2. **Extract file.** Use the largest `photo` (`photo[-1]`), or a `document` whose
   `mime_type` is `image/*`. If there is neither, reply "send me a photo of a receipt" and stop.
   File name: `receipt_<yyyy-MM-dd_HH-mm-ss in Europe/Madrid>_<message_id>.<ext>`.
3. **Save first.** Download the file from Telegram and upload it to the Google Drive folder
   `receipts`. Insert a `receipt_payments` row with
   `status=pending`. Reply "✅ Receipt saved: <link>. Reading the items…".
   The photo is stored even if parsing fails later.
   *taler-bot:* save to `RECEIPTS_DIR` instead (see Photo storage), with no link in the reply.
4. **Parse.** Send the image (detail `high`) to an OpenAI vision model (currently
   `gpt-6-luna`, 120 s timeout) with a strict JSON schema. The model returns: is_receipt,
   store, receipt, currency, items[], totals (with taxes[]), payment, loyalty, and issues[].
   - On an LLM error: `status=failed`, store `errorMessage`, reply "❌ Could not read…".
5. **Normalize** (the core logic, see `docs/n8n-reference/normalize_receipt.js`):
   - `storeKey` = slug of the store name with legal suffixes removed (S.A., S.L.U., LLC, ООО…).
     The fallback is `unknown-store`.
   - `purchasedAt` is parsed in `Europe/Madrid`. If it is missing or invalid, use the
     Telegram message time. If the date is more than 60 days before the message or more than
     1 day after it, treat it as a misread year: try the message's year, then the year before.
   - `receiptKey` (dedupe key) = `storeKey|RECEIPTNO|yyyy-MM-dd|total`. If there is no
     receipt number, it is `storeKey|yyyy-MM-ddTHH:mm|total`.
   - `productKey` = `storeKey::slug(name_raw)`. If `name_raw` starts with the line's quantity
     ("2 AIGUA…"), drop that prefix. The printed POS text is stable; the LLM's
     `name_normalized` is not, so it is never part of the key.
   - Unit aliases map to `pcs|kg|g|l|ml` (ud, шт, кг, lt…). `unitPrice` falls back to the
     reference price, then to `lineTotal / quantity`.
   - Workflow sanity checks become issues with `source=workflow`: missing store, total or
     currency; card digits that are not 4 digits; a card ending never seen in past parsed
     payments; no items; line math off by more than 0.02; lines not adding up to the total.
   - Model issues with `source=model` are kept, except name notes
     (`unknown_abbreviation`/`ambiguous` on `items.name*`) for products already in
     `store_products`.
   - Discounts: if `discount_total` just repeats the sum of line discounts, drop it. Stored
     values satisfy `subtotal − discountTotal = total`, where `subtotal` is before any discount.
   - Card numbers: keep only the last 4 digits, ever.
6. **Not a receipt.** Set `status=not_receipt` and reply 🤔. The file stays in Drive.
7. **Duplicate.** Another `parsed` payment with the same `receiptKey` →
   `status=duplicate`, reply ♻️, and move the Drive photo to the trash (not a permanent delete).
8. **Store.** Update the payment row (`status=storing`, then `parsed`), then:
   - insert new `store_products` rows. These are unique by `productKey` and **never
     overwritten**: `productName`/`category` may have been edited by hand;
   - insert one `product_prices` row per line (`productId` → store_products.id,
     `paymentId` → receipt_payments.id);
   - insert one `receipt_issues` row per issue;
   - reply with a summary (HTML): store, date `dd.MM.yyyy HH:mm`, total, payment
     (`card VISA •1234`), item count, and up to 5 issues.

All replies are threaded (`reply_to_message_id`). Failures to send a Telegram reply are
retried and must not break the pipeline.

### n8n data tables (source for the import)

| table | purpose | taler-bot table |
|---|---|---|
| `telegram_whitelist` | `userId` (string), `name` | `users.is_allowed` |
| `receipt_payments` | one row per photo. Status: `pending → storing → parsed`, or `failed` / `not_receipt` / `duplicate`. Holds `rawJson`, `model`, `parserVersion`, Drive ids | `receipts` + `receipt_parses` + `receipt_photos` |
| `store_products` | catalogue per store, keyed by `productKey` | `store_products` (+ `stores`) |
| `product_prices` | price history, one row per receipt line | `receipt_items` |
| `receipt_issues` | model and workflow notes, used to improve the prompt | `receipt_issues` |

Category enum: produce, meat, fish, dairy, bakery, drinks, alcohol, snacks, frozen,
pantry, household, personal_care, baby, pet, other.

### Reference files

`docs/n8n-reference/` is a verbatim snapshot of the workflow taken on 2026-10-16:
`system_prompt.md`, `receipt_schema.json` and `normalize_receipt.js`. Port the behaviour
from these files, not from memory. If the n8n workflow changes, refresh the snapshot
through the n8n MCP server (`get_workflow_details`).

## Domain rules

- **Everything in the repository is in English**: code, identifiers, comments,
  docstrings, docs, commit messages, migration names and `.ftl` texts. The only exception
  is data literals that must match what receipts print (for example the unit aliases
  `шт`/`кг` or the legal suffixes `ООО`/`ИП`). The conversation with the user may be in
  Russian, but nothing from it is copied into files untranslated.
- **Bump `PARSER_VERSION`** (n8n is at `2026-10-15.1`) whenever the prompt, schema, model
  or normalization changes. Store it on every `receipt_parses` row.
- Timezone is `Europe/Madrid`. Default currency is `EUR`.
- Money: round to 2 decimals for comparisons and use a 0.02 tolerance. Keep 4 decimals
  for unit prices.
- Never log or store full card numbers, tokens or API keys. Secrets come from env / `.env`
  (git-ignored) through pydantic-settings. Keep `src/config/envs/.env.template` up to date.
- One Telegram bot token has one webhook. Do not reuse the Casa Receipts or Casa Mail bot
  tokens while the n8n workflows are active. Use a separate dev bot.
- Normalization should be pure functions with unit tests that use real receipt JSON
  fixtures (`rawJson` from `receipt_payments`).

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues of `semaputnik/taler-bot` (public), managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root, created lazily. See `docs/agents/domain.md`.
