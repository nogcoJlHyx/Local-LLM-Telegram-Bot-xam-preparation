import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from dotenv import load_dotenv

from checker import check_answer

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("exam_bot")

# Список разрешенных Telegram ID пользователей
ALLOWED_USERS = [
    123456789,  # Вашии ID
]

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("В файле .env отсутствует BOT_TOKEN")

BASE_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = BASE_DIR / "questions.json"

if not QUESTIONS_FILE.exists():
    raise FileNotFoundError(f"Файл вопросов не найден: {QUESTIONS_FILE}")

with QUESTIONS_FILE.open("r", encoding="utf-8") as file:
    QUESTIONS = json.load(file)

logger.info("Успешно загружено %d вопросов из %s", len(QUESTIONS), QUESTIONS_FILE.name)

# Сессия с таймаутом 120с
session = AiohttpSession(timeout=120.0)
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())


@dp.update.outer_middleware()
async def access_middleware(handler, event, data):
    user = data.get("event_from_user")
    if not user:
        return await handler(event, data)

    logger.info("Запрос от Telegram ID: %s (@%s)", user.id, user.username)

    if user.id not in ALLOWED_USERS:
        logger.warning("Доступ запрещен для ID: %s", user.id)
        if event.message:
            await event.message.answer("⛔ Извините, у вас нет доступа к этому боту.")
        elif event.callback_query:
            await event.callback_query.answer("⛔ Доступ ограничен.", show_alert=True)
        return

    return await handler(event, data)


class ExamState(StatesGroup):
    answering = State()


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Разбивает длинный отчет на сообщения, не превышающие лимит Telegram."""
    parts = []
    current = ""

    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 <= limit:
            current += paragraph + "\n\n"
        else:
            if current.strip():
                parts.append(current.strip())
            current = paragraph + "\n\n"

    if current.strip():
        parts.append(current.strip())

    return parts


async def send_current_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    current_index = data.get("current_index", 0)

    if current_index >= len(QUESTIONS):
        await finish_exam(message, state)
        return

    question = QUESTIONS[current_index]

    text = (
        f"❓ <b>Вопрос {current_index + 1}/{len(QUESTIONS)}</b>\n\n"
        f"{question['question']}\n\n"
        "<i>Введите ответ сообщением в чат.</i>"
    )

    await message.answer(text)


@dp.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "👋 <b>Добро пожаловать в бот-экзаменатор!</b>\n\n"
        f"В базе сейчас <b>{len(QUESTIONS)}</b> вопросов.\n"
        "Для начала теста отправьте команду /exam."
    )


@dp.message(Command("exam"))
async def exam_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(
        current_index=0,
        answers=[],
    )
    await state.set_state(ExamState.answering)
    await send_current_question(message, state)


@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Тестирование отменено. Для нового запуска используйте /exam.")


@dp.message(ExamState.answering, F.text)
async def process_answer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    answers = data.get("answers", [])

    question = QUESTIONS[current_index]

    try:
        # ЗАМЕНА: Используем asyncio.to_thread для запуска синхронной проверки в отдельном потоке.
        # Это позволяет боту не зависать, пока Ollama анализирует текст.
        check_result = await asyncio.to_thread(
            check_answer,
            question=question["question"],
            correct_answer=question["correct_answer"],
            user_answer=message.text,
            question_type=question.get("type", "semantic"),
            required_elements=question.get("required_elements", {}),
        )
    except Exception as error:
        logger.exception("Ошибка проверки ответа: %s", error)
        check_result = {
            "is_correct": False,
            "score": 0,
            "missing_elements": ["ошибка сервиса проверки"],
            "detected_elements": {},
            "explanation": "Сервис проверки временно недоступен.",
        }

    is_correct = bool(check_result.get("is_correct", False))

    # --- МГНОВЕННЫЙ ОТВЕТ С МИКРОПОЯСНЕНИЕМ ПОСЛЕ КАЖДОГО ВОПРОСА ---
    status = "✅ <b>ВЕРНО!</b>" if is_correct else "❌ <b>НЕВЕРНО!</b>"
    
    explanation = question.get("explanation") or check_result.get("explanation", "")
    checker_explanation = check_result.get("explanation", "")

    feedback_msg = [
        f"{status}",
        f"<b>Эталонный ответ:</b> {question['correct_answer']}"
    ]

    if explanation:
        feedback_msg.append(f"💡 <b>Пояснение:</b> {explanation}")
    elif checker_explanation:
        feedback_msg.append(f"💡 <b>Пояснение:</b> {checker_explanation}")

    missing = check_result.get("missing_elements", [])
    if not is_correct and missing:
        feedback_msg.append(f"⚠️ <b>Пропущено в ответе:</b> {', '.join(missing)}")

    await message.answer("\n".join(feedback_msg))

    # Сохраняем ответ
    answers.append(
        {
            "number": question.get("number", f"Вопрос {current_index + 1}"),
            "question": question["question"],
            "user_answer": message.text,
            "correct_answer": question["correct_answer"],
            "is_correct": is_correct,
            "score": check_result.get("score", 0),
            "explanation": question.get("explanation", ""),
            "checker_explanation": check_result.get("explanation", ""),
            "missing_elements": check_result.get("missing_elements", []),
        }
    )

    await state.update_data(
        current_index=current_index + 1,
        answers=answers,
    )

    await send_current_question(message, state)


async def finish_exam(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    answers = data.get("answers", [])

    correct_count = sum(1 for item in answers if item["is_correct"])
    total = len(answers)
    percent = round(correct_count / total * 100, 1) if total else 0

    report = [
        "🏁 <b>ТЕСТИРОВАНИЕ ЗАВЕРШЕНО!</b>",
        f"📊 Итоговый результат: <b>{correct_count}</b> из <b>{total}</b> ({percent}%)",
        "",
        "Спасибо за прохождение теста!"
    ]

    report_text = "\n".join(report)

    for part in split_message(report_text):
        await message.answer(part)

    await state.clear()


async def main() -> None:
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as error:
        logger.warning("Не удалось удалить вебхук: %s", error)

    logger.info("Запуск polling Telegram...")
    await dp.start_polling(
        bot,
        polling_timeout=20,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот успешно остановлен.")
