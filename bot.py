import asyncio
import json
import os
import logging
from datetime import datetime
import requests
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
LAMIX_API_URL = os.environ.get("LAMIX_API_URL", "http://51.77.216.195/crapi/lamix/viewstats")

ACCOUNTS = [
    {"label": "Lamix", "token": os.environ.get("LAMIX_TOKEN")},
    {"label": "Agent Panel", "token": os.environ.get("LAMIX_TOKEN_2")},
]

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "5"))
SEEN_IDS_FILE = "seen_sms_ids.json"
MAX_SEEN_IDS = 2000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("lamix_bot")


def check_env_vars():
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    active_accounts = [a for a in ACCOUNTS if a["token"]]
    if not active_accounts:
        missing.append("LAMIX_TOKEN (অন্তত একটা একাউন্ট টোকেন দরকার)")

    if missing:
        logger.error(f"এই Environment Variable(গুলো) সেট করা নেই: {', '.join(missing)}")
        logger.error("Railway Dashboard > Variables ট্যাব থেকে এগুলো যোগ করুন।")
        raise SystemExit(1)

    for acc in ACCOUNTS:
        if not acc["token"]:
            logger.warning(f"'{acc['label']}' একাউন্টের টোকেন নেই — এটা স্কিপ করা হবে।")


check_env_vars()
bot = Bot(token=TELEGRAM_BOT_TOKEN)


def load_seen_ids() -> set:
    if os.path.exists(SEEN_IDS_FILE):
        try:
            with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"seen_sms_ids ফাইল লোড করতে সমস্যা হয়েছে: {e}")
    return set()


def save_seen_ids(seen_ids: set):
    try:
        trimmed = list(seen_ids)[-MAX_SEEN_IDS:]
        with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f)
    except Exception as e:
        logger.warning(f"seen_sms_ids ফাইল সেভ করতে সমস্যা হয়েছে: {e}")


seen_sms_ids: set = load_seen_ids()


def get_latest_sms(token: str, label: str):
    today = datetime.now().strftime("%Y-%m-%d")
    params = {
        "token": token,
        "dt1": f"{today} 00:00:00",
        "dt2": f"{today} 23:59:59",
        "records": "10",
    }
    try:
        response = requests.get(LAMIX_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and data.get("status") == "success" and isinstance(data.get("data"), list):
            return data["data"]
        elif isinstance(data, list):
            return data
        else:
            logger.warning(f"[{label}] অপ্রত্যাশিত API রেসপন্স ফরম্যাট: {data}")
    except requests.exceptions.RequestException as e:
        logger.error(f"[{label}] API Fetch Error: {e}")
    except ValueError as e:
        logger.error(f"[{label}] API JSON Parse Error: {e}")

    return []


def escape_markdown(text: str) -> str:
    if not text:
        return text
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{ch}" if ch in special_chars else ch for ch in str(text))


async def main():
    logger.info("Bot is LIVE & Checking for new SMS...")

    try:
        me = await bot.get_me()
        logger.info(f"বট কানেক্টেড হয়েছে: @{me.username}")
    except TelegramError as e:
        logger.error(f"বট টোকেন যাচাই ব্যর্থ হয়েছে: {e}")
        return

    active_accounts = [a for a in ACCOUNTS if a["token"]]

    while True:
        for acc in active_accounts:
            label = acc["label"]
            token = acc["token"]
            try:
                sms_list = get_latest_sms(token, label)

                for sms in reversed(sms_list):
                    number = sms.get("num", "Unknown")
                    message_text = sms.get("message", "")
                    date_str = sms.get("dt", "N/A")
                    service_client = sms.get("cli", "N/A")

                    sms_key = f"{label}_{number}_{message_text}_{date_str}"

                    if sms_key in seen_sms_ids:
                        continue

                    telegram_msg = (
                        f"🔔 *New SMS Received* \\({escape_markdown(label)}\\)\n\n"
                        f"📱 *Number:* `{escape_markdown(number)}`\n"
                        f"🏢 *Service:* {escape_markdown(service_client)}\n"
                        f"💬 *SMS:* {escape_markdown(message_text)}\n"
                        f"⏰ *Time:* {escape_markdown(date_str)}"
                    )

                    try:
                        await bot.send_message(
                            chat_id=TELEGRAM_CHAT_ID,
                            text=telegram_msg,
                            parse_mode=ParseMode.MARKDOWN_V2,
                        )
                        seen_sms_ids.add(sms_key)
                        save_seen_ids(seen_sms_ids)
                        logger.info(f"পাঠানো হয়েছে [{label}]: {sms_key}")

                    except TelegramError as e:
                        logger.error(f"Telegram Send Error ({sms_key}): {e}")

            except Exception as e:
                logger.error(f"[{label}] Loop Error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("বট বন্ধ করা হয়েছে।")
