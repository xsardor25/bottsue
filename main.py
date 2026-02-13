import json
import asyncio
import os
import logging
import warnings
import gspread
import re 
from datetime import datetime
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from playwright.async_api import async_playwright
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# .env faylini yuklash
load_dotenv()

warnings.filterwarnings("ignore", category=UserWarning)

# --- SOZLAMALAR (Muhitdan olinadi) ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
JSON_FILE = os.getenv("JSON_FILE", "tsuedata.json")
SHEET_ID = os.getenv("SHEET_ID")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

chat_selected_group = {} 

# --- GOOGLE SHEETS ---
def setup_google_sheets():
    try:
        if not os.path.exists(CREDENTIALS_FILE): 
            logging.error(f"{CREDENTIALS_FILE} topilmadi!")
            return None
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        logging.error(f"Sheets xatosi: {e}")
        return None

sheet_instance = setup_google_sheets()

def save_user_log(user_id, username, full_name, faculty, group):
    global sheet_instance
    if sheet_instance is None: sheet_instance = setup_google_sheets()
    if sheet_instance:
        try:
            existing_ids = sheet_instance.col_values(2) 
            if str(user_id) not in existing_ids:
                now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                uname = f"@{username}" if username else "Mavjud emas"
                sheet_instance.append_row([now, str(user_id), uname, full_name, faculty, group])
        except Exception as e:
            logging.error(f"Log saqlashda xato: {e}")

# --- SKRINSHOT FUNKSIYALARI ---
async def take_screenshot_optimized(url, filename):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(viewport={'width': 1280, 'height': 800}, device_scale_factor=2)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.add_style_tag(content=".no-print, .main-menu, .sk-header, .footer, #header, .pnl-print-hidden { display: none !important; } .tt-grid-container::after { content: '@tsuetimebot'; display: block; text-align: right; font-size: 20px; font-weight: bold; color: #d1d1d1; padding: 10px; } body { background: white !important; }")
            target = await page.query_selector(".tt-grid-container")
            if target: await target.screenshot(path=filename)
            else: await page.screenshot(path=filename, full_page=False)
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
        logging.error(f"Avto-yuborishda xato: {e}")

# --- ADMIN PANEL HANDLERLARI ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"))
    kb.row(types.InlineKeyboardButton(text="📢 Reklama yuborish", callback_data="admin_reklama"))
    await message.answer("🛠 **Admin paneliga xush kelibsiz!**", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "admin_stats", F.from_user.id == ADMIN_ID)
async def admin_stats(callback: types.CallbackQuery):
    global sheet_instance
    if sheet_instance is None: sheet_instance = setup_google_sheets()
    try:
        users = sheet_instance.col_values(2)[1:]
        total_users = len(set(users))
        active_jobs = len(scheduler.get_jobs())
        text = (f"📊 **Bot statistikasi:**\n\n👤 Jami foydalanuvchilar: {total_users}\n🔔 Faol avto-yuborishlar: {active_jobs}")
        await callback.message.answer(text)
    except Exception as e:
        await callback.message.answer(f"Statistika olishda xato: {e}")
    await callback.answer()

@dp.callback_query(F.data == "admin_reklama", F.from_user.id == ADMIN_ID)
async def admin_reklama_prompt(callback: types.CallbackQuery):
    await callback.message.answer("📢 **Reklama xabarini yuboring.**")
    await callback.answer()

@dp.message(F.from_user.id == ADMIN_ID, ~F.text.startswith("/"))
async def start_broadcast(message: types.Message):
    global sheet_instance
    if sheet_instance is None: sheet_instance = setup_google_sheets()
    try:
        users = list(set(sheet_instance.col_values(2)[1:]))
        count, error = 0, 0
        msg = await message.answer(f"⏳ **Yuborish boshlandi...**")
        for user_id in users:
            try:
                await message.copy_to(chat_id=user_id)
                count += 1
                await asyncio.sleep(0.05)
            except: error += 1
        await msg.edit_text(f"✅ **Tugadi!**\n🚀 Yetkazildi: {count}\n❌ Xato: {error}")
    except Exception as e:
        await message.answer(f"Xatolik: {e}")

# --- FOYDALANUVCHI HANDLERLARI ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang_uz"))
    builder.row(types.InlineKeyboardButton(text="🇷🇺 Русский язык", callback_data="lang_ru"))
    await message.answer(f"Salom! Jadval uchun tilni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "lang_uz")
@dp.callback_query(F.data == "lang_ru")
async def lang_callback(callback: types.CallbackQuery):
    if not os.path.exists(JSON_FILE):
        return await callback.message.answer("Xato: Ma'lumotlar fayli topilmadi.")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for fak in data.keys():
        builder.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    try: await callback.message.delete()
    except: pass
    await callback.message.answer("Fakultetni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("fak_"))
async def fak_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    fak_name = callback.data.split("_")[1]
    builder = InlineKeyboardBuilder()
    for kurs in data[fak_name].keys():
        builder.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak_name}_{kurs}"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="lang_uz"))
    await callback.message.edit_text(f"Kursni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    _, fak, kurs = callback.data.split("_")
    builder = InlineKeyboardBuilder()
    for g_id in data[fak][kurs].keys():
        builder.add(types.InlineKeyboardButton(text=g_id, callback_data=f"gr_{fak}_{kurs}_{g_id}"))
    builder.adjust(3)
    builder.row(types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"fak_{fak}"))
    await callback.message.edit_text(f"Guruhni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("gr_"))
async def group_callback(callback: types.CallbackQuery):
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    _, fak, kurs, group = callback.data.split("_")
    url = data[fak][kurs][group]
    chat_id = callback.message.chat.id
    chat_selected_group[chat_id] = {"url": url, "group": group}
    
    if callback.message.chat.type == "private":
        save_user_log(callback.from_user.id, callback.from_user.username, callback.from_user.full_name, fak, group)
    
    try: await callback.message.delete()
    except: pass
    
    status_msg = await callback.message.answer(f"⏳ **{group}** jadvali yuklanmoqda...")
    filename = f"table_{chat_id}.png"
    try:
        await take_screenshot_optimized(url, filename)
        if os.path.exists(filename):
            kb = InlineKeyboardBuilder()
            kb.row(types.InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"gr_{fak}_{kurs}_{group}"))
            kb.row(types.InlineKeyboardButton(text="⚙️ Sozlash", callback_data="setup_info"))
            kb.row(types.InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="lang_uz"))
            await callback.message.answer_photo(photo=types.FSInputFile(filename), caption=f"✅ **Guruh:** {group}\n🤖 @tsuetimebot", parse_mode="Markdown", reply_markup=kb.as_markup())
            os.remove(filename)
    except Exception as e: await callback.message.answer(f"Xatolik: {e}")
    finally: await status_msg.delete()

@dp.callback_query(F.data == "setup_info")
async def setup_info(callback: types.CallbackQuery):
    text = ("⚙️ **Jadvalni avtomatlashtirish**\n\n🔹 `/sethour n` - har `n` soatda\n🔹 `/setday n` - har `n` kunda\n🔹 `/setminute n` - har `n` minutda\n\n❌ `/stopauto` - to'xtatish.")
    await callback.message.answer(text, parse_mode="Markdown")

@dp.message(Command(re.compile(r"setminute|sethour|setday")))
async def process_setting_commands(message: types.Message, command: CommandObject):
    chat_id = message.chat.id
    if chat_id not in chat_selected_group:
        return await message.answer("❌ Avval guruhni menyudan tanlang!")
    if not command.args or not command.args.isdigit():
        return await message.answer("❌ Son kiriting!")

    n = int(command.args)
    job_id = f"job_{chat_id}"
    u_data = chat_selected_group[chat_id]

    if scheduler.get_job(job_id): scheduler.remove_job(job_id)

    if command.command == "setminute":
        scheduler.add_job(send_auto_timetable, "interval", minutes=n, args=[chat_id, u_data['url'], u_data['group']], id=job_id)
    elif command.command == "sethour":
        scheduler.add_job(send_auto_timetable, "interval", hours=n, args=[chat_id, u_data['url'], u_data['group']], id=job_id)
    elif command.command == "setday":
        scheduler.add_job(send_auto_timetable, "interval", days=n, start_date=datetime.now().replace(hour=8, minute=0), args=[chat_id, u_data['url'], u_data['group']], id=job_id)

    await message.answer(f"✅ Har {n} {command.command[3:]}da yuboriladi.")

@dp.message(Command("stopauto"))
async def stop_auto(message: types.Message):
    chat_id = message.chat.id
    job_id = f"job_{chat_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        await message.answer("📴 To'xtatildi.")
    else:
        await message.answer("ℹ️ Faol emas.")

async def main():
    scheduler.start()
    logging.info("Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())