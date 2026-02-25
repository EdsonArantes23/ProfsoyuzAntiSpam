import asyncio
import logging
import json
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
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
        await message.answer(
            "🤖 **ProfsoyuzAntiSpam Bot**\n\n"
            "📌 **Управление стоп-словами**\n\n"
            "➕ `/add <chat_id> <topic_id> <слово>` — Добавить слово\n"
            "➖ `/del <chat_id> <topic_id> <слово>` — Удалить слово\n"
            "📋 `/rules <chat_id> [topic_id]` — Показать правила\n"
            "📊 `/all` — Все правила во всех чатах\n"
            "↩️ `/undo <chat_id> <topic_id>` — Откатить изменение\n"
            "🗑 `/clean <chat_id> <topic_id> <user_id>` — Удалить сообщения\n"
            "ℹ️ `/info` — Узнать ID чата/темы\n\n"
            "💡 **Параметры:**\n"
            "• `chat_id` — ID группы (например: `-1001234567890`)\n"
            "• `topic_id` — `0` для всей группы или `N` для ветки\n"
            "• `слово` — текст или команда для блокировки\n\n"
            "⚡ **Все команды работают только в ЛС с вами!**",
            parse_mode="Markdown"
        )
    else:
        await message.answer("🤖 Бот для модерации групп.")

@dp.message(Command("info"))
async def cmd_info(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    if message.reply_to_message:
        fwd = message.reply_to_message
        chat_id = fwd.chat.id
        topic_id = fwd.message_thread_id if hasattr(fwd, 'is_topic_message') and fwd.is_topic_message else None
        chat_name = fwd.chat.title or "Чат"
        
        text = f"📋 **Информация о чате**\n\n"
        text += f"📛 Название: `{chat_name}`\n"
        text += f"🆔 Chat ID: `{chat_id}`\n"
        if topic_id is not None:
            text += f"📑 Topic ID: `{topic_id}`\n"
        else:
            text += f"📑 Topic ID: `0` (обычная группа)\n"
        text += f"👤 От: `{fwd.from_user.id}`\n\n"
        text += "💡 Используйте эти ID в командах"
        
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer(
            "📌 **Перешлите сообщение** из чата или ветки,\n"
            "чтобы узнать его ID.\n\n"
            "Или введите вручную:\n"
            "`/info -1001234567890` — ID группы\n"
            "`/info -1001234567890 5` — ID ветки",
            parse_mode="Markdown"
        )

@dp.message(Command("all"))
async def cmd_all(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    rules = await get_all_rules_summary()
    
    if not rules:
        await message.answer("📭 Нет настроенных правил")
        return
    
    text = "📊 **Все правила во всех чатах**\n\n"
    current_chat = None
    
    for chat_id, topic_id, words in rules:
        if chat_id != current_chat:
            current_chat = chat_id
            text += f"\n━━━━━━━━━━━━\n🆔 **Группа:** `{chat_id}`\n"
        
        topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
        text += f"  📑 {topic_name}: {len(words)} слов\n"
        
        if words:
            preview = ", ".join(f"`{w}`" for w in words[:5])
            if len(words) > 5:
                preview += f" ... +{len(words) - 5}"
            text += f"     Пример: {preview}\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    
    if len(args) < 2:
        await message.answer(
            "❌ **Неверный формат**\n\n"
            "Используйте:\n"
            "`/rules <chat_id>` — все ветки чата\n"
            "`/rules <chat_id> <topic_id>` — конкретная ветка\n\n"
            "Пример: `/rules -1001234567890 1`",
            parse_mode="Markdown"
        )
        return
    
    try:
        chat_id = int(args[1])
        
        if len(args) >= 3:
            topic_id = int(args[2]) if args[2] != "0" else None
            words = await get_rules(chat_id, topic_id)
            topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
            
            text = f"📋 **Правила для: {topic_name}**\n"
            text += f"🆔 Группа: `{chat_id}`\n\n"
            
            if words:
                for i, word in enumerate(words, 1):
                    text += f"{i}. `{word}`\n"
                text += f"\n✅ Всего: {len(words)} слов"
            else:
                text += "📭 Нет правил"
            
            await message.answer(text, parse_mode="Markdown")
        else:
            topics = await get_all_topics_for_chat(chat_id)
            
            if not topics:
                await message.answer(f"📭 Для группы `{chat_id}` нет правил")
                return
            
            text = f"📋 **Все правила для группы `{chat_id}`**\n\n"
            
            for topic_id, words in topics:
                topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
                text += f"━━━━━━━━━━━━\n📑 **{topic_name}** ({len(words)} слов):\n"
                
                if words:
                    for word in words[:10]:
                        text += f"  • `{word}`\n"
                    if len(words) > 10:
                        text += f"  ... и ещё {len(words) - 10}\n"
                else:
                    text += "  📭 Пусто\n"
            
            await message.answer(text, parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ ID должны быть числами")

@dp.message(Command("add"))
async def cmd_add(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    
    if len(args) < 4:
        await message.answer(
            "❌ **Неверный формат**\n\n"
            "Используйте: `/add <chat_id> <topic_id> <слово>`\n\n"
            "**Примеры:**\n"
            "`/add -1001234567890 0 казино` — для всей группы\n"
            "`/add -1001234567890 1 /dick` — для ветки 1",
            parse_mode="Markdown"
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
                f"✅ **Добавлено:** `{word}`\n\n"
                f"📍 Группа: `{chat_id}`\n"
                f"📑 {topic_name}\n"
                f"📋 Всего слов: {len(current_words)}",
                parse_mode="Markdown"
            )
        else:
            await message.answer("⚠️ Это слово уже в списке")
    except ValueError:
        await message.answer("❌ ID должны быть числами")

@dp.message(Command("del"))
async def cmd_del(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    
    if len(args) < 4:
        await message.answer(
            "❌ **Неверный формат**\n\n"
            "Используйте: `/del <chat_id> <topic_id> <слово>`\n\n"
            "**Пример:**\n"
            "`/del -1001234567890 1 /dick`",
            parse_mode="Markdown"
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
                f"✅ **Удалено:** `{word}`\n\n"
                f"📍 Группа: `{chat_id}`\n"
                f"📑 {topic_name}\n"
                f"📋 Осталось слов: {remaining}",
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                f"⚠️ Слово не найдено\n\n"
                f"📍 Группа: `{chat_id}`\n"
                f"📑 {topic_name}\n"
                f"🔍 Проверьте: `/rules {chat_id} {args[2]}`",
                parse_mode="Markdown"
            )
    except ValueError:
        await message.answer("❌ ID должны быть числами")

@dp.message(Command("clean"))
async def cmd_clean(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    
    if len(args) < 4:
        await message.answer(
            "❌ **Неверный формат**\n\n"
            "Используйте: `/clean <chat_id> <topic_id> <user_id>`\n\n"
            "**Пример:**\n"
            "`/clean -1001234567890 0 1264548383`",
            parse_mode="Markdown"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        user_id = int(args[3])
        
        await message.answer(f"🔄 Удаляю сообщения пользователя `{user_id}`...")
        
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
                f"⚠️ **Удалено: 0**\n\n"
                f"📍 Группа: `{chat_id}`\n"
                f"📑 {topic_name}\n"
                f"👤 Пользователь: `{user_id}`\n\n"
                f"❌ Кэш пуст. Бот не сохранил сообщения.\n"
                f"💡 Сообщения удаляются только за последние 48 часов.",
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                f"✅ **Удалено: {deleted}**\n\n"
                f"📍 Группа: `{chat_id}`\n"
                f"📑 {topic_name}\n"
                f"👤 Пользователь: `{user_id}`",
                parse_mode="Markdown"
            )
    except ValueError:
        await message.answer("❌ ID должны быть числами")

@dp.message(Command("undo"))
async def cmd_undo(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    args = message.text.split()
    
    if len(args) < 3:
        await message.answer(
            "❌ **Неверный формат**\n\n"
            "Используйте: `/undo <chat_id> <topic_id>`\n\n"
            "**Пример:**\n"
            "`/undo -1001234567890 1`",
            parse_mode="Markdown"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        
        success = await undo_last_change(chat_id, topic_id)
        topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
        
        if success:
            await message.answer(
                f"↩️ **Откат выполнен**\n\n"
                f"📍 Группа: `{chat_id}`\n"
                f"📑 {topic_name}",
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                "❌ Нечего откатывать\n\n"
                f"📍 Группа: `{chat_id}`\n"
                f"📑 {topic_name}\n\n"
                "История изменений пуста.",
                parse_mode="Markdown"
            )
    except ValueError:
        await message.answer("❌ ID должны быть числами")

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
        await asyncio.sleep(21600)
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
