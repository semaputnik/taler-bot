# taler-bot

Telegram bot for household receipts. It replaces the **Receipts Bot** workflow in n8n
(workflow id `macYuhowbTG2gdRo`) and adds more features. The first goal is parity with
that workflow. New features come after.

**Planned features and dialogs are in [docs/features.md](docs/features.md).**
Read it before working on any user-facing flow. Key decisions:
- All data is scoped by the Telegram user (`user_id` on every table). There is no
  shared or household view yet.
- The UI is in English. All user-facing text goes through fluentogram (`.ftl` files).
- **One receipt has one photo and one parse** (ADR-0002). A bad reading is fixed by
  deleting the receipt and sending a new photo, or by editing values by hand. The same
  photo sent twice is refused without an LLM call; the same receipt photographed twice
  is marked `duplicate`, like n8n step 7 below.

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

`fluentogram` was added with the user's agreement (issue #4).
Add a new dependency only after asking the user. Record each decision here.

```bash
cp .env.template .env           # fill in BOT__TOKEN and LLM__API_KEY
docker compose up -d --wait     # postgres on localhost:5447, redis on localhost:6390
uv sync
uv run alembic upgrade head
uv run python -m src
uv run pytest                   # needs only the dev Postgres; no env file (see Tests); skips the `llm` test
LLM__API_KEY=... uv run pytest -m llm   # the live model test: needs the key exported and tests/fixtures/images/receipt.jpg
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "..."   # then review it, see Database
uv run alembic check
```

## Architecture

The layout follows the user's earlier project `~/Documents/Projects/paper-work-bot`,
including the layered DB design that its CLAUDE.MD describes.

**The reference for every architecture discussion is Percival & Gregory, *Architecture
Patterns with Python* (free at https://www.cosmicpython.com/book/).** Before proposing a
structural change, check what the book says (domain model ch. 1, repository ch. 2, service
layer ch. 4, Unit of Work ch. 6, aggregates ch. 7) and cite it. Decisions already taken are
in `docs/adr/`; the project vocabulary is in `GLOSSARY.md`. Use those terms in code names.

```
src/
  __main__.py              # App(settings).run()
  exception.py             # AppException → DatabaseException, DomainException, IntegrationException, …
  config/                  # settings.py (root Settings) + bot.py, database.py, redis.py,
                           # llm.py, storage.py (nested models); standalone DatabaseSettings for Alembic
  bot/                     # everything that knows about aiogram
    app.py                 # App: Bot, Dispatcher, RedisStorage, TranslatorHub, Services, lifespan
    dispatcher.py          # create_dispatcher: middlewares + handlers
    tasks.py               # TaskRegistry: spawn (reference kept, errors logged), shutdown, drain (tests)
    middlewares/           # services and tasks injection, access (ensures the user, drops strangers), i18n
    handlers/
      command/             # one module per command (only /start so far), each exposes register_xxx(dp)
      callback/            # taps on the card's plain buttons: receipt.py edits the current card in place or sends a fresh one
      message/photo.py     # photo intake: save, reply "Saved", parse in the background, then start the card; catch-all "send me a photo"
      dialog/              # common.py (TransferKeys), widgets.py (I18nText), media.py (StoredPhoto + its message manager), one folder per dialog
        receipt_card/      # dialog.py, getters.py, click_event.py, common.py, model.py, values.py (parses a typed issue value), keyboard.py (CardKeyboard: the card's plain buttons) (main, items, item, photo, delete_confirm, issue, issue_input, review_done)
    keyboards/receipt.py   # the card's inline keyboard, ReceiptCallback (prefix "receipt")
    render.py              # receipt texts (currency sign, header) used by the card
    states/                # StatesGroup classes (receipt_card.py: ReceiptCardSG)
    locales/en/LC_MESSAGES/  # button.ftl, view.ftl, error.ftl
  database/
    engine.py              # create_engine / create_sessionmaker; install_error_translation
    errors.py              # SQLSTATE → app exception mapping
    models/                # SQLAlchemy ORM; never leaves database/
    dto/                   # UserDTO / NewUserDTO (the user repository's plain-data types)
    interfaces/            # Protocols for the UoW and the three repositories (typing)
    repositories/          # one per aggregate: ReceiptRepository, CatalogRepository, UserRepository
    mapping/               # ORM rows ↔ domain aggregates (the only place both are known)
    uow/                   # SqlAlchemyUnitOfWork
  services/                # application services: one class per entity, action methods
    container.py           # Services (users, receipts): built once by App
    user.py                # UserService.ensure, .allow
    receipt.py             # ReceiptService: save_photo, parse, edit_item, edit_header, resolve_issue, review, correct_issue, soft_delete, card, items, photo, photo_bytes
    results.py             # CurrentUser, NewPhoto, ReceiptCard, IssueCard, ParseResult: the services' own pydantic types
  integration/
    llm/                   # ReceiptParser (Protocol), ParserOutput, LLMError, OpenAIReceiptParser (pydantic-ai), RawParse
    storage/               # PhotoStorage (Protocol), LocalPhotoStorage, StorageError
  domain/                  # the model: aggregates with behaviour, value objects
    enums.py
    receipt.py             # Receipt aggregate (+ Photo, Item, Issue, Header inside it)
    parse.py               # Parse, ParsedItem, ParsedIssue, ParseOutcome (value objects)
    edits.py               # Edit, the editable fields, ISSUE_FIELDS (issue field -> editable field)
    catalog.py             # Catalog aggregate: Store, Product
alembic/                   # migrations (alembic.ini at the repo root)
.env.template, .env        # settings template (committed) and local values (git-ignored)
tests/                     # domain/ database/ services/ bot/ + root conftest.py, helpers.py
```

Not built yet (each arrives with its feature): `domain/matching.py` (a domain service) and
the value entry of the issue review (`issue_input` is a placeholder) and the history dialog.

### Layers and dependencies

`bot → services → (domain, database via UoW, integration)`. Nothing imports `bot`, and
`domain` imports nothing from the other layers. See ADR-0001.

- **domain** is the model, not a utils bag. Rules live on the objects they protect:
  - **Aggregates** are classes with behaviour. `Receipt` owns its photo, parse, items,
    issues and edits; `receipt.apply_parse(parse)` sets or replaces the parse, rebuilds
    the header, items and issues, applies the edits and reports released products.
    `record_edit`, `mark_failed`, `soft_delete` keep the same invariants. Nothing outside the aggregate
    changes its parts. `Catalog` (stores and products) is a second aggregate: it outlives
    receipts and is edited by hand.
  - **Domain services** (planned) are the few stateless operations that fit no entity:
    `normalize` (raw LLM output → `Parse`, including the receipt key).
  - No DB, network or filesystem access. Tested with plain unit tests on the objects,
    and `normalize` with real receipt JSON fixtures.
- **integration**: one package per external system. It maps external errors to
  `IntegrationException` subclasses. Services depend on its interfaces, so tests can stub
  the LLM.
- **database**:
  - **One repository per aggregate**, never per table. `uow.receipts.get(id)` returns a
    whole `Receipt`; `uow.receipts.save(receipt)` writes every table it spans. The
    ORM ↔ aggregate mapping lives in `database/mapping/`.
  - Use `async with uow:` to get repositories (`uow.receipts`, `uow.catalog`, `uow.users`).
  - Commit only explicitly with `await uow.commit()`. Leaving the block without a
    commit rolls back.
  - Repositories never commit and never return ORM objects.
  - Read models for lists and stats (`ReceiptListRow`, …) are separate query methods
    that return pydantic models shaped for the screen, not aggregates.
- **services** are application services (one class per entity, action methods:
  `ReceiptService.save_photo`, `.edit_item`, `.soft_delete`; `UserService.ensure`). Every
  method takes the `user_id`, and another user's receipt counts as not found.
  - A method does: load the aggregate → call the LLM or storage outside any transaction
    → call **one** aggregate method → save → commit. It contains no receipt rules; if a
    rule is appearing in a service, move it to the aggregate.
  - Dependencies (the UoW factory and `PhotoStorage` now; `ReceiptParser` later) come in
    through `__init__`. The bot passes in plain data (`NewPhoto`, ids), never aiogram objects.
  - A write that sets or replaces the parse also applies the `ParseOutcome` to the catalog
    in the same transaction: new stores and products first (the receipt's store and items
    refer to them), the receipt, then the released products this receipt created.
  - Results are the service's own pydantic types (e.g. `CurrentUser`, `ReceiptCard`),
    so the bot never depends on `database` or `domain` internals.
- **bot**:
  - Handlers and getters only call services and render the results through i18n. `bot`
    never imports `domain`; it uses the services' result types.
  - Texts: call `i18n.get("receipt-saved", **vars)` with the `.ftl` key. The attribute form
    (`i18n.receipt.saved()`) cannot reach keys with more than one dash segment, and a failed
    lookup leaves the translator's chain polluted.
  - `App` owns one `TaskRegistry` (handler data key `tasks`, put there by `TasksMiddleware`);
    `lifespan` awaits pending parses for up to `TASK_SHUTDOWN_TIMEOUT`, cancels the rest, then
    closes the bot session. Handler order: commands, callbacks, the photo handler, the dialogs, then the
    catch-all "send me a photo". A dialog consumes every message sent while it is open, so photos must
    be handled before the dialogs and the catch-all after them.
  - `App` builds the services once (`Services` in `services/container.py`, handler data key `services`), and a
    middleware puts them into handler data, so getters receive them as arguments. There
    is no DI library.
  - `bot/app.py` is the composition root: the only module in `bot` that may import
    `database` (to wire the SQLAlchemy Unit of Work). `tests/test_layers.py` enforces
    this and the other import rules.

### Code rules

- **Never hold a DB transaction across an LLM call** (up to 120 s). Photo intake is two
  service calls:
  1. `ReceiptService.save_photo(user_id, data, photo)` saves the file and a `pending` receipt, commits, and the
     bot replies "✅ Saved, reading…";
  2. `ReceiptService.parse` runs as a background task (`asyncio.create_task`, with a reference
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
| `dialog.py` | `create_xxx_dialog()` returning `Dialog(Window(...), ...)` (a factory: a router attaches to one dispatcher only), `on_start` |
| `getters.py` | window data; calls services |
| `click_event.py` | button and input handlers |
| `common.py` | key constants: `DialogDataKeys` (dialog_data), `PreviewDataKeys` (getter output) |
| `model.py` | pydantic preview models for `Select`/`ScrollingGroup` items |

Keys passed between dialogs through `start_data` live in one shared `TransferKeys`
class. State groups live in `bot/states/`. Every text comes from `.ftl`, and there are
no string literals in windows.

The parse reply is the card: `_parse_and_reply` (photo handler) starts `ReceiptCardSG.main` with
`dialog_manager.bg()` and `StartMode.RESET_STACK, ShowMode.SEND` after the parse (or its failure),
and the `main` window's text covers every outcome. Its buttons are `CardKeyboard`, a custom
`Keyboard` widget that renders plain `ReceiptCallback` buttons (no intent id, via
`PlainKeyboardFactory`). `callback/receipt.py` handles them before the dialogs, so they work on any
card, however old: a tap on the dialog's last message restarts the dialog with `ShowMode.EDIT`
(in place), a tap on an older card with `ShowMode.SEND` and leaves that card's keyboard alone
(`StoredPhotoMessageManager` skips aiogram-dialog's keyboard removal for those sends). **The card
never calls `done()`**: it would strip the buttons. Every exit goes `switch_to(ReceiptCardSG.main)`,
which is also where a deleted receipt ends. There is no Close button.

The issue review walk lives in `ReceiptCard`'s `dialog_data`: the ordered issue ids (`walk`), the
`position`, `current_issue_id` and the counters, loaded once by `click_event.start_review`.
`click_event.advance` moves on after any action that closes an issue; a skipped issue stays
reviewable (domain `reviewable_issues`), so Skip does not lower the `Review (n)` count.

A window that shows a stored receipt photo uses `DynamicMedia` with a `StoredPhoto` (by Telegram
file id). `StoredPhotoMessageManager`, passed to `setup_dialogs`, uploads the bytes only when Telegram
refuses the id, and shows a notice if the bytes are unreadable.

### Tests

- Layout: `tests/domain/` (aggregates, plain objects, no database), `tests/database/`
  (repositories and constraints through the aggregate repositories), `tests/services/`
  (services through the Unit of Work), `tests/integration/` (adapters, e.g. `LocalPhotoStorage` on a tmp dir), `tests/bot/` (the real dispatcher with a stubbed
  Telegram session), and root-level tests for settings, migrations, error translation, layers.
  `tests/conftest.py` has `make_uow`; `tests/helpers.py` seeds users, catalogs and receipts;
  `tests/domain/builders.py` builds `Parse` and `Photo` values.
- Repositories and services are tested against a real Postgres (a separate `<db>_test`
  database, each test rolled back). Tests never read the app's env file: the server is
  the dev Postgres by default, or `TEST_DATABASE_URL` (its database name is only a prefix
  for the scratch databases). There is no fake UoW: it would double the code and
  could not check SQL constraints.
- The LLM is stubbed behind the `ReceiptParser` interface (`StubReceiptParser` in `tests/stubs.py`).
  `domain` is tested with JSON fixtures. The one `llm`-marked test calls the real model; it reads
  `LLM__API_KEY` (and optionally `LLM__MODEL`) from the process environment only, never `.env`,
  and skips without a key or photo: `LLM__API_KEY=... uv run pytest -m llm`.

### Database

Every table is reached through the Unit of Work (`async with uow:`) and one repository per
aggregate (ADR-0001): `uow.receipts` (receipt + photo, parse, items, issues, edits),
`uow.catalog` (stores, products), `uow.users`. Protocols in
`src/database/interfaces/`, implementations in `src/database/repositories/`. Repositories
have only the methods the code and tests need today; add more when a service needs them.
Tests never import ORM models.

Models: `src/database/models/`. Enums: `src/domain/enums.py`. Decisions: ADR-0001
(aggregates), ADR-0002 (one photo and one parse per receipt).

- A `receipts` row is one receipt with one photo (`receipt_photos`, 1:1) and at most one
  parse (`receipt_parses`, 1:1). Status: `pending → parsing → parsed`, or `failed`,
  `not_receipt`, `duplicate` (same receipt key as an earlier parsed receipt;
  `duplicate_of_id` points at it, and the row keeps its own parse).
- Receipt header columns are the parse with `receipt_edits` applied. `receipt_items`
  and `receipt_issues` are rebuilt from `receipt_parses.normalized` whenever the parse is
  set or replaced. **These rules are enforced by the `Receipt` aggregate, not by
  repositories or services**; the DB constraints are the second line of defence.
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
  `create_table` (iteration 1 hit this with a receipts ↔ parses cycle). Partial
  indexes and CHECKs must be checked too. Run `alembic check` and a down/up round trip.
- DB tests run against a real Postgres. Each test is rolled back (`tests/conftest.py`).
  Add a constraint test for every new constraint.
- By-id lookups (`get(id)`) return soft-deleted receipts too, because restore needs
  them. Only list, stats and uniqueness queries filter `deleted_at IS NULL`.
- Database errors never leave `src/database` as SQLAlchemy errors: one engine-level
  `handle_error` listener (`translate_db_error`, installed by `install_error_translation`)
  maps reads, writes and commit failures to `UniqueViolationError`,
  `ForeignKeyViolationError` (also RESTRICT), `CheckViolationError`, `DataViolationError`
  (SQLSTATE class 22) or `DatabaseException`. Repositories carry no wrappers. A test engine
  must call `install_error_translation` too.

### Photo storage

- Root directory: the `STORAGE__RECEIPTS_DIR` setting (`settings.storage.receipts_dir`), mounted as a docker volume.
- Layout: `RECEIPTS_DIR/yyyy/mm/receipt_<yyyy-MM-dd_HH-mm-ss>_<message_id>.<ext>`. The
  DB stores the path relative to `RECEIPTS_DIR`.
- Write to a temp file in the same directory, then rename it, so a crash never leaves a
  half-written photo.
- Never delete photos. A deleted receipt's photo moves to `RECEIPTS_DIR/.trash/`.

## What the n8n workflow does (the spec for parity)

Steps 2 to 8 are done in taler-bot (stage 0, `handlers/message/photo.py`); step 1 is the
access middleware.

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
- Which issue `field` is which editable field (`ISSUE_FIELDS` in `domain/edits.py`) is domain
  knowledge, not bot knowledge: `Receipt.reviewable_issues`, `.issue_correction` and
  `.correct_issue` use it, and the services expose the result as `IssueCard.editable` and
  `.input_kind`. Product names are not in it (item-edit spec).
- Timezone is `Europe/Madrid`. Default currency is `EUR`.
- Money: round to 2 decimals for comparisons and use a 0.02 tolerance. Keep 4 decimals
  for unit prices.
- Never log or store full card numbers, tokens or API keys. Secrets come from env / the repo-root `.env`
  (git-ignored) through pydantic-settings. Keep `.env.template` up to date.
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

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root (ADR-0001: Receipt aggregate, services; ADR-0002: one photo per receipt). See `docs/agents/domain.md`.
