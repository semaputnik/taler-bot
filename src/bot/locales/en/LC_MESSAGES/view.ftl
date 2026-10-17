start-greeting = Hello, { $first_name }! I read photos of your purchase receipts. Send me one to get started.

photo-send-me-one = Send me a photo of a receipt.
photo-too-large = This file is too large (the limit is 20 MB). Send a smaller photo.
photo-already-have = I already have this photo.

receipt-saved = ✅ Saved, reading…
receipt-not-a-receipt = 🤔 This does not look like a receipt. Nothing was recorded.
receipt-duplicate = ♻️ Already recorded: <b>{ $store }</b>, { $date }, { $amount }

receipt-summary =
    🧾 <b>{ $store }</b>
    { "" }
    { $date }
    Total: <b>{ $amount }</b>
    Payment: { $payment }
    Items: { $items }
receipt-store-tag = #{ $tag }
receipt-unknown-store = Unknown store
receipt-amount = { $total } { $currency }
receipt-amount-unknown = unknown
receipt-payment-card-brand = card { $brand } •{ $last4 }
receipt-payment-card = card •{ $last4 }
receipt-payment-method = { $method }
receipt-payment-none = not specified

card-deleted-alert = This receipt was deleted.
card-deleted = 🗑 This receipt was deleted.
card-status-pending = ⏳ Waiting to be read.
card-status-parsing = ⏳ Being read…
card-received = Photo received: { $date }
card-delete-confirm = Delete this receipt? The photo is kept in the trash.
card-cannot-delete-parsing = This receipt is still being read. Try again in a moment.

card-items-title = 📋 Items ({ $count })

item-title =
    <b>{ $name }</b>
    { "" }
item-printed = <b>Printed as:</b> { $name }
item-category = <b>Category:</b> { $category }
item-quantity = <b>Quantity:</b> { $quantity } { $unit }
item-unit-price = <b>Unit price:</b> { $price }
item-reference-price = <b>Reference price:</b> { $price } per { $unit }
item-discount = <b>Discount:</b> { $amount }
item-line-total = <b>Line total:</b> { $amount }
item-vat = <b>VAT:</b> { $rate }%
item-amount = { $amount } { $sign }
item-not-specified = not specified
item-gone = This item is no longer on the receipt.
item-row = { $name } · { $quantity } { $unit } · { $total }

category-produce = Produce
category-meat = Meat
category-fish = Fish
category-dairy = Dairy
category-bakery = Bakery
category-drinks = Drinks
category-alcohol = Alcohol
category-snacks = Snacks
category-frozen = Frozen
category-pantry = Pantry
category-household = Household
category-personal-care = Personal care
category-baby = Baby
category-pet = Pet
category-other = Other
category-current = ✓ { $name }
item-category-prompt = Pick the category for { $name }
item-input-prompt =
    Enter the { $field } ({ $hint })
    { "" }
    <b>Current value:</b> { $value }
card-photo-unavailable = The photo could not be loaded.

issue-title = ⚠️ <b>Issue { $position } of { $total }</b> { $icon }
issue-severity-high = 🔴
issue-severity-medium = 🟡
issue-item = <b>Item:</b> { $name }
issue-current-value = <b>Current value:</b> { $value }
issue-input-prompt = Enter the { $field } ({ $hint })
issue-input-error = ❌ Not accepted. Send { $hint }.
issue-input-gone = This issue is no longer open. Go back.

field-purchased-at = date and time
field-number = receipt number
field-currency = currency
field-total = total
field-subtotal = subtotal
field-discount-total = total discount
field-tax-total = total tax
field-method = payment method
field-card-last4 = card ending
field-name = name
field-quantity = quantity
field-unit-price = unit price
field-reference-price = reference price
field-discount = discount
field-line-total = line total
field-vat-rate = VAT rate, %

input-hint-datetime = dd.mm.yyyy hh:mm
input-hint-money = a number with a point, like 12.50
input-hint-number = a number with a point, like 1.5
input-hint-last4 = four digits
input-hint-currency = a 3-letter code, like EUR
input-hint-text = free text
review-done = { $reviewed } reviewed: { $corrected } corrected, { $confirmed } confirmed, { $skipped } skipped
