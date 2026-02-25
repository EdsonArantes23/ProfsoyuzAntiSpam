import asyncio
import logging
import json
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv
from datetime import datetime

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 417850992

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- JSON ХРАНИЛИЩЕ (вместо SQLite) ---
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"rules": {}, "history": [], "cache": []}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")

def get_rules_key(chat_id, topic_id):
    return f"{chat_id}_{topic_id}" if topic_id else f"{chat_id}_global"

def get_rules(chat_id, topic_id=None):
    data = load_data()
    key = get_rules_key(chat_id, topic_id)
    return data["rules"].get(key, [])

def add_rule(chat_id, topic_id, word):
    data = load_data()
    key = get_rules_key(chat_id, topic_id)
    if key not in data["rules"]:
        data["rules"][key] = []
    if word not in data["rules"][key]:
        data["history"].append({
            "chat_id": chat_id,
            "topic_id": topic_id,
            "action": "add",
            "word": word,
            "old_words": data["rules"][key].copy(),
            "timestamp": datetime.now().isoformat()
        })
        data["rules"][key].append(word)
        save_data(data)
        return True
    return False

def del_rule(chat_id, topic_id, word):
    data = load_data()
    key = get_rules_key(chat_id, topic_id)
    if key in data["rules"] and word in data["rules"][key]:
        data["history"].append({
            "chat_id": chat_id,
            "topic_id": topic_id,
            "action": "del",
            "word": word,
            "old_words": data["rules"][key].copy(),
            "timestamp": datetime.now().isoformat()
        })
        data["rules"][key].remove(word)
        save_data(data)
        return True
    return False

def undo_last_change(chat_id, topic_id):
    data = load_data()
    for i in range(len(data["history"]) - 1, -1, -1):
        h = data["history"][i]
        if h["chat_id"] == chat_id and h["topic_id"] == topic_id:
            key = get_rules_key(chat_id, topic_id)
            data["rules"][key] = h["old_words"]
            data["history"].pop(i)
            save_data(data)
            return True
    return False

def cache_message(message_id, chat_id, topic_id, user_id, text):
    data = load_data()
    data["cache"].append({
        "message_id": message_id,
        "chat_id": chat_id,
        "topic_id": topic_id,
        "user_id": user_id,
        "text": text,
        "timestamp": datetime.now().isoformat()
    })
    if len(data["cache"]) > 1000:
        data["cache"] = data["cache"][-1000:]
    save_data(data)

def get_user_messages(chat_id, user_id, topic_id=None):
    data = load_data()
    messages = []
    for msg in data["cache"]:
        if msg["chat_id"] == chat_id and msg["user_id"] == user_id:
            if topic_id is None or msg["topic_id"] == topic_id:
                messages.append(msg["message_id"])
    return messages

def clear_user_cache(chat_id, user_id, topic_id=None):
    data = load_data()
    data["cache"] = [
        msg for msg in data["cache"]
        if not (msg["chat_id"] == chat_id and msg["user_id"] == user_id and 
                (topic_id is None or msg["topic_id"] == topic_id))
    ]
    save_data(data)

def clear_old_cache():
    data = load_data()
    cutoff = datetime.now().timestamp() - (48 * 3600)
    data["cache"] = [
        msg for msg in data["cache"]
        if datetime.fromisoformat(msg["timestamp"]).timestamp() > cutoff
    ]
    save_data(data)

def get_all_rules_summary():
    data = load_data()
    result = []
    for key, words in data["rules"].items():
        parts = key.rsplit("_", 1)
        chat_id = int(parts[0])
        topic_id = int(parts[1]) if parts[1] != "global" else None
        result.append((chat_id, topic_id, words))
    return sorted(result, key=lambda x: (x[0], x[1] or 0))

def get_all_topics_for_chat(chat_id):
    data = load_data()
    result = []
    for key, words in data["rules"].items():
        if key.startswith(f"{chat_id}_"):
            parts = key.rsplit("_", 1)
            topic_id = int(parts[1]) if parts[1] != "global" else None
            result.append((topic_id, words))
    return sorted(result, key=lambda x: x[0] or 0)

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
            "**Команды:**\n"
            "/add <chat_id> <topic_id> <слово> — Добавить\n"
            "/del <chat_id> <topic_id> <слово> — Удалить\n"
            "/rules <chat_id> [topic_id] — Правила\n"
            "/all — Все правила\n"
            "/undo <chat_id> <topic_id> — Откат\n"
            "/clean <chat_id> <topic_id> <user_id> — Удалить сообщения\n"
            "/info — Узнать ID (переслать сообщение)\n\n"
            "topic_id=0 для всей группы",
            parse_mode="Markdown"
        )
    else:
        await message.answer("Бот для модерации групп.")

@dp.message(Command("info"))
async def cmd_info(message: Message):
    if not await is_admin_in_pm(message):
        return
    if message.reply_to_message:
        fwd = message.reply_to_message
        chat_id = fwd.chat.id
        topic_id = fwd.message_thread_id if hasattr(fwd, 'is_topic_message') and fwd.is_topic_message else None
        chat_name = fwd.chat.title or "Чат"
        text = f"**Информация:**\n\n"
        text += f"Название: `{chat_name}`\n"
        text += f"Chat ID: `{chat_id}`\n"
        if topic_id is not None:
            text += f"Topic ID: `{topic_id}`\n"
        else:
            text += f"Topic ID: `0` (обычная группа)\n"
        text += f"От: `{fwd.from_user.id}`"
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("Перешлите сообщение из чата для получения ID")

@dp.message(Command("all"))
async def cmd_all(message: Message):
    if not await is_admin_in_pm(message):
        return
    rules = get_all_rules_summary()
    if not rules:
        await message.answer("Нет правил")
        return
    text = "**Все правила:**\n\n"
    for chat_id, topic_id, words in rules:
        topic_name = f"Ветка #{topic_id}" if topic_id else "Вся группа"
        text += f"`{chat_id}` | {topic_name}: {len(words)} слов\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    if not await is_admin_in_pm(message):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Используйте: `/rules <chat_id> [topic_id]`")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if len(args) > 2 and args[2] != "0" else None
        words = get_rules(chat_id, topic_id)
        if words:
            text = "**Правила:**\n" + "\n".join(f"• `{w}`" for w in words)
            await message.answer(text, parse_mode="Markdown")
        else:
            await message.answer("Нет правил")
    except ValueError:
        await message.answer("ID должны быть числами")

@dp.message(Command("add"))
async def cmd_add(message: Message):
    if not await is_admin_in_pm(message):
        return
    args = message.text.split()
    if len(args) < 4:
        await message.answer("Используйте: `/add <chat_id> <topic_id> <слово>`")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        word = " ".join(args[3:])
        if add_rule(chat_id, topic_id, word):
            await message.answer(f"Добавлено: `{word}`")
        else:
            await message.answer("Уже есть в списке")
    except ValueError:
        await message.answer("ID должны быть числами")

@dp.message(Command("del"))
async def cmd_del(message: Message):
    if not await is_admin_in_pm(message):
        return
    args = message.text.split()
    if len(args) < 4:
        await message.answer("Используйте: `/del <chat_id> <topic_id> <слово>`")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        word = " ".join(args[3:])
        if del_rule(chat_id, topic_id, word):
            await message.answer(f"Удалено: `{word}`")
        else:
            await message.answer("Не найдено")
    except ValueError:
        await message.answer("ID должны быть числами")

@dp.message(Command("clean"))
async def cmd_clean(message: Message):
    if not await is_admin_in_pm(message):
        return
    args = message.text.split()
    if len(args) < 4:
        await message.answer("Используйте: `/clean <chat_id> <topic_id> <user_id>`")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        user_id = int(args[3])
        msg_ids = get_user_messages(chat_id, user_id, topic_id)
        deleted = 0
        for msg_id in msg_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                deleted += 1
            except:
                pass
        clear_user_cache(chat_id, user_id, topic_id)
        await message.answer(f"Удалено: {deleted}")
    except ValueError:
        await message.answer("ID должны быть числами")

@dp.message(Command("undo"))
async def cmd_undo(message: Message):
    if not await is_admin_in_pm(message):
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Используйте: `/undo <chat_id> <topic_id>`")
        return
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        if undo_last_change(chat_id, topic_id):
            await message.answer("Откат выполнен")
        else:
            await message.answer("Нечего откатывать")
    except ValueError:
        await message.answer("ID должны быть числами")

# --- ПРОВЕРКА СПАМА ---
@dp.message()
async def check_spam(message: Message):
    if message.chat.type == "private":
        return
    chat_id = message.chat.id
    topic_id = message.message_thread_id if message.is_topic_message else None
    user_id = message.from_user.id
    text = message.text or ""
    cache_message(message.message_id, chat_id, topic_id, user_id, text)
    if not text:
        return
    words = get_rules(chat_id, topic_id)
    if not words:
        words = get_rules(chat_id, None)
    if not words:
        return
    for word in words:
        if word.lower() in text.lower():
            try:
                await message.delete()
                logging.info(f"Удалено: {word}")
            except Exception as e:
                logging.error(f"Ошибка: {e}")
            break

# --- ОЧИСТКА КЭША ---
async def clear_cache_periodically():
    while True:
        await asyncio.sleep(21600)
        clear_old_cache()

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(clear_cache_periodically())
    me = await bot.get_me()
    logging.info(f"Бот запущен: @{me.username}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
