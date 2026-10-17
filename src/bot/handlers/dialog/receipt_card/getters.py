from datetime import datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from aiogram_dialog import DialogManager
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.handlers.dialog.media import StoredPhoto
from src.bot.handlers.dialog.receipt_card.click_event import settle
from src.bot.handlers.dialog.receipt_card.common import (
    CATEGORIES,
    DialogDataKeys,
    PreviewDataKeys,
)
from src.bot.handlers.dialog.receipt_card.model import (
    CategoriesPreview,
    CategoryChoice,
    InputPreview,
    IssuePreview,
    ItemChoice,
    ItemPreview,
    ItemsPreview,
    MainPreview,
    TallyPreview,
)
from src.bot.handlers.dialog.receipt_card.values import ITEM_FIELD_KINDS
from src.services.container import Services
from src.services.results import CurrentUser, IssueCard, ItemRow, ReceiptCard

_STATUS_KEYS = {
    "pending": "card-status-pending",
    "parsing": "card-status-parsing",
}


async def main_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await services.receipts.card(
        user.id, dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    )
    return MainPreview(
        text=_text(card, i18n, ZoneInfo(user.timezone)),
        can_delete=not card.deleted,
        has_items=card.status == "parsed" and card.item_count > 0 and not card.deleted,
        review_count=card.review_count if card.status == "parsed" and not card.deleted else 0,
    ).to_data()


async def items_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    rows = await services.receipts.items(
        user.id, dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    )
    return ItemsPreview(
        text=i18n.get("card-items-title", count=str(len(rows))),
        items=[ItemChoice(id=str(i), text=_row_text(row, i18n)) for i, row in enumerate(rows)],
    ).to_data()


async def item_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    # One service call; the selected item is picked from the result.
    rows = await services.receipts.items(
        user.id, dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    )
    ref = dialog_manager.dialog_data.get(DialogDataKeys.ITEM_REF)
    row = next((r for r in rows if r.ref == ref), None)
    text = _item_text(row, i18n) if row is not None else i18n.get("item-gone")
    return ItemPreview(text=text, has_item=row is not None).to_data()


async def _selected_item(
    dialog_manager: DialogManager, services: Services, user: CurrentUser
) -> ItemRow | None:
    rows = await services.receipts.items(
        user.id, dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    )
    ref = dialog_manager.dialog_data.get(DialogDataKeys.ITEM_REF)
    return next((r for r in rows if r.ref == ref), None)


async def item_input_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    """The prompt for the item field being edited: label, hint, current value, error line."""
    data = dialog_manager.dialog_data
    row = await _selected_item(dialog_manager, services, user)
    field = data.get(DialogDataKeys.EDIT_FIELD)
    if row is None or field not in ITEM_FIELD_KINDS:
        return InputPreview(text=i18n.get("item-gone")).to_data()
    hint = i18n.get(f"input-hint-{ITEM_FIELD_KINDS[field]}")
    lines = [
        i18n.get(
            "item-input-prompt",
            field=i18n.get(f"field-{field.replace('_', '-')}"),
            hint=hint,
            value=_item_value(row, field, i18n),
        )
    ]
    if data.get(DialogDataKeys.INPUT_ERROR):
        lines += ["", i18n.get("issue-input-error", hint=hint)]
    return InputPreview(text="\n".join(lines)).to_data()


def _item_value(row: ItemRow, field: str, i18n: TranslatorRunner) -> str:
    match field:
        case "name":
            return escape(row.readable_name)
        case "quantity":
            return render.quantity(row.quantity)
        case "unit_price":
            return render.money(row.unit_price, i18n, row.currency)
        case _:
            return render.money(row.line_total, i18n, row.currency)


async def item_categories_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    """The category list with the item's current category marked."""
    row = await _selected_item(dialog_manager, services, user)
    if row is None:
        return CategoriesPreview(text=i18n.get("item-gone"), categories=[]).to_data()
    choices = []
    for category in CATEGORIES:
        label = i18n.get(f"category-{category.replace('_', '-')}")
        if category == row.category:
            label = i18n.get("category-current", name=label)
        choices.append(CategoryChoice(id=category, text=label))
    return CategoriesPreview(
        text=i18n.get("item-category-prompt", name=escape(row.readable_name)), categories=choices
    ).to_data()


async def issue_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    """The issue the walk is on, read live by id (one `review` call, one `card` call for the
    currency). If every remaining issue vanished meanwhile, the tally takes its place."""
    data = dialog_manager.dialog_data
    receipt_id = data[DialogDataKeys.RECEIPT_ID]
    cards = await services.receipts.review(user.id, receipt_id)
    current = settle(dialog_manager, cards)
    if current is None:
        return IssuePreview(
            text=_tally(data, i18n),
            has_issue=False,
            can_enter_value=False,
            can_rename=False,
        ).to_data()
    card = await services.receipts.card(user.id, receipt_id)
    return IssuePreview(
        text=_issue_text(
            current,
            i18n,
            ZoneInfo(user.timezone),
            card.currency,
            position=data[DialogDataKeys.POSITION] + 1,
            total=len(data[DialogDataKeys.WALK]),
        ),
        has_issue=True,
        can_enter_value=current.editable,
        can_rename=current.renamable,
    ).to_data()


async def issue_input_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    """The prompt for the issue on screen, plus the error line after a refused value."""
    data = dialog_manager.dialog_data
    cards = await services.receipts.review(user.id, data[DialogDataKeys.RECEIPT_ID])
    current = next(
        (c for c in cards if c.issue_id == data.get(DialogDataKeys.CURRENT_ISSUE_ID)), None
    )
    if current is None or not current.editable:
        return InputPreview(text=i18n.get("issue-input-gone")).to_data()
    hint = i18n.get(f"input-hint-{current.input_kind}")
    lines = [i18n.get("issue-input-prompt", field=_field_label(current, i18n), hint=hint)]
    if data.get(DialogDataKeys.INPUT_ERROR):
        lines += ["", i18n.get("issue-input-error", hint=hint)]
    return InputPreview(text="\n".join(lines)).to_data()


async def issue_rename_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    """The prompt to rename the product behind the issue on screen, with its current name."""
    data = dialog_manager.dialog_data
    cards = await services.receipts.review(user.id, data[DialogDataKeys.RECEIPT_ID])
    current = next(
        (c for c in cards if c.issue_id == data.get(DialogDataKeys.CURRENT_ISSUE_ID)), None
    )
    if current is None or not current.renamable:
        return InputPreview(text=i18n.get("issue-input-gone")).to_data()
    hint = i18n.get("input-hint-text")
    lines = [
        i18n.get(
            "item-input-prompt",
            field=i18n.get("field-name"),
            hint=hint,
            value=escape(current.item_name or ""),
        )
    ]
    if data.get(DialogDataKeys.INPUT_ERROR):
        lines += ["", i18n.get("issue-input-error", hint=hint)]
    return InputPreview(text="\n".join(lines)).to_data()


def _field_label(issue: IssueCard, i18n: TranslatorRunner) -> str:
    """`totals.total` -> `field-total`, `payment.card_last4` -> `field-card-last4`."""
    name = (issue.field or "").rsplit(".", 1)[-1].replace("_", "-")
    return i18n.get(f"field-{name}")


async def review_done_getter(dialog_manager: DialogManager, i18n: TranslatorRunner, **_) -> dict:
    return TallyPreview(text=_tally(dialog_manager.dialog_data, i18n)).to_data()


def _tally(data: dict, i18n: TranslatorRunner) -> str:
    confirmed, corrected, skipped = (
        data[DialogDataKeys.CONFIRMED],
        data[DialogDataKeys.CORRECTED],
        data[DialogDataKeys.SKIPPED],
    )
    return i18n.get(
        "review-done",
        reviewed=str(confirmed + corrected + skipped),
        corrected=str(corrected),
        confirmed=str(confirmed),
        skipped=str(skipped),
    )


def _issue_text(
    issue: IssueCard,
    i18n: TranslatorRunner,
    tz: ZoneInfo,
    currency: str | None,
    *,
    position: int,
    total: int,
) -> str:
    lines = [
        i18n.get(
            "issue-title",
            position=str(position),
            total=str(total),
            icon=i18n.get(f"issue-severity-{issue.severity}"),
        ),
        "",
    ]
    if issue.item_name:
        lines.append(i18n.get("issue-item", name=escape(issue.item_name)))
    lines.append(escape(issue.message))
    if issue.editable:
        lines += ["", i18n.get("issue-current-value", value=_value(issue, i18n, tz, currency))]
    return "\n".join(lines)


def _value(issue: IssueCard, i18n: TranslatorRunner, tz: ZoneInfo, currency: str | None) -> str:
    value = issue.current_value
    if value is None:
        return i18n.get("item-not-specified")
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime(render.DATE_FORMAT)
    if isinstance(value, Decimal):
        if issue.input_kind == "money":
            return render.money(value, i18n, currency)
        return render.quantity(value)
    return escape(value)


def _row_text(row: ItemRow, i18n: TranslatorRunner) -> str:
    return i18n.get(
        "item-row",
        name=row.readable_name,
        quantity=render.quantity(row.quantity),
        unit=row.unit,
        total=render.money(row.line_total, i18n, row.currency),
    )


def _item_text(row: ItemRow, i18n: TranslatorRunner) -> str:
    lines = [
        i18n.get("item-title", name=escape(row.readable_name)),
        i18n.get("item-printed", name=escape(row.printed_name)),
        i18n.get("item-category", category=i18n.get(f"category-{row.category.replace('_', '-')}")),
        i18n.get("item-quantity", quantity=render.quantity(row.quantity), unit=escape(row.unit)),
        i18n.get("item-unit-price", price=render.money(row.unit_price, i18n, row.currency)),
        i18n.get(
            "item-reference-price",
            price=render.money(row.reference_price, i18n, row.currency),
            unit=escape(row.reference_unit) if row.reference_unit else "",
        )
        if row.reference_price is not None
        else None,
        i18n.get("item-discount", amount=render.money(row.discount, i18n, row.currency))
        if row.discount
        else None,
        i18n.get("item-line-total", amount=render.money(row.line_total, i18n, row.currency)),
        i18n.get("item-vat", rate=render.quantity(row.vat_rate))
        if row.vat_rate is not None
        else None,
    ]
    return "\n".join(line for line in lines if line is not None)


async def photo_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    """The photo by its Telegram file id. The bytes are loaded only if Telegram refuses it."""
    receipt_id = dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    ref = await services.receipts.photo(user.id, receipt_id)
    return {
        PreviewDataKeys.PHOTO: StoredPhoto(
            ref.telegram_file_id,
            lambda: services.receipts.photo_bytes(user.id, receipt_id),
            i18n.get("card-photo-unavailable"),
        )
    }


def _text(card: ReceiptCard, i18n: TranslatorRunner, tz: ZoneInfo) -> str:
    """The `main` window's text for every outcome: the card is the parse reply."""
    if card.deleted:
        return i18n.get("card-deleted")
    match card.status:
        case "parsed":
            return render.header(card, i18n, tz)
        case "not_receipt":
            status = i18n.get("receipt-not-a-receipt")
        case "failed":
            status = i18n.get("receipt-failed")
        case "duplicate":
            original = card.duplicate_of or card
            status = i18n.get(
                "receipt-duplicate",
                store=render.store(original, i18n),
                date=render.date(original, tz),
                amount=render.amount(original, i18n),
            )
        case _:
            status = i18n.get(_STATUS_KEYS[card.status])
    received = card.received_at.astimezone(tz).strftime(render.DATE_FORMAT)
    return "\n".join([status, i18n.get("card-received", date=received)])
