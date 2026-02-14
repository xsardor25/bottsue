import json, asyncio, os, logging, warnings, gspread, time, re
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from playwright.async_api import async_playwright
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.exceptions import TelegramBadRequest

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

class GroupSetup(StatesGroup):
    waiting_for_time = State()

screenshot_cache = {} 
user_settings = {} # Foydalanuvchi sozlamalari
favorites_db = {}     
DAYS = {0: "Dushanba", 1: "Seshanba", 2: "Chorshanba", 3: "Payshanba", 4: "Juma", 5: "Shanba", 6: "Yakshanba"}

MESSAGES = {
    'uz': {
        'start': "Assalomu alaykum! Fakultetni tanlang:",
        'select_day': "📅 Haftaning qaysi kuni jadval yuborilsin?",
        'select_time': "⏰ Vaqtni tanlang yoki o'zingiz yozing (masalan: 14:20):",
        'loading': "⏳ Jadval tayyorlanmoqda...",
        'menu': "🏠 Asosiy menyu",
        'fav_btn': "⭐ Sevimlilarga saqlash",
        'fav_ok': "✅ Guruh saqlandi! Endi /my_table orqali kirishingiz mumkin.",
        'no_fav': "❌ Sizda saqlangan guruh yo'q.",
        'error': "❌ Xatolik yuz berdi.",
        'group_saved': "✅ Sozlamalar saqlandi! Har {day} kuni soat {time}da yuboriladi."
    },
    'ru': {
        'start': "Выберите факультет:",
        'select_day': "В какой день недели отправлять?",
        'select_time': "Выберите время или введите сами (напр: 14:20):",
        'loading': "⏳ Расписание готовится...",
        'menu': "🏠 Главное меню",
        'fav_btn': "⭐ Сохранить в избранное",
        'fav_ok': "✅ Группа сохранена! Используйте /my_table.",
        'no_fav': "❌ У вас нет сохраненной группы.",
        'error': "❌ Ошибка.",
        'group_saved': "✅ Сохранено! Будет отправляться в {day} в {time}."
    }
}

# --- Yordamchi Funksiya: Sozlamalarni xavfsiz olish ---
def get_user_lang(chat_id):
    if chat_id not in user_settings:
        user_settings[chat_id] = {'lang': 'uz'}
    return user_settings[chat_id]['lang']

# --- GOOGLE SHEETS ---
def setup_sheets():
    try:
        if not os.path.exists(CREDENTIALS_FILE): return None
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_values()[1:]
        for row in records:
            if len(row) >= 6: favorites_db[str(row[1])] = row[5]
        return sheet
    except: return None

sheet_instance = setup_sheets()

def save_to_sheets(user, faculty, url):
    uid = str(user.id)
    if not sheet_instance: return
    try:
        ids = sheet_instance.col_values(2)
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        uname = f"@{user.username}" if user.username else "Noma'lum"
        data = [now, uid, uname, user.full_name, faculty, url]
        if uid in ids:
            sheet_instance.update(f"A{ids.index(uid)+1}:F{ids.index(uid)+1}", [data])
        else: sheet_instance.append_row(data)
        favorites_db[uid] = url
    except: pass

# --- SKRINSHOT ---
async def take_screenshot(url, filename):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page(viewport={'width': 1280, 'height': 800}, device_scale_factor=2)
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.add_style_tag(content=".no-print, .main-menu, .footer, #header { display: none !important; }")
            target = await page.query_selector(".tt-grid-container")
            await (target or page).screenshot(path=filename)
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
    for fak in data.keys(): builder.row(types.InlineKeyboardButton(text=fak.upper(), callback_data=f"fak_{fak}"))
    try:
        await callback.message.edit_text(MESSAGES[lang]['start'], reply_markup=builder.as_markup())
    except TelegramBadRequest: pass

@dp.callback_query(F.data.startswith("fak_"))
async def fak_select(callback: types.CallbackQuery):
    lang = get_user_lang(callback.message.chat.id)
    fak = callback.data.split("_")[1]
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for kurs in data[fak].keys(): builder.row(types.InlineKeyboardButton(text=kurs, callback_data=f"kurs_{fak}_{kurs}"))
    try:
        await callback.message.edit_text(MESSAGES[lang]['start'], reply_markup=builder.as_markup())
    except TelegramBadRequest: pass

@dp.callback_query(F.data.startswith("kurs_"))
async def kurs_select(callback: types.CallbackQuery):
    lang = get_user_lang(callback.message.chat.id)
    _, fak, kurs = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    builder = InlineKeyboardBuilder()
    for g_id in data[fak][kurs].keys(): builder.add(types.InlineKeyboardButton(text=g_id, callback_data=f"gr_{fak}_{kurs}_{g_id}"))
    builder.adjust(3)
    try:
        await callback.message.edit_text(MESSAGES[lang]['start'], reply_markup=builder.as_markup())
    except TelegramBadRequest: pass

@dp.callback_query(F.data.startswith("gr_"))
async def group_select(callback: types.CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback.message.chat.id)
    _, fak, kurs, group = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    url = data[fak][kurs][group]

    if callback.message.chat.type in ["group", "supergroup"]:
        await state.update_data(url=url, group=group, fak=fak)
        builder = InlineKeyboardBuilder()
        for i, name in DAYS.items(): builder.row(types.InlineKeyboardButton(text=name, callback_data=f"day_{i}"))
        await callback.message.edit_text(MESSAGES[lang]['select_day'], reply_markup=builder.as_markup())
    else:
        await send_timetable(callback.message.chat.id, url, group, lang, fak)

@dp.callback_query(F.data.startswith("day_"))
async def day_select(callback: types.CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback.message.chat.id)
    await state.update_data(day=callback.data.split("_")[1])
    builder = InlineKeyboardBuilder()
    for t in ["08:00", "10:00", "12:00", "16:00", "20:00"]: 
        builder.add(types.InlineKeyboardButton(text=t, callback_data=f"st_{t}"))
    builder.adjust(2)
    await state.set_state(GroupSetup.waiting_for_time)
    await callback.message.edit_text(MESSAGES[lang]['select_time'], reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("st_"), GroupSetup.waiting_for_time)
async def time_btn(callback: types.CallbackQuery, state: FSMContext):
    await finalize(callback.message, state, callback.data.split("_")[1])

@dp.message(GroupSetup.waiting_for_time)
async def time_input(message: types.Message, state: FSMContext):
    v_time = message.text.strip().replace(".", ":").replace("-", ":")
    if re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', v_time):
        if len(v_time.split(":")[0]) == 1: v_time = "0" + v_time
        await finalize(message, state, v_time)
    else:
        await message.answer("❌ HH:MM formatda yozing (masalan 14:20)!")

async def finalize(message, state, v_time):
    lang = get_user_lang(message.chat.id)
    data = await state.get_data()
    h, m = map(int, v_time.split(":"))
    job_id = f"job_{message.chat.id}"
    if scheduler.get_job(job_id): scheduler.remove_job(job_id)
    scheduler.add_job(send_timetable_auto, "cron", day_of_week=int(data['day']), hour=h, minute=m, args=[message.chat.id, data['url'], data['group']], id=job_id)
    await message.answer(MESSAGES[lang]['group_saved'].format(day=DAYS[int(data['day'])], time=v_time))
    await state.clear()

@dp.message(Command("my_table"))
async def my_table(message: types.Message):
    lang = get_user_lang(message.chat.id)
    uid = str(message.from_user.id)
    try: await message.delete()
    except: pass
    if uid in favorites_db: await send_timetable(message.chat.id, favorites_db[uid], "Sevimli", lang)
    else: await message.answer(MESSAGES[lang]['no_fav'])

async def send_timetable(chat_id, url, group, lang, fak=""):
    await delete_old(chat_id)
    now = time.time()
    kb = InlineKeyboardBuilder()
    if fak: kb.row(types.InlineKeyboardButton(text=MESSAGES[lang]['fav_btn'], callback_data=f"sv_{fak}_{group}"))
    kb.row(types.InlineKeyboardButton(text=MESSAGES[lang]['menu'], callback_data="lang_"+lang))
    
    if url in screenshot_cache and (now - screenshot_cache[url]['time']) < 3600:
        try:
            sent = await bot.send_photo(chat_id, screenshot_cache[url]['id'], caption=f"✅ {group}", reply_markup=kb.as_markup())
            user_settings[chat_id]['last_pic'] = sent.message_id
            return
        except: pass

    status = await bot.send_message(chat_id, MESSAGES[lang]['loading'])
    fname = f"t_{chat_id}.png"
    try:
        await take_screenshot(url, fname)
        sent = await bot.send_photo(chat_id, types.FSInputFile(fname), caption=f"✅ {group}", reply_markup=kb.as_markup())
        screenshot_cache[url] = {"id": sent.photo[-1].file_id, "time": now}
        user_settings[chat_id]['last_pic'] = sent.message_id
        if os.path.exists(fname): os.remove(fname)
    except Exception as e:
        logging.error(f"Screenshot Error: {e}")
        await bot.send_message(chat_id, MESSAGES[lang]['error'])
    finally:
        try: await status.delete()
        except: pass

async def send_timetable_auto(chat_id, url, group):
    fname = f"a_{chat_id}.png"
    try:
        await take_screenshot(url, fname)
        await bot.send_photo(chat_id, types.FSInputFile(fname), caption=f"🔔 Avtomatik jadval: {group}")
        if os.path.exists(fname): os.remove(fname)
    except: pass

@dp.callback_query(F.data.startswith("sv_"))
async def save_fav(callback: types.CallbackQuery):
    lang = get_user_lang(callback.message.chat.id)
    _, fak, group = callback.data.split("_")
    with open(JSON_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    url = ""
    for k in data[fak].values():
        if group in k: url = k[group]; break
    if url:
        save_to_sheets(callback.from_user, fak, url)
        await callback.answer(MESSAGES[lang]['fav_ok'], show_alert=True)

async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
