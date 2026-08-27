import asyncio
import json
import logging
import os
import requests
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ---------------------------------------------------------------------------
# Environment Variables
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Main/Updated Panel-এর URL
LAMIX_API_URL_1 = os.environ.get(
    "LAMIX_API_URL", "https://panel.lamix.org/api/v1/messages"
)
DEFAULT_TOKEN_1 = "C57kIlfs-FfhslhXZnaJiM8TD8bNIQ65VtXt0ah3-Nk"

# Backdated/Old Panel-এর URL (Railway Variable থেকে 'LAMIX_API_URL_2' যোগ করতে পারেন, না দিলে নিচে সরাসরি ব্যাকডেটেড IP কাজ করবে)
LAMIX_API_URL_2 = os.environ.get(
    "LAMIX_API_URL_2", "http://51.77.216.195/crap/api/lamix/viewstats"
)

ACCOUNTS = []

# Main Panel (Account 1)
token_1 = os.environ.get("LAMIX_TOKEN", DEFAULT_TOKEN_1)
if token_1:
    ACCOUNTS.append({
        "label": "Lamix Main (New)", 
        "token": token_1,
        "url": LAMIX_API_URL_1
    })

# Backdated Panel (Account 2)
token_2 = os.environ.get("LAMIX_TOKEN_2")
if token_2:
    ACCOUNTS.append({
        "label": "Agent Panel (Old)", 
        "token": token_2,
        "url": LAMIX_API_URL_2
    })

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "5"))
SEEN_IDS_FILE = "seen_sms_ids.json"
MAX_SEEN_IDS = 2000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not ACCOUNTS:
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
# API Fetch Function (Independent URL Support)
# ---------------------------------------------------------------------------
async def fetch_sms_for_account(acc: dict) -> list:
    label = acc["label"]
    token = acc["token"]
    api_url = acc["url"]
    params = {"token": token}
    loop = asyncio.get_running_loop()

    try:
        # ৫ সেকেন্ডের টাইমআউট - ব্যাকডেটেড প্যানেল স্লো থাকলে যেন মেইন প্যানেল আটকে না যায়
        response = await loop.run_in_executor(
            None, lambda: requests.get(api_url, params=params, timeout=5)
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and "data" in data:
            return data["data"]
        elif isinstance(data, list):
            return data
    except requests.exceptions.HTTPError as e:
        # ৫০৩ সার্ভার এরর হলে এটি শুধু ওয়ার্নিং দেখাবে, পুরো বট থামবে না
        logger.warning(f"[{label}] API Error/Unavailable: {e}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[{label}] Connection Timeout/Error: {e}")
    except Exception as e:
        logger.error(f"[{label}] Unexpected Error: {e}")

    return []


def escape_markdown(text: str) -> str:
    if not text:
        return ""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{ch}" if ch in special_chars else ch for ch in str(text))


# ---------------------------------------------------------------------------
# SMS Processing Logic
# ---------------------------------------------------------------------------
async def process_account_sms(acc: dict):
    label = acc["label"]
    sms_list = await fetch_sms_for_account(acc)

    for sms in reversed(sms_list):
        number = sms.get("num", sms.get("number", "Unknown"))
        message_text = sms.get("message", sms.get("text", ""))
        date_str = sms.get("dt", sms.get("created_at", "N/A"))
        service_client = sms.get("cli", sms.get("service", "N/A"))

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
            logger.info(f"নতুন SMS পাঠানো হয়েছে [{label}]: {sms_key}")
        except TelegramError as e:
            logger.error(f"Telegram Send Error [{label}]: {e}")


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
    tasks = [fetch_sms_for_account(acc) for acc in ACCOUNTS]
    results = await asyncio.gather(*tasks)

    for idx, sms_list in enumerate(results):
        label = ACCOUNTS[idx]["label"]
        for sms in sms_list:
            number = sms.get("num", sms.get("number", "Unknown"))
            message_text = sms.get("message", sms.get("text", ""))
            date_str = sms.get("dt", sms.get("created_at", "N/A"))
            sms_key = f"{label}_{number}_{message_text}_{date_str}"
            seen_sms_ids.add(sms_key)

    save_seen_ids(seen_sms_ids)
    logger.info("পুরানো SMS স্কিপ সম্পন্ন। লাইভ মনিটরিং শুরু হচ্ছে...")

    # প্যারালাল লাইভ চেক
    while True:
        try:
            await asyncio.gather(
                *(process_account_sms(acc) for acc in ACCOUNTS)
            )
        except Exception as e:
            logger.error(f"Main Loop Error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
