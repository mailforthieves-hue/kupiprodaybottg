import asyncio
import logging
import sqlite3
import os
import random
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [571694385,718488418] 
CHANNEL_ID = -1003779573728
DB_PATH = "bot_database.db"

# Глобальный статус розыгрыша (в памяти)
CURRENT_GIVEAWAY = {"active": False, "title": "", "desc": ""}

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (user_id INTEGER PRIMARY KEY, 
                    warns INTEGER DEFAULT 0, 
                    approved_ads INTEGER DEFAULT 0, 
                    total_ads INTEGER DEFAULT 0,
                    reports_received INTEGER DEFAULT 0,
                    reg_date TEXT,
                    ban_until REAL DEFAULT 0, 
                    ban_reason TEXT)''')
    
    # Авто-обновление структуры БД при запуске
    try:
        cur.execute("ALTER TABLE users ADD COLUMN total_ads INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE users ADD COLUMN reports_received INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE users ADD COLUMN reg_date TEXT")
    except: pass

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
    category = State()
    item = State()
    price = State()
    contact = State()
    photo = State()
    confirm = State() 
    waiting_for_warn_reason = State()
    waiting_for_report_reason = State()
    waiting_for_broadcast = State()
    waiting_for_giveaway_title = State()
    waiting_for_giveaway_desc = State()

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

skip_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚫 Без фото")]], resize_keyboard=True)

confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✅ Отправить", callback_data="final_send")],
    [InlineKeyboardButton(text="❌ Сбросить", callback_data="cancel_ad")]
])

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_report_kb(seller_id):
    # !!! ЗАМЕНИ НА СВОЙ ЮЗЕРНЕЙМ БЕЗ @ !!!
    bot_username = "Kupi_proday_12server_bot" 
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚩 Пожаловаться", url=f"https://t.me/{bot_username}?start=report_{seller_id}")]
    ])

# --- АДМИН-СТАТИСТИКА (ИНФОГРАФИКА) ---
@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        u_count = db_query("SELECT COUNT(*) FROM users", fetch=True)[0][0] or 1
        b_count = db_query("SELECT COUNT(*) FROM users WHERE ban_until > ?", (time.time(),), fetch=True)[0][0] or 0
        total_ads = db_query("SELECT SUM(total_ads) FROM users", fetch=True)[0][0] or 0
        appr_ads = db_query("SELECT SUM(approved_ads) FROM users", fetch=True)[0][0] or 0
        
        active_users = u_count - b_count
        global_ratio = (appr_ads / total_ads * 100) if total_ads > 0 else 0
        filled = int(global_ratio / 10)
        bar = "🟢" * filled + "⚪" * (10 - filled)

        text = (
            f"📊 <b>ОТЧЕТ АДМИНИСТРАЦИИ (12 SERVER)</b>\n"
            f"<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 <b>ЖИТЕЛИ:</b>\n"
            f"├ Всего: <code>{u_count}</code>\n"
            f"├ Активных: <code>{active_users}</code>\n"
            f"└ В бане: <code>{b_count}</code>\n\n"
            f"📦 <b>ОБОРОТ ОБЪЯВЛЕНИЙ:</b>\n"
            f"├ Обработано: <code>{total_ads}</code>\n"
            f"└ Одобрено: <code>{appr_ads}</code>\n\n"
            f"📈 <b>КАЧЕСТВО ПОСТОВ: {global_ratio:.1f}%</b>\n"
            f"[{bar}]\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💎 <b>РОЗЫГРЫШ:</b> {'✅ АКТИВЕН' if CURRENT_GIVEAWAY['active'] else '❌ ВЫКЛЮЧЕН'}"
        )
        await message.answer(text, parse_mode="HTML")

# --- СТАРТ И ОБРАБОТКА DEEP LINKING (ЖАЛОБЫ) ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    now = datetime.now().strftime("%d.%m.%Y")
    db_query("INSERT OR IGNORE INTO users (user_id, reg_date) VALUES (?, ?)", (message.from_user.id, now), commit=True)
    
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("report_"):
        seller_id = args[1].split("_")[1]
        await state.update_data(report_target=seller_id)
        await message.answer(f"🚩 <b>Оформление жалобы</b>\n\nВы подаете жалобу на игрока ID: <code>{seller_id}</code>\n\nОпишите причину подробно (обман, спам, цена):", parse_mode="HTML")
        await state.set_state(AdForm.waiting_for_report_reason)
        return

    await state.clear()
    await message.answer("👋 Добро пожаловать на торговую площадку 12 сервера!", reply_markup=main_kb)

# --- ПРИЕМ ТЕКСТА ЖАЛОБЫ ---
@dp.message(AdForm.waiting_for_report_reason)
async def process_report(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_id = data.get('report_target')
    db_query("UPDATE users SET reports_received = reports_received + 1 WHERE user_id = ?", (t_id,), commit=True)
    
    # Получаем инфо о нарушителе для админа
    target_info = db_query("SELECT warns FROM users WHERE user_id = ?", (t_id,), fetch=True)[0]
    warns_bar = "⚠️" * target_info[0] + "⚪" * (3 - target_info[0])

    admin_txt = (f"🚩 <b>НОВАЯ ЖАЛОБА</b>\n━━━━━━━━━━━━━━━\n"
                 f"👤 <b>Нарушитель:</b> ID <code>{t_id}</code>\n"
                 f"📊 <b>Репутация:</b> {warns_bar}\n"
                 f"👤 <b>Отправитель:</b> ID <code>{message.from_user.id}</code>\n"
                 f"📝 <b>Причина:</b> {message.text}")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ ВЫДАТЬ ВАРН", callback_data=f"warn_{t_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="rej_")]
    ])
    
    for a_id in ADMIN_IDS:
        try: await bot.send_message(a_id, admin_txt, reply_markup=kb, parse_mode="HTML")
        except: pass
    await message.answer("✅ Ваша жалоба отправлена модераторам.", reply_markup=main_kb)
    await state.clear()

# --- ПРОФИЛЬ (РАСШИРЕННЫЙ) ---
@dp.message(F.text == "👤 Мой профиль")
async def profile(message: types.Message):
    u_id = message.from_user.id
    res = db_query("SELECT warns, approved_ads, total_ads, reports_received, reg_date, ban_until FROM users WHERE user_id = ?", (u_id,), fetch=True)
    
    if not res: return
    warns, approved, total, reports, reg_date, b_until = res[0]
    
    ratio = (approved / total * 100) if total > 0 else 0
    status = "🟢 Активен" if b_until < time.time() else "🔴 ЗАБАНЕН"
    
    text = (f"👤 <b>ПРОФИЛЬ (12 SERVER)</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{u_id}</code>\n"
            f"📅 В штате с: {reg_date}\n"
            f"🛡 Статус: {status}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 <b>АКТИВНОСТЬ:</b>\n"
            f"├ Подано: {total}\n"
            f"├ Одобрено: {approved}\n"
            f"└ Качество: {ratio:.1f}%\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ <b>РЕПУТАЦИЯ:</b>\n"
            f"├ Варны: {warns}/3\n"
            f"└ Жалобы: {reports}\n"
            f"━━━━━━━━━━━━━━━")
    await message.answer(text, parse_mode="HTML", reply_markup=main_kb)

# --- ОДОБРЕНИЕ ОБЪЯВЛЕНИЙ ---
@dp.callback_query(F.data.startswith("aprv_"))
async def approve(callback: types.CallbackQuery):
    u_id = int(callback.data.split("_")[1])
    raw = callback.message.html_text if not callback.message.photo else callback.message.caption
    content = raw.split("━━━━━━━━━━━━━━━")[1].strip()
    full_text = f"📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n{content}"
    
    db_query("UPDATE users SET approved_ads = approved_ads + 1 WHERE user_id = ?", (u_id,), commit=True)
    photo_id = callback.message.photo[-1].file_id if callback.message.photo else None
    kb = get_report_kb(u_id)

    if photo_id: await bot.send_photo(CHANNEL_ID, photo_id, caption=full_text, parse_mode="HTML", reply_markup=kb)
    else: await bot.send_message(CHANNEL_ID, full_text, parse_mode="HTML", reply_markup=kb)

    users = db_query("SELECT user_id FROM users", fetch=True)
    for user in users:
        try:
            if photo_id: await bot.send_photo(user[0], photo_id, caption=full_text, parse_mode="HTML", reply_markup=kb)
            else: await bot.send_message(user[0], full_text, parse_mode="HTML", reply_markup=kb)
            await asyncio.sleep(0.04)
        except: pass
    await callback.message.delete()

# --- ЛОГИКА ВАРНОВ ---
@dp.callback_query(F.data.startswith("warn_"))
async def start_warn(callback: types.CallbackQuery, state: FSMContext):
    target_id = callback.data.split("_")[1]
    await state.update_data(warn_target=target_id)
    await callback.message.answer(f"📝 Причина варна для ID {target_id}:")
    await state.set_state(AdForm.waiting_for_warn_reason)

@dp.message(AdForm.waiting_for_warn_reason)
async def process_warn(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_id = int(data['warn_target'])
    db_query("UPDATE users SET warns = warns + 1 WHERE user_id = ?", (t_id,), commit=True)
    res = db_query("SELECT warns FROM users WHERE user_id = ?", (t_id,), fetch=True)
    warns = res[0][0]
    
    if warns >= 3:
        until = time.time() + (30 * 24 * 3600)
        db_query("UPDATE users SET ban_until = ?, ban_reason = ?, warns = 0 WHERE user_id = ?", (until, f"3/3 варна: {message.text}", t_id), commit=True)
        try: await bot.send_message(t_id, f"🚫 Бан на 30 дней (3/3 варна).\nПричина: {message.text}")
        except: pass
    else:
        try: await bot.send_message(t_id, f"⚠️ Предупреждение ({warns}/3)!\nПричина: {message.text}")
        except: pass
    await message.answer(f"✅ Варн выдан. Теперь у юзера {warns}/3 варна.", reply_markup=main_kb)
    await state.clear()

# --- (ОСТАЛЬНЫЕ ФУНКЦИИ: BROADCAST, GIVEAWAY, ПОДАЧА ОБЪЯВЛЕНИЙ) ---

@dp.message(Command("broadcast"))
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("📝 Введите текст рассылки:"); await state.set_state(AdForm.waiting_for_broadcast)

@dp.message(AdForm.waiting_for_broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    users = db_query("SELECT user_id FROM users", fetch=True)
    for u in users:
        try: await bot.send_message(u[0], message.text); await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Готово!"); await state.clear()

@dp.message(F.text == "🎁 Розыгрыш")
async def show_giveaway(message: types.Message):
    if not CURRENT_GIVEAWAY["active"]: return await message.answer("😔 Активных розыгрышей нет.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Участвовать", callback_data="join_g")]])
    await message.answer(f"🎉 <b>{CURRENT_GIVEAWAY['title']}</b>\n\n{CURRENT_GIVEAWAY['desc']}", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "join_g")
async def join_giveaway(callback: types.CallbackQuery):
    u_id = callback.from_user.id
    check = db_query("SELECT * FROM giveaway WHERE user_id = ?", (u_id,), fetch=True)
    if check: return await callback.answer("⚠️ Вы уже участвуете!", show_alert=True)
    db_query("INSERT INTO giveaway (user_id) VALUES (?)", (u_id,), commit=True)
    await callback.answer("✅ Вы зарегистрированы!", show_alert=True)

@dp.message(Command("new_giveaway"))
async def new_giveaway_cmd(message: types.Message, state: FSMContext):
    if message.from_user.id in ADMIN_IDS:
        db_query("DELETE FROM giveaway", commit=True)
        await message.answer("🏆 Название розыгрыша:"); await state.set_state(AdForm.waiting_for_giveaway_title)

@dp.message(AdForm.waiting_for_giveaway_title)
async def g_title(message: types.Message, state: FSMContext):
    await state.update_data(gt=message.text); await message.answer("📝 Описание:"); await state.set_state(AdForm.waiting_for_giveaway_desc)

@dp.message(AdForm.waiting_for_giveaway_desc)
async def g_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    CURRENT_GIVEAWAY.update({"active": True, "title": data['gt'], "desc": message.text})
    await message.answer("✅ Розыгрыш запущен!"); await state.clear()

@dp.message(Command("winner"))
async def pick_winner(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        users = db_query("SELECT user_id FROM giveaway", fetch=True)
        if not users: return await message.answer("❌ Участников нет.")
        winner = random.choice(users)[0]
        CURRENT_GIVEAWAY["active"] = False
        await message.answer(f"🎊 Победитель: <a href='tg://user?id={winner}'>Ссылка на профиль</a>", parse_mode="HTML")

@dp.message(F.text.in_(["💰 Продать", "🛒 Купить"]))
async def start_ad(message: types.Message, state: FSMContext):
    res = db_query("SELECT ban_until FROM users WHERE user_id = ?", (message.from_user.id,), fetch=True)
    if res and res[0][0] > time.time(): return await message.answer("🚫 Вы забанены.")
    await message.answer("📁 Категория:", reply_markup=cat_kb); await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def set_cat(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text); await message.answer("📝 Описание:", reply_markup=ReplyKeyboardRemove()); await state.set_state(AdForm.item)

@dp.message(AdForm.item)
async def set_item(message: types.Message, state: FSMContext):
    await state.update_data(item=message.text); await message.answer("💵 Цена:"); await state.set_state(AdForm.price)

@dp.message(AdForm.price)
async def set_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text); await message.answer("📞 Контакт:"); await state.set_state(AdForm.contact)

@dp.message(AdForm.contact)
async def set_contact(message: types.Message, state: FSMContext):
    await state.update_data(contact=message.text); await message.answer("📸 Скриншот:", reply_markup=skip_kb); await state.set_state(AdForm.photo)

@dp.message(AdForm.photo)
async def process_photo(message: types.Message, state: FSMContext):
    p_id = message.photo[-1].file_id if message.photo else None
    if message.text != "🚫 Без фото" and not message.photo: return await message.answer("📸 Отправьте фото или нажмите кнопку.")
    await state.update_data(photo=p_id); data = await state.get_data()
    txt = f"🧐 Проверка:\n━━━━━━━━━━━━━━━\nТовар: {data['item']}\nЦена: {data['price']}\nКонтакт: {data['contact']}"
    if p_id: await message.answer_photo(p_id, caption=txt, reply_markup=confirm_kb, parse_mode="HTML")
    else: await message.answer(txt, reply_markup=confirm_kb, parse_mode="HTML")
    await state.set_state(AdForm.confirm)

@dp.callback_query(F.data == "final_send", AdForm.confirm)
async def final_send(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    db_query("UPDATE users SET total_ads = total_ads + 1 WHERE user_id = ?", (callback.from_user.id,), commit=True)
    p_id = data.get('photo')
    txt = (f"📄 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>\n━━━━━━━━━━━━━━━\n📦 Товар: {data['item']}\n💰 Цена: {data['price']}\n📞 Тел: {data['contact']}\n━━━━━━━━━━━━━━━\n👤 Автор: <a href='tg://user?id={callback.from_user.id}'>Профиль</a>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"aprv_{callback.from_user.id}")],[InlineKeyboardButton(text="❌ Отклонить", callback_data="rej_")],[InlineKeyboardButton(text="⚠️ ВАРН", callback_data=f"warn_{callback.from_user.id}")]])
    for a_id in ADMIN_IDS:
        try:
            if p_id: await bot.send_photo(a_id, p_id, caption=txt, reply_markup=kb, parse_mode="HTML")
            else: await bot.send_message(a_id, txt, reply_markup=kb, parse_mode="HTML")
        except: pass
    await callback.message.delete(); await callback.message.answer("⏳ На проверке!", reply_markup=main_kb); await state.clear()

@dp.callback_query(F.data == "cancel_ad")
async def cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear(); await callback.message.delete(); await callback.message.answer("❌ Отменено.", reply_markup=main_kb)

@dp.callback_query(F.data == "rej_")
async def reject(callback: types.CallbackQuery): await callback.message.delete()

@dp.message(F.text == "📜 Правила")
async def rules(message: types.Message):
    await message.answer("📝 <b>Правила:</b>\n1. Без спама.\n2. Только реальные цены.\n3. Скрины из игры.", parse_mode="HTML")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
