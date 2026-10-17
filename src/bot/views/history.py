"""The history message: text and plain inline keyboard for the month and payee chooser screens."""

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.keyboards.expense import ExpenseCallback, ExpenseWindow
from src.bot.keyboards.history import HistoryAction, HistoryCallback
from src.bot.keyboards.receipt import CardWindow, ReceiptCallback
from src.services.results import PAGE_SIZE, HistoryPage, HistoryRow

# Row status -> the icon shown instead of an amount (the service gives the status as a string).
_STATUS_ICONS = {
    "failed": "❌",
    "duplicate": "♻️",
    "not_receipt": "🤔",
    "pending": "⏳",
    "parsing": "⏳",
}


def pages_of(page: HistoryPage) -> int:
    return max(1, -(-page.total_rows // PAGE_SIZE))


def current_page(page: HistoryPage, requested: int) -> int:
    """The page the service really returned: a request past the end gives the last page."""
    return min(max(requested, 0), pages_of(page) - 1)


def month_before(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def month_after(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def title(page: HistoryPage, i18n: TranslatorRunner) -> str:
    month = i18n.get(f"month-{page.month}")
    if page.payee_name:
        return i18n.get(
            "history-title-filtered",
            month=month,
            year=str(page.year),
            payee=escape(page.payee_name),
        )
    return i18n.get("history-title", month=month, year=str(page.year))


def summary(page: HistoryPage, i18n: TranslatorRunner) -> str:
    if page.total_rows == 0:
        return i18n.get("history-empty")
    if page.expense_count == 0:
        return i18n.get("history-summary-none")
    totals = ", ".join(render.money(t.amount, i18n, t.currency) for t in page.totals)
    return i18n.get("history-summary", count=page.expense_count, totals=totals)


def show_text(page: HistoryPage, i18n: TranslatorRunner) -> str:
    return f"{title(page, i18n)}\n{summary(page, i18n)}"


def _row_label(row: HistoryRow, i18n: TranslatorRunner) -> str:
    day = f"{row.day.day:02d}.{row.day.month:02d}"
    # A button is plain text, so the payee name is not HTML-escaped here.
    payee = row.payee_name or i18n.get("receipt-unknown-store")
    icon = _STATUS_ICONS.get(row.status)
    if icon is not None:
        return i18n.get("history-row-status", day=day, payee=payee, status=icon)
    amount = render.money(row.amount, i18n, row.currency)
    # An expense typed by hand has no receipt: its own icon instead of the plain bullet.
    key = "history-row" if row.has_receipt else "history-row-manual"
    return i18n.get(key, day=day, payee=payee, amount=amount)


def _open_card(row: HistoryRow) -> str:
    """The row opens a card: the receipt card, or the expense card of an expense typed by hand."""
    if row.receipt_id is not None:
        return ReceiptCallback(receipt_id=row.receipt_id, window=CardWindow.MAIN).pack()
    assert row.expense_id is not None  # a row has a receipt or an expense
    return ExpenseCallback(expense_id=row.expense_id, window=ExpenseWindow.MAIN).pack()


def _button(text: str, data: HistoryCallback) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def show_keyboard(
    page: HistoryPage, shown: HistoryCallback, i18n: TranslatorRunner
) -> InlineKeyboardMarkup:
    number = current_page(page, shown.page)
    here = shown.model_copy(update={"year": page.year, "month": page.month})

    def go(**fields) -> HistoryCallback:
        return here.model_copy(update={"action": HistoryAction.SHOW, **fields})

    rows = [
        [InlineKeyboardButton(text=_row_label(row, i18n), callback_data=_open_card(row))]
        for row in page.rows
    ]
    nav: list[InlineKeyboardButton] = []
    if page.has_earlier:
        year, month = month_before(page.year, page.month)
        nav.append(
            _button(
                i18n.get("button-prev-month", month=i18n.get(f"month-short-{month}")),
                go(year=year, month=month, page=0),
            )
        )
    nav.append(
        _button(
            i18n.get("button-payee-filter"),
            here.model_copy(update={"action": HistoryAction.PAYEES, "page": number}),
        )
    )
    if page.has_later:
        year, month = month_after(page.year, page.month)
        nav.append(
            _button(
                i18n.get("button-next-month", month=i18n.get(f"month-short-{month}")),
                go(year=year, month=month, page=0),
            )
        )
    rows.append(nav)
    pages = pages_of(page)
    if pages > 1:
        paging: list[InlineKeyboardButton] = []
        if number > 0:
            paging.append(_button(i18n.get("button-prev-page"), go(page=number - 1)))
        paging.append(
            _button(
                i18n.get("history-page", page=str(number + 1), pages=str(pages)), go(page=number)
            )
        )
        if number < pages - 1:
            paging.append(_button(i18n.get("button-next-page"), go(page=number + 1)))
        rows.append(paging)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payees_text(page: HistoryPage, i18n: TranslatorRunner) -> str:
    return title(page, i18n)


def payees_keyboard(
    page: HistoryPage, shown: HistoryCallback, i18n: TranslatorRunner
) -> InlineKeyboardMarkup:
    here = shown.model_copy(
        update={"year": page.year, "month": page.month, "action": HistoryAction.SHOW}
    )
    rows = []
    for payee in page.payees:
        key = (
            "button-payee-option-selected"
            if payee.payee_id == shown.payee_id
            else "button-payee-option"
        )
        rows.append(
            [
                _button(
                    i18n.get(key, name=payee.name),
                    here.model_copy(update={"payee_id": payee.payee_id, "page": 0}),
                )
            ]
        )
    rows.append(
        [_button(i18n.get("button-all-payees"), here.model_copy(update={"payee_id": 0, "page": 0}))]
    )
    rows.append([_button(i18n.get("button-back"), here)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
