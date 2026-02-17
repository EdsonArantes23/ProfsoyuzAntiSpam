import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import Message

# ================= ЗАГРУЗКА КОНФИГУРАЦИИ =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 417850992  # Ваш ID админа

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в настройках хостинга!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= НАСТРОЙКИ (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ!) =================

# 📍 Где работать
TARGET_CHAT_ID = -1002977868330   # Группа: Профсоюз Зяблов
TARGET_TOPIC_ID = 1               # Топик: Общая (из ссылки ..._1)

# 🤖 Боты: ВСЕ их сообщения будут удаляться в указанном топике
# (независимо от текста, команд, содержания)
CLEAN_BOTS = [1264548383]         # pipisabot — удалять ВСЁ

# ⚡ Команды: удалять сообщения, содержащие эти команды (от любых пользователей)
CLEAN_COMMANDS = [
    "/dick",
    "/top_dick", 
    "/stats",
    "/global_top",
    "/dick@pipisabot",
    "/top_dick@pipisabot",
    "/stats@pipisabot",
    "/global_top@pipisabot"
]

# 🚫 Стоп-слова: удалять сообщения, содержащие эти слова (от любых пользователей)
STOP_WORDS = []  # Можно добавить: ["спам", "реклама"]

# ================= ИНИЦИАЛИЗАЦИЯ =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= КОМАНДЫ АДМИНА =================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🤖 Бот работает!\nВсе настройки в коде.\n/status — показать настройки")

@dp.message(Command("status"))
async def cmd_status(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    text = (
        f"⚙️ **НАСТРОЙКИ БОТА**\n\n"
        f"📍 Группа: `{TARGET_CHAT_ID}`\n"
        f"📁 Топик: `{TARGET_TOPIC_ID}`\n\n"
        f"🤖 **Боты (удалять ВСЕ сообщения):**\n"
        + "\n".join([f"- `{b}`" for b in CLEAN_BOTS]) + "\n\n"
        f"⚡ **Команды (удалять сообщения с ними):**\n"
        + "\n".join([f"- `{c}`" for c in CLEAN_COMMANDS]) + "\n\n"
        f"🚫 **Стоп-слова:**\n"
        + ("\n".join([f"- `{w}`" for w in STOP_WORDS]) or "Нет")
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("test"))
async def cmd_test(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("✅ Бот онлайн! Настройки активны.")

# ================= ОСНОВНОЙ ФИЛЬТР =================

@dp.message()
async def message_handler(message: Message):
    try:
        # Игнорируем сообщения от самого себя
        if message.from_user.id == bot.id:
            return

        chat_id = message.chat.id
        topic_id = message.message_thread_id if message.is_topic_message else 0
        
        # 🔹 Проверка группы
        if chat_id != TARGET_CHAT_ID:
            return
        
        # 🔹 Проверка топика
        if TARGET_TOPIC_ID > 0 and topic_id != TARGET_TOPIC_ID:
            return
        
        should_delete = False
        delete_reason = ""

        # 🔹 1. ПРОВЕРКА БОТОВ: удаляем ВСЕ сообщения от указанных ботов
        if message.from_user.id in CLEAN_BOTS:
            should_delete = True
            delete_reason = f"БОТ {message.from_user.id} (все сообщения)"
        
        # 🔹 2. ПРОВЕРКА КОМАНД: удаляем сообщения с запрещенными командами
        if not should_delete and message.text:
            for cmd in CLEAN_COMMANDS:
                if cmd.lower() in message.text.lower():
                    should_delete = True
                    delete_reason = f"команда '{cmd}'"
                    break
        
        # 🔹 3. ПРОВЕРКА СТОП-СЛОВ: удаляем сообщения с запрещенными словами
        if not should_delete and message.text:
            for word in STOP_WORDS:
                if word.lower() in message.text.lower():
                    should_delete = True
                    delete_reason = f"стоп-слово '{word}'"
                    break
        
        # 🔹 УДАЛЕНИЕ
        if should_delete:
            try:
                await message.delete()
                logger.info(f"🗑 УДАЛЕНО: {delete_reason} | От: {message.from_user.id} | Текст: {message.text[:30] if message.text else '(нет текста)'}")
            except Exception as e:
                logger.error(f"❌ Ошибка удаления: {e}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике: {e}")

# ================= ЗАПУСК =================

async def main():
    logger.info("🚀 Бот запущен...")
    logger.info(f"👤 Admin ID: {ADMIN_ID}")
    logger.info(f"📍 Группа: {TARGET_CHAT_ID} | Топик: {TARGET_TOPIC_ID}")
    logger.info(f"🤖 Ботов (удалять ВСЁ): {CLEAN_BOTS}")
    logger.info(f"⚡ Команд на чистку: {len(CLEAN_COMMANDS)}")
    logger.info(f"🚫 Стоп-слов: {len(STOP_WORDS)}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
