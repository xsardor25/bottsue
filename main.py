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

# --- MAXFIYAT VA KESH ---
screenshot_cache = {}  # {url: {"file_id": id, "time": timestamp}}
user_settings = {}     # {user_id: {"lang": "uz", "last_msg": msg_id, "last_pic": pic_id}}

MESSAGES = {
    'uz': {
        'start': "Assalomu alaykum! Tilni tanlang:",
        'select_fak': "Fakultetni tanlang:",
        'select_kurs': "Kursni tanlang:",
        'select_group': "Guruhni tanlang:",
        'loading': "⏳ Jadval tayyorlanmoqda...",
        'fav_btn': "⭐ Sevimlilarga qo'shish",
        'menu': "🏠 Asosiy menyu",
        'error': "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring."
    },
    'ru': {
        'start': "Здравствуйте! Выберите язык:",
        'select_fak': "Выберите факультет:",
        'select_kurs': "Выберите курс:",
        'select_group': "Выберите группу:",
        'loading': "⏳ Расписание готовится...",
        'fav_btn': "⭐ Добавить в избранное",
        'menu': "🏠 Главное меню",
        'error': "❌ Произошла ошибка. Попробуйте еще раз."
    }
}

# --- YORDAMCHI FUNKSIYALAR ---
async def delete_old_messages(chat_id):
    """Eski menyu va rasmlarni chatdan tozalash"""
    if chat_id in user_settings:
        data = user_settings[chat_id]
        # Eski rasmni o'chirish
        if 'last_pic' in data:
            try: await bot.delete_message(chat_id, data['last_pic'])
            except: pass
        # Eski menyuni o'chirish
        if 'last_msg' in data:
            try: await bot.delete_message(chat_id, data['last_msg'])
            except: pass

async def take_screenshot_optimized(url, filename):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(viewport={'width': 1280, 'height': 800}, device_scale_factor=2)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.add_style_tag(content="""
                .no-print, .main-menu, .sk-header, .footer, #header { display: none !important; }
                body { background: white !important; }
            """)
            target = await page.query_selector(".tt-grid-container")
            if target: await target.screenshot(path=filename)
            else: await page.screenshot(path=filename)
        finally:
            await browser.close()

# --- HANDLERLAR ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await delete_old_messages(message.chat.id)
    try: await message.delete() # Foydalanuvchi buyrug'ini o'chirish
    except: pass

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang_uz"))
    builder.row(types.InlineKeyboardButton(text="🇷🇺 Русский язык", callback_data="lang_ru"))
    
    sent = await message.answer(MESSAGES['uz']['start'], reply_markup=builder.as_markup())
    user_settings[message.chat.id] = {'last_msg': sent.message_id, 'lang': 'uz'}

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_settings[callback.message.chat.id]['lang'] = lang
    
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for fak in data.keys():
        builder.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    
    await callback.message.edit_text(MESSAGES[lang]['select_fak'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("fak_"))
async def fak_select(callback: types.CallbackQuery):
    lang = user_settings[callback.message.chat.id]['lang']
    fak = callback.data.split("_")[1]
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    
    builder = InlineKeyboardBuilder()
    for kurs in data[fak].keys():
        builder.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak}_{kurs}"))
    await callback.message.edit_text(MESSAGES[lang]['select_kurs'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_select(callback: types.CallbackQuery):
    lang = user_settings[callback.message.chat.id]['lang']
    _, fak, kurs = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    
    builder = InlineKeyboardBuilder()
    for g_id in data[fak][kurs].keys():
        builder.add(types.InlineKeyboardButton(text=g_id, callback_data=f"gr_{fak}_{kurs}_{g_id}"))
    builder.adjust(3)
    builder.row(types.InlineKeyboardButton(text="⬅️", callback_data=f"fak_{fak}"))
    await callback.message.edit_text(MESSAGES[lang]['select_group'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("gr_"))
async def group_select(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    lang = user_settings[chat_id]['lang']
    _, fak, kurs, group = callback.data.split("_")
    
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    url = data[fak][kurs][group]

    # Oldingi xabarlarni tozalash (rasm va menyu)
    await delete_old_messages(chat_id)

    # KESH TEKSHIRISH (1 soat)
    now = time.time()
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text=MESSAGES[lang]['menu'], callback_data="lang_"+lang))
    
    if url in screenshot_cache and (now - screenshot_cache[url]['time']) < 3600:
        sent_pic = await bot.send_photo(
            chat_id=chat_id, 
            photo=screenshot_cache[url]['file_id'], 
            caption=f"✅ {group}", 
            reply_markup=kb.as_markup()
        )
        user_settings[chat_id]['last_pic'] = sent_pic.message_id
        return

    # YANGI RASM OLISH
    status = await bot.send_message(chat_id, MESSAGES[lang]['loading'])
    filename = f"t_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        sent_pic = await bot.send_photo(
            chat_id=chat_id, 
            photo=types.FSInputFile(filename), 
            caption=f"✅ {group}", 
            reply_markup=kb.as_markup()
        )
        # Keshga yozish
        screenshot_cache[url] = {"file_id": sent_pic.photo[-1].file_id, "time": now}
        user_settings[chat_id]['last_pic'] = sent_pic.message_id
        if os.path.exists(filename): os.remove(filename)
    except Exception as e:
        await bot.send_message(chat_id, MESSAGES[lang]['error'])
        logging.error(f"Screenshot error: {e}")
    finally:
        await status.delete()

async def main():
    logging.info("🚀 Bot cleaned and optimized!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
