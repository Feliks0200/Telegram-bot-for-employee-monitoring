import asyncio
import json
import logging
import os
import sys

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message, message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

admin = "id"
USERS_FILE = "Users.json"
TOKEN = "token"

dp = Dispatcher()
bot = Bot(token=TOKEN)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

def load_users() -> set:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_users(users_set: set):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(users_set), f)

active_users = load_users()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in active_users:
        active_users.add(user_id)
        save_users(active_users)

    await message.answer(
        "Привет! Я бот для учета смен.\n"
        "Я буду присылать тебе опросники по графику."
    )

@dp.message(Command('test'))
async def cmd_test(message: Message):
    user_id = message.from_user.id
    # Вызываем отправку напрямую
    try:
        await send_shift_request_to_user(user_id)
        await message.answer("🧪 Тестовый опросник отправлен!")
    except Exception as e:
        await message.answer(f"Ошибка при отправке: {e}")
        print(f"Ошибка в /test: {e}")

def get_shift_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data="shift_yes"),
            InlineKeyboardButton(text="Нет", callback_data="shift_no"),
        ],
        [
            InlineKeyboardButton(text="Спросить через 30 мин",callback_data="shift_later"),
        ]
    ])

@dp.callback_query(F.data.startswith("shift_"))
async def shift_callback(calback: CallbackQuery):
    action = calback.data.split("_")[1]
    user = calback.from_user

    text_map = {
        "yes" : "Да, вышел",
        "no" : "еще не вышел",
        "later" : "напомнить нажал"
    }
    answer_text = text_map.get(action, "Не ответил")

    if action == "later":
        scheduler.add_job(
            send_shift_request_to_user,
            'interval',
            minutes=30,
            args=[user.id],
            id=f"later_{user.id}",
            max_instances=1,
            misfire_grace_time=60,
        )
        await calback.message.edit_text("Хорошо переспрошу через 30 мин.")
        await calback.message.edit_text("Напоминание отложенно!")
        return
    username_str = f"@{user.username}" if user.username else f"ID:{user.id}"
    await bot.send_message(
        admin,
        f"Отчет по смене : \n"
        f"От : {user.full_name} ({username_str}) \n"
        f"Ответ **{answer_text}**",
    )
    await calback.answer("Ответ записан")
    await calback.message.edit_text(f"Твой ответ принят: **{answer_text}**")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message,state: FSMContext):
    await state.clear()

    args = message.text.split(maxsplit=1)
    text_to_send = args[1] if len(args) > 1 else "Пустая задача"
    success_count = 0
    for user_id in active_users:
        try:
            await bot.send_message(user_id, f"Задача : {text_to_send}")
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            print(e)
    await message.answer(f"Рассылка завершена. Отправлено {success_count} работникам.")

async def send_shift_request_to_user(user_id: id):
    try:
        await bot.send_message(
            user_id,
            "Напоминание : ты вышел на смену?",
            reply_markup=get_shift_keyboard(),
        )
    except Exception as e:
        print(e)

async def scheduled_shift_broadcast():
    for user_id in active_users:
        await send_shift_request_to_user(user_id)


async def main() -> None:
    scheduler.add_job(scheduled_shift_broadcast, 'cron', hour=9, minute=0)
    scheduler.add_job(scheduled_shift_broadcast, 'cron', hour=20, minute=0)
    scheduler.start()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass