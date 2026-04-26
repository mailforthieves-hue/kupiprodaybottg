import asyncio
import logging
import sqlite3
import os
import random
import time
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton
)

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [571694385] 
CHANNEL_ID = -1003779573728
DB_PATH = "bot_database.db"

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (user_id INTEGER PRIMARY KEY, warns INTEGER DEFAULT 0, 
                    approved_ads INTEGER DEFAULT 0, ban_until REAL DEFAULT 0, ban_reason TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS giveaway (user_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

def db_query(sql, params=(), fetch=False, commit=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    res = None
    if fetch: res = cur.fetchall()
    if commit: conn.commit()
    conn.close()
    return res

# --- СОСТОЯНИЯ ---
class AdForm(StatesGroup):
    type = State()
    category = State()
    item = State()
    price = State()
    contact = State()
    photo = State()
    confirm = State() 
    waiting_for_broadcast = State()
    waiting_for_giveaway_title = State()
    waiting_for_giveaway_desc = State()
    waiting_for_report_reason = State()
    waiting_for_warn_reason = State()

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="💰 Продать"), KeyboardButton(text="🛒 Купить")],
    [KeyboardButton(text="🎁 Розыгрыш")],
    [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📜 Правила")]
], resize_keyboard=True)

cat_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🚗 Авто"), KeyboardButton(text="🏠 Дом/Бизнес")],
    [KeyboardButton(text="👕 Скин/Аксессуар"), KeyboardButton(text="📦 Прочее")]
], resize_keyboard=True)

confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✅ Отправить модераторам", callback_data="final_send")],
    [InlineKeyboardButton(text="❌ Сбросить", callback_data="cancel_ad")]
])

# --- ПРОВЕРКА БАНА ---
async def is_banned(user_id):
    res = db_query("SELECT ban_until, ban_reason FROM users WHERE user_id = ?", (user_id,), fetch=True)
    if res and res[0][0] > time.time():
        return res[0]
    return False

# --- ПРОФИЛЬ ---
@dp.message(F.text == "👤 Мой профиль")
async def profile(message: types.Message):
    u_id = message.from_user.id
    res = db_query("SELECT warns, approved_ads, ban_until, ban_reason FROM users WHERE user_id = ?", (u_id,), fetch=True)
    if not res:
        db_query("INSERT INTO users (user_id) VALUES (?)", (u_id,), commit=True)
        res = [(0, 0, 0, "")]

    warns, approved, b_until, b_reason = res[0]
    status = "🟢 Активен"
    if b_until > time.time():
        dt = datetime.fromtimestamp(b_until).strftime('%d.%m.%Y %H:%M')
        status = f"🔴 БАН до {dt}\nПричина: {b_reason}"

    text = (f"👤 <b>ВАШ ПРОФИЛЬ</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{u_id}</code>\n"
            f"🛡 Статус: {status}\n"
            f"⚠️ Предупреждения: <b>{warns}/3</b>\n"
            f"✅ Успешных сделок: {approved}\n"
            f"━━━━━━━━━━━━━━━")
    await message.answer(text, parse_mode="HTML")

# --- ЛОГИКА ВАРНОВ ---
@dp.callback_query(F.data.startswith("warn_"))
async def start_warn(callback: types.CallbackQuery, state: FSMContext):
    target_id = callback.data.split("_")[1]
    await state.update_data(warn_target=target_id)
    await callback.message.answer(f"📝 Введите причину варна для ID {target_id}:")
    await state.set_state(AdForm.waiting_for_warn_reason)
    await callback.answer()

@dp.message(AdForm.waiting_for_warn_reason)
async def process_warn(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_id = int(data['warn_target'])
    reason = message.text
    
    db_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (t_id,), commit=True)
    db_query("UPDATE users SET warns = warns + 1 WHERE user_id = ?", (t_id,), commit=True)
    
    res = db_query("SELECT warns FROM users WHERE user_id = ?", (t_id,), fetch=True)
    warns = res[0][0]
    
    if warns >= 3:
        ban_time = time.time() + (30 * 24 * 3600) # 30 дней
        db_query("UPDATE users SET ban_until = ?, ban_reason = ?, warns = 0 WHERE user_id = ?", 
                 (ban_time, f"3/3 варнов: {reason}", t_id), commit=True)
        try: await bot.send_message(t_id, f"🚫 Вы забанены на 30 дней!\nПричина: 3/3 варнов ({reason})")
        except: pass
        await message.answer(f"⛔ Юзер {t_id} набрал 3 варна и забанен на 30 дней.")
    else:
        try: await bot.send_message(t_id, f"⚠️ Вам выдано предупреждение ({warns}/3)!\nПричина: {reason}")
        except: pass
        await message.answer(f"✅ Варн выдан. Текущий счет юзера: {warns}/3")
    
    await state.clear()

# --- ОДОБРЕНИЕ ---
@dp.callback_query(F.data.startswith("aprv_"))
async def approve(callback: types.CallbackQuery):
    try:
        u_id = int(callback.data.split("_")[1])
        raw = callback.message.html_text if not callback.message.photo else callback.message.caption
        content = raw.split("━━━━━━━━━━━━━━━")[1].strip()
        full_text = f"📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n{content}"
        
        db_query("UPDATE users SET approved_ads = approved_ads + 1 WHERE user_id = ?", (u_id,), commit=True)
        
        photo_id = callback.message.photo[-1].file_id if callback.message.photo else None
        rep_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"report_{u_id}")]])

        if photo_id: await bot.send_photo(CHANNEL_ID, photo_id, caption=full_text, parse_mode="HTML", reply_markup=rep_kb)
        else: await bot.send_message(CHANNEL_ID, full_text, parse_mode="HTML", reply_markup=rep_kb)

        # Рассылка всем
        all_users = db_query("SELECT user_id FROM users", fetch=True)
        for user in all_users:
            try:
                if photo_id: await bot.send_photo(user[0], photo_id, caption=full_text, parse_mode="HTML", reply_markup=rep_kb)
                else: await bot.send_message(user[0], full_text, parse_mode="HTML", reply_markup=rep_kb)
                await asyncio.sleep(0.05)
            except: pass
        await callback.message.delete()
    except Exception as e: await callback.answer(f"Ошибка: {e}")

# --- ЖАЛОБЫ ---
@dp.callback_query(F.data.startswith("report_"))
async def report_start(callback: types.CallbackQuery, state: FSMContext):
    target_id = callback.data.split("_")[1]
    await state.update_data(rep_target=target_id)
    await callback.message.answer("📝 Опишите причину жалобы:")
    await state.set_state(AdForm.waiting_for_report_reason)
    await callback.answer()

@dp.message(AdForm.waiting_for_report_reason)
async def report_done(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_id = data['rep_target']
    
    for a_id in ADMIN_IDS:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚠️ ВАРН", callback_data=f"warn_{t_id}")]])
        await bot.send_message(a_id, f"🚩 <b>ЖАЛОБА</b>\nНа ID: {t_id}\nОт: {message.from_user.id}\nПричина: {message.text}", reply_markup=kb, parse_mode="HTML")
    
    await message.answer("✅ Жалоба отправлена модераторам.")
    await state.clear()

# --- ПОДАЧА ОБЪЯВЛЕНИЯ ---
@dp.message(F.text.in_(["💰 Продать", "🛒 Купить"]))
async def start_ad(message: types.Message, state: FSMContext):
    ban = await is_banned(message.from_user.id)
    if ban:
        dt = datetime.fromtimestamp(ban[0]).strftime('%d.%m.%Y %H:%M')
        return await message.answer(f"🚫 Вы забанены до {dt}\nПричина: {ban[1]}")
    
    await state.update_data(type=message.text)
    await message.answer("📁 Категория:", reply_markup=cat_kb)
    await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def set_cat(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text); await message.answer("📝 Описание:", reply_markup=types.ReplyKeyboardRemove()); await state.set_state(AdForm.item)

@dp.message(AdForm.item)
async def set_item(message: types.Message, state: FSMContext):
    await state.update_data(item=message.text); await message.answer("💵 Цена:"); await state.set_state(AdForm.price)

@dp.message(AdForm.price)
async def set_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text); await message.answer("📞 Контакты:"); await state.set_state(AdForm.contact)

@dp.message(AdForm.contact)
async def set_contact(message: types.Message, state: FSMContext):
    await state.update_data(contact=message.text); await message.answer("📸 Скриншот (или кнопка):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚫 Без фото")]], resize_keyboard=True)); await state.set_state(AdForm.photo)

@dp.message(AdForm.photo)
@dp.message(F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    p_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo=p_id); data = await state.get_data()
    txt = f"🧐 Проверка:\nТовар: {data['item']}\nЦена: {data['price']}"
    await message.answer_photo(p_id, caption=txt, reply_markup=confirm_kb) if p_id else await message.answer(txt, reply_markup=confirm_kb)
    await state.set_state(AdForm.confirm)

@dp.callback_query(F.data == "final_send", AdForm.confirm)
async def final_send(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    photo_id = data.get('photo')
    text = (f"📄 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>\n━━━━━━━━━━━━━━━\n"
            f"📦 Товар: {data['item']}\n💰 Цена: {data['price']}\n"
            f"📂 Кат: {data['category']}\n📞 Тел: {data['contact']}\n"
            f"━━━━━━━━━━━━━━━\n👤 Автор: <a href='tg://user?id={callback.from_user.id}'>Профиль</a>")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"aprv_{callback.from_user.id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data="rej_")],
        [InlineKeyboardButton(text="⚠️ ВАРН", callback_data=f"warn_{callback.from_user.id}")]
    ])
    
    for a_id in ADMIN_IDS:
        try:
            if photo_id: await bot.send_photo(a_id, photo_id, caption=text, reply_markup=kb, parse_mode="HTML")
            else: await bot.send_message(a_id, text, reply_markup=kb, parse_mode="HTML")
        except: pass
    await callback.message.delete(); await callback.message.answer("⏳ Отправлено на модерацию!", reply_markup=main_kb); await state.clear()

@dp.callback_query(F.data == "cancel_ad")
async def cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear(); await callback.message.delete(); await callback.message.answer("❌ Отменено.", reply_markup=main_kb)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    db_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,), commit=True)
    await state.clear(); await message.answer("👋 Добро пожаловать!", reply_markup=main_kb)

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())            return set(line.strip() for line in f if line.strip())
    return set()

def save_data(file_path, item):
    data = load_data(file_path)
    if str(item) not in data:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"{item}\n")

user_timeouts = {}
LIMIT_TIME = 30 * 60 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

class AdForm(StatesGroup):
    type = State()
    category = State()
    item = State()
    price = State()
    contact = State()
    photo = State()
    confirm = State() 
    waiting_for_broadcast = State()
    waiting_for_giveaway_title = State()
    waiting_for_giveaway_desc = State()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="💰 Продать"), KeyboardButton(text="🛒 Купить")],
    [KeyboardButton(text="🎁 Розыгрыш")],
    [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📜 Правила")]
], resize_keyboard=True)

cat_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🚗 Авто"), KeyboardButton(text="🏠 Дом/Бизнес")],
    [KeyboardButton(text="👕 Скин/Аксессуар"), KeyboardButton(text="📦 Прочее")]
], resize_keyboard=True)

skip_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚫 Без фото")]], resize_keyboard=True)

confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✅ Отправить модераторам", callback_data="final_send")],
    [InlineKeyboardButton(text="❌ Сбросить", callback_data="cancel_ad")]
])

def get_giveaway_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Участвовать", callback_data="participate_giveaway")]
    ])

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def send_to_admins(data, user_id):
    photo_id = data.get('photo')
    text = (f"📄 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📦 <b>Товар:</b> {data['item']}\n"
            f"💰 <b>Цена:</b> {data['price']}\n"
            f"📂 Категория: {data['category']}\n"
            f"📞 Контакт: {data['contact']}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👤 Автор: <a href='tg://user?id={user_id}'>Профиль</a>")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"aprv_{user_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{user_id}")],
        [InlineKeyboardButton(text="🚫 БАН", callback_data=f"ban_{user_id}")]
    ])
    
    for a_id in ADMIN_IDS:
        try:
            if photo_id: await bot.send_photo(a_id, photo_id, caption=text, reply_markup=kb, parse_mode="HTML")
            else: await bot.send_message(a_id, text, reply_markup=kb, parse_mode="HTML")
        except: pass

# --- ОБРАБОТЧИКИ АДМИН-КОМАНД ---
@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        count = len(load_data(USERS_FILE))
        await message.answer(f"📊 Пользователей в базе: {count}")

@dp.message(Command("broadcast"))
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("📝 Введите текст для рассылки всем пользователям:")
        await state.set_state(AdForm.waiting_for_broadcast)

@dp.message(AdForm.waiting_for_broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear()
        return await message.answer("❌ Рассылка отменена.")
        
    users = load_data(USERS_FILE)
    await message.answer(f"🚀 Начинаю рассылку на {len(users)} чел...")
    for u_id in users:
        try:
            await bot.send_message(u_id, message.text)
            await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Готово!")
    await state.clear()

# --- ЛОГИКА ОДОБРЕНИЯ ОБЪЯВЛЕНИЙ ---
@dp.callback_query(F.data.startswith("aprv_"))
async def approve(callback: types.CallbackQuery):
    try:
        u_id = callback.data.split("_")[1]
        raw = callback.message.html_text if not callback.message.photo else callback.message.caption
        content = raw.split("━━━━━━━━━━━━━━━")[1].strip()
        
        header = "📢 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>"
        broadcast_text = f"{header}\n\n{content}"
        
        users = load_data(USERS_FILE)
        photo_id = callback.message.photo[-1].file_id if callback.message.photo else None

        if photo_id:
            await bot.send_photo(CHANNEL_ID, photo_id, caption=broadcast_text, parse_mode="HTML")
        else:
            await bot.send_message(CHANNEL_ID, broadcast_text, parse_mode="HTML")

        for user in users:
            try:
                if photo_id: await bot.send_photo(user, photo_id, caption=broadcast_text, parse_mode="HTML")
                else: await bot.send_message(user, broadcast_text, parse_mode="HTML")
                await asyncio.sleep(0.05)
            except: pass

        try: await bot.send_message(u_id, "✅ Ваше объявление одобрено и разослано всем!")
        except: pass
        await callback.message.delete()
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# --- ЛОГИКА РОЗЫГРЫШЕЙ ---
@dp.message(F.text == "🎁 Розыгрыш")
async def show_giveaway(message: types.Message):
    if not CURRENT_GIVEAWAY["active"]:
        return await message.answer("😔 На данный момент активных розыгрышей нет.")
    text = f"🎉 <b>АКТИВНЫЙ РОЗЫГРЫШ: {CURRENT_GIVEAWAY['title']}</b>\n\n{CURRENT_GIVEAWAY['desc']}"
    await message.answer(text, reply_markup=get_giveaway_kb(), parse_mode="HTML")

@dp.message(Command("new_giveaway"))
async def start_giveaway(message: types.Message, state: FSMContext):
    if message.from_user.id in ADMIN_IDS:
        if os.path.exists(GIVEAWAY_USERS): os.remove(GIVEAWAY_USERS)
        await message.answer("🏆 Введите НАЗВАНИЕ розыгрыша:")
        await state.set_state(AdForm.waiting_for_giveaway_title)

@dp.message(AdForm.waiting_for_giveaway_title)
async def set_g_title(message: types.Message, state: FSMContext):
    await state.update_data(g_title=message.text)
    await message.answer("📝 Введите УСЛОВИЯ:")
    await state.set_state(AdForm.waiting_for_giveaway_desc)

@dp.message(AdForm.waiting_for_giveaway_desc)
async def confirm_g(message: types.Message, state: FSMContext):
    data = await state.get_data()
    CURRENT_GIVEAWAY.update({"active": True, "title": data['g_title'], "desc": message.text})
    users = load_data(USERS_FILE)
    broadcast_text = f"📢 <b>НОВЫЙ РОЗЫГРЫШ!</b>\n\n🏆 {CURRENT_GIVEAWAY['title']}\n\nНажми кнопку «Розыгрыш» в меню!"
    for u_id in users:
        try: await bot.send_message(u_id, broadcast_text, parse_mode="HTML"); await asyncio.sleep(0.05)
        except: pass
    await state.clear()
    await message.answer("✅ Розыгрыш запущен!")

@dp.message(Command("winner"))
async def choose_winner(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        participants = list(load_data(GIVEAWAY_USERS))
        if not participants: return await message.answer("❌ Участников нет.")
        
        winner_id = random.choice(participants)
        prize = CURRENT_GIVEAWAY["title"]
        CURRENT_GIVEAWAY["active"] = False
        
        try:
            winner_chat = await bot.get_chat(winner_id)
            winner_link = f"@{winner_chat.username}" if winner_chat.username else f"<a href='tg://user?id={winner_id}'>{winner_chat.full_name}</a>"
        except:
            winner_link = f"<a href='tg://user?id={winner_id}'>Победитель (ссылка)</a>"

        users = load_data(USERS_FILE)
        end_text = f"🏁 <b>РОЗЫГРЫШ ЗАВЕРШЕН!</b>\n\n🏆 Приз: {prize}\n🎊 Победитель: {winner_link}\n\nПоздравляем!"
        
        for u_id in users:
            try: await bot.send_message(u_id, end_text, parse_mode="HTML"); await asyncio.sleep(0.05)
            except: pass
            
        await message.answer(f"✅ Победитель выбран! \nID: {winner_id}\nПрофиль: {winner_link}", parse_mode="HTML")

@dp.callback_query(F.data == "participate_giveaway")
async def participate(callback: types.CallbackQuery):
    if not CURRENT_GIVEAWAY["active"]: return await callback.answer("❌ Завершено!", show_alert=True)
    u_id = str(callback.from_user.id)
    if u_id in load_data(GIVEAWAY_USERS): await callback.answer("⚠️ Вы уже участвуете!", show_alert=True)
    else: save_data(GIVEAWAY_USERS, u_id); await callback.answer("✅ Успешно!", show_alert=True)

# --- БАЗОВЫЕ ОБРАБОТЧИКИ ---
@dp.message(CommandStart())
@dp.message(F.text == "📜 Правила")
async def cmd_start(message: types.Message, state: FSMContext):
    if str(message.from_user.id) in load_data(BAN_FILE): return await message.answer("🚫 Вы заблокированы.")
    save_data(USERS_FILE, message.from_user.id)
    await state.clear()
    if message.text == "📜 Правила": return await message.answer("📝 <b>Правила:</b>\n1. Без спама.\n2. Реальные цены.\n3. Скрины из игры.", parse_mode="HTML")
    await message.answer("👋 Привет! Выберите действие:", reply_markup=main_kb)

@dp.message(F.text.in_(["💰 Продать", "🛒 Купить"]))
async def start_ad(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if str(user_id) in load_data(BAN_FILE): return await message.answer("🚫 Вы заблокированы.")
    if user_id in user_timeouts and user_id not in ADMIN_IDS:
        rem = int(LIMIT_TIME - (time.time() - user_timeouts[user_id]))
        if rem > 0: return await message.answer(f"⏳ Подождите {rem // 60} мин.")
    await state.update_data(type=message.text)
    await message.answer("📁 Выберите категорию:", reply_markup=cat_kb)
    await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def set_cat(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text); await message.answer("📝 Описание товара:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(AdForm.item)

@dp.message(AdForm.item)
async def set_item(message: types.Message, state: FSMContext):
    await state.update_data(item=message.text); await message.answer("💵 Введите цену:"); await state.set_state(AdForm.price)

@dp.message(AdForm.price)
async def set_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text); await message.answer("📞 Контакты:"); await state.set_state(AdForm.contact)

@dp.message(AdForm.contact)
async def set_contact(message: types.Message, state: FSMContext):
    await state.update_data(contact=message.text); await message.answer("📸 Фото:", reply_markup=skip_kb)
    await state.set_state(AdForm.photo)

@dp.message(AdForm.photo)
@dp.message(F.photo)
async def process_photo_preview(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo=photo_id); data = await state.get_data()
    text = f"🧐 <b>Проверка:</b>\n\nТовар: {data['item']}\nЦена: {data['price']}\nКонтакт: {data['contact']}"
    if photo_id: await message.answer_photo(photo_id, caption=text, reply_markup=confirm_kb, parse_mode="HTML")
    else: await message.answer(text, reply_markup=confirm_kb, parse_mode="HTML")
    await state.set_state(AdForm.confirm)

# Обработчик кнопки "❌ Сбросить" (ОТМЕНА)
@dp.callback_query(F.data == "cancel_ad")
async def cancel_ad(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Объявление отменено.", reply_markup=main_kb)

@dp.callback_query(F.data == "final_send", AdForm.confirm)
async def final_process(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data(); await send_to_admins(data, callback.from_user.id)
    await callback.message.delete(); await callback.message.answer("⏳ Отправлено!", reply_markup=main_kb)
    user_timeouts[callback.from_user.id] = time.time(); await state.clear()

@dp.message(F.text == "👤 Мой профиль")
async def profile(message: types.Message):
    await message.answer(f"👤 Ваш ID: <code>{message.from_user.id}</code>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("rej_"))
async def reject(callback: types.CallbackQuery):
    await callback.message.delete()

@dp.callback_query(F.data.startswith("ban_"))
async def ban_user(callback: types.CallbackQuery):
    u_id = callback.data.split("_")[1]; save_data(BAN_FILE, u_id); await callback.message.delete()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
