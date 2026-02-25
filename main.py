import asyncio
import logging
import json
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
import os
from datetime import datetime

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 417850992  # Ваш ID

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
DB_NAME = "antispam.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                chat_id INTEGER,
                topic_id INTEGER,
                spam_words TEXT,
                PRIMARY KEY (chat_id, topic_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                topic_id INTEGER,
                old_words TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_cache (
                message_id INTEGER,
                chat_id INTEGER,
                topic_id INTEGER,
                user_id INTEGER,
                text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (message_id, chat_id)
            )
        """)
        await db.commit()

# --- ФУНКЦИИ БД ---

async def get_rules(chat_id, topic_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT spam_words FROM rules WHERE chat_id = ? AND topic_id = ?", 
            (chat_id, topic_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
        
        async with db.execute(
            "SELECT spam_words FROM rules WHERE chat_id = ? AND topic_id IS NULL", 
            (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
        
        return []

async def get_all_topics_for_chat(chat_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT topic_id, spam_words FROM rules WHERE chat_id = ? ORDER BY topic_id",
            (chat_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [(row[0], json.loads(row[1])) for row in rows]

async def get_all_rules_summary():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT chat_id, topic_id, spam_words FROM rules ORDER BY chat_id, topic_id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [(row[0], row[1], json.loads(row[2])) for row in rows]

async def save_rules_backup(chat_id, topic_id, old_words):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO history (chat_id, topic_id, old_words) VALUES (?, ?, ?)",
            (chat_id, topic_id, json.dumps(old_words if old_words else []))
        )
        await db.commit()

async def update_rules(chat_id, topic_id, new_words):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR REPLACE INTO rules (chat_id, topic_id, spam_words) 
            VALUES (?, ?, ?)
        """, (chat_id, topic_id, json.dumps(new_words)))
        await db.commit()

async def delete_single_rule(chat_id, topic_id, word_to_delete):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT spam_words FROM rules WHERE chat_id = ? AND topic_id = ?",
            (chat_id, topic_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                current_words = json.loads(row[0])
                if word_to_delete in current_words:
                    await save_rules_backup(chat_id, topic_id, current_words)
                    current_words.remove(word_to_delete)
                    if current_words:
                        await update_rules(chat_id, topic_id, current_words)
                    else:
                        await db.execute(
                            "DELETE FROM rules WHERE chat_id = ? AND topic_id = ?",
                            (chat_id, topic_id)
                        )
                        await db.commit()
                    return True, len(current_words)
                return False, len(current_words)
            return False, 0

async def undo_last_change(chat_id, topic_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, old_words FROM history WHERE chat_id = ? AND topic_id IS ? ORDER BY id DESC LIMIT 1",
            (chat_id, topic_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                history_id, old_words = row
                await db.execute("""
                    INSERT OR REPLACE INTO rules (chat_id, topic_id, spam_words) 
                    VALUES (?, ?, ?)
                """, (chat_id, topic_id, old_words))
                await db.execute("DELETE FROM history WHERE id = ?", (history_id,))
                await db.commit()
                return True
            return False

async def get_all_chats_with_rules():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT DISTINCT chat_id FROM rules ORDER BY chat_id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def cache_message(message_id, chat_id, topic_id, user_id, text):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR REPLACE INTO message_cache (message_id, chat_id, topic_id, user_id, text)
            VALUES (?, ?, ?, ?, ?)
        """, (message_id, chat_id, topic_id, user_id, text))
        await db.commit()

async def get_user_messages(chat_id, user_id, topic_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        if topic_id is not None:
            async with db.execute(
                "SELECT message_id FROM message_cache WHERE chat_id = ? AND user_id = ? AND topic_id = ?",
                (chat_id, user_id, topic_id)
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
        else:
            async with db.execute(
                "SELECT message_id FROM message_cache WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

async def clear_user_cache(chat_id, user_id, topic_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        if topic_id is not None:
            await db.execute(
                "DELETE FROM message_cache WHERE chat_id = ? AND user_id = ? AND topic_id = ?",
                (chat_id, user_id, topic_id)
            )
        else:
            await db.execute(
                "DELETE FROM message_cache WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
        await db.commit()

async def clear_old_cache():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            DELETE FROM message_cache WHERE timestamp < datetime('now', '-48 hours')
        """)
        await db.commit()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_chat_type_name(topic_id):
    return "Ветка" if topic_id else "Вся группа"

def get_chat_type_emoji(topic_id):
    return "🧵" if topic_id else "🌐"

def get_chat_type_prefix(topic_id):
    return "Ветка #" if topic_id else "Вся группа"

def create_navigation_keyboard(current_chat_id=None):
    builder = InlineKeyboardBuilder()
    
    # Кнопки для навигации
    if current_chat_id:
        builder.button(text="◀️ Назад к списку чатов", callback_data="all_chats")
    else:
        builder.button(text="🔄 Обновить", callback_data="refresh")
    
    builder.adjust(1)
    return builder.as_markup()

# --- ПРОВЕРКА АДМИНА И ЛС ---
async def is_admin_in_pm(message: Message):
    if message.chat.type != "private":
        return False
    if message.from_user.id != ADMIN_ID:
        return False
    return True

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.type != "private":
        return
    
    if message.from_user.id == ADMIN_ID:
        # Создаем красивую клавиатуру с командами
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📝 Просмотреть правила", callback_data="view_rules")
        keyboard.button(text="➕ Добавить правило", callback_data="add_rule")
        keyboard.button(text="🧹 Очистить сообщения", callback_data="clean_messages")
        keyboard.button(text="ℹ️ Как пользоваться", callback_data="help")
        keyboard.adjust(2)
        
        welcome_text = (
            "🌟 <b>Добро пожаловать в ProfsoyuzAntiSpam Bot</b> 🌟\n\n"
            "Этот бот поможет вам автоматически удалять спам и нежелательные сообщения в ваших чатах.\n\n"
            "🔧 <b>Основные функции:</b>\n"
            "• Удаление сообщений по стоп-словам\n"
            "• Поддержка групп и веток\n"
            "• Удобное управление через команды\n"
            "• Быстрая очистка сообщений\n\n"
            "📌 <b>Доступные команды:</b>\n\n"
            "➕ <b>/add &lt;chat_id&gt; &lt;topic_id&gt; &lt;слово&gt;</b>\n"
            "   Добавляет стоп-слово в правила\n"
            "   Пример: /add -1001234567890 0 казино\n\n"
            "➖ <b>/del &lt;chat_id&gt; &lt;topic_id&gt; &lt;слово&gt;</b>\n"
            "   Удаляет стоп-слово из правил\n"
            "   Пример: /del -1001234567890 1 /dick\n\n"
            "📋 <b>/rules &lt;chat_id&gt; [&lt;topic_id&gt;]</b>\n"
            "   Показывает все правила для чата или ветки\n"
            "   Пример: /rules -1001234567890 1\n\n"
            "📊 <b>/all</b>\n"
            "   Показывает все правила во всех чатах\n\n"
            "↩️ <b>/undo &lt;chat_id&gt; &lt;topic_id&gt;</b>\n"
            "   Откатывает последнее изменение правил\n"
            "   Пример: /undo -1001234567890 1\n\n"
            "🗑 <b>/clean &lt;chat_id&gt; &lt;topic_id&gt; &lt;user_id&gt;</b>\n"
            "   Удаляет все сообщения пользователя из кэша\n"
            "   Пример: /clean -1001234567890 0 1264548383\n\n"
            "ℹ️ <b>/info</b>\n"
            "   Показывает как узнать ID чата или ветки\n\n"
            "💡 <b>Совет:</b>\n"
            "• Используйте <code>0</code> вместо <code>topic_id</code>, чтобы применить правило ко всему чату\n"
            "• Бот удаляет только сообщения за последние 48 часов"
        )
        
        await message.answer(
            welcome_text,
            parse_mode="HTML",
            reply_markup=keyboard.as_markup()
        )
    else:
        await message.answer(
            "Этот бот предназначен для модерации групп. "
            "Обратитесь к администратору для получения доступа."
        )

# --- КОЛЛБЭКИ ДЛЯ ИНЛЕНЙ КНОПОК ---
@dp.callback_query(F.data == "view_rules")
async def callback_view_rules(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔍 <b>Как посмотреть правила?</b>\n\n"
        "Введите команду:\n"
        "/rules <code>&lt;chat_id&gt;</code> [<code>topic_id</code>]\n\n"
        "📌 <b>Примеры:</b>\n"
        "/rules -1001234567890 — для всей группы\n"
        "/rules -1001234567890 1 — для ветки 1\n\n"
        "💡 Вы также можете переслать сообщение из чата, чтобы автоматически получить ID.",
        parse_mode="HTML",
        reply_markup=create_navigation_keyboard(None)
    )
    await callback.answer()

@dp.callback_query(F.data == "add_rule")
async def callback_add_rule(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "➕ <b>Как добавить стоп-слово?</b>\n\n"
        "Введите команду:\n"
        "/add <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;слово&gt;</code>\n\n"
        "📌 <b>Примеры:</b>\n"
        "/add -1001234567890 0 казино — для всей группы\n"
        "/add -1001234567890 1 /dick — для ветки 1\n\n"
        "💡 Используйте <code>0</code> для всей группы или номер ветки.",
        parse_mode="HTML",
        reply_markup=create_navigation_keyboard(None)
    )
    await callback.answer()

@dp.callback_query(F.data == "clean_messages")
async def callback_clean_messages(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🧹 <b>Как очистить сообщения?</b>\n\n"
        "Введите команду:\n"
        "/clean <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;user_id&gt;</code>\n\n"
        "📌 <b>Пример:</b>\n"
        "/clean -1001234567890 0 1264548383\n\n"
        "💡 Это удалит все сообщения пользователя из кэша бота.",
        parse_mode="HTML",
        reply_markup=create_navigation_keyboard(None)
    )
    await callback.answer()

@dp.callback_query(F.data == "help")
async def callback_help(callback: types.CallbackQuery):
    help_text = (
        "📚 <b>Инструкция по использованию ProfsoyuzAntiSpam Bot</b>\n\n"
        
        "<b>1. Получение ID чата/темы</b>\n"
        "• Перешлите любое сообщение из чата боту\n"
        "• Бот покажет ID чата и (если есть) ID темы\n\n"
        
        "<b>2. Добавление стоп-слов</b>\n"
        "• /add <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;слово&gt;</code>\n"
        "• Например: /add -1001234567890 0 казино\n\n"
        
        "<b>3. Просмотр правил</b>\n"
        "• /rules <code>&lt;chat_id&gt;</code> — все правила для чата\n"
        "• /rules <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> — правила для ветки\n\n"
        
        "<b>4. Удаление правил</b>\n"
        "• /del <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;слово&gt;</code>\n\n"
        
        "<b>5. Очистка сообщений</b>\n"
        "• /clean <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;user_id&gt;</code>\n\n"
        
        "💡 <b>Совет:</b>\n"
        "• Используйте <code>0</code> вместо <code>topic_id</code>, чтобы применить правило ко всему чату\n"
        "• Бот удаляет только сообщения за последние 48 часов"
    )
    
    await callback.message.edit_text(
        help_text,
        parse_mode="HTML",
        reply_markup=create_navigation_keyboard(None)
    )
    await callback.answer()

@dp.callback_query(F.data == "all_chats")
async def callback_all_chats(callback: types.CallbackQuery):
    rules = await get_all_rules_summary()
    
    if not rules:
        await callback.message.edit_text(
            "📭 <b>Нет настроенных правил</b>\n\n"
            "Вы можете добавить правила с помощью команды /add",
            parse_mode="HTML",
            reply_markup=create_navigation_keyboard(None)
        )
        await callback.answer()
        return
    
    text = "📊 <b>Все правила во всех чатах</b>\n\n"
    current_chat = None
    
    for chat_id, topic_id, words in rules:
        if chat_id != current_chat:
            current_chat = chat_id
            text += f"━━━━━━━━━━━━━━━━━━━━\n"
            text += f"🆔 <b>Группа:</b> <code>{chat_id}</code>\n"
        
        topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
        text += f"  📌 <b>{topic_name}:</b> {len(words)} стоп-слов\n"
        
        if words:
            # Показываем все слова, но если их много, делаем аккуратный вывод
            if len(words) <= 10:
                for word in words:
                    text += f"     • <code>{word}</code>\n"
            else:
                for word in words[:10]:
                    text += f"     • <code>{word}</code>\n"
                text += f"     • ... и ещё {len(words) - 10} стоп-слов\n"
        
        text += "\n"
    
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=create_navigation_keyboard(None)
    )
    await callback.answer()

@dp.callback_query(F.data == "refresh")
async def callback_refresh(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔄 <b>Обновление данных...</b>",
        parse_mode="HTML"
    )
    
    # Небольшая задержка для имитации загрузки
    await asyncio.sleep(0.5)
    
    await callback_all_chats(callback)

# --- ОСНОВНЫЕ КОМАНДЫ ---

@dp.message(Command("info"))
async def cmd_info(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    if message.reply_to_message:
        fwd = message.reply_to_message
        chat_id = fwd.chat.id
        topic_id = fwd.message_thread_id if hasattr(fwd, 'is_topic_message') and fwd.is_topic_message else None
        chat_name = fwd.chat.title or "Чат"
        
        text = (
            "🔍 <b>Информация о чате</b>\n\n"
            f"📌 <b>Название:</b> <code>{chat_name}</code>\n"
            f"🆔 <b>Chat ID:</b> <code>{chat_id}</code>\n"
        )
        
        if topic_id is not None:
            text += f"🧵 <b>Topic ID:</b> <code>{topic_id}</code>\n"
        else:
            text += "🧵 <b>Topic ID:</b> <code>0</code> (обычная группа)\n"
        
        text += f"👤 <b>Отправитель:</b> <code>{fwd.from_user.id}</code>"
        
        # Создаем клавиатуру с быстрыми действиями
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📋 Просмотреть правила", callback_data=f"rules_{chat_id}_0")
        keyboard.button(text="➕ Добавить правило", callback_data=f"add_{chat_id}_0")
        keyboard.adjust(1)
        
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard.as_markup())
    else:
        await message.answer(
            "ℹ️ <b>Как узнать ID чата или темы?</b>\n\n"
            "1. Перешлите любое сообщение из чата боту\n"
            "2. Бот автоматически покажет ID чата и (если есть) ID темы\n\n"
            "💡 Вы также можете использовать команду:\n"
            "/info <code>&lt;chat_id&gt;</code> — для получения информации о чате",
            parse_mode="HTML"
        )

@dp.message(Command("all"))
async def cmd_all(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    rules = await get_all_rules_summary()
    
    if not rules:
        await message.answer(
            "📭 <b>Нет настроенных правил</b>\n\n"
            "Вы можете добавить правила с помощью команды /add",
            parse_mode="HTML"
        )
        return
    
    text = "📊 <b>Все правила во всех чатах</b>\n\n"
    current_chat = None
    
    for chat_id, topic_id, words in rules:
        if chat_id != current_chat:
            current_chat = chat_id
            text += f"━━━━━━━━━━━━━━━━━━━━\n"
            text += f"🆔 <b>Группа:</b> <code>{chat_id}</code>\n"
        
        topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
        text += f"  📌 <b>{topic_name}:</b> {len(words)} стоп-слов\n"
        
        if words:
            # Показываем все слова, но если их много, делаем аккуратный вывод
            if len(words) <= 10:
                for word in words:
                    text += f"     • <code>{word}</code>\n"
            else:
                for word in words[:10]:
                    text += f"     • <code>{word}</code>\n"
                text += f"     • ... и ещё {len(words) - 10} стоп-слов\n"
        
        text += "\n"
    
    # Создаем клавиатуру с кнопкой обновления
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Обновить", callback_data="refresh")
    keyboard.adjust(1)
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard.as_markup())

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "🔍 <b>Как посмотреть правила?</b>\n\n"
            "Введите команду:\n"
            "/rules <code>&lt;chat_id&gt;</code> [<code>topic_id</code>]\n\n"
            "📌 <b>Примеры:</b>\n"
            "/rules -1001234567890 — для всей группы\n"
            "/rules -1001234567890 1 — для ветки 1\n\n"
            "💡 Вы также можете переслать сообщение из чата, чтобы автоматически получить ID.",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if len(args) > 2 and args[2] != "0" else None
        
        words = await get_rules(chat_id, topic_id)
        
        if not words:
            await message.answer(
                f"📭 <b>Нет правил для {get_chat_type_prefix(topic_id)}{topic_id or ''}</b>\n\n"
                "Вы можете добавить правила с помощью команды:\n"
                f"/add <code>{chat_id}</code> <code>{topic_id or 0}</code> <code>&lt;слово&gt;</code>",
                parse_mode="HTML"
            )
            return
        
        text = (
            f"{get_chat_type_emoji(topic_id)} <b>{get_chat_type_prefix(topic_id)}{topic_id or ''}</b>\n"
            f"Для чата: <code>{chat_id}</code>\n\n"
            "<b>Стоп-слова:</b>\n"
        )
        
        for i, word in enumerate(words, 1):
            text += f"{i}. <code>{word}</code>\n"
        
        text += f"\nВсего: {len(words)} стоп-слов"
        
        # Создаем клавиатуру с действиями
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="➕ Добавить стоп-слово", callback_data=f"add_{chat_id}_{topic_id or 0}")
        keyboard.button(text="◀️ Назад к списку веток", callback_data=f"topics_{chat_id}")
        keyboard.adjust(1)
        
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard.as_markup())
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка</b>: ID должны быть числами\n\n"
            "Убедитесь, что вы правильно указали chat_id и topic_id",
            parse_mode="HTML"
        )

@dp.message(Command("add"))
async def cmd_add(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    if len(args) < 4:
        await message.answer(
            "➕ <b>Как добавить стоп-слово?</b>\n\n"
            "Введите команду:\n"
            "/add <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;слово&gt;</code>\n\n"
            "📌 <b>Примеры:</b>\n"
            "/add -1001234567890 0 казино — для всей группы\n"
            "/add -1001234567890 1 /dick — для ветки 1\n\n"
            "💡 Используйте <code>0</code> для всей группы или номер ветки.",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        word = " ".join(args[3:])
        
        current_words = await get_rules(chat_id, topic_id)
        await save_rules_backup(chat_id, topic_id, current_words)
        
        if word not in current_words:
            current_words.append(word)
            await update_rules(chat_id, topic_id, current_words)
            
            topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
            
            await message.answer(
                f"✅ <b>Стоп-слово добавлено!</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🧵 <b>{topic_name}:</b>\n"
                f"   • <code>{word}</code>\n\n"
                f"Всего стоп-слов в этой секции: {len(current_words)}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"⚠️ <b>Внимание</b>: Это слово уже в списке\n\n"
                f"Группа: <code>{chat_id}</code>\n"
                f"Ветка: <code>{topic_id or 'вся группа'}</code>",
                parse_mode="HTML"
            )
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка</b>: ID должны быть числами\n\n"
            "Убедитесь, что вы правильно указали chat_id и topic_id",
            parse_mode="HTML"
        )

@dp.message(Command("del"))
async def cmd_del(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    if len(args) < 4:
        await message.answer(
            "➖ <b>Как удалить стоп-слово?</b>\n\n"
            "Введите команду:\n"
            "/del <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;слово&gt;</code>\n\n"
            "📌 <b>Пример:</b>\n"
            "/del -1001234567890 1 /dick",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        word = " ".join(args[3:])
        
        success, remaining = await delete_single_rule(chat_id, topic_id, word)
        topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
        
        if success:
            await message.answer(
                f"✅ <b>Стоп-слово удалено!</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🧵 <b>{topic_name}:</b>\n"
                f"   • <code>{word}</code>\n\n"
                f"Осталось стоп-слов в этой секции: {remaining}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"⚠️ <b>Внимание</b>: Слово не найдено\n\n"
                f"Группа: <code>{chat_id}</code>\n"
                f"Ветка: <code>{topic_id or 'вся группа'}</code>\n\n"
                "🔍 Вы можете проверить правила с помощью:\n"
                f"/rules <code>{chat_id}</code> <code>{topic_id or 0}</code>",
                parse_mode="HTML"
            )
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка</b>: ID должны быть числами\n\n"
            "Убедитесь, что вы правильно указали chat_id и topic_id",
            parse_mode="HTML"
        )

@dp.message(Command("clean"))
async def cmd_clean(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    if len(args) < 4:
        await message.answer(
            "🧹 <b>Как очистить сообщения?</b>\n\n"
            "Введите команду:\n"
            "/clean <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;user_id&gt;</code>\n\n"
            "📌 <b>Пример:</b>\n"
            "/clean -1001234567890 0 1264548383\n\n"
            "💡 Это удалит все сообщения пользователя из кэша бота.",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        user_id = int(args[3])
        
        await message.answer(f"🔄 Удаляю сообщения пользователя <code>{user_id}</code>...", parse_mode="HTML")
        
        msg_ids = await get_user_messages(chat_id, user_id, topic_id)
        deleted = 0
        
        for msg_id in msg_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                deleted += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logging.error(f"❌ Не удалил {msg_id}: {e}")
        
        await clear_user_cache(chat_id, user_id, topic_id)
        
        topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
        
        if deleted == 0:
            await message.answer(
                f"⚠️ <b>Нет сообщений для удаления</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🧵 <b>{topic_name}</b>\n"
                f"👤 <b>Пользователь:</b> <code>{user_id}</code>\n\n"
                "❌ Кэш пуст. Бот не сохранил сообщения.\n"
                "💡 Сообщения удаляются только за последние 48 часов.",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"✅ <b>Успешно удалено: {deleted} сообщений</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🧵 <b>{topic_name}</b>\n"
                f"👤 <b>Пользователь:</b> <code>{user_id}</code>",
                parse_mode="HTML"
            )
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка</b>: ID должны быть числами\n\n"
            "Убедитесь, что вы правильно указали chat_id, topic_id и user_id",
            parse_mode="HTML"
        )

@dp.message(Command("undo"))
async def cmd_undo(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "↩️ <b>Как откатить изменения?</b>\n\n"
            "Введите команду:\n"
            "/undo <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code>\n\n"
            "📌 <b>Пример:</b>\n"
            "/undo -1001234567890 1",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        
        success = await undo_last_change(chat_id, topic_id)
        topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
        
        if success:
            await message.answer(
                f"↩️ <b>Изменения откачены!</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🧵 <b>{topic_name}</b>\n\n"
                "Последнее изменение было отменено.",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "❌ <b>Ошибка</b>: Нечего откатывать\n\n"
                f"Группа: <code>{chat_id}</code>\n"
                f"Ветка: <code>{topic_id or 'вся группа'}</code>\n\n"
                "История изменений пуста.",
                parse_mode="HTML"
            )
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка</b>: ID должны быть числами\n\n"
            "Убедитесь, что вы правильно указали chat_id и topic_id",
            parse_mode="HTML"
        )

# --- ПРОВЕРКА СПАМА (В ГРУППАХ) ---
@dp.message()
async def check_spam(message: Message):
    if message.chat.type == "private":
        return
    
    chat_id = message.chat.id
    topic_id = message.message_thread_id if message.is_topic_message else None
    user_id = message.from_user.id
    text = message.text or ""
    
    # Кэшируем сообщение (для функции /clean)
    await cache_message(message.message_id, chat_id, topic_id, user_id, text)
    
    # Если нет текста — пропускаем
    if not text:
        return
    
    # Загружаем правила: сначала для ветки, потом для всей группы
    words = await get_rules(chat_id, topic_id)
    if not words:
        words = await get_rules(chat_id, None)
    
    if not words:
        return
    
    # Проверка стоп-слов
    for word in words:
        if word.lower() in text.lower():
            try:
                await message.delete()
                logging.info(f"🗑 Удалено: '{word}' | Чат:{chat_id} Ветка:{topic_id} Юзер:{user_id}")
            except Exception as e:
                logging.error(f"❌ Ошибка удаления: {e}")
            break

# --- ОЧИСТКА КЭША (каждые 6 часов) ---
async def clear_cache_periodically():
    while True:
        await asyncio.sleep(21600)  # 6 часов
        await clear_old_cache()
        logging.info("🧹 Старый кэш очищен")

# --- ЗАПУСК ---
async def main():
    await init_db()
    asyncio.create_task(clear_cache_periodically())
    me = await bot.get_me()
    logging.info(f"🤖 Бот запущен: @{me.username}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
