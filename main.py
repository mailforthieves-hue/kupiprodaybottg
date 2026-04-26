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
    # Состояния для розыгрыша
    waiting_for_giveaway_title = State()
    waiting_for_giveaway_desc = State()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="💰 Продать"), KeyboardButton(text="🛒 Купить")],
    [KeyboardButton(text="🎁 Розыгрыш")], # Кнопка всегда в меню
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
    users = load_data(USERS_FILE)
    await message.answer(f"🚀 Начинаю рассылку на {len(users)} чел...")
    for u_id in users:
        try:
            await bot.send_message(u_id, message.text)
            await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Готово!")
    await state.clear()

# --- ЛОГИКА РОЗЫГРЫШЕЙ ---

@dp.message(F.text == "🎁 Розыгрыш")
async def show_giveaway(message: types.Message):
    if not CURRENT_GIVEAWAY["active"]:
        return await message.answer("😔 На данный момент активных розыгрышей нет.")
    
    text = f"🎉 <b>ТЕКУЩИЙ РОЗЫГРЫШ: {CURRENT_GIVEAWAY['title']}</b>\n\n{CURRENT_GIVEAWAY['desc']}"
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
    await message.answer("📝 Введите УСЛОВИЯ и описание:")
    await state.set_state(AdForm.waiting_for_giveaway_desc)

@dp.message(AdForm.waiting_for_giveaway_desc)
async def confirm_g(message: types.Message, state: FSMContext):
    data = await state.get_data()
    CURRENT_GIVEAWAY["active"] = True
    CURRENT_GIVEAWAY["title"] = data['g_title']
    CURRENT_GIVEAWAY["desc"] = message.text
    
    users = load_data(USERS_FILE)
    broadcast_text = (f"📢 <b>НОВЫЙ РОЗЫГРЫШ!</b>\n\n"
                      f"🏆 {CURRENT_GIVEAWAY['title']}\n\n"
                      f"Нажми кнопку «Розыгрыш» в меню, чтобы принять участие!")
    
    await message.answer(f"🚀 Уведомляю {len(users)} пользователей...")
    for u_id in users:
        try:
            await bot.send_message(u_id, broadcast_text, parse_mode="HTML")
            await asyncio.sleep(0.05)
        except: pass
    await state.clear()
    await message.answer("✅ Розыгрыш запущен!")

@dp.callback_query(F.data == "participate_giveaway")
async def participate(callback: types.CallbackQuery):
    if not CURRENT_GIVEAWAY["active"]:
        return await callback.answer("❌ Розыгрыш уже завершен!", show_alert=True)
    
    u_id = str(callback.from_user.id)
    participants = load_data(GIVEAWAY_USERS)
    if u_id in participants:
        await callback.answer("⚠️ Вы уже участвуете!", show_alert=True)
    else:
        save_data(GIVEAWAY_USERS, u_id)
        await callback.answer("✅ Регистрация успешна!", show_alert=True)

@dp.message(Command("winner"))
async def choose_winner(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        participants = list(load_data(GIVEAWAY_USERS))
        if not participants: return await message.answer("❌ Участников нет.")
        
        winner = random.choice(participants)
        prize = CURRENT_GIVEAWAY["title"]
        CURRENT_GIVEAWAY["active"] = False # Закрываем розыгрыш
        
        users = load_data(USERS_FILE)
        end_text = (f"🏁 <b>РОЗЫГРЫШ ЗАВЕРШЕН!</b>\n\n"
                    f"🏆 Приз: {prize}\n"
                    f"🎊 Победитель: <a href='tg://user?id={winner}'>Нажми сюда</a>\n\n"
                    f"Поздравляем!")
        
        for u_id in users:
            try:
                await bot.send_message(u_id, end_text, parse_mode="HTML")
                await asyncio.sleep(0.05)
            except: pass
            
        await message.answer(f"✅ Победитель выбран: {winner}")

# --- БАЗОВЫЕ ОБРАБОТЧИКИ ---

@dp.message(CommandStart())
@dp.message(F.text == "📜 Правила")
async def cmd_start(message: types.Message, state: FSMContext):
    if str(message.from_user.id) in load_data(BAN_FILE):
        return await message.answer("🚫 Вы заблокированы.")
    save_data(USERS_FILE, message.from_user.id)
    await state.clear()
    if message.text == "📜 Правила":
        return await message.answer("📝 <b>Правила:</b>\n1. Без спама.\n2. Реальные цены.\n3. Скрины из игры.", parse_mode="HTML")
    await message.answer("👋 Привет! Выберите действие:", reply_markup=main_kb)

@dp.message(F.text.in_(["💰 Продать", "🛒 Купить"]))
async def start_ad(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if str(user_id) in load_data(BAN_FILE):
        return await message.answer("🚫 Вы заблокированы.")
    if user_id in user_timeouts and user_id not in ADMIN_IDS:
        rem = int(LIMIT_TIME - (time.time() - user_timeouts[user_id]))
        if rem > 0:
            return await message.answer(f"⏳ Подождите {rem // 60} мин.")
    
    await state.update_data(type=message.text)
    await message.answer("📁 Выберите категорию:", reply_markup=cat_kb)
    await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def set_cat(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("📝 Введите название товара и описание:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(AdForm.item)

@dp.message(AdForm.item)
async def set_item(message: types.Message, state: FSMContext):
    await state.update_data(item=message.text)
    await message.answer("💵 Введите цену:")
    await state.set_state(AdForm.price)

@dp.message(AdForm.price)
async def set_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text)
    user_nick = f"@{message.from_user.username}" if message.from_user.username else ""
    await message.answer(f"📞 <b>Как с вами связаться?</b>\n\nВведите ник (например, {user_nick}) или номер телефона.", parse_mode="HTML")
    await state.set_state(AdForm.contact)

@dp.message(AdForm.contact)
async def set_contact(message: types.Message, state: FSMContext):
    await state.update_data(contact=message.text)
    await message.answer("📸 Отправьте фото или нажмите кнопку:", reply_markup=skip_kb)
    await state.set_state(AdForm.photo)

@dp.message(AdForm.photo)
@dp.message(F.photo)
async def process_photo_preview(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    if not message.photo and message.text != "🚫 Без фото":
        return await message.answer("⚠️ Используйте кнопку или отправьте фото.")
    
    await state.update_data(photo=photo_id)
    data = await state.get_data()
    text = (f"🧐 <b>Проверьте объявление:</b>\n\nТовар: {data['item']}\nЦена: {data['price']}\nКонтакт: {data['contact']}")
    
    if photo_id:
        await message.answer_photo(photo_id, caption=text, reply_markup=confirm_kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=confirm_kb, parse_mode="HTML")
    await state.set_state(AdForm.confirm)

@dp.callback_query(F.data == "final_send", AdForm.confirm)
async def final_process(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # Функция отправки админам должна быть определена выше (как в твоем исходнике)
    await send_to_admins(data, callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("⏳ Отправлено модераторам!", reply_markup=main_kb)
    user_timeouts[callback.from_user.id] = time.time()
    await state.clear()

@dp.callback_query(F.data.startswith("aprv_"))
async def approve(callback: types.CallbackQuery):
    try:
        u_id = callback.data.split("_")[1]
        raw = callback.message.html_text if not callback.message.photo else callback.message.caption
        content = raw.split("━━━━━━━━━━━━━━━")[1].strip()
        header = "📢 <b>ОБЪЯВЛЕНИЕ</b>"
        
        if callback.message.photo:
            await bot.send_photo(CHANNEL_ID, callback.message.photo[-1].file_id, caption=f"{header}\n\n{content}", parse_mode="HTML")
        else:
            await bot.send_message(CHANNEL_ID, f"{header}\n\n{content}", parse_mode="HTML")
        
        try: await bot.send_message(u_id, "✅ Ваше объявление опубликовано!")
        except: pass
        await callback.message.delete()
        await callback.answer("Опубликовано!")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("rej_"))
async def reject(callback: types.CallbackQuery):
    u_id = callback.data.split("_")[1]
    try: await bot.send_message(u_id, "❌ Объявление отклонено.")
    except: pass
    await callback.message.delete()

@dp.callback_query(F.data.startswith("ban_"))
async def ban_user(callback: types.CallbackQuery):
    u_id = callback.data.split("_")[1]
    save_data(BAN_FILE, u_id)
    await callback.message.delete()
    await callback.answer("🚫 Забанен")

@dp.callback_query(F.data == "cancel_ad")
async def cancel_ad(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Отменено.", reply_markup=main_kb)

@dp.message(F.text == "👤 Мой профиль")
async def profile(message: types.Message):
    await message.answer(f"👤 Ваш ID: <code>{message.from_user.id}</code>", parse_mode="HTML")

# --- ОТПРАВКА АДМИНАМ (ВСПОМОГАТЕЛЬНАЯ) ---
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

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())def save_data(file_path, item):
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
    # Состояния для розыгрыша
    waiting_for_giveaway_title = State()
    waiting_for_giveaway_desc = State()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="💰 Продать"), KeyboardButton(text="🛒 Купить")],
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
        [InlineKeyboardButton(text="🎁 Принять участие", callback_data="participate_giveaway")]
    ])

# --- ОТПРАВКА АДМИНАМ ---
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
            if photo_id:
                await bot.send_photo(a_id, photo_id, caption=text, reply_markup=kb, parse_mode="HTML")
            else:
                await bot.send_message(a_id, text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Ошибка админки: {e}")

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
    users = load_data(USERS_FILE)
    await message.answer(f"🚀 Начинаю рассылку на {len(users)} чел...")
    for u_id in users:
        try:
            await bot.send_message(u_id, message.text)
            await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Готово!")
    await state.clear()

# --- ЛОГИКА РОЗЫГРЫШЕЙ ---

@dp.message(Command("new_giveaway"))
async def start_giveaway(message: types.Message, state: FSMContext):
    if message.from_user.id in ADMIN_IDS:
        if os.path.exists(GIVEAWAY_USERS): os.remove(GIVEAWAY_USERS)
        await message.answer("🏆 Введите НАЗВАНИЕ розыгрыша:")
        await state.set_state(AdForm.waiting_for_giveaway_title)

@dp.message(AdForm.waiting_for_giveaway_title)
async def set_g_title(message: types.Message, state: FSMContext):
    await state.update_data(g_title=message.text)
    await message.answer("📝 Введите УСЛОВИЯ и описание розыгрыша:")
    await state.set_state(AdForm.waiting_for_giveaway_desc)

@dp.message(AdForm.waiting_for_giveaway_desc)
async def confirm_g(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data['g_title']
    desc = message.text
    users = load_data(USERS_FILE)
    
    text = f"🎉 <b>НОВЫЙ РОЗЫГРЫШ: {title}</b>\n\n{desc}"
    await message.answer(f"🚀 Рассылаю розыгрыш {len(users)} пользователям...")
    
    for u_id in users:
        try:
            await bot.send_message(u_id, text, reply_markup=get_giveaway_kb(), parse_mode="HTML")
            await asyncio.sleep(0.05)
        except: pass
    await state.clear()
    await message.answer("✅ Розыгрыш запущен!")

@dp.callback_query(F.data == "participate_giveaway")
async def participate(callback: types.CallbackQuery):
    u_id = str(callback.from_user.id)
    participants = load_data(GIVEAWAY_USERS)
    if u_id in participants:
        await callback.answer("⚠️ Вы уже участвуете!", show_alert=True)
    else:
        save_data(GIVEAWAY_USERS, u_id)
        await callback.answer("✅ Вы успешно зарегистрированы!", show_alert=True)

@dp.message(Command("winner"))
async def choose_winner(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        participants = list(load_data(GIVEAWAY_USERS))
        if not participants: return await message.answer("❌ Участников нет.")
        winner = random.choice(participants)
        await message.answer(f"🎊 Победитель: <code>{winner}</code>\n<a href='tg://user?id={winner}'>Профиль</a>", parse_mode="HTML")

# --- БАЗОВЫЕ ОБРАБОТЧИКИ ---

@dp.message(CommandStart())
@dp.message(F.text == "📜 Правила")
async def cmd_start(message: types.Message, state: FSMContext):
    if str(message.from_user.id) in load_data(BAN_FILE):
        return await message.answer("🚫 Вы заблокированы.")
    save_data(USERS_FILE, message.from_user.id)
    await state.clear()
    if message.text == "📜 Правила":
        return await message.answer("📝 <b>Правила:</b>\n1. Без спама.\n2. Реальные цены.\n3. Скрины из игры.", parse_mode="HTML")
    await message.answer("👋 Привет! Выберите действие:", reply_markup=main_kb)

@dp.message(F.text.in_(["💰 Продать", "🛒 Купить"]))
async def start_ad(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if str(user_id) in load_data(BAN_FILE):
        return await message.answer("🚫 Вы заблокированы.")
    if user_id in user_timeouts and user_id not in ADMIN_IDS:
        rem = int(LIMIT_TIME - (time.time() - user_timeouts[user_id]))
        if rem > 0:
            return await message.answer(f"⏳ Подождите {rem // 60} мин.")
    
    await state.update_data(type=message.text)
    await message.answer("📁 Выберите категорию:", reply_markup=cat_kb)
    await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def set_cat(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("📝 Введите название товара и описание:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(AdForm.item)

@dp.message(AdForm.item)
async def set_item(message: types.Message, state: FSMContext):
    await state.update_data(item=message.text)
    await message.answer("💵 Введите цену:")
    await state.set_state(AdForm.price)

@dp.message(AdForm.price)
async def set_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text)
    user_nick = f"@{message.from_user.username}" if message.from_user.username else ""
    await message.answer(f"📞 <b>Как с вами связаться?</b>\n\nВведите ник (например, {user_nick}) или номер телефона.", parse_mode="HTML")
    await state.set_state(AdForm.contact)

@dp.message(AdForm.contact)
async def set_contact(message: types.Message, state: FSMContext):
    await state.update_data(contact=message.text)
    await message.answer("📸 Отправьте фото или нажмите кнопку:", reply_markup=skip_kb)
    await state.set_state(AdForm.photo)

@dp.message(AdForm.photo)
@dp.message(F.photo)
async def process_photo_preview(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    if not message.photo and message.text != "🚫 Без фото":
        return await message.answer("⚠️ Используйте кнопку или отправьте фото.")
    
    await state.update_data(photo=photo_id)
    data = await state.get_data()
    text = (f"🧐 <b>Проверьте объявление:</b>\n\nТовар: {data['item']}\nЦена: {data['price']}\nКонтакт: {data['contact']}")
    
    if photo_id:
        await message.answer_photo(photo_id, caption=text, reply_markup=confirm_kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=confirm_kb, parse_mode="HTML")
    await state.set_state(AdForm.confirm)

@dp.callback_query(F.data == "final_send", AdForm.confirm)
async def final_process(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await send_to_admins(data, callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("⏳ Отправлено модераторам!", reply_markup=main_kb)
    user_timeouts[callback.from_user.id] = time.time()
    await state.clear()

@dp.callback_query(F.data.startswith("aprv_"))
async def approve(callback: types.CallbackQuery):
    try:
        u_id = callback.data.split("_")[1]
        raw = callback.message.html_text if not callback.message.photo else callback.message.caption
        content = raw.split("━━━━━━━━━━━━━━━")[1].strip()
        header = "📢 <b>ОБЪЯВЛЕНИЕ</b>"
        
        if callback.message.photo:
            await bot.send_photo(CHANNEL_ID, callback.message.photo[-1].file_id, caption=f"{header}\n\n{content}", parse_mode="HTML")
        else:
            await bot.send_message(CHANNEL_ID, f"{header}\n\n{content}", parse_mode="HTML")
        
        try: await bot.send_message(u_id, "✅ Ваше объявление опубликовано!")
        except: pass
        await callback.message.delete()
        await callback.answer("Опубликовано!")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("rej_"))
async def reject(callback: types.CallbackQuery):
    u_id = callback.data.split("_")[1]
    try: await bot.send_message(u_id, "❌ Объявление отклонено.")
    except: pass
    await callback.message.delete()

@dp.callback_query(F.data.startswith("ban_"))
async def ban_user(callback: types.CallbackQuery):
    u_id = callback.data.split("_")[1]
    save_data(BAN_FILE, u_id)
    await callback.message.delete()
    await callback.answer("🚫 Забанен")

@dp.callback_query(F.data == "cancel_ad")
async def cancel_ad(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Отменено.", reply_markup=main_kb)

@dp.message(F.text == "👤 Мой профиль")
async def profile(message: types.Message):
    await message.answer(f"👤 Ваш ID: <code>{message.from_user.id}</code>", parse_mode="HTML")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
