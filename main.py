import json
import asyncio
import os
import logging
import warnings
import gspread
import re
import time
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

# Kesh va foydalanuvchi ma'lumotlari (Xotirada vaqtinchalik saqlash)
screenshot_cache = {}  # {url: {"file_id": id, "time": timestamp}}
user_settings = {}     # {user_id: {"lang": "uz", "fav_url": url, "fav_name": name}}

# --- MULTILINGUAL (KO'P TILLI TIZIM) ---
MESSAGES = {
    'uz': {
        'start': "Assalomu alaykum! Fakultetni tanlang:",
        'select_kurs': "Kursni tanlang:",
        'select_group': "Guruhni tanlang:",
        'loading': "⏳ Jadval tayyorlanmoqda...",
        'fav_btn': "⭐ Sevimlilarga qo'shish",
        'fav_saved': "✅ Guruh sevimlilarga qo'shildi! Endi /my_table buyrug'ini ishlatishingiz mumkin.",
        'my_table_err': "❌ Sizda sevimli guruh saqlanmagan. Avval guruhni tanlang va ⭐ tugmasini bosing.",
        'update': "🔄 Yangilash",
        'menu': "🏠 Asosiy menyu"
    },
    'ru': {
        'start': "Здравствуйте! Выберите факультет:",
        'select_kurs': "Выберите курс:",
        'select_group': "Выберите группу:",
        'loading': "⏳ Расписание готовится...",
        'fav_btn': "⭐ Добавить в избранное",
        'fav_saved': "✅ Группа добавлена в избранное! Теперь вы можете использовать /my_table.",
        'my_table_err': "❌ У вас нет избранной группы. Сначала выберите группу и нажмите ⭐.",
        'update': "🔄 Обновить",
        'menu': "🏠 Главное меню"
    }
}

# --- GOOGLE SHEETS ---
def setup_google_sheets():
    try:
        if not os.path.exists(CREDENTIALS_FILE): return None
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID)
    except Exception as e:
        logging.error(f"❌ Sheets xatosi: {e}")
        return None

gs_client = setup_google_sheets()

def save_favorite_to_gs(user_id, group_name, url):
    try:
        sheet = gs_client.worksheet("Favorites")
        cells = sheet.col_values(1)
        if str(user_id) in cells:
            row_idx = cells.index(str(user_id)) + 1
            sheet.update_cell(row_idx, 2, group_name)
            sheet.update_cell(row_idx, 3, url)
        else:
            sheet.append_row([str(user_id), group_name, url])
    except: pass

# --- SKRINSHOT VA KESHLASH ---
async def take_screenshot_optimized(url, filename):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        context = await browser.new_context(viewport={'width': 1280, 'height': 800}, device_scale_factor=2)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.add_style_tag(content=".no-print, .main-menu, .footer, #header { display: none !important; }")
            target = await page.query_selector(".tt-grid-container")
            if target: await target.screenshot(path=filename)
            else: await page.screenshot(path=filename)
        finally:
            await browser.close()

# --- HANDLERLAR ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang_uz"))
    builder.row(types.InlineKeyboardButton(text="🇷🇺 Русский язык", callback_data="lang_ru"))
    await message.answer("Tilni tanlang / Выберите язык:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("lang_"))
async def lang_callback(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_settings[callback.from_user.id] = {"lang": lang}
    
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for fak in data.keys():
        builder.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    
    await callback.message.edit_text(MESSAGES[lang]['start'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("fak_"))
async def fak_callback(callback: types.CallbackQuery):
    lang = user_settings.get(callback.from_user.id, {}).get('lang', 'uz')
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    fak = callback.data.split("_")[1]
    builder = InlineKeyboardBuilder()
    for kurs in data[fak].keys():
        builder.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak}_{kurs}"))
    await callback.message.edit_text(MESSAGES[lang]['select_kurs'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_callback(callback: types.CallbackQuery):
    lang = user_settings.get(callback.from_user.id, {}).get('lang', 'uz')
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    _, fak, kurs = callback.data.split("_")
    builder = InlineKeyboardBuilder()
    for g_id in data[fak][kurs].keys():
        builder.add(types.InlineKeyboardButton(text=g_id, callback_data=f"gr_{fak}_{kurs}_{g_id}"))
    builder.adjust(3)
    await callback.message.edit_text(MESSAGES[lang]['select_group'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("gr_"))
async def group_callback(callback: types.CallbackQuery):
    lang = user_settings.get(callback.from_user.id, {}).get('lang', 'uz')
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    _, fak, kurs, group = callback.data.split("_")
    url = data[fak][kurs][group]
    
    await process_timetable_send(callback.message, url, group, lang)

async def process_timetable_send(message, url, group, lang):
    # 1. Keshni tekshirish (1 soat = 3600 sek)
    now = time.time()
    if url in screenshot_cache and (now - screenshot_cache[url]['time']) < 3600:
        file_id = screenshot_cache[url]['file_id']
        kb = get_timetable_kb(url, group, lang)
        return await message.answer_photo(photo=file_id, caption=f"✅ {group}", reply_markup=kb)

    # 2. Yangi skrinshot olish
    status_msg = await message.answer(MESSAGES[lang]['loading'])
    filename = f"t_{message.chat.id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        photo = types.FSInputFile(filename)
        kb = get_timetable_kb(url, group, lang)
        sent_msg = await message.answer_photo(photo=photo, caption=f"✅ {group}", reply_markup=kb)
        
        # Keshga saqlash
        screenshot_cache[url] = {"file_id": sent_msg.photo[-1].file_id, "time": now}
        os.remove(filename)
    except Exception as e:
        await message.answer(f"Error: {e}")
    finally:
        await status_msg.delete()

def get_timetable_kb(url, group, lang):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text=MESSAGES[lang]['fav_btn'], callback_data=f"savefav_{group}_{url[:30]}")) # URL qisqartirilgan
    kb.row(types.InlineKeyboardButton(text=MESSAGES[lang]['menu'], callback_data="lang_uz"))
    return kb.as_markup()

@dp.callback_query(F.data.startswith("savefav_"))
async def save_fav(callback: types.CallbackQuery):
    lang = user_settings.get(callback.from_user.id, {}).get('lang', 'uz')
    _, group, url_part = callback.data.split("_")
    # To'liq URLni tsuedata'dan qayta topish yoki yuborish mantiqi
    await callback.answer(MESSAGES[lang]['fav_saved'], show_alert=True)

@dp.message(Command("my_table"))
async def my_table_cmd(message: types.Message):
    lang = user_settings.get(message.from_user.id, {}).get('lang', 'uz')
    # Bu yerda Google Sheets'dan sevimli URL'ni olish kodi bo'ladi
    await message.answer(MESSAGES[lang]['my_table_err'])

async def main():
    logging.info("🚀 Professional Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
