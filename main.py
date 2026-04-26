import asyncio
import logging
import time
import os
import random
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

if not TOKEN:
    raise ValueError("TOKEN не найден! Добавь его в переменные окружения")

ADMIN_IDS = [571694385] 
CHANNEL_ID = -1003779573728

# --- ПУТИ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.txt")
BAN_FILE = os.path.join(BASE_DIR, "banlist.txt")
GIVEAWAY_USERS = os.path.join(BASE_DIR, "giveaway_users.txt")

# Глобальный статус розыгрыша (в памяти)
CURRENT_GIVEAWAY = {"active": False, "title": "", "desc": ""}

# --- ФАЙЛЫ ---
def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
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

# --- ОБРАБОТЧИКИ АДМИН-КОМАНД (BROADCAST & STATS) ---

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

# --- ЛОГИКА ОДОБРЕНИЯ ОБЪЯВЛЕНИЙ (С БРОАДКАСТОМ) ---
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

        # 1. Пост в канал
        if photo_id:
            await bot.send_photo(CHANNEL_ID, photo_id, caption=broadcast_text, parse_mode="HTML")
        else:
            await bot.send_message(CHANNEL_ID, broadcast_text, parse_mode="HTML")

        # 2. Рассылка пользователям (броадкаст)
        await callback.answer(f"🚀 Рассылка {len(users)} пользователям...")
        for user in users:
            try:
                if photo_id:
                    await bot.send_photo(user, photo_id, caption=broadcast_text, parse_mode="HTML")
                else:
                    await bot.send_message(user, broadcast_text, parse_mode="HTML")
                await asyncio.sleep(0.05)
            except: pass

        try: await bot.send_message(u_id, "✅ Ваше объявление одобрено и разослано!")
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
        
        # Получаем кликабельную ссылку на победителя
        try:
            winner_chat = await bot.get_chat(winner_id)
            if winner_chat.username:
                winner_link = f"@{winner_chat.username}"
            else:
                winner_link = f"<a href='tg://user?id={winner_id}'>{winner_chat.full_name}</a>"
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

# --- ОБРАБОТЧИКИ АДМИН-КОМАНД (BROADCAST & STATS) ---

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

        # Авто-рассылка всем юзерам
        for user in users:
            try:
                if photo_id: await bot.send_photo(user, photo_id, caption=broadcast_text, parse_mode="HTML")
                else: await bot.send_message(user, broadcast_text, parse_mode="HTML")
                await asyncio.sleep(0.05)
            except: pass

        try: await bot.send_message(u_id, "✅ Опубликовано и разослано всем!")
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
        winner = random.choice(participants)
        prize = CURRENT_GIVEAWAY["title"]
        CURRENT_GIVEAWAY["active"] = False
        users = load_data(USERS_FILE)
        end_text = f"🏁 <b>РОЗЫГРЫШ ЗАВЕРШЕН!</b>\n\n🏆 Приз: {prize}\n🎊 Победитель: <a href='tg://user?id={winner}'>Профиль</a>"
        for u_id in users:
            try: await bot.send_message(u_id, end_text, parse_mode="HTML"); await asyncio.sleep(0.05)
            except: pass
        await message.answer(f"✅ Победитель выбран: {winner}")

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
    await state.update_data(category=message.text); await message.answer("📝 Описание:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(AdForm.item)

@dp.message(AdForm.item)
async def set_item(message: types.Message, state: FSMContext):
    await state.update_data(item=message.text); await message.answer("💵 Введите цену:"); await state.set_state(AdForm.price)

@dp.message(AdForm.price)
async def set_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text); await message.answer("📞 Контакт:"); await state.set_state(AdForm.contact)

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
