"""Texts about a receipt that both the parse reply and the card dialog show."""

import re
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from fluentogram import TranslatorRunner

from src.services.results import ExpenseCard, ReceiptCard

DATE_FORMAT = "%d.%m.%Y %H:%M"
DATE_ONLY_FORMAT = "%d.%m.%Y"


def store(card: ReceiptCard, i18n: TranslatorRunner) -> str:
    return escape(card.store_name) if card.store_name else i18n.get("receipt-unknown-store")


def date(card: ReceiptCard, tz: ZoneInfo) -> str:
    return card.purchased_at.astimezone(tz).strftime(DATE_FORMAT) if card.purchased_at else ""


def amount(card: ReceiptCard, i18n: TranslatorRunner) -> str:
    if card.total is None:
        return i18n.get("receipt-amount-unknown")
    return i18n.get(
        "receipt-amount", total=format(card.total, ".2f"), currency=_sign(card.currency)
    )


_CURRENCY_SIGNS = {"EUR": "€", "USD": "$", "GBP": "£", "RUB": "₽", "UAH": "₴", "CHF": "CHF"}


def _sign(currency: str | None) -> str:
    """The currency sign (`€`), or the escaped code when there is no sign for it."""
    if not currency:
        return ""
    return _CURRENCY_SIGNS.get(currency.upper(), escape(currency))


def money(value: Decimal | None, i18n: TranslatorRunner, currency: str | None = None) -> str:
    """An amount with 2 decimals and the currency sign (`12.30 €`), or "not specified"."""
    if value is None:
        return i18n.get("item-not-specified")
    amount = format(value, ".2f")
    if not currency:
        return amount
    return i18n.get("item-amount", amount=amount, sign=_sign(currency))


def quantity(value: Decimal) -> str:
    """Up to 4 decimals, trailing zeros stripped: `2`, `0.35`, `1.2345`."""
    return format(value.quantize(Decimal("0.0001")).normalize(), "f")


def payment(card: ReceiptCard, i18n: TranslatorRunner) -> str:
    if card.card_last4:
        if card.card_brand:
            brand = escape(card.card_brand)
            return i18n.get("receipt-payment-card-brand", brand=brand, last4=card.card_last4)
        return i18n.get("receipt-payment-card", last4=card.card_last4)
    if card.payment_method:
        return i18n.get("receipt-payment-method", method=escape(card.payment_method))
    return i18n.get("receipt-payment-none")


def header(card: ReceiptCard, i18n: TranslatorRunner, tz: ZoneInfo) -> str:
    """The card's text: store, a blank line, the facts, a blank line, the store's hashtag."""
    text = i18n.get(
        "receipt-summary",
        store=store(card, i18n),
        date=date(card, tz),
        amount=amount(card, i18n),
        payment=payment(card, i18n),
    )
    if card.expense_category is not None:
        text += "\n" + i18n.get(
            "receipt-category",
            category=i18n.get(f"expense-category-{card.expense_category.replace('_', '-')}"),
        )
    hashtags = " ".join(tag for tag in map(hashtag, card.tags) if tag)
    if hashtags:
        text += "\n" + i18n.get("expense-tags", tags=hashtags)
    text += "\n" + i18n.get("receipt-items", items=str(card.item_count))
    if card.store_key:
        text += "\n\n" + i18n.get("receipt-store-tag", tag=store_tag(card.store_key))
    return text


def store_tag(store_key: str) -> str:
    """A Telegram hashtag body from the store's slug: lower case, letters, digits, underscores."""
    return re.sub(r"[^a-z0-9_]", "_", store_key.lower()).strip("_") or "store"


def expense_text(card: ExpenseCard, i18n: TranslatorRunner) -> str:
    """An expense as a message: the payee, a blank line, the facts, a blank line, the payee's
    hashtag. `spent_at` is already the user's local day, so no time zone comes in."""
    facts = [
        card.spent_at.strftime(DATE_ONLY_FORMAT),
        i18n.get("expense-amount", amount=money(card.amount, i18n, card.currency)),
        i18n.get(
            "expense-source",
            source=escape(card.payment_source_name)
            if card.payment_source_name
            else i18n.get("item-not-specified"),
        ),
        i18n.get("receipt-category", category=_expense_category(card.category, i18n)),
    ]
    tags = " ".join(tag for tag in map(hashtag, card.tags) if tag)
    if tags:
        facts.append(i18n.get("expense-tags", tags=tags))
    payee = escape(card.payee_name) if card.payee_name else i18n.get("expense-unknown-payee")
    text = i18n.get("expense-title", payee=payee) + "\n\n" + "\n".join(facts)
    if card.payee_key:
        text += "\n\n" + i18n.get("expense-payee-tag", tag=store_tag(card.payee_key))
    return text


def _expense_category(category: str, i18n: TranslatorRunner) -> str:
    return i18n.get(f"expense-category-{category.replace('_', '-')}")


def hashtag(tag: str) -> str:
    """A tag as a Telegram hashtag (`#new_year`): word characters only; empty when none are left."""
    body = re.sub(r"\W+", "_", tag.lower()).strip("_")
    return f"#{body}" if body else ""
