from pydantic import BaseModel

from src.bot.handlers.dialog.receipt_card.common import PreviewDataKeys


class MainPreview(BaseModel):
    """What the `main` window shows: the rendered card text and which buttons apply."""

    text: str
    can_delete: bool
    has_items: bool

    def to_data(self) -> dict:
        return {
            PreviewDataKeys.TEXT: self.text,
            PreviewDataKeys.CAN_DELETE: self.can_delete,
            PreviewDataKeys.HAS_ITEMS: self.has_items,
        }


class ItemChoice(BaseModel):
    """One row of the item list. `id` is the item's position: a ref can overflow the 64 bytes
    of a button's callback data."""

    id: str
    text: str


class ItemsPreview(BaseModel):
    """What the `items` window shows: a title and one choice per item."""

    text: str
    items: list[ItemChoice]

    def to_data(self) -> dict:
        return {PreviewDataKeys.TEXT: self.text, PreviewDataKeys.ITEMS: self.items}


class ItemPreview(BaseModel):
    """What the `item` window shows: the rendered details."""

    text: str

    def to_data(self) -> dict:
        return {PreviewDataKeys.TEXT: self.text}
