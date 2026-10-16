start-greeting = Hello, { $first_name }! I read photos of your purchase receipts. Send me one to get started.

photo-send-me-one = Send me a photo of a receipt.
photo-too-large = This file is too large (the limit is 20 MB). Send a smaller photo.
photo-already-have = I already have this photo.

receipt-saved = ✅ Saved, reading…
receipt-not-a-receipt = 🤔 This does not look like a receipt. Nothing was recorded.
receipt-duplicate = ♻️ Already recorded: <b>{ $store }</b>, { $date }, { $amount }

receipt-summary =
    🧾 <b>{ $store }</b>
    { $date }
    Total: <b>{ $amount }</b>
    Payment: { $payment }
    Items: { $items }
receipt-unknown-store = Unknown store
receipt-amount = { $total } { $currency }
receipt-amount-unknown = unknown
receipt-payment-card-brand = card { $brand } •{ $last4 }
receipt-payment-card = card •{ $last4 }
receipt-payment-method = { $method }
receipt-payment-none = not specified
receipt-issues = ⚠️ Issues ({ $count }):
receipt-issue-line = • { $item }: { $message }
receipt-issue-line-plain = • { $message }
receipt-issues-more = …

card-deleted-alert = This receipt was deleted.
card-deleted = 🗑 This receipt was deleted.
card-deleted-done = 🗑 Deleted
card-status-pending = ⏳ Waiting to be read.
card-status-parsing = ⏳ Being read…
card-status-failed = ❌ Could not be read.
card-status-not-receipt = 🤔 Not a receipt.
card-status-duplicate = ♻️ Duplicate.
card-received = Photo received: { $date }
card-repeats = Repeats <b>{ $store }</b>, { $date }, { $amount }
card-delete-confirm = Delete this receipt? The photo is kept in the trash.
card-cannot-delete-parsing = This receipt is still being read. Try again in a moment.
