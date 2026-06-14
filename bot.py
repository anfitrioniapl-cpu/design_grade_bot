# -*- coding: utf-8 -*-
"""
Телеграм-бот «Тест на грейд графического дизайнера».

Логика:
1. /start → проверка подписки на канал (бот должен быть админом канала).
2. Не подписан → кнопки «Подписаться» и «Я подписался».
3. Подписан → ситуационный тест, каждый ответ даёт 0–3 балла.
4. Перед выдачей результата подписка проверяется повторно.

Настройка — через переменные окружения:
  BOT_TOKEN — токен от @BotFather
  CHANNEL   — юзернейм канала, например @my_design_channel
"""

import asyncio
import logging
import os
import random

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from questions import MAX_SCORE, QUESTIONS, get_grade

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8978364388:AAE2D6qHX2o5YUAC3WhJdcf5e6Hf61e5MQ0")
CHANNEL = os.getenv("CHANNEL", "@alinuchka")
CHANNEL_URL = f"https://t.me/{CHANNEL.lstrip('@')}"

if not BOT_TOKEN:
    raise SystemExit("Задайте переменную окружения BOT_TOKEN (токен от @BotFather)")

LETTERS = ["А", "Б", "В", "Г", "Д", "Е"]

# Папка с картинками: в конце теста бот пришлёт случайную из неё (под спойлером)
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")


def random_image():
    """Случайная картинка из папки images (png/jpg/jpeg/webp)."""
    if not os.path.isdir(IMAGES_DIR):
        return None
    files = [
        os.path.join(IMAGES_DIR, f)
        for f in os.listdir(IMAGES_DIR)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ]
    return random.choice(files) if files else None


# Сессии теста в памяти: user_id -> {"q": номер вопроса, "score": баллы, "orders": перемешивание вариантов}
sessions: dict[int, dict] = {}


# ---------------------------------------------------------------- подписка

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """True, если пользователь подписан на канал."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in ("creator", "administrator", "member")
    except Exception as e:
        logging.warning("Не удалось проверить подписку: %s", e)
        return False


def subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")],
    ])


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать тест", callback_data="begin")],
    ])


# ---------------------------------------------------------------- вопросы

def question_text(q_index: int, order: list) -> str:
    q = QUESTIONS[q_index]
    lines = [f"<b>Вопрос {q_index + 1} из {len(QUESTIONS)}</b>", "", q["text"], ""]
    for i, opt_i in enumerate(order):
        lines.append(f"<b>{LETTERS[i]})</b> {q['options'][opt_i][0]}")
    return "\n".join(lines)


def question_keyboard(q_index: int, order: list) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text=LETTERS[i], callback_data=f"ans:{q_index}:{opt_i}")
        for i, opt_i in enumerate(order)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


async def send_question(message: Message, user_id: int, edit: bool = False) -> None:
    s = sessions[user_id]
    q_index = s["q"]
    order = s["orders"][q_index]
    text = question_text(q_index, order)
    kb = question_keyboard(q_index, order)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


def new_session(user_id: int) -> None:
    orders = []
    for q in QUESTIONS:
        order = list(range(len(q["options"])))
        random.shuffle(order)  # варианты перемешиваются у каждого по-своему
        orders.append(order)
    sessions[user_id] = {"q": 0, "score": 0, "orders": orders}


# ---------------------------------------------------------------- хендлеры

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    if await is_subscribed(bot, message.from_user.id):
        await message.answer(
            "Привет! Это тест на грейд графического дизайнера.\n\n"
            f"{len(QUESTIONS)} рабочих ситуаций — выбирайте, как поступили бы вы. "
            "Правильных ответов нет, но каждое решение оценивается по зрелости.\n\n"
            "В конце — ваш грейд: от Junior− до Senior+.",
            reply_markup=start_keyboard(),
        )
    else:
        await message.answer(
            "Привет! Это тест на грейд графического дизайнера.\n\n"
            f"Тест доступен подписчикам канала {CHANNEL}.\n"
            "Подпишитесь и нажмите «Я подписался».",
            reply_markup=subscribe_keyboard(),
        )


@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery, bot: Bot) -> None:
    if await is_subscribed(bot, call.from_user.id):
        await call.message.edit_text(
            f"Подписка подтверждена ✅\n\n"
            f"{len(QUESTIONS)} рабочих ситуаций — выбирайте, как поступили бы вы. "
            "В конце — ваш грейд: от Junior− до Senior+.",
            reply_markup=start_keyboard(),
        )
    else:
        await call.answer(
            "Пока не вижу подписки. Подпишитесь на канал и нажмите ещё раз.",
            show_alert=True,
        )


@dp.callback_query(F.data == "begin")
async def cb_begin(call: CallbackQuery, bot: Bot) -> None:
    # Сообщение может быть фото с результатом — поэтому удаляем и шлём новое
    try:
        await call.message.delete()
    except Exception:
        pass
    if not await is_subscribed(bot, call.from_user.id):
        await call.message.answer(
            f"Тест доступен подписчикам канала {CHANNEL}.",
            reply_markup=subscribe_keyboard(),
        )
        await call.answer()
        return
    new_session(call.from_user.id)
    await send_question(call.message, call.from_user.id, edit=False)
    await call.answer()


@dp.callback_query(F.data.startswith("ans:"))
async def cb_answer(call: CallbackQuery, bot: Bot) -> None:
    user_id = call.from_user.id
    s = sessions.get(user_id)
    if s is None:
        await call.answer("Сессия не найдена — нажмите /start", show_alert=True)
        return

    _, q_str, opt_str = call.data.split(":")
    q_index, opt_index = int(q_str), int(opt_str)

    if q_index != s["q"]:
        await call.answer("На этот вопрос вы уже ответили 🙂")
        return

    s["score"] += QUESTIONS[q_index]["options"][opt_index][1]
    s["q"] += 1

    if s["q"] < len(QUESTIONS):
        await send_question(call.message, user_id, edit=True)
        await call.answer()
        return

    # Тест пройден — повторная проверка подписки перед результатом
    if not await is_subscribed(bot, user_id):
        await call.message.edit_text(
            f"Чтобы увидеть результат, вернитесь в канал {CHANNEL} 🙂",
            reply_markup=subscribe_keyboard(),
        )
        await call.answer()
        return

    score = s["score"]
    grade, description, img_name = get_grade(score)
    percent = round(score * 100 / MAX_SCORE)
    del sessions[user_id]

    caption = (
        f"<b>Ваш грейд: {grade}</b>\n\n"
        f"Баллы: {score} из {MAX_SCORE} ({percent}%)\n\n"
        f"{description}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Пройти ещё раз", callback_data="begin")],
    ])

    image_path = random_image()
    if image_path:
        await call.message.delete()
        await call.message.answer_photo(
            FSInputFile(image_path),
            caption=caption,
            reply_markup=kb,
            has_spoiler=True,
        )
    else:
        await call.message.edit_text(caption, reply_markup=kb)
    await call.answer()


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer("Команды:\n/start — начать тест\n/help — эта справка")


# ---------------------------------------------------------------- запуск

async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
