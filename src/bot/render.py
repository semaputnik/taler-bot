"""Texts about a receipt that both the parse reply and the card dialog show."""

from html import escape
from zoneinfo import ZoneInfo

from fluentogram import TranslatorRunner

from src.services.results import ReceiptCard

DATE_FORMAT = "%d.%m.%Y %H:%M"


def store(card: ReceiptCard, i18n: TranslatorRunner) -> str:
    return escape(card.store_name) if card.store_name else i18n.get("receipt-unknown-store")


def date(card: ReceiptCard, tz: ZoneInfo) -> str:
    return card.purchased_at.astimezone(tz).strftime(DATE_FORMAT) if card.purchased_at else ""


def amount(card: ReceiptCard, i18n: TranslatorRunner) -> str:
    if card.total is None:
        return i18n.get("receipt-amount-unknown")
    currency = escape(card.currency or "")
    return i18n.get("receipt-amount", total=format(card.total, ".2f"), currency=currency)


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
    """The summary's first lines: store, date, total, payment, item count."""
    return i18n.get(
        "receipt-summary",
        store=store(card, i18n),
        date=date(card, tz),
        amount=amount(card, i18n),
        payment=payment(card, i18n),
        items=str(card.item_count),
    )
