"""The background read of one receipt, shared by photo intake and the card's Re-parse button.

`read_and_show_card` is the one path: typing status, `ReceiptService.parse`, then the card as
a fresh message. The caller spawns it on the `TaskRegistry`.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, ReplyParameters
from aiogram.utils.chat_action import ChatActionSender
from aiogram_dialog import ShowMode, StartMode
from aiogram_dialog.api.protocols import BaseDialogManager

from src.bot.handlers.dialog.common import TransferKeys
from src.bot.states.receipt_card import ReceiptCardSG
from src.services.container import Services

logger = logging.getLogger(__name__)

TYPING_INTERVAL = 4.0  # seconds; Telegram shows "typing" for about 5 s after each action


async def read_and_show_card(
    bot: Bot,
    bg: BaseDialogManager,
    chat_id: int,
    user_id: int,
    receipt_id: int,
    services: Services,
) -> None:
    """Parse, then start the card: the parse reply is the dialog's `main` window. Nothing but
    cancellation leaves this function."""
    try:
        # The sender's worker dies on a failed `sendChatAction` and the block still ends
        # normally, so the typing status never affects the parse or the reply.
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id, interval=TYPING_INTERVAL):
            await services.receipts.parse(user_id, receipt_id)
    except Exception:
        # The service has already recorded the failure; the card shows it.
        logger.exception("Parsing receipt %s failed", receipt_id)
    try:
        await bg.start(
            ReceiptCardSG.main,
            data={TransferKeys.RECEIPT_ID: receipt_id},
            mode=StartMode.RESET_STACK,  # the previous card keeps its keyboard
            show_mode=ShowMode.SEND,
        )
    except Exception:
        logger.exception("Could not send the card of receipt %s", receipt_id)


async def send_reply(
    bot: Bot,
    chat_id: int,
    reply_to: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """A Telegram failure is logged, never raised into the caller."""
    try:
        await bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            reply_parameters=ReplyParameters(message_id=reply_to, allow_sending_without_reply=True),
        )
    except TelegramAPIError:
        logger.exception("Could not send a reply to chat %s", chat_id)
