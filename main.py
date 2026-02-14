import json
import asyncio
import os
import logging
import warnings
import gspread
import time
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from playwright.async_api import async_playwright
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Logs
logging.basicConfig(level=logging.INFO)
warnings.filterwarnings("ignore", category=UserWarning)

# --- SOZLAMALAR ---
TOKEN = "8442363419:AAFpVXcRKPhpbk9F33acO1mo7y6py9FRmkk"
JSON_FILE = "tsuedata.json"
SHEET_ID = "1vZLVKA__HPQAL70HfzI0eYu3MpsE-Namho6D-2RLIYw"
CREDENTIALS_FILE = "credentials.json"

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- XOTIRA ---
screenshot_cache = {} 
user_settings = {}    
favorites_db = {}     
group_schedules = {} # {chat_id: {"url": url, "day": 6, "time": "08:00"}}

DAYS = {
    0: "Dushanba", 1: "Seshanba", 2: "Chorshanba", 
    3: "Payshanba", 4: "Juma", 5: "Shanba", 6: "Yakshanba"
}

MESSAGES = {
    'uz': {
        'start': "Assalomu alaykum! Fakultetni tanlang:",
        'select_day': "Haftaning qaysi kuni jadval yuborilsin?",
        'select_time': "Soat nechida? (Masalan: 08:00)",
        'group_saved': "✅ Guruh sozlamalari saqlandi! Har {day} kuni soat {time}da jadval yuboriladi.",
        'loading': "⏳ Jadval tayyorlanmoqda...",
        'menu': "🏠 Asosiy menyu",
        'fav_btn': "⭐ Sevimlilarga saqlash",
        'error': "❌ Xatolik yuz berdi."
    }
}

# --- GOOGLE SHEETS ---
def setup_google_sheets():
    try:
        if not os.path.exists(CREDENTIALS_FILE): return None
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except: return None

sheet_instance = setup_google_sheets()

# --- SKRINSHOT ---
async def take_screenshot_optimized(url, filename):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        context = await browser.new_context(viewport={'width': 1280, 'height': 800}, device_scale_factor=2)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.add_style_tag(content=".no-print, .main-menu, .footer, #header { display: none !important; } body { background: white !important; }")
            target = await page.query_selector(".tt-grid-container")
            if target: await target.screenshot(path=filename)
            else: await page.screenshot(path=filename)
        finally: await browser.close()

# --- AVTOMATIK YUBORISH (SCHEDULER) ---
async def send_auto_timetable(chat_id, url, group_name):
    filename = f"auto_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        photo = types.FSInputFile(filename)
        await bot.send_photo(chat_id, photo, caption=f"🔔 Haftalik avtomatik jadval\n👥 Guruh: {group_name}")
        os.remove(filename)
    except Exception as e:
        logging.error(f"Auto-send error: {e}")

# --- HANDLERLAR ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    # Chat turini tekshirish (Guruh yoki Shaxsiy)
    is_group = message.chat.type in ["group", "supergroup"]
    
    builder = InlineKeyboardBuilder()
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    for fak in data.keys():
        builder.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    
    await message.answer(MESSAGES['uz']['start'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("fak_"))
async def fak_select(callback: types.CallbackQuery):
    fak = callback.data.split("_")[1]
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for kurs in data[fak].keys():
        builder.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak}_{kurs}"))
    await callback.message.edit_text("Kursni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_select(callback: types.CallbackQuery):
    _, fak, kurs = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for g_id in data[fak][kurs].keys():
        builder.add(types.InlineKeyboardButton(text=g_id, callback_data=f"gr_{fak}_{kurs}_{g_id}"))
    builder.adjust(3)
    await callback.message.edit_text("Guruhni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("gr_"))
async def group_select(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    _, fak, kurs, group = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    url = data[fak][kurs][group]

    if callback.message.chat.type in ["group", "supergroup"]:
        # Guruh bo'lsa - kunni tanlashga o'tamiz
        builder = InlineKeyboardBuilder()
        for i, name in DAYS.items():
            builder.row(types.InlineKeyboardButton(text=name, callback_data=f"day_{i}_{group}_{fak}_{kurs}"))
        await callback.message.edit_text(MESSAGES['uz']['select_day'], reply_markup=builder.as_markup())
    else:
        # Shaxsiy bo'lsa - odatdagidek jadval yuboramiz
        await send_timetable_logic(chat_id, url, group, 'uz')

@dp.callback_query(F.data.startswith("day_"))
async def day_select(callback: types.CallbackQuery):
    _, day_idx, group, fak, kurs = callback.data.split("_")
    # Vaqtni tanlash (oddiy misol uchun 08:00 dan 10:00 gacha variantlar)
    builder = InlineKeyboardBuilder()
    times = ["08:00", "08:30", "09:00", "19:41"] # Test uchun hozirgi vaqtingizga yaqinini qo'shing
    for t in times:
        builder.add(types.InlineKeyboardButton(text=t, callback_data=f"set_{day_idx}_{t}_{group}_{fak}_{kurs}"))
    await callback.message.edit_text(MESSAGES['uz']['select_time'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("set_"))
async def final_set(callback: types.CallbackQuery):
    _, day_idx, v_time, group, fak, kurs = callback.data.split("_")
    chat_id = callback.message.chat.id
    
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    url = data[fak][kurs][group]
    
    # Schedulerga qo'shish
    h, m = map(int, v_time.split(":"))
    job_id = f"job_{chat_id}"
    
    # Eski job bo'lsa o'chirish
    if scheduler.get_job(job_id): scheduler.remove_job(job_id)
    
    scheduler.add_job(
        send_auto_timetable, 
        "cron", 
        day_of_week=int(day_idx), 
        hour=h, 
        minute=m, 
        args=[chat_id, url, group],
        id=job_id
    )
    
    res_text = MESSAGES['uz']['group_saved'].format(day=DAYS[int(day_idx)], time=v_time)
    await callback.message.edit_text(res_text)

async def send_timetable_logic(chat_id, url, group, lang):
    # (Bu yerda avvalgi send_timetable kodini ishlatsangiz bo'ladi)
    status = await bot.send_message(chat_id, MESSAGES[lang]['loading'])
    filename = f"t_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        await bot.send_photo(chat_id, types.FSInputFile(filename), caption=f"✅ {group}")
        os.remove(filename)
    finally: await status.delete()

async def main():
    scheduler.start()
    logging.info("🚀 Scheduler va Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
