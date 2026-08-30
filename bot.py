import asyncio
import json
import logging
import os
import requests
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ---------------------------------------------------------------------------
# Environment Variables & Configuration
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

LAMIX_API_URL = os.environ.get(
    "LAMIX_API_URL", "https://panel.lamix.org/api/v1/messages"
).strip()

DEFAULT_TOKEN = "C57kIlfs-FfhslhXZnaJiM8TD8bNIQ65VtXt0ah3-Nk"
LAMIX_TOKEN = os.environ.get("LAMIX_TOKEN", DEFAULT_TOKEN).strip()

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "10"))
SEEN_IDS_FILE = "seen_sms_ids.json"
MAX_SEEN_IDS = 2000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not LAMIX_TOKEN:
    logger.error("প্রয়োজনীয় Environment Variables পাওয়া যায়নি!")
    raise SystemExit(1)

bot = Bot(token=TELEGRAM_BOT_TOKEN)


# ---------------------------------------------------------------------------
# Persistence Helpers
# ---------------------------------------------------------------------------
def load_seen_ids() -> set:
    if os.path.exists(SEEN_IDS_FILE):
        try:
            with open(SEEN_IDS_FILE, "r") as f:
                return set(json.load(f))
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
# API Fetch Function
# ---------------------------------------------------------------------------
async def fetch_sms() -> list:
    # URL এর সাথে সরাসরি token প্যারামিটার যোগ করা
    url = f"{LAMIX_API_URL}?token={LAMIX_TOKEN}" if "?" not in LAMIX_API_URL else f"{LAMIX_API_URL}&token={LAMIX_TOKEN}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    loop = asyncio.get_running_loop()

    try:
        response = await loop.run_in_executor(
            None, lambda: requests.get(url, headers=headers, timeout=15)
        )

        if response.status_code == 429:
            logger.warning("[Lamix Panel] Rate Limit (429)! Waiting 20s...")
            await asyncio.sleep(20)
            return []

        # যদি কোনো কারণে 200 OK না আসে
        if response.status_code != 200:
            logger.warning(f"[Lamix Panel] API Status Code: {response.status_code} | Text: {response.text[:100]}")
            return []

        # রেসপন্স খালি কিনা চেক
        if not response.text or not response.text.strip():
            logger.warning("[Lamix Panel] Received empty response from server.")
            return []

        # JSON পার্স করার চেষ্টা
        try:
            data = response.json()
        except Exception:
            logger.warning(f"[Lamix Panel] Non-JSON Response received: {response.text[:100]}")
            return []

        if isinstance(data, dict) and "records" in data:
            return data["records"]
        elif isinstance(data, list):
            return data

    except requests.exceptions.RequestException as e:
        logger.warning(f"[Lamix Panel] Network/Connection Error: {e}")
    except Exception as e:
        logger.error(f"[Lamix Panel] Unexpected Error: {e}")

    return []


def escape_markdown(text: str) -> str:
    if not text:
        return ""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{ch}" if ch in special_chars else ch for ch in str(text))


# ---------------------------------------------------------------------------
# SMS Processing Logic
# ---------------------------------------------------------------------------
async def process_sms():
    sms_list = await fetch_sms()

    for sms in reversed(sms_list):
        number = sms.get("number", "Unknown")
        message_text = sms.get("content", sms.get("message", ""))
        date_str = sms.get("time", sms.get("created_at", "N/A"))
        service_client = sms.get("cli", "N/A")

        sms_key = f"Lamix_{number}_{message_text}_{date_str}"

        if sms_key in seen_sms_ids:
            continue

        telegram_msg = (
            f"🔔 *New SMS Received* \\(Lamix Main\\)\n\n"
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
            logger.info(f"নতুন SMS পাঠানো হয়েছে [Lamix Main]: {sms_key}")
        except TelegramError as e:
            logger.error(f"Telegram Send Error: {e}")


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------
async def main():
    logger.info("Bot is LIVE & Checking for NEW SMS...")

    try:
        bot_info = await bot.get_me()
        logger.info(f"Telegram Bot connected: @{bot_info.username}")
    except Exception as e:
        logger.error(f"বট টোকেন কাজ করছে না: {e}")
        return

    # পুরানো মেসেজ স্কিপিং
    logger.info("পুরানো SMS চিহ্নিত (Skip) করা হচ্ছে...")
    sms_list = await fetch_sms()
    for sms in sms_list:
        number = sms.get("number", "Unknown")
        message_text = sms.get("content", sms.get("message", ""))
        date_str = sms.get("time", sms.get("created_at", "N/A"))
        sms_key = f"Lamix_{number}_{message_text}_{date_str}"
        seen_sms_ids.add(sms_key)

    save_seen_ids(seen_sms_ids)
    logger.info("পুরানো SMS স্কিপ সম্পন্ন। লাইভ মনিটরিং শুরু হচ্ছে...")

    # লাইভ চেক লুপ
    while True:
        try:
            await process_sms()
        except Exception as e:
            logger.error(f"Main Loop Error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
