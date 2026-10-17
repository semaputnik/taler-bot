"""The stats message: text and plain inline keyboard for one week or month of spending."""

from datetime import date, timedelta
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.keyboards.history import HistoryAction, HistoryCallback
from src.bot.keyboards.stats import StatsCallback, StatsKind
from src.services import periods
from src.services.results import Compared, ComparedBlock, SpendingReport

NOT_ITEMISED = "not_itemised"
NONE = "none"  # an expense without a payee, or without a payment source


def title(report: SpendingReport, i18n: TranslatorRunner) -> str:
    if report.kind == "month":
        return i18n.get(
            "stats-title-month",
            month=i18n.get(f"month-{report.start.month}"),
            year=str(report.start.year),
        )
    last = report.end - timedelta(days=1)  # `end` is exclusive
    return i18n.get(
        "stats-title-week",
        week=str(report.start.isocalendar().week),
        **{"from": f"{report.start:%d.%m}", "to": f"{last:%d.%m.%Y}"},
    )


def _previous_name(report: SpendingReport, i18n: TranslatorRunner) -> str:
    if report.kind == "week":
        return i18n.get("stats-previous-week")
    before = periods.previous(report.start, report.end)[0]
    return i18n.get(f"month-{before.month}")


def _percent(change: int | None, i18n: TranslatorRunner) -> str:
    if change is None or change == 0:
        return i18n.get("stats-change-same")
    key = "stats-change-up" if change > 0 else "stats-change-down"
    return i18n.get(key, percent=str(abs(change)))


def headline(report: SpendingReport, block: ComparedBlock, i18n: TranslatorRunner) -> str:
    total = render.money(block.total, i18n, block.currency)
    if block.previous_total is None or block.change is None:
        return i18n.get("stats-headline-no-previous", total=total, count=block.expense_count)
    return i18n.get(
        "stats-headline",
        total=total,
        count=block.expense_count,
        change=_percent(block.change, i18n),
        previous=_previous_name(report, i18n),
        previous_total=render.money(block.previous_total, i18n, block.currency),
    )


def _change(line: Compared, block: ComparedBlock, i18n: TranslatorRunner) -> str | None:
    """The change text of a line, None when there is nothing to compare with."""
    if block.previous_total is None:
        return None
    if line.previous is None:
        return i18n.get("stats-change-new")
    if line.change is None:
        return None
    return _percent(line.change, i18n)


def _line(
    label: str, line: Compared, block: ComparedBlock, i18n: TranslatorRunner, *, share: bool
) -> str:
    amount = render.money(line.value, i18n, block.currency)
    change = _change(line, block, i18n)
    prefix = "stats-line" if share else "stats-card-line"
    fields = {"label": label, "amount": amount, "share": str(line.share)}
    if change is None:
        return i18n.get(f"{prefix}-no-change", **fields)
    return i18n.get(prefix, change=change, **fields)


def _category_label(line: Compared, i18n: TranslatorRunner) -> str:
    """An expense category (`groceries`, `rent`, ...)."""
    return i18n.get(f"expense-category-{line.key.replace('_', '-')}")


def _product_label(line: Compared, i18n: TranslatorRunner) -> str:
    """A product category (`produce`, `dairy`, ...), or the not-itemised remainder."""
    if line.key == NOT_ITEMISED:
        return i18n.get("stats-not-itemised")
    return i18n.get(f"category-{line.key.replace('_', '-')}")


def _payee_label(line: Compared, i18n: TranslatorRunner) -> str:
    return i18n.get("receipt-unknown-store") if line.key == NONE else escape(line.label)


def _source_label(line: Compared, i18n: TranslatorRunner) -> str:
    """A card or cash by its name."""
    return i18n.get("item-not-specified") if line.key == NONE else escape(line.label)


def _block_text(report: SpendingReport, block: ComparedBlock, i18n: TranslatorRunner) -> str:
    parts = [headline(report, block, i18n)]
    sections = [
        (
            "stats-section-categories",
            [_line(_category_label(c, i18n), c, block, i18n, share=True) for c in block.categories],
        ),
        (
            "stats-section-products",
            [_line(_product_label(p, i18n), p, block, i18n, share=True) for p in block.products],
        ),
        (
            "stats-section-payees",
            [_line(_payee_label(p, i18n), p, block, i18n, share=True) for p in block.payees],
        ),
        (
            "stats-section-sources",
            [_line(_source_label(s, i18n), s, block, i18n, share=False) for s in block.sources],
        ),
    ]
    for key, lines in sections:
        if lines:
            parts.append(i18n.get(key) + "\n" + "\n".join(lines))
    return "\n\n".join(parts)


def show_text(report: SpendingReport, i18n: TranslatorRunner) -> str:
    if not report.blocks:
        return f"{title(report, i18n)}\n{i18n.get('stats-empty')}"
    texts = []
    for block in report.blocks:
        text = _block_text(report, block, i18n)
        if len(report.blocks) > 1:
            text = i18n.get("stats-currency-block", currency=escape(block.currency)) + "\n" + text
        texts.append(text)
    return title(report, i18n) + "\n" + "\n\n".join(texts)


def _button(text: str, data: StatsCallback) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def _arrow_label(
    key: str, report: SpendingReport, shown_start: date, i18n: TranslatorRunner
) -> str:
    name = (
        i18n.get(f"month-short-{shown_start.month}")
        if report.kind == "month"
        else f"{shown_start:%d.%m}"
    )
    return i18n.get(key, month=name)


def show_keyboard(report: SpendingReport, i18n: TranslatorRunner) -> InlineKeyboardMarkup:
    kind = StatsKind(report.kind)
    # `◀` is always there: an empty earlier period just says so. Only the future is closed.
    before = periods.previous(report.start, report.end)[0]
    nav: list[InlineKeyboardButton] = [
        _button(
            _arrow_label("button-prev-month", report, before, i18n),
            StatsCallback.at(kind, periods.previous_anchor(report.start, report.end)),
        )
    ]
    if not report.is_current:
        nav.append(
            _button(
                _arrow_label("button-next-month", report, report.end, i18n),
                StatsCallback.at(kind, periods.next_anchor(report.start, report.end)),
            )
        )
    other = StatsKind.WEEK if kind is StatsKind.MONTH else StatsKind.MONTH
    switch = _button(i18n.get(f"button-stats-{other.value}"), StatsCallback.at(other, report.start))
    rows = [nav, [switch]] if nav else [[switch]]
    if kind is StatsKind.MONTH:
        history = HistoryCallback(
            year=report.start.year, month=report.start.month, action=HistoryAction.OPEN
        )
        rows.append(
            [InlineKeyboardButton(text=i18n.get("button-expenses"), callback_data=history.pack())]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
