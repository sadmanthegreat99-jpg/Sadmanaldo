import asyncio
import time
import requests
from telegram import Bot

TELEGRAM_BOT_TOKEN = "8809488487:AAE_8aTbFgBUnym-KDsMVvWnSJ7Dn0lhO88"
TELEGRAM_CHAT_ID = "-1003999914043"
LAMIX_API_URL = "http://51.77.216.195/crapi/lamix/viewstats"
LAMIX_TOKEN = "iZKYSleJgIdkalaLV19YdEhVj1R8YWVfQ2pWXEeRgFU"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
seen_sms_ids = set()


def get_latest_sms():
    today = time.strftime("%Y-%m-%d")
    params = {
        "token": LAMIX_TOKEN,
        "dt1": f"{today} 00:00:00",
        "dt2": f"{today} 23:59:59",
        "records": "5",
    }
    try:
        response = requests.get(LAMIX_API_URL, params=params, timeout=10)
        data = response.json()
        if data.get("status") != "error" and "data" in data:
            return data["data"]
    except Exception as e:
        print(f"API Error: {e}")
    return []


async def main():
    print("Bot is LIVE & Checking for new SMS...")
    while True:
        sms_list = get_latest_sms()
        for sms in sms_list:
            sms_key = f"{sms.get('number')}_{sms.get('msg')}"
            if sms_key not in seen_sms_ids:
                seen_sms_ids.add(sms_key)

                message = (
                    f"🔔 **New SMS Received**\n\n"
                    f"📱 **Number:** `{sms.get('number')}`\n"
                    f"💬 **SMS:** {sms.get('msg')}\n"
                    f"⏰ **Time:** {sms.get('date')}"
                )
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown"
                )

        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
