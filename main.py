import asyncio
import logging
import sqlite3
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message

# ================= ЗАГРУЗКА КОНФИГУРАЦИИ =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в настройках хостинга!")
if not ADMIN_ID:
    raise ValueError("❌ ADMIN_ID не найден в настройках хостинга!")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    raise ValueError("❌ ADMIN_ID должен быть числом!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= БАЗА ДАННЫХ =================
DB_NAME = "bot_settings.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            chat_name TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            topic_id INTEGER,
            UNIQUE(chat_id, topic_id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stop_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            topic_id INTEGER,
            word TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clean_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            topic_id INTEGER,
            bot_id INTEGER
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clean_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            topic_id INTEGER,
            command TEXT
        )
    """)
    
    conn.commit()
    conn.close()

def db_execute(query, params=()):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    conn.close()

def db_fetchall(query, params=()):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = cursor.fetchall()
    conn.close()
    return result

# ================= ИНИЦИАЛИЗАЦИЯ =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
init_db()

# ================= ХЕЛПЕРЫ БД =================

def add_group(chat_id, chat_name=""):
    db_execute("INSERT OR REPLACE INTO groups (chat_id, chat_name) VALUES (?, ?)", (chat_id, chat_name))

def add_topic(chat_id, topic_id):
    db_execute("INSERT OR IGNORE INTO topics (chat_id, topic_id) VALUES (?, ?)", (chat_id, topic_id))

def add_stop_word(chat_id, topic_id, word):
    db_execute("INSERT INTO stop_words (chat_id, topic_id, word) VALUES (?, ?, ?)", (chat_id, topic_id, word))

def remove_stop_word(chat_id, topic_id, word):
    db_execute("DELETE FROM stop_words WHERE chat_id=? AND topic_id=? AND word=?", (chat_id, topic_id, word))

def get_stop_words(chat_id, topic_id):
    return [row[0] for row in db_fetchall("SELECT word FROM stop_words WHERE chat_id=? AND topic_id=?", (chat_id, topic_id))]

def add_clean_bot(chat_id, topic_id, bot_id):
    db_execute("INSERT OR IGNORE INTO clean_bots (chat_id, topic_id, bot_id) VALUES (?, ?, ?)", (chat_id, topic_id, bot_id))

def get_clean_bots(chat_id, topic_id):
    return [row[0] for row in db_fetchall("SELECT bot_id FROM clean_bots WHERE chat_id=? AND topic_id=?", (chat_id, topic_id))]

def add_clean_command(chat_id, topic_id, command):
    db_execute("INSERT OR IGNORE INTO clean_commands (chat_id, topic_id, command) VALUES (?, ?, ?)", (chat_id, topic_id, command))

def get_clean_commands(chat_id, topic_id):
    return [row[0] for row in db_fetchall("SELECT command FROM clean_commands WHERE chat_id=? AND topic_id=?", (chat_id, topic_id))]

def get_all_topics():
    return db_fetchall("SELECT chat_id, topic_id FROM topics")

# ================= АДМИН КОМАНДЫ =================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🤖 **Универсальный Анти-Спам Бот**\n\n"
        "Полная настройка под каждый топик.\n\n"
        "📋 **Команды:**\n"
        "/add_group <id> - Добавить группу\n"
        "/add_topic <id> <topic_id> - Добавить топик\n"
        "/add_word <id> <topic_id> <слово> - Стоп-слово\n"
        "/add_bot <id> <topic_id> <bot_id> - Чистка бота\n"
        "/add_cmd <id> <topic_id> <команда> - Чистка команды\n"
        "/show_config <id> <topic_id> - Настройки топика\n"
        "/my_chats - Все активные чаты\n"
        "/help_admin - Подробная инструкция"
    , parse_mode="Markdown")

@dp.message(Command("help_admin"))
async def cmd_help_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = (
        "🛠 **ПОЛНАЯ ИНСТРУКЦИЯ**\n\n"
        "1️⃣ **Группа:** `/add_group -100123456789`\n"
        "2️⃣ **Топик:** `/add_topic -100123456789 1`\n"
        "3️⃣ **Слово:** `/add_word -100123456789 1 спам`\n"
        "4️⃣ **Бот:** `/add_bot -100123456789 1 12345678`\n"
        "5️⃣ **Команда:** `/add_cmd -100123456789 1 /dick`\n\n"
        "ℹ️ ID топика — цифра после _ в ссылке на тему."
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("add_group"))
async def cmd_add_group(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Пример: `/add_group -100123456789`", parse_mode="Markdown")
        return
    try:
        chat_id = int(args[1])
        add_group(chat_id)
        await message.answer(f"✅ Группа `{chat_id}` добавлена.", parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный ID.")

@dp.message(Command("add_topic"))
async def cmd_add_topic(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Пример: `/add_topic -100123456789 1`", parse_mode="Markdown")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2])
        add_topic(chat_id, topic_id)
        await message.answer(f"✅ Топик `{topic_id}` активирован.", parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный ID.")

@dp.message(Command("add_word"))
async def cmd_add_word(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer("❌ Пример: `/add_word -100.. 1 слово`", parse_mode="Markdown")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2])
        word = args[3]
        add_stop_word(chat_id, topic_id, word)
        await message.answer(f"✅ Стоп-слово `{word}` добавлено.", parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный ID.")

@dp.message(Command("add_bot"))
async def cmd_add_bot(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 4:
        await message.answer("❌ Пример: `/add_bot -100.. 1 12345678`", parse_mode="Markdown")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2])
        bot_id = int(args[3])
        add_clean_bot(chat_id, topic_id, bot_id)
        await message.answer(f"✅ Бот `{bot_id}` будет удаляться.", parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный ID.")

@dp.message(Command("add_cmd"))
async def cmd_add_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer("❌ Пример: `/add_cmd -100.. 1 /dick`", parse_mode="Markdown")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2])
        cmd = args[3]
        add_clean_command(chat_id, topic_id, cmd)
        await message.answer(f"✅ Команда `{cmd}` будет удаляться.", parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный ID.")

@dp.message(Command("show_config"))
async def cmd_show_config(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Пример: `/show_config -100.. 1`", parse_mode="Markdown")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2])
        
        words = get_stop_words(chat_id, topic_id)
        bots = get_clean_bots(chat_id, topic_id)
        cmds = get_clean_commands(chat_id, topic_id)
        
        text = f"⚙️ **Настройки: `{chat_id}` / Топик `{topic_id}`**\n\n"
        text += f"🚫 **Стоп-слова ({len(words)}):**\n" + "\n".join([f"- `{w}`" for w in words]) + "\n\n"
        text += f"🤖 **Боты ({len(bots)}):**\n" + "\n".join([f"- `{b}`" for b in bots]) + "\n\n"
        text += f"⚡ **Команды ({len(cmds)}):**\n" + "\n".join([f"- `{c}`" for c in cmds])
        
        if not words and not bots and not cmds:
            text += "Пусто..."
            
        await message.answer(text, parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный ID.")

@dp.message(Command("my_chats"))
async def cmd_my_chats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    topics = get_all_topics()
    if not topics:
        await message.answer("📭 Нет настроенных топиков.")
        return
    
    text = "📂 **Активные мониторинги:**\n\n"
    for chat_id, topic_id in topics:
        text += f"▫️ Группа: `{chat_id}` | Топик: `{topic_id}`\n"
    
    await message.answer(text, parse_mode="Markdown")

# ================= ОСНОВНОЙ ФИЛЬТР =================

@dp.message()
async def message_handler(message: Message):
    if message.from_user.id == bot.id:
        return

    chat_id = message.chat.id
    topic_id = message.message_thread_id if message.is_topic_message else 0

    topics = db_fetchall("SELECT 1 FROM topics WHERE chat_id=? AND topic_id=?", (chat_id, topic_id))
    if not topics:
        return

    should_delete = False

    # 1. Стоп-слова
    if message.text:
        words = get_stop_words(chat_id, topic_id)
        for word in words:
            if word.lower() in message.text.lower():
                should_delete = True
                break
    
    # 2. Боты/Пользователи
    if not should_delete:
        clean_bots = get_clean_bots(chat_id, topic_id)
        if message.from_user.id in clean_bots:
            should_delete = True
            
    # 3. Команды
    if not should_delete and message.text:
        cmds = get_clean_commands(chat_id, topic_id)
        for cmd in cmds:
            if cmd.lower() in message.text.lower():
                should_delete = True
                break

    if should_delete:
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")

# ================= ЗАПУСК =================
async def main():
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
