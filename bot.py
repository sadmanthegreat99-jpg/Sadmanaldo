import asyncio
import json
import logging
import os
from datetime import datetime, timezone
import requests
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ---------------------------------------------------------------------------
# কনফিগারেশন — Railway তে Variables ট্যাব থেকে সেট করা যাবে
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

LAMIX_API_URL = os.environ.get(
    "LAMIX_API_URL", "https://panel.lamix.org/api/v1/messages"
)
DEFAULT_TOKEN = "C57kIlfs-FfhslhXZnaJiM8TD8bNIQ65VtXt0ah3-Nk"

LAMIX_TOKEN = os.environ.get("LAMIX_TOKEN", DEFAULT_TOKEN)

ACCOUNTS = [
    {"label": "Lamix", "token": os.environ.get("LAMIX_TOKEN", DEFAULT_TOKEN)},
    {
        "label": "Agent Panel",
        "token": os.environ.get("LAMIX_TOKEN_2", DEFAULT_TOKEN),
    },
]

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "5"))
SEEN_IDS_FILE = "seen_sms_ids.json"
MAX_SEEN_IDS = 2000

# বট স্টার্ট হওয়ার সঠিক সময় ধরে রাখার জন্য
START_TIME = datetime.now()

# ---------------------------------------------------------------------------
# লগিং
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def check_env_vars():
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if not LAMIX_TOKEN:
        missing.append("LAMIX_TOKEN")

    active_accounts = [a for a in ACCOUNTS if a["token"]]
    if not active_accounts:
        missing.append("LAMIX_TOKEN (অন্তত একটা একাউন্ট টোকেন দরকার)")

    if missing:
        logger.error(
            f"এই Environment Variable(গুলো) সেট করা নেই: {', '.join(missing)}"
        )
        logger.error(
            "Railway Dashboard > Variables ট্যাব থেকে এগুলো যোগ করুন।"
        )
        raise SystemExit(1)


check_env_vars()
bot = Bot(token=TELEGRAM_BOT_TOKEN)


# ---------------------------------------------------------------------------
# seen_sms_ids ডিস্কে সেভ/লোড করার ফাংশন
# ---------------------------------------------------------------------------
def load_seen_ids() -> set:
    if os.path.exists(SEEN_IDS_FILE):
        try:
            with open(SEEN_IDS_FILE, "r") as f:
                data = json.load(f)
                return set(data)
        except Exception as e:
            logger.error(f"seen_sms_ids লোড করতে সমস্যা: {e}")
    return set()


def save_seen_ids(seen_ids: set):
    try:
        if len(seen_ids) > MAX_SEEN_IDS:
            seen_ids = set(list(seen_ids)[-MAX_SEEN_IDS:])
        with open(SEEN_IDS_FILE, "w") as f:
            json.dump(list(seen_ids), f)
    except Exception as e:
        logger.error(f"seen_sms_ids সেভ করতে সমস্যা: {e}")


seen_sms_ids: set = load_seen_ids()


# ---------------------------------------------------------------------------
# API থেকে SMS আনার ফাংশন
# ---------------------------------------------------------------------------
def get_latest_sms(token: str, label: str):
    params = {"token": token}
    try:
        response = requests.get(LAMIX_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and "data" in data:
            return data["data"]
        elif isinstance(data, list):
            return data
    except requests.exceptions.RequestException as e:
        logger.error(f"[{label}] API Fetch Error: {e}")
    except ValueError as e:
        logger.error(f"[{label}] API JSON Parse Error: {e}")

    return []


def escape_markdown(text: str) -> str:
    """Telegram MarkdownV2 স্পেশাল ক্যারেক্টার escape করা"""
    if not text:
        return text
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{ch}" if ch in special_chars else ch for ch in str(text))


# ---------------------------------------------------------------------------
# মূল লুপ
# ---------------------------------------------------------------------------
async def main():
    logger.info("Bot is LIVE & Checking for NEW SMS...")

    try:
        bot_info = await bot.get_me()
        logger.info(f"Telegram Bot connected: @{bot_info.username}")
    except Exception as e:
        logger.error(f"বট টোকেন যাচাই ব্যর্থ হয়েছে: {e}")
        return

    active_accounts = [a for a in ACCOUNTS if a["token"]]

    # -----------------------------------------------------------------------
    # স্টার্টআপ চেক: পুরানো সব মেসেজ আগে Mark/Skip করে নেওয়া
    # -----------------------------------------------------------------------
    logger.info("পুরানো SMS এগুলো চিহ্নিত (skip) করা হচ্ছে...")
    for acc in active_accounts:
        label = acc["label"]
        token = acc["token"]
        existing_sms = get_latest_sms(token, label)
        for sms in existing_sms:
            number = sms.get("num", sms.get("number", "Unknown"))
            message_text = sms.get("message", sms.get("text", ""))
            date_str = sms.get("dt", sms.get("created_at", "N/A"))
            sms_key = f"{label}_{number}_{message_text}_{date_str}"
            seen_sms_ids.add(sms_key)

    save_seen_ids(seen_sms_ids)
    logger.info(
        "পুরানো SMS স্কিপিং সম্পূর্ণ হয়েছে। এখন নতুন OTP/SMS-এর জন্য অপেক্ষা করা হচ্ছে..."
    )

    # -----------------------------------------------------------------------
    # লাইভ লুপ
    # -----------------------------------------------------------------------
    while True:
        try:
            for acc in active_accounts:
                label = acc["label"]
                token = acc["token"]
                try:
                    sms_list = get_latest_sms(token, label)

                    for sms in reversed(sms_list):
                        number = sms.get("num", sms.get("number", "Unknown"))
                        message_text = sms.get(
                            "message", sms.get("text", "")
                        )
                        date_str = sms.get("dt", sms.get("created_at", "N/A"))
                        service_client = sms.get(
                            "cli", sms.get("service", "N/A")
                        )

                        sms_key = f"{label}_{number}_{message_text}_{date_str}"

                        # আগে থেকে প্রসেস করা হয়ে থাকলে স্কিপ করবে
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
                            logger.info(
                                f"নতুন SMS পাঠানো হয়েছে [{label}]: {sms_key}"
                            )

                        except TelegramError as e:
                            logger.error(
                                f"Telegram Send Error ({sms_key}): {e}"
                            )

                except Exception as e:
                    logger.error(f"[{label}] Loop Error: {e}")

        except Exception as e:
            logger.error(f"Global Loop Error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
