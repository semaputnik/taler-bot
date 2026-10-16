# Receipt fixtures for `normalize`

One file per receipt the n8n Receipts Bot processed (exported 2026-10-17 from its
`receipt_payments` and `store_products` data tables; file name = n8n payment id, store
key, n8n status). Each file has:

- `raw`: the model's output exactly as n8n stored it (`rawJson`), the input to `normalize`;
- `context`: what n8n's normalizer saw when it ran: the Telegram message time
  (`received_at`), the time zone, the product keys that already existed for that store
  (`known_product_keys`) and the card endings of earlier parsed receipts
  (`known_card_last4`);
- `expected_n8n`: the header n8n's normalizer produced (`receiptKey`, `purchasedAt`,
  totals, payment, `itemsCount`, `status`). The port must reproduce these, modulo the
  known differences noted in the test that loads them;
- `source`: the n8n parser version and model.

Interesting cases: weighed items (04, 11, 15); a line discount repeated as a separate
"savings" line that must be counted once (11); line discounts summed into
`discountTotal` (09); a misread year corrected to the message's year (11); a card
ending never seen before (11: `0048` vs the known `0848`); an item with no quantity
(12); a duplicate receipt key (06); name notes on products already in the catalog (07, 13).

Drive ids and URLs were dropped. Everything else is what the receipts print.
