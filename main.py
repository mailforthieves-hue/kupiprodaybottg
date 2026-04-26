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

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="💰 Продать"), KeyboardButton(text="🛒 Купить")],
    [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📜 Правила")]
], resize_keyboard=True)

cat_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🚗 Авто"), KeyboardButton(text="🏠 Дом/Бизнес")],
    [KeyboardButton(text="👕 Скин/Аксессуар"), KeyboardButton(text="📦 Прочее")]
], resize_keyboard=True)

# Кнопка для пропуска фото
skip_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚫 Без фото")]], resize_keyboard=True)

confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✅ Отправить", callback_data="final_send")],
    [InlineKeyboardButton(text="❌ Сбросить", callback_data="cancel_ad")]
])

# --- ЛОГИКА ВАРНОВ ---
@dp.callback_query(F.data.startswith("warn_"))
async def start_warn(callback: types.CallbackQuery, state: FSMContext):
    target_id = callback.data.split("_")[1]
    await state.update_data(warn_target=target_id)
    await callback.message.answer(f"📝 Причина варна для ID {target_id}:")
    await state.set_state(AdForm.waiting_for_warn_reason)
    await callback.answer()

@dp.message(AdForm.waiting_for_warn_reason)
async def process_warn(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_id = int(data['warn_target'])
    db_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (t_id,), commit=True)
    db_query("UPDATE users SET warns = warns + 1 WHERE user_id = ?", (t_id,), commit=True)
    res = db_query("SELECT warns FROM users WHERE user_id = ?", (t_id,), fetch=True)
    warns = res[0][0]
    
    if warns >= 3:
        until = time.time() + (30 * 24 * 3600)
        db_query("UPDATE users SET ban_until = ?, ban_reason = ?, warns = 0 WHERE user_id = ?", 
                 (until, f"3/3 варна: {message.text}", t_id), commit=True)
        try: await bot.send_message(t_id, f"🚫 Бан на 30 дней (3/3 варна).\nПричина: {message.text}")
        except: pass
    else:
        try: await bot.send_message(t_id, f"⚠️ Предупреждение ({warns}/3)!\nПричина: {message.text}")
        except: pass
    await message.answer(f"✅ Готово. У юзера {warns}/3 варна.", reply_markup=main_kb)
    await state.clear()

# --- ОДОБРЕНИЕ ---
@dp.callback_query(F.data.startswith("aprv_"))
async def approve(callback: types.CallbackQuery):
    u_id = int(callback.data.split("_")[1])
    raw = callback.message.html_text if not callback.message.photo else callback.message.caption
    content = raw.split("━━━━━━━━━━━━━━━")[1].strip()
    full_text = f"📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n{content}"
    db_query("UPDATE users SET approved_ads = approved_ads + 1 WHERE user_id = ?", (u_id,), commit=True)
    photo_id = callback.message.photo[-1].file_id if callback.message.photo else None
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"rep_{u_id}")]])

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

@dp.message(F.text == "👤 Мой профиль")
async def profile(message: types.Message):
    u_id = message.from_user.id
    res = db_query("SELECT warns, approved_ads, ban_until FROM users WHERE user_id = ?", (u_id,), fetch=True)
    if not res: 
        db_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (u_id,), commit=True)
        res = [(0,0,0)]
    warns, approved, b_until = res[0]
    status = "🟢 Активен" if b_until < time.time() else "🔴 ЗАБАНЕН"
    await message.answer(
        f"👤 <b>ПРОФИЛЬ</b>\n━━━━━━━━━━━━━━━\nID: <code>{u_id}</code>\nСтатус: {status}\nВарны: {warns}/3\nСделок: {approved}", 
        parse_mode="HTML", reply_markup=main_kb
    )

@dp.message(F.text.in_(["💰 Продать", "🛒 Купить"]))
async def start_ad(message: types.Message, state: FSMContext):
    res = db_query("SELECT ban_until FROM users WHERE user_id = ?", (message.from_user.id,), fetch=True)
    if res and res[0][0] > time.time(): 
        return await message.answer("🚫 Вы забанены.")
    await message.answer("📁 Категория:", reply_markup=cat_kb)
    await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def set_cat(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("📝 Описание (Товар, тюнинг):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdForm.item)

@dp.message(AdForm.item)
async def set_item(message: types.Message, state: FSMContext):
    await state.update_data(item=message.text)
    await message.answer("💵 Цена:")
    await state.set_state(AdForm.price)

@dp.message(AdForm.price)
async def set_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text)
    await message.answer("📞 Контакт:")
    await state.set_state(AdForm.contact)

@dp.message(AdForm.contact)
async def set_contact(message: types.Message, state: FSMContext):
    await state.update_data(contact=message.text)
    await message.answer("📸 Скриншот (из игры):", reply_markup=skip_kb)
    await state.set_state(AdForm.photo)

# Обработка фото ИЛИ текста "Без фото"
@dp.message(AdForm.photo)
async def process_photo(message: types.Message, state: FSMContext):
    p_id = message.photo[-1].file_id if message.photo else None
    
    # Если нажал кнопку "Без фото" или просто прислал текст - игнорируем текст, если это не кнопка пропуска
    if message.text == "🚫 Без фото":
        p_id = None
    elif not message.photo:
        return await message.answer("📸 Пожалуйста, отправьте фото или нажмите кнопку пропуска.")

    await state.update_data(photo=p_id)
    data = await state.get_data()
    txt = f"🧐 Проверка:\n━━━━━━━━━━━━━━━\nТовар: {data['item']}\nЦена: {data['price']}\nКонтакт: {data['contact']}"
    
    if p_id: 
        await message.answer_photo(p_id, caption=txt, reply_markup=confirm_kb, parse_mode="HTML")
    else: 
        await message.answer(txt, reply_markup=confirm_kb, parse_mode="HTML")
    await state.set_state(AdForm.confirm)

@dp.callback_query(F.data == "final_send", AdForm.confirm)
async def final_send(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    p_id = data.get('photo')
    txt = (f"📄 <b>НОВОЕ ОБЪЯВЛЕНИЕ</b>\n━━━━━━━━━━━━━━━\n"
           f"📦 Товар: {data['item']}\n💰 Цена: {data['price']}\n"
           f"📞 Контакт: {data['contact']}\n━━━━━━━━━━━━━━━\n"
           f"👤 Автор: <a href='tg://user?id={callback.from_user.id}'>Профиль</a>")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"aprv_{callback.from_user.id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data="rej_")],
        [InlineKeyboardButton(text="⚠️ ВАРН", callback_data=f"warn_{callback.from_user.id}")]
    ])
    
    for a_id in ADMIN_IDS:
        try:
            if p_id: await bot.send_photo(a_id, p_id, caption=txt, reply_markup=kb, parse_mode="HTML")
            else: await bot.send_message(a_id, txt, reply_markup=kb, parse_mode="HTML")
        except: pass
    
    await callback.message.delete()
    await callback.message.answer("⏳ Отправлено модераторам!", reply_markup=main_kb)
    await state.clear()

@dp.callback_query(F.data == "cancel_ad")
async def cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Отменено.", reply_markup=main_kb)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    db_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,), commit=True)
    await state.clear()
    await message.answer("👋 Привет! Используйте кнопки меню.", reply_markup=main_kb)

@dp.callback_query(F.data == "rej_")
async def reject(callback: types.CallbackQuery): 
    await callback.message.delete()

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
