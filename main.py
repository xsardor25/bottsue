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
TOKEN = "8442363419:AAFpVXcRKPhpbk9F33acO1mo7y6py9FRmkk"
ADMIN_ID = 7878916781
JSON_FILE = "tsuedata.json"
SHEET_ID = "1vZLVKA__HPQAL70HfzI0eYu3MpsE-Namho6D-2RLIYw"
CREDENTIALS_FILE = "credentials.json"

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
chat_selected_group = {} 

# --- GOOGLE SHEETS ULANISHI ---
def setup_google_sheets():
    try:
        if not os.path.exists(CREDENTIALS_FILE):
            logging.error(f"❌ {CREDENTIALS_FILE} topilmadi!")
            return None
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
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

# --- SKRINSHOT (PLAYWRIGHT) - RAILWAY UCHUN OPTIMIZATSIYA ---
async def take_screenshot_optimized(url, filename):
    async with async_playwright() as p:
        # Railway uchun eng muhim argumentlar: --no-sandbox va --disable-gpu
        browser = await p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800}, 
            device_scale_factor=2
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            # Keraksiz menyularni o'chirish va bot nomini qo'shish
            await page.add_style_tag(content="""
                .no-print, .main-menu, .sk-header, .footer, #header, .pnl-print-hidden { display: none !important; } 
                .tt-grid-container::after { 
                    content: '@tsuetimebot'; 
                    display: block; 
                    text-align: right; 
                    font-size: 20px; 
                    font-weight: bold; 
                    color: #d1d1d1; 
                    padding: 10px; 
                } 
                body { background: white !important; }
            """)
            target = await page.query_selector(".tt-grid-container")
            if target: 
                await target.screenshot(path=filename)
            else: 
                await page.screenshot(path=filename, full_page=False)
        finally:
            await browser.close()

async def send_auto_timetable(chat_id, url, group):
    filename = f"auto_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        if os.path.exists(filename):
            caption_text = f"🔔 **Avtomatik jadval**\n✅ Guruh: {group}\n🤖 @tsuetimebot"
            await bot.send_photo(chat_id=chat_id, photo=types.FSInputFile(filename), caption=caption_text, parse_mode="Markdown")
            os.remove(filename)
    except Exception as e:
        logging.error(f"❌ Avto-yuborishda xato: {e}")

# --- ADMIN PANEL ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"))
    await message.answer("🛠 **Admin paneliga xush kelibsiz!**", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if sheet_instance:
        try:
            users = sheet_instance.col_values(2)[1:]
            total = len(set(users))
            await callback.message.answer(f"📊 Jami foydalanuvchilar: {total}")
        except:
            await callback.message.answer("Statistika olishda xato.")
    await callback.answer()

# --- FOYDALANUVCHI QISMI ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang_uz"))
    await message.answer(f"Salom! Jadvalni ko'rish uchun fakultetni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "lang_uz")
async def lang_callback(callback: types.CallbackQuery):
    if not os.path.exists(JSON_FILE):
        return await callback.message.answer("Xatolik: Ma'lumotlar bazasi topilmadi!")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for fak in data.keys():
        builder.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    await callback.message.edit_text("Fakultetni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("fak_"))
async def fak_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    fak = callback.data.split("_")[1]
    builder = InlineKeyboardBuilder()
    for kurs in data[fak].keys():
        builder.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak}_{kurs}"))
    await callback.message.edit_text("Kursni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    _, fak, kurs = callback.data.split("_")
    builder = InlineKeyboardBuilder()
    for g_id in data[fak][kurs].keys():
        builder.add(types.InlineKeyboardButton(text=g_id, callback_data=f"gr_{fak}_{kurs}_{g_id}"))
    builder.adjust(3)
    await callback.message.edit_text("Guruhni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("gr_"))
async def group_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    _, fak, kurs, group = callback.data.split("_")
    url = data[fak][kurs][group]
    chat_id = callback.message.chat.id
    chat_selected_group[chat_id] = {"url": url, "group": group}
    
    save_user_log(callback.from_user.id, callback.from_user.username, callback.from_user.full_name, fak, group)
    
    status_msg = await callback.message.answer(f"⏳ **{group}** jadvali tayyorlanmoqda...")
    filename = f"t_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        if os.path.exists(filename):
            await callback.message.answer_photo(
                photo=types.FSInputFile(filename), 
                caption=f"✅ **Guruh:** {group}\n🤖 @tsuetimebot"
            )
            os.remove(filename)
    except Exception as e:
        await callback.message.answer(f"❌ Xatolik yuz berdi: {e}")
    finally:
        await status_msg.delete()

async def main():
    scheduler.start()
    logging.info("🚀 Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

