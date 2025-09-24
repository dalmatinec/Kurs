import asyncio
import logging
import json
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import aiohttp
from datetime import datetime
import xml.etree.ElementTree as ET
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import sqlite3
import time

API_TOKEN = "7951894150:AAFOX6FvOpqnA6t9Od1NeTFyERYYLuaKPY0"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# --- SQLite ---
conn = sqlite3.connect("subscribers.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS subscribers (chat_id INTEGER PRIMARY KEY)")
conn.commit()

# --- Антиспам ---
last_request = {}  # {user_id: {"cbr": timestamp, "nbk": timestamp, "other": timestamp}}
LIMIT_SECONDS = 15

def check_limit(user_id, key):
    now = time.time()
    if user_id in last_request and key in last_request[user_id]:
        if now - last_request[user_id][key] < LIMIT_SECONDS:
            return False
    if user_id not in last_request:
        last_request[user_id] = {}
    last_request[user_id][key] = now
    return True

# --- Кнопки ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Курс ЦБ РФ"), KeyboardButton(text="📊 Курс НБ РК")],
        [KeyboardButton(text="🌍 Остальные валюты")],
        [KeyboardButton(text="🔔 Подписка на уведомления")]
    ],
    resize_keyboard=True
)

# --- Получение курсов ЦБ РФ ---
async def get_cbr_rates():
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            text = await resp.text()
            data = json.loads(text)
            return data["Valute"]

# --- Получение курсов НБ РК ---
async def get_nbk_rates():
    url = "https://nationalbank.kz/rss/get_rates.cfm?fdate=" + datetime.now().strftime("%d.%m.%Y")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            text = await resp.text()
            root = ET.fromstring(text)
            rates = {}
            for item in root.findall("item"):
                title = item.find("title").text
                description = item.find("description").text
                rates[title] = float(description.replace(",", "."))
            return rates

# --- Форматирование ЦБ РФ ---
def format_cbr(rates):
    usd = rates["USD"]["Value"]
    eur = rates["EUR"]["Value"]
    kzt = rates["KZT"]["Value"]
    rub = 1
    today = datetime.now(pytz.timezone("Asia/Almaty")).strftime("%d.%m.%Y")
    return (
        f"📅 Курс ЦБ РФ ({today})\n\n"
        f"🇺🇸 1 USD | {usd:.2f} ₽\n"
        f"🇪🇺 1 EUR | {eur:.2f} ₽\n"
        f"🇰🇿 100 KZT | {kzt*100:.2f} ₽\n"
        f"🇷🇺 1 RUB | {rub} ₽"
    )

# --- Форматирование НБ РК ---
def format_nbk(rates):
    usd = rates["USD"]
    eur = rates["EUR"]
    rub = rates["RUB"]
    kzt = 1
    today = datetime.now(pytz.timezone("Asia/Almaty")).strftime("%d.%m.%Y")
    return (
        f"📅 Курс НБ РК ({today})\n\n"
        f"🇺🇸 1 USD | {usd:.2f} ₸\n"
        f"🇪🇺 1 EUR | {eur:.2f} ₸\n"
        f"🇷🇺 1 RUB | {rub:.2f} ₸\n"
        f"🇰🇿 1 KZT | {kzt} ₸"
    )

# --- Остальные валюты по НБ РК ---
def format_other_nbk(rates):
    today = datetime.now(pytz.timezone("Asia/Almaty")).strftime("%d.%m.%Y")
    other = {
        "🇧🇾": "BYN",
        "🇺🇦": "UAH",
        "🇺🇿": "UZS",
        "🇰🇬": "KGS",
        "🇹🇭": "THB",
        "🇹🇷": "TRY",
    }
    text = f"📅 Остальные валюты ({today})\n<i>(данные НБ РК)</i>\n\n"
    for flag, code in other.items():
        if code in rates:
            value = rates[code]
            text += f"{flag} 1 {code} | {value:.2f} ₸\n"
    return text

# --- Хэндлеры ---
@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer("Выберите действие:", reply_markup=main_kb)

@dp.message(F.text == "📊 Курс ЦБ РФ")
async def show_cbr(message: Message):
    if not check_limit(message.chat.id, "cbr"):
        return await message.answer("⏳ Слишком часто, попробуйте позже.")
    rates = await get_cbr_rates()
    await message.answer(format_cbr(rates))

@dp.message(F.text == "📊 Курс НБ РК")
async def show_nbk(message: Message):
    if not check_limit(message.chat.id, "nbk"):
        return await message.answer("⏳ Слишком часто, попробуйте позже.")
    rates = await get_nbk_rates()
    await message.answer(format_nbk(rates))

@dp.message(F.text == "🌍 Остальные валюты")
async def show_other(message: Message):
    if not check_limit(message.chat.id, "other"):
        return await message.answer("⏳ Слишком часто, попробуйте позже.")
    rates = await get_nbk_rates()
    await message.answer(format_other_nbk(rates))

@dp.message(F.text == "🔔 Подписка на уведомления")
async def subscription_menu(message: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подписаться", callback_data="subscribe")],
            [InlineKeyboardButton(text="❌ Отписаться", callback_data="unsubscribe")]
        ]
    )
    await message.answer(
        "📢 Уведомления приходят каждый день в 09:30 по времени Астаны.\nИсточник: НБ РК.",
        reply_markup=kb
    )

@dp.callback_query(F.data == "subscribe")
async def subscribe(call):
    await call.answer()  # 🔹 фикс мигания кнопки
    cursor.execute("SELECT 1 FROM subscribers WHERE chat_id=?", (call.message.chat.id,))
    if cursor.fetchone():
        await call.message.answer("⚠️ Вы уже подписаны на уведомления.")
    else:
        cursor.execute("INSERT INTO subscribers (chat_id) VALUES (?)", (call.message.chat.id,))
        conn.commit()
        await call.message.answer("✅ Вы подписались на ежедневные уведомления.")

@dp.callback_query(F.data == "unsubscribe")
async def unsubscribe(call):
    await call.answer()  # 🔹 фикс мигания кнопки
    cursor.execute("SELECT 1 FROM subscribers WHERE chat_id=?", (call.message.chat.id,))
    if cursor.fetchone():
        cursor.execute("DELETE FROM subscribers WHERE chat_id=?", (call.message.chat.id,))
        conn.commit()
        await call.message.answer("❌ Вы отписались от уведомлений.")
    else:
        await call.message.answer("⚠️ Вы не подписаны на уведомления.")

# --- Рассылка ---
async def send_daily_rates():
    cursor.execute("SELECT chat_id FROM subscribers")
    subs = cursor.fetchall()
    if not subs:
        return
    rates = await get_nbk_rates()
    text = format_nbk(rates)
    for (chat_id,) in subs:
        try:
            await bot.send_message(chat_id, "📢 Ежедневное уведомление:\n\n" + text)
            await asyncio.sleep(0.05)  # антифлуд
        except Exception as e:
            logging.error(f"Ошибка отправки {chat_id}: {e}")

# --- Запуск ---
async def main():
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Almaty"))
    scheduler.add_job(send_daily_rates, CronTrigger(hour=9, minute=30))
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
