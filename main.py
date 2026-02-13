import os
import json
import asyncio
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

# --- SOZLAMALAR (Railway Variables) ---
# os.environ.get - Railway tizimidagi o'zgaruvchilarni to'g'ridan-to'g'ri o'qiydi
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 7878916781))
SHEET_ID = os.environ.get("SHEET_ID")
JSON_FILE = os.environ.get("JSON_FILE", "tsuedata.json")
CREDENTIALS_FILE = os.environ.get("CREDENTIALS_FILE", "credentials.json")

# Tokenni majburiy tekshirish
if not TOKEN:
    logging.error("❌ CRITICAL: BOT_TOKEN topilmadi! Railway Variables bo'limini tekshiring.")
    # Agar token bo'lmasa, botni ishga tushirib bo'lmaydi
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
chat_selected_group = {}

# --- GOOGLE SHEETS ULANISHI ---
def setup_google_sheets():
    try:
        # Fayl nomini kichik yoki katta harf ekanligini avtomatik tekshirish
        actual_file = CREDENTIALS_FILE
        if not os.path.exists(actual_file):
            if os.path.exists("Credentials.json"):
                actual_file = "Credentials.json"
            else:
                logging.error(f"❌ {CREDENTIALS_FILE} fayli topilmadi!")
                return None
                
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(actual_file, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        logging.error(f"❌ Google Sheets ulanishda xato: {e}")
        return None

sheet_instance = setup_google_sheets()

def save_user_log(user_id, username, full_name, faculty, group):
    global sheet_instance
    if sheet_instance is None: 
        sheet_instance = setup_google_sheets()
    
    if sheet_instance:
        try:
            now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            uname = f"@{username}" if username else "Mavjud emas"
            sheet_instance.append_row([now, str(user_id), uname, full_name, faculty, group])
        except Exception as e:
            logging.error(f"❌ Log saqlashda xato: {e}")

# --- SKRINSHOT OLISH (PLAYWRIGHT) ---
async def take_screenshot_optimized(url, filename):
    async with async_playwright() as p:
        # Railway uchun --no-sandbox va --disable-gpu argumentlari juda muhim
        browser = await p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
        )
        context = await browser.new_context(viewport={'width': 1280, 'height': 800}, device_scale_factor=2)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            # Keraksiz elementlarni CSS orqali yashirish
            await page.add_style_tag(content="""
                .no-print, .main-menu, .sk-header, .footer, #header { display: none !important; }
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
            await bot.send_photo(
                chat_id=chat_id, 
                photo=types.FSInputFile(filename), 
                caption=f"🔔 **Avto-jadval**\n✅ Guruh: {group}"
            )
            os.remove(filename)
    except Exception as e:
        logging.error(f"❌ Avto-yuborishda xato: {e}")

# --- BOT INTERFEYSI ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.add(types.InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang_uz"))
    await message.answer("Assalomu alaykum! Jadvalni ko'rish uchun tilni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "lang_uz")
async def lang_callback(callback: types.CallbackQuery):
    if not os.path.exists(JSON_FILE):
        return await callback.message.answer(f"❌ {JSON_FILE} topilmadi!")
        
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    kb = InlineKeyboardBuilder()
    for fak in data.keys():
        kb.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    
    await callback.message.edit_text("Fakultetni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("fak_"))
async def fak_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    fak = callback.data.split("_")[1]
    kb = InlineKeyboardBuilder()
    for kurs in data[fak].keys():
        kb.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak}_{kurs}"))
    await callback.message.edit_text("Kursni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    _, fak, kurs = callback.data.split("_")
    kb = InlineKeyboardBuilder()
    for group in data[fak][kurs].keys():
        kb.add(types.InlineKeyboardButton(text=group, callback_data=f"gr_{fak}_{kurs}_{group}"))
    kb.adjust(3)
    await callback.message.edit_text("Guruhni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("gr_"))
async def group_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    _, fak, kurs, group = callback.data.split("_")
    url = data[fak][kurs][group]
    chat_id = callback.message.chat.id
    
    chat_selected_group[chat_id] = {"url": url, "group": group}
    save_user_log(callback.from_user.id, callback.from_user.username, callback.from_user.full_name, fak, group)
    
    status_msg = await callback.message.answer(f"⏳ **{group}** jadvali tayyorlanmoqda...")
    filename = f"t_{chat_id}.png"
    
    try:
        await take_screenshot_optimized(url, filename)
        await callback.message.answer_photo(
            photo=types.FSInputFile(filename), 
            caption=f"✅ **Guruh:** {group}\n🤖 @tsuetimebot"
        )
        if os.path.exists(filename): os.remove(filename)
    except Exception as e:
        await callback.message.answer(f"❌ Xato: {e}")
    finally:
        await status_msg.delete()

# --- AVTO-YUBORISH ---
@dp.message(Command(re.compile(r"sethour|setday")))
async def process_auto_set(message: types.Message, command: CommandObject):
    chat_id = message.chat.id
    if chat_id not in chat_selected_group:
        return await message.answer("❌ Avval guruhni tanlang!")
    if not command.args or not command.args.isdigit():
        return await message.answer("❌ Vaqtni kiriting (masalan: /sethour 2)")

    n = int(command.args)
    job_id = f"job_{chat_id}"
    u_data = chat_selected_group[chat_id]

    if scheduler.get_job(job_id): scheduler.remove_job(job_id)

    if "hour" in command.command:
        scheduler.add_job(send_auto_timetable, "interval", hours=n, args=[chat_id, u_data['url'], u_data['group']], id=job_id)
    else:
        scheduler.add_job(send_auto_timetable, "interval", days=n, args=[chat_id, u_data['url'], u_data['group']], id=job_id)

    await message.answer(f"✅ Sozlandi! Har {n} {command.command[3:]}da yuboriladi.")

async def main():
    scheduler.start()
    logging.info("🚀 Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi.")
