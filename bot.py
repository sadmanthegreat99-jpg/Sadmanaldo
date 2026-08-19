import asyncio
import requests
from telegram import Bot

TELEGRAM_BOT_TOKEN = "8809488487:AAE_8aTbFgBUnym-KDsMVvWnSJ7Dn0lhO88"
TELEGRAM_CHAT_ID = "-1003999914043"
LAMIX_API_URL = "http://51.77.216.195/crapi/lamix/viewstats"
LAMIX_TOKEN = "iZKYSleJgIdkalaLV19YdEhVj1R8YWVfQ2pWXEeRgFU="

bot = Bot(token=TELEGRAM_BOT_TOKEN)
seen_sms_ids = set()


def get_latest_sms():
    params = {
        "token": LAMIX_TOKEN,
        "records": "10",
    }
    try:
        response = requests.get(LAMIX_API_URL, params=params, timeout=10)
        data = response.json()

        if data.get("status") == "success" and isinstance(data.get("data"), list):
            return data["data"]
        elif isinstance(data, list):
            return data
    except Exception as e:
        print(f"API Fetch Error: {e}")

    return []


async def main():
    print("Bot is LIVE & Checking for new SMS...")
    while True:
        try:
            sms_list = get_latest_sms()
            for sms in sms_list:
                number = sms.get("num", "Unknown")
                message_text = sms.get("message", "")
                date_str = sms.get("dt", "N/A")
                service_client = sms.get("cli", "N/A")

                sms_key = f"{number}_{message_text}_{date_str}"

                if sms_key not in seen_sms_ids:
                    seen_sms_ids.add(sms_key)

                    telegram_msg = (
                        f"🔔 *New SMS Received*\n\n"
                        f"📱 *Number:* `{number}`\n"
                        f"🏢 *Service:* {service_client}\n"
                        f"💬 *SMS:* {message_text}\n"
                        f"⏰ *Time:* {date_str}"
                    )

                    await bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        text=telegram_msg,
                        parse_mode="Markdown",
                    )
        except Exception as e:
            print(f"Loop Error: {e}")

        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
