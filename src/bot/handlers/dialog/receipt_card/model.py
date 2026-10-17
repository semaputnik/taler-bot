from pydantic import BaseModel

from src.bot.handlers.dialog.receipt_card.common import PreviewDataKeys


class MainPreview(BaseModel):
    """What the `main` window shows: the rendered card text and which buttons apply."""

    text: str
    can_delete: bool
    has_items: bool
    review_count: int
    can_reparse: bool

    def to_data(self) -> dict:
        return {
            PreviewDataKeys.TEXT: self.text,
            PreviewDataKeys.CAN_DELETE: self.can_delete,
            PreviewDataKeys.HAS_ITEMS: self.has_items,
            PreviewDataKeys.REVIEW_COUNT: self.review_count,
            PreviewDataKeys.CAN_REPARSE: self.can_reparse,
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
    """What the `item` window shows: the rendered details. `has_item` is false when the item
    vanished (a re-parse), and then the edit buttons are hidden."""

    text: str
    has_item: bool

    def to_data(self) -> dict:
        return {PreviewDataKeys.TEXT: self.text, PreviewDataKeys.HAS_ITEM: self.has_item}


class CategoryChoice(BaseModel):
    """One button of the category list: `id` is the category's name, `text` the label."""

    id: str
    text: str


class CategoriesPreview(BaseModel):
    """What the `item_category` window shows: the prompt and the 15 categories."""

    text: str
    categories: list[CategoryChoice]

    def to_data(self) -> dict:
        return {PreviewDataKeys.TEXT: self.text, PreviewDataKeys.CATEGORIES: self.categories}


class IssuePreview(BaseModel):
    """What the `issue` window shows: the rendered issue and which buttons apply. When every
    remaining issue vanished (resolved elsewhere), `has_issue` is false and `text` is the tally."""

    text: str
    has_issue: bool
    can_enter_value: bool
    can_rename: bool

    def to_data(self) -> dict:
        return {
            PreviewDataKeys.TEXT: self.text,
            PreviewDataKeys.HAS_ISSUE: self.has_issue,
            PreviewDataKeys.CAN_ENTER_VALUE: self.can_enter_value,
            PreviewDataKeys.CAN_RENAME: self.can_rename,
        }


class TallyPreview(BaseModel):
    """What the `review_done` window shows: the tally."""

    text: str

    def to_data(self) -> dict:
        return {PreviewDataKeys.TEXT: self.text}


class InputPreview(BaseModel):
    """What the `issue_input` window shows: the prompt, with the error line after a refusal."""

    text: str

    def to_data(self) -> dict:
        return {PreviewDataKeys.TEXT: self.text}
