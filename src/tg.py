import os

from telegram import Bot

TG_BOT_ACCESS_TOKEN = os.getenv("TG_BOT_ACCESS_TOKEN", "")
if TG_BOT_ACCESS_TOKEN == "":
    raise RuntimeError("!TG_BOT_ACCESS_TOKEN")

TG_GROUP_CHAT_ID = int(os.getenv("TG_GROUP_CHAT_ID", "0"))
if TG_GROUP_CHAT_ID == 0:
    raise RuntimeError("!TG_GROUP_CHAT_ID")


async def notify_group_chat(
    text: str,
    parse_mode: str = "HTML",
    chat_id: int = TG_GROUP_CHAT_ID,
    disable_web_page_preview: bool = True,
) -> None:
    try:
        bot = Bot(token=TG_BOT_ACCESS_TOKEN)
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except Exception as e:
        print(f"Failed to send message to group chat: {e}")