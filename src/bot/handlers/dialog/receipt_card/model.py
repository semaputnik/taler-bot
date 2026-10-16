from pydantic import BaseModel

from src.bot.handlers.dialog.receipt_card.common import PreviewDataKeys


class MainPreview(BaseModel):
    """What the `main` window shows: the rendered card text and which buttons apply."""

    text: str
    can_delete: bool

    def to_data(self) -> dict:
        return {PreviewDataKeys.TEXT: self.text, PreviewDataKeys.CAN_DELETE: self.can_delete}
