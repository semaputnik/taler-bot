---
status: accepted
date: 2026-10-17
extends: ADR-0001, ADR-0002
---

# The expense is the root; a receipt is attached to it

The bot started as a receipt reader. The user now wants it to keep **every** outflow of
money, most of which has no receipt: rent, a restaurant, a subscription, cash at a market.
Receipts stay the rich path (items, issues, re-parse), but they are one way of entering an
expense, not the thing the bot is about.

We introduce `Expense` as the root concept and attach the `Receipt` to it (one expense has
at most one receipt; a receipt belongs to exactly one expense). An expense carries the facts
every outflow has: amount, currency, date, payee, payment source, expense category, tags.
For an expense read from a receipt these facts come from the receipt's header (the parse with
the user's edits) and change with it; for a manual expense they are typed.

Two concepts generalise what the receipt model had:

- `Payee` generalises `Store`: who received the money. A payee may own a product catalog
  (then it is a store); most payees do not. Existing stores become payees with their catalogs.
- `PaymentSource` replaces the loose `card_brand` / `card_last4` header fields as the thing
  statistics group by: a card (brand, last four digits, a name) or cash. Cards are created
  from receipts automatically and by hand. The receipt header keeps its card fields as what
  was printed; the expense points at the source.

Categories split in two: `ExpenseCategory` on the expense (groceries, restaurants, rent, …)
and `ProductCategory` on catalog products (produce, dairy, …). An expense from a receipt is
`groceries` by default and can be changed; the product categories remain the breakdown
inside groceries.

## Considered options

- **Generalise `Receipt` into the expense** (a receipt without a photo and parse): keeps one
  aggregate, but every receipt rule (photo uniqueness, parse statuses, re-parse, issues) would
  need a "no receipt" branch, and the receipt's lifecycle (`pending → parsing → parsed`) means
  nothing for a typed expense. Rejected.
- **A separate `ManualExpense` beside `Receipt`**: no migration, but history and statistics
  would union two shapes forever, and tags, payees and sources would be duplicated or bolted
  onto receipts. Rejected.
- **Expense as the root with the receipt attached** (chosen): the receipt aggregate and its
  rules stay as they are; the expense is small and uniform; lists and statistics read one
  table.

## Consequences

- New tables: `expenses`, `payees` (from `stores`), `payment_sources`, `tags`, `expense_tags`.
  `expenses.receipt_id` (unique). `store_products.payee_id` points at a payee. The migration
  creates an expense for every parsed receipt (a receipt that is failed, not a receipt, a
  duplicate or still being read is not a purchase and has none) and a payment source for every
  card ending seen.
- An amount read from a receipt may be 0.00 when the total is unknown; a manual amount must be
  positive. The database only forbids negative amounts.
- `Expense` is an aggregate with its own repository and service (`ExpenseService`); `Receipt`
  stays an aggregate. A receipt's header change updates its expense in the same Unit of Work
  (the service does both saves; the rule "an expense mirrors its receipt's header" lives on
  the expense).
- `Payee` and `PaymentSource` join the `Catalog` aggregate's family: the user's catalog holds
  payees (with or without products) and payment sources.
- `/receipts` becomes `/expenses`; `/stats` groups by expense category, payee and payment
  source, and keeps the product breakdown for groceries.
- The glossary gains Expense, Payee, Payment source, Expense category, Product category, Tag,
  Screen; "store" narrows to "a payee with a catalog".
