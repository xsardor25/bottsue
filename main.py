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

# --- KESH VA XOTIRA ---
screenshot_cache = {} 
user_settings = {}    # {user_id: {"lang": "uz", "last_msg": id, "last_pic": id}}
favorites_db = {}     # {user_id: "url"}

MESSAGES = {
    'uz': {
        'start': "Assalomu alaykum! Fakultetni tanlang:",
        'loading': "⏳ Jadval tayyorlanmoqda...",
        'menu': "🏠 Asosiy menyu",
        'fav_btn': "⭐ Sevimlilarga saqlash",
        'fav_ok': "✅ Guruh saqlandi! Endi /my_table orqali kirishingiz mumkin.",
        'no_fav': "❌ Sizda saqlangan guruh yo'q. Avval guruhni tanlang va ⭐ tugmasini bosing.",
        'error': "❌ Xatolik yuz berdi."
    },
    'ru': {
        'start': "Выберите факультет:",
        'loading': "⏳ Расписание готовится...",
        'menu': "🏠 Главное меню",
        'fav_btn': "⭐ Сохранить в избранное",
        'fav_ok': "✅ Группа сохранена! Теперь используйте /my_table.",
        'no_fav': "❌ У вас нет сохраненной группы.",
        'error': "❌ Произошла ошибка."
    }
}

# --- GOOGLE SHEETS UNIKAL BOSHQARUV ---
def setup_google_sheets():
    try:
        if not os.path.exists(CREDENTIALS_FILE): return None
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        
        # Mavjud foydalanuvchilarni xotiraga yuklash
        try:
            records = sheet.get_all_values()[1:] # Sarlavhasiz
            for row in records:
                if len(row) >= 6:
                    favorites_db[str(row[1])] = row[5] # 2-ustun ID, 6-ustun URL
        except: pass
        return sheet
    except Exception as e:
        logging.error(f"❌ Sheets xatosi: {e}"); return None

sheet_instance = setup_google_sheets()

def save_to_sheets(user: types.User, faculty, group_name, url):
    global sheet_instance
    uid = str(user.id)
    if not sheet_instance: return
    
    try:
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        uname = f"@{user.username}" if user.username else "Noma'lum"
        
        ids = sheet_instance.col_values(2)
        if uid in ids:
            row_idx = ids.index(uid) + 1
            # Ma'lumotni yangilash (Duplicate bo'lmasligi uchun)
            sheet_instance.update(f"A{row_idx}:F{row_idx}", [[now, uid, uname, user.full_name, faculty, url]])
        else:
            # Yangi qator qo'shish
            sheet_instance.append_row([now, uid, uname, user.full_name, faculty, url])
        
        favorites_db[uid] = url # Xotirani yangilash
    except Exception as e:
        logging.error(f"Save error: {e}")

# --- PLAYWRIGHT ---
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
        finally: await browser.close()

async def delete_old(chat_id):
    if chat_id in user_settings:
        for key in ['last_pic', 'last_msg']:
            try: await bot.delete_message(chat_id, user_settings[chat_id].get(key))
            except: pass

# --- HANDLERLAR ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await delete_old(message.chat.id)
    try: await message.delete()
    except: pass
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="lang_uz"),
                types.InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"))
    sent = await message.answer("Tilni tanlang / Выберите язык:", reply_markup=builder.as_markup())
    user_settings[message.chat.id] = {'last_msg': sent.message_id, 'lang': 'uz'}

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_settings[callback.message.chat.id]['lang'] = lang
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for fak in data.keys():
        builder.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    await callback.message.edit_text(MESSAGES[lang]['start'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("fak_"))
async def fak_select(callback: types.CallbackQuery):
    lang = user_settings[callback.message.chat.id]['lang']
    fak = callback.data.split("_")[1]
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for kurs in data[fak].keys():
        builder.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak}_{kurs}"))
    await callback.message.edit_text(MESSAGES[lang]['start'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_select(callback: types.CallbackQuery):
    lang = user_settings[callback.message.chat.id]['lang']
    _, fak, kurs = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for g_id in data[fak][kurs].keys():
        builder.add(types.InlineKeyboardButton(text=g_id, callback_data=f"gr_{fak}_{kurs}_{g_id}"))
    builder.adjust(3)
    await callback.message.edit_text(MESSAGES[lang]['start'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("gr_"))
async def group_select(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    lang = user_settings[chat_id]['lang']
    _, fak, kurs, group = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    url = data[fak][kurs][group]
    await send_timetable(chat_id, url, group, lang, fak)

@dp.message(Command("my_table"))
async def my_table_cmd(message: types.Message):
    uid = str(message.from_user.id)
    lang = user_settings.get(message.chat.id, {}).get('lang', 'uz')
    try: await message.delete()
    except: pass
    
    if uid in favorites_db:
        await send_timetable(message.chat.id, favorites_db[uid], "Sevimli", lang)
    else:
        await message.answer(MESSAGES[lang]['no_fav'])

async def send_timetable(chat_id, url, group, lang, fak=""):
    await delete_old(chat_id)
    now = time.time()
    
    kb = InlineKeyboardBuilder()
    if fak: # Agar bu menyu orqali tanlangan bo'lsa, saqlash tugmasini qo'shish
        kb.row(types.InlineKeyboardButton(text=MESSAGES[lang]['fav_btn'], callback_data=f"save_{fak}_{group}"))
    kb.row(types.InlineKeyboardButton(text=MESSAGES[lang]['menu'], callback_data="lang_"+lang))

    # KESH
    if url in screenshot_cache and (now - screenshot_cache[url]['time']) < 3600:
        sent = await bot.send_photo(chat_id, screenshot_cache[url]['file_id'], caption=f"✅ {group}", reply_markup=kb.as_markup())
        user_settings[chat_id]['last_pic'] = sent.message_id
        return

    status = await bot.send_message(chat_id, MESSAGES[lang]['loading'])
    filename = f"t_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        sent = await bot.send_photo(chat_id, types.FSInputFile(filename), caption=f"✅ {group}", reply_markup=kb.as_markup())
        screenshot_cache[url] = {"file_id": sent.photo[-1].file_id, "time": now}
        user_settings[chat_id]['last_pic'] = sent.message_id
        if os.path.exists(filename): os.remove(filename)
    except: await bot.send_message(chat_id, MESSAGES[lang]['error'])
    finally:
        try: await status.delete()
        except: pass

@dp.callback_query(F.data.startswith("save_"))
async def save_callback(callback: types.CallbackQuery):
    _, fak, group = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    # To'liq URLni topish (kurslar ichidan qidirish)
    url = ""
    for kurs in data[fak].values():
        if group in kurs: url = kurs[group]; break
    
    save_to_sheets(callback.from_user, fak, group, url)
    lang = user_settings[callback.message.chat.id]['lang']
    await callback.answer(MESSAGES[lang]['fav_ok'], show_alert=True)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
