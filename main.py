import json
import asyncio
import os
import logging
import warnings
import gspread
import re 
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from playwright.async_api import async_playwright
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Logs sozlamalari
logging.basicConfig(level=logging.INFO)
warnings.filterwarnings("ignore", category=UserWarning)

# --- SOZLAMALAR ---
# Tokenni to'g'ridan-to'g'ri shu yerga yozdik
TOKEN = "8442363419:AAFpVXcRKPhpbk9F33acO1mo7y6py9FRmkk"
ADMIN_ID = 7878916781
SHEET_ID = "1vZLVKA__HPQAL70HfzI0eYu3MpsE-Namho6D-2RLIYw"
JSON_FILE = "tsuedata.json"
CREDENTIALS_FILE = "credentials.json"

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
chat_selected_group = {} 

# --- GOOGLE SHEETS ULANISHI ---
def setup_google_sheets():
    try:
        # Fayl nomi 'credentials.json' yoki 'Credentials.json' bo'lishi mumkin
        c_file = CREDENTIALS_FILE if os.path.exists(CREDENTIALS_FILE) else "Credentials.json"
        if not os.path.exists(c_file):
            logging.error(f"❌ {c_file} topilmadi!")
            return None
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(c_file, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        logging.error(f"❌ Google Sheets xatosi: {e}")
        return None

sheet_instance = setup_google_sheets()

def save_user_log(user_id, username, full_name, faculty, group):
    global sheet_instance
    if sheet_instance is None: sheet_instance = setup_google_sheets()
    if sheet_instance:
        try:
            now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            uname = f"@{username}" if username else "Mavjud emas"
            sheet_instance.append_row([now, str(user_id), uname, full_name, faculty, group])
        except Exception as e:
            logging.error(f"❌ Log xatosi: {e}")

# --- SKRINSHOT (PLAYWRIGHT) ---
async def take_screenshot_optimized(url, filename):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"])
        context = await browser.new_context(viewport={'width': 1280, 'height': 800}, device_scale_factor=2)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.add_style_tag(content=".no-print, .main-menu, .footer, #header { display: none !important; } body { background: white !important; }")
            target = await page.query_selector(".tt-grid-container")
            if target: 
                await target.screenshot(path=filename)
            else: 
                await page.screenshot(path=filename)
        finally:
            await browser.close()

async def send_auto_timetable(chat_id, url, group):
    filename = f"auto_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        if os.path.exists(filename):
            await bot.send_photo(chat_id=chat_id, photo=types.FSInputFile(filename), caption=f"🔔 **Avto-jadval**\n✅ Guruh: {group}")
            os.remove(filename)
    except Exception as e:
        logging.error(f"❌ Avto-yuborishda xato: {e}")

# --- BOT FUNKSIYALARI ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.add(types.InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang_uz"))
    await message.answer("Assalomu alaykum! Jadvalni ko'rish uchun tilni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "lang_uz")
async def lang_callback(callback: types.CallbackQuery):
    if not os.path.exists(JSON_FILE):
        return await callback.message.answer(f"❌ {JSON_FILE} topilmadi!")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    kb = InlineKeyboardBuilder()
    for fak in data.keys():
        kb.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    await callback.message.edit_text("Fakultetni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("fak_"))
async def fak_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    fak = callback.data.split("_")[1]
    kb = InlineKeyboardBuilder()
    for kurs in data[fak].keys():
        kb.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak}_{kurs}"))
    await callback.message.edit_text("Kursni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    _, fak, kurs = callback.data.split("_")
    kb = InlineKeyboardBuilder()
    for group in data[fak][kurs].keys():
        kb.add(types.InlineKeyboardButton(text=group, callback_data=f"gr_{fak}_{kurs}_{group}"))
    kb.adjust(3)
    await callback.message.edit_text("Guruhni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("gr_"))
async def group_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    _, fak, kurs, group = callback.data.split("_")
    url = data[fak][kurs][group]
    chat_id = callback.message.chat.id
    chat_selected_group[chat_id] = {"url": url, "group": group}
    
    save_user_log(callback.from_user.id, callback.from_user.username, callback.from_user.full_name, fak, group)
    
    status = await callback.message.answer(f"⏳ **{group}** jadvali yuklanmoqda...")
    filename = f"t_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        await callback.message.answer_photo(photo=types.FSInputFile(filename), caption=f"✅ Guruh: {group}\n🤖 @tsuetimebot")
        if os.path.exists(filename): os.remove(filename)
    except Exception as e:
        await callback.message.answer(f"❌ Xato: {e}")
    finally:
        await status.delete()

async def main():
    scheduler.start()
    logging.info("🚀 Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
