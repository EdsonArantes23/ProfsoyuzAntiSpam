import asyncio
import logging
import json
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from datetime import datetime

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 417850992  # Ваш ID

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- JSON ХРАНИЛИЩЕ (вместо SQLite) ---
DATA_FILE = "data.json"

def load_data():
    """Загружает данные из JSON файла"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки данных: {e}")
    return {"rules": {}, "history": [], "cache": []}

def save_data(data):
    """Сохраняет данные в JSON файл"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")

def get_rules_key(chat_id, topic_id):
    """
    Генерирует ключ для правил.
    topic_id может быть None (для всей группы/"веб-ветки _1") или числом (для настоящих тем).
    """
    # Используем "global" для None, чтобы избежать проблем с ключами
    return f"{chat_id}_{topic_id}" if topic_id is not None else f"{chat_id}_global"

def get_rules(chat_id, topic_id=None):
    """
    Получает правила для чата/темы.
    topic_id = None соответствует "веб-ветке _1" или всей основной группе.
    topic_id = число соответствует настоящей теме (topic).
    """
    data = load_data()
    key = get_rules_key(chat_id, topic_id)
    return data["rules"].get(key, [])

def add_rule(chat_id, topic_id, word):
    """
    Добавляет правило.
    topic_id = None используется для "веб-ветки _1" и всей основной группы.
    topic_id = число используется для настоящих тем (topics).
    """
    data = load_data()
    key = get_rules_key(chat_id, topic_id)
    
    if key not in data["rules"]:
        data["rules"][key] = []
    
    if word not in data["rules"][key]:
        # Сохраняем историю для отката
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
    """
    Удаляет правило.
    topic_id = None используется для "веб-ветки _1" и всей основной группы.
    topic_id = число используется для настоящих тем (topics).
    """
    data = load_data()
    key = get_rules_key(chat_id, topic_id)
    
    if key in data["rules"] and word in data["rules"][key]:
        # Сохраняем историю для отката
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
    """
    Откатывает последнее изменение.
    topic_id = None используется для "веб-ветки _1" и всей основной группы.
    topic_id = число используется для настоящих тем (topics).
    """
    data = load_data()
    # Ищем последнее изменение для этого чата/топика
    for i in range(len(data["history"]) - 1, -1, -1):
        h = data["history"][i]
        if h["chat_id"] == chat_id and h["topic_id"] == topic_id:
            # Восстанавливаем
            key = get_rules_key(chat_id, topic_id)
            data["rules"][key] = h["old_words"]
            # Удаляем запись истории
            data["history"].pop(i)
            save_data(data)
            return True
    return False

def cache_message(message_id, chat_id, topic_id, user_id, text):
    """Кэширует сообщение"""
    data = load_data()
    # Добавляем в кэш
    data["cache"].append({
        "message_id": message_id,
        "chat_id": chat_id,
        "topic_id": topic_id,
        "user_id": user_id,
        "text": text,
        "timestamp": datetime.now().isoformat()
    })
    # Храним только последние 1000 сообщений
    if len(data["cache"]) > 1000:
        data["cache"] = data["cache"][-1000:]
    save_data(data)

def get_user_messages(chat_id, user_id, topic_id=None):
    """Получает сообщения пользователя"""
    data = load_data()
    messages = []
    for msg in data["cache"]:
        if msg["chat_id"] == chat_id and msg["user_id"] == user_id:
            if topic_id is None or msg["topic_id"] == topic_id:
                messages.append(msg["message_id"])
    return messages

def clear_user_cache(chat_id, user_id, topic_id=None):
    """Очищает кэш пользователя"""
    data = load_data()
    data["cache"] = [
        msg for msg in data["cache"]
        if not (msg["chat_id"] == chat_id and 
                msg["user_id"] == user_id and 
                (topic_id is None or msg["topic_id"] == topic_id))
    ]
    save_data(data)

def clear_old_cache():
    """Очищает старый кэш (старше 48 часов)"""
    data = load_data()
    cutoff = datetime.now().timestamp() - (48 * 3600)  # 48 часов
    data["cache"] = [
        msg for msg in data["cache"]
        if datetime.fromisoformat(msg["timestamp"]).timestamp() > cutoff
    ]
    save_data(data)

def get_all_rules_summary():
    """Возвращает все правила для отображения"""
    data = load_data()
    result = []
    for key, words in data["rules"].items():
        parts = key.rsplit("_", 1)
        chat_id = int(parts[0])
        # Проверяем, является ли последняя часть числом (topic_id) или "global"
        if parts[1] == "global":
            topic_id = None
        else:
            topic_id = int(parts[1])
        result.append((chat_id, topic_id, words))
    # Сортируем: сначала по chat_id, потом None (вся группа) идут первыми, затем по topic_id
    return sorted(result, key=lambda x: (x[0], x[1] is not None, x[1] or 0))

def get_all_topics_for_chat(chat_id):
    """
    Возвращает все настоящие темы (не включая "веб-ветку _1" или всю группу) для чата.
    Используется в интерфейсе для отображения списка тем.
    """
    data = load_data()
    result = []
    for key, words in data["rules"].items():
        parts = key.rsplit("_", 1)
        stored_chat_id = int(parts[0])
        if stored_chat_id == chat_id and parts[1] != "global":
            topic_id = int(parts[1])
            result.append((topic_id, words))
    return sorted(result, key=lambda x: x[0])

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_chat_type_name(topic_id):
    return "Тема" if topic_id is not None else "Вся группа / Веб-ветка _1"

def get_chat_type_emoji(topic_id):
    return "🏷" if topic_id is not None else "🌐"

def get_chat_type_prefix(topic_id):
    return "Тема #" if topic_id is not None else "Вся группа / Веб-ветка _1"

def create_navigation_keyboard(current_chat_id=None):
    """Создает клавиатуру навигации"""
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
            "• Поддержка групп и <u>настоящих тем (форумов)</u>\n"
            "• Также работает с \"веб-веткой _1\" (где <code>message_thread_id = None</code>)\n"
            "• Учитывает регистр при проверке слов\n"
            "• Удобное управление через команды\n"
            "• Быстрая очистка сообщений\n\n"
            "📌 <b>Доступные команды:</b>\n\n"
            "➕ <b>/add &lt;chat_id&gt; &lt;topic_id&gt; &lt;слово&gt;</b>\n"
            "   Добавляет стоп-слово в правила\n"
            "   Пример: /add -1001234567890 0 казино\n"
            "   Пример (тема): /add -1001234567890 123 /dick\n\n"
            "   <b>ВАЖНО:</b> <code>topic_id = 0</code> используется для \"веб-ветки _1\" и всей основной группы.\n\n"
            "➖ <b>/del &lt;chat_id&gt; &lt;topic_id&gt; &lt;слово&gt;</b>\n"
            "   Удаляет стоп-слово из правил\n"
            "   Пример: /del -1001234567890 123 /dick\n\n"
            "📋 <b>/rules &lt;chat_id&gt; [&lt;topic_id&gt;]</b>\n"
            "   Показывает все правила для чата или темы\n"
            "   Пример: /rules -1001234567890 123\n\n"
            "📊 <b>/all</b>\n"
            "   Показывает все правила во всех чатах\n\n"
            "↩️ <b>/undo &lt;chat_id&gt; &lt;topic_id&gt;</b>\n"
            "   Откатывает последнее изменение правил\n"
            "   Пример: /undo -1001234567890 123\n\n"
            "🗑 <b>/clean &lt;chat_id&gt; &lt;topic_id&gt; &lt;user_id&gt;</b>\n"
            "   Удаляет все сообщения пользователя из кэша\n"
            "   Пример: /clean -1001234567890 0 1264548383\n\n"
            "ℹ️ <b>/info</b>\n"
            "   Показывает как узнать ID чата или темы\n\n"
            "💡 <b>Совет:</b>\n"
            "• Используйте <code>0</code> вместо <code>topic_id</code>, чтобы применить правило к \"веб-ветке _1\" или всей группе\n"
            "• <code>topic_id</code> — это <u>числовой ID настоящей темы</u> (форума)\n"
            "• Бот учитывает регистр при проверке слов\n"
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
        "/rules -1001234567890 — для всей группы / веб-ветки _1\n"
        "/rules -1001234567890 123 — для темы 123\n\n"
        "💡 Вы также можете переслать сообщение из темы боту, чтобы автоматически получить ID.",
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
        "/add -1001234567890 0 казино — для всей группы / веб-ветки _1\n"
        "/add -1001234567890 123 /dick — для темы 123\n\n"
        "💡 Используйте <code>0</code> для всей группы / веб-ветки _1 или числовой ID темы.",
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
        "• Перешлите любое сообщение из чата или темы боту\n"
        "• Бот покажет ID чата и (если есть) ID темы\n\n"
        
        "<b>2. Добавление стоп-слов</b>\n"
        "• /add <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;слово&gt;</code>\n"
        "• Например: /add -1001234567890 0 казино\n"
        "• Или (для темы): /add -1001234567890 123 /dick\n"
        "• <b>ВАЖНО:</b> <code>topic_id = 0</code> используется для \"веб-ветки _1\" и всей основной группы.\n\n"
        
        "<b>3. Просмотр правил</b>\n"
        "• /rules <code>&lt;chat_id&gt;</code> — все правила для чата\n"
        "• /rules <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> — правила для темы\n\n"
        
        "<b>4. Удаление правил</b>\n"
        "• /del <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;слово&gt;</code>\n\n"
        
        "<b>5. Очистка сообщений</b>\n"
        "• /clean <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;user_id&gt;</code>\n\n"
        
        "💡 <b>Совет:</b>\n"
        "• Используйте <code>0</code> вместо <code>topic_id</code>, чтобы применить правило к \"веб-ветке _1\" или всей группе\n"
        "• <code>topic_id</code> — это <u>числовой ID настоящей темы</u> (форума)\n"
        "• Бот учитывает регистр при проверке слов\n"
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
    rules = get_all_rules_summary()
    
    if not rules:
        await callback.message.edit_text(
            "ostringstream <b>Нет настроенных правил</b>\n\n"
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
        
        topic_name = get_chat_type_prefix(topic_id) + ("" if topic_id is None else f" #{topic_id}")
        text += f"  📌 <b>{topic_name}:</b> {len(words)} стоп-слов\n"
        
        if words:
            # Показываем все слова (максимум 20, чтобы не перегружать)
            for i, word in enumerate(words[:20], 1):
                text += f"     {i}. <code>{word}</code>\n"
            if len(words) > 20:
                text += f"     • ... и ещё {len(words) - 20} стоп-слов\n"
        
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
        
        # ПРАВИЛЬНЫЙ СПОСОБ ОПРЕДЕЛЕНИЯ ТЕМЫ В AIOTGRAM 3.X
        topic_id = fwd.message_thread_id  # Это ключевая исправленная строка
        
        chat_name = fwd.chat.title or "Чат"
        
        # ДОБАВЛЯЕМ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ
        logging.info(f"ℹ️ Получен запрос info для чата: {chat_id}, тема: {topic_id}")
        logging.info(f"ℹ️ Тип объекта: {type(fwd)}")
        logging.info(f"ℹ️ Доступные атрибуты: {dir(fwd)}")
        
        text = (
            "🔍 <b>Информация о чате/теме</b>\n\n"
            f"📌 <b>Название:</b> <code>{chat_name}</code>\n"
            f"🆔 <b>Chat ID:</b> <code>{chat_id}</code>\n"
        )
        
        if topic_id is not None:
            text += f"🏷 <b>Topic ID:</b> <code>{topic_id}</code>\n"
            # ДОБАВЛЯЕМ ПОДСКАЗКУ ПОЛЬЗОВАТЕЛЮ
            text += f"💡 <b>Используйте этот ID:</b> <code>{topic_id}</code>\n"
        else:
            text += "🌐 <b>Topic ID:</b> <code>0</code> (вся группа / веб-ветка _1)\n"
        
        text += f"👤 <b>Отправитель:</b> <code>{fwd.from_user.id}</code>"
        
        # Создаем клавиатуру с быстрыми действиями
        keyboard = InlineKeyboardBuilder()
        if topic_id is not None:
            keyboard.button(text="📋 Просмотреть правила", callback_data=f"rules_{chat_id}_{topic_id}")
            keyboard.button(text="➕ Добавить правило", callback_data=f"add_{chat_id}_{topic_id}")
        else:
            keyboard.button(text="📋 Просмотреть правила", callback_data=f"rules_{chat_id}_0")
            keyboard.button(text="➕ Добавить правило", callback_data=f"add_{chat_id}_0")
        keyboard.adjust(1)
        
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard.as_markup())
        
        # ДОПОЛНИТЕЛЬНОЕ УВЕДОМЛЕНИЕ В ЛС
        await message.answer(
            "⚠️ <b>Важно:</b>\n"
            "• <u>Topic ID</u> — это <b>числовой идентификатор настоящей темы (форума)</b> в Telegram API.\n"
            "• Если <b>Topic ID: 0</b>, это может быть <b>веб-ветка _1</b> или <b>вся основная группа</b>.\n"
            "• Используйте <b>ID 0</b> в командах для настройки правил для \"веб-ветки _1\".\n"
            "• Пример правильной команды:\n"
            f"<code>/add {chat_id} 0 /dick</code>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "ℹ️ <b>Как узнать ID чата или темы?</b>\n\n"
            "1. Перешлите любое сообщение из чата или темы боту\n"
            "2. Бот автоматически покажет ID чата и (если есть) ID темы\n\n"
            "💡 Вы также можете использовать команду:\n"
            "/info <code>&lt;chat_id&gt;</code> — для получения информации о чате",
            parse_mode="HTML"
        )

@dp.message(Command("all"))
async def cmd_all(message: Message):
    if not await is_admin_in_pm(message):
        return
    
    rules = get_all_rules_summary()
    
    if not rules:
        await message.answer(
            "ostringstream <b>Нет настроенных правил</b>\n\n"
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
        
        topic_name = get_chat_type_prefix(topic_id) + ("" if topic_id is None else f" #{topic_id}")
        text += f"  📌 <b>{topic_name}:</b> {len(words)} стоп-слов\n"
        
        if words:
            # Показываем все слова (максимум 20, чтобы не перегружать)
            for i, word in enumerate(words[:20], 1):
                text += f"     {i}. <code>{word}</code>\n"
            if len(words) > 20:
                text += f"     • ... и ещё {len(words) - 20} стоп-слов\n"
        
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
            "/rules -1001234567890 — для всей группы / веб-ветки _1\n"
            "/rules -1001234567890 123 — для темы 123\n\n"
            "💡 Вы также можете переслать сообщение из темы боту, чтобы автоматически получить ID.",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if len(args) > 2 and args[2] != "0" else None
        
        words = get_rules(chat_id, topic_id)
        
        if not words:
            await message.answer(
                f"ostringstream <b>Нет правил для {get_chat_type_prefix(topic_id)}{'' if topic_id is None else f' #{topic_id}'}</b>\n\n"
                "Вы можете добавить правила с помощью команды:\n"
                f"/add <code>{chat_id}</code> <code>{topic_id or 0}</code> <code>&lt;слово&gt;</code>",
                parse_mode="HTML"
            )
            return
        
        text = (
            f"{get_chat_type_emoji(topic_id)} <b>{get_chat_type_prefix(topic_id)}{'' if topic_id is None else f' #{topic_id}'}</b>\n"
            f"Для чата: <code>{chat_id}</code>\n\n"
            "<b>Стоп-слова:</b>\n"
        )
        
        for i, word in enumerate(words, 1):
            text += f"{i}. <code>{word}</code>\n"
        
        text += f"\nВсего: {len(words)} стоп-слов"
        
        # Создаем клавиатуру с действиями
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="➕ Добавить стоп-слово", callback_data=f"add_{chat_id}_{topic_id or 0}")
        keyboard.button(text="◀️ Назад к списку тем", callback_data=f"topics_{chat_id}")
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
            "/add -1001234567890 0 казино — для всей группы / веб-ветки _1\n"
            "/add -1001234567890 123 /dick — для темы 123\n\n"
            "💡 Используйте <code>0</code> для всей группы / веб-ветки _1 или числовой ID темы.",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        word = " ".join(args[3:])
        
        if add_rule(chat_id, topic_id, word):
            topic_name = get_chat_type_prefix(topic_id) + ("" if topic_id is None else f" #{topic_id}")
            
            await message.answer(
                f"✅ <b>Стоп-слово добавлено!</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🏷 <b>{topic_name}:</b>\n"
                f"   • <code>{word}</code>\n\n"
                f"Всего стоп-слов в этой секции: {len(get_rules(chat_id, topic_id))}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"⚠️ <b>Внимание</b>: Это слово уже в списке\n\n"
                f"Группа: <code>{chat_id}</code>\n"
                f"Тема: <code>{topic_id or 'вся группа / веб-ветка _1'}</code>",
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
            "_MINUS <b>Как удалить стоп-слово?</b>\n\n"
            "Введите команду:\n"
            "/del <code>&lt;chat_id&gt;</code> <code>&lt;topic_id&gt;</code> <code>&lt;слово&gt;</code>\n\n"
            "📌 <b>Пример:</b>\n"
            "/del -1001234567890 123 /dick",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        word = " ".join(args[3:])
        
        if del_rule(chat_id, topic_id, word):
            topic_name = get_chat_type_prefix(topic_id) + ("" if topic_id is None else f" #{topic_id}")
            
            await message.answer(
                f"✅ <b>Стоп-слово удалено!</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🏷 <b>{topic_name}:</b>\n"
                f"   • <code>{word}</code>\n\n"
                f"Осталось стоп-слов в этой секции: {len(get_rules(chat_id, topic_id))}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"⚠️ <b>Внимание</b>: Слово не найдено\n\n"
                f"Группа: <code>{chat_id}</code>\n"
                f"Тема: <code>{topic_id or 'вся группа / веб-ветка _1'}</code>\n\n"
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
        
        msg_ids = get_user_messages(chat_id, user_id, topic_id)
        deleted = 0
        
        for msg_id in msg_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                deleted += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logging.error(f"❌ Не удалил {msg_id}: {e}")
        
        clear_user_cache(chat_id, user_id, topic_id)
        
        topic_name = get_chat_type_prefix(topic_id) + ("" if topic_id is None else f" #{topic_id}")
        
        if deleted == 0:
            await message.answer(
                f"⚠️ <b>Нет сообщений для удаления</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🏷 <b>{topic_name}</b>\n"
                f"👤 <b>Пользователь:</b> <code>{user_id}</code>\n\n"
                "❌ Кэш пуст. Бот не сохранил сообщения.\n"
                "💡 Сообщения удаляются только за последние 48 часов.",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"✅ <b>Успешно удалено: {deleted} сообщений</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🏷 <b>{topic_name}</b>\n"
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
            "/undo -1001234567890 123",
            parse_mode="HTML"
        )
        return
    
    try:
        chat_id = int(args[1])
        topic_id = int(args[2]) if args[2] != "0" else None
        
        if undo_last_change(chat_id, topic_id):
            topic_name = get_chat_type_prefix(topic_id) + ("" if topic_id is None else f" #{topic_id}")
            
            await message.answer(
                f"↩️ <b>Изменения откачены!</b>\n\n"
                f"📌 <b>Группа:</b> <code>{chat_id}</code>\n"
                f"🏷 <b>{topic_name}</b>\n\n"
                "Последнее изменение было отменено.",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "❌ <b>Ошибка</b>: Нечего откатывать\n\n"
                f"Группа: <code>{chat_id}</code>\n"
                f"Тема: <code>{topic_id or 'вся группа / веб-ветка _1'}</code>\n\n"
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
    # ПРАВИЛЬНЫЙ СПОСОБ ОПРЕДЕЛЕНИЯ ТЕМЫ В AIOTGRAM 3.X
    topic_id = message.message_thread_id # Это ключевая строка
    user_id = message.from_user.id
    is_bot = message.from_user.is_bot
    text = message.text or ""
    
    # 🔥 ДОБАВЬТЕ ЭТО ЛОГИРОВАНИЕ
    logging.info(f"📨 Получено сообщение: chat={chat_id}, topic={topic_id}, user={user_id}, is_bot={is_bot}, text='{text[:50]}'")
    
    # Кэшируем сообщение (для функции /clean)
    cache_message(message.message_id, chat_id, topic_id, user_id, text)
    
    # Если нет текста — пропускаем
    if not text:
        logging.info("⚠️ Нет текста, пропускаем")
        return
    
    # Загружаем правила: сначала для темы, потом для всей группы
    # topic_id может быть None (для "веб-ветки _1") или числом (для настоящей темы)
    words = get_rules(chat_id, topic_id)
    if not words:
        words = get_rules(chat_id, None) # Если нет правил для темы, проверяем "всю группу / веб-ветку _1"
    
    if not words:
        logging.info("ℹ️ Нет правил для этого чата/темы")
        return
    
    # Проверка стоп-слов (с учётом регистра)
    for word in words:
        if word.lower() in text.lower():  # <-- Проверка без учёта регистра
            logging.info(f"🗑 СТОП-СЛОВО НАЙДЕНО: '{word}' в теме {topic_id}")
            try:
                await message.delete()
                logging.info(f"✅ УСПЕШНО УДАЛЕНО")
            except Exception as e:
                logging.error(f"❌ ОШИБКА УДАЛЕНИЯ: {type(e).__name__}: {e}")
            break

# --- ОЧИСТКА КЭША (каждые 6 часов) ---
async def clear_cache_periodically():
    while True:
        await asyncio.sleep(21600)  # 6 часов
        clear_old_cache()
        logging.info("🧹 Старый кэш очищен")

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(clear_cache_periodically())
    me = await bot.get_me()
    logging.info(f"🤖 Бот запущен: @{me.username}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
