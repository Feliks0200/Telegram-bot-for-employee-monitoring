import asyncio
import json
import logging
import os
import sys

import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message, message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

admin = "админ айди"
USERS_FILE = "Users.json"
WORK_FILE = "Work.json"
TOKEN = "токен бота"

dp = Dispatcher()
bot = Bot(token=TOKEN)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

admin_command = {"/setrole : меняет роли работникам","/task : задача для определенного сотрудника","/broadcast : рассылка задач по всем сотрудникам"}

def load_shifts() -> dict:
    if os.path.exists(WORK_FILE):
        try:
            with open(WORK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_shifts(shifts_data: dict):
    with open(WORK_FILE, "w", encoding="utf-8") as f:
        json.dump(shifts_data, f, ensure_ascii=False, indent=4)

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_users(users_dict: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_dict, f, ensure_ascii=False, indent=4)

active_users = load_users()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id not in active_users:
        username = f"@{message.from_user.username}" if message.from_user.username else "Без ника"
        active_users[user_id] = {
            "username": username,
            "name": message.from_user.full_name,
            "role": "работник"
        }
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
            replace_existing=True,
        )
        await calback.message.edit_text("Хорошо переспрошу через 30 мин.")
        await calback.message.answer("Напоминание отложенно!")
        return
    elif action == "yes":
        user_id = str(calback.from_user.id)
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        shifts_data = load_shifts()
        if user_id not in shifts_data:
            shifts_data[user_id] = []
        shifts_data[user_id].append(current_time)
        shifts_data[user_id] = shifts_data[user_id][-10:]
        save_shifts(shifts_data)
    username_str = f"@{user.username}" if user.username else f"ID:{user.id}"
    await bot.send_message(
        admin,
        f"Отчет по смене : \n"
        f"От : {user.full_name} ({username_str}) \n"
        f"Ответ <b>{answer_text}</b>",
    )
    await calback.answer("Ответ записан")
    await calback.message.edit_text(f"Твой ответ принят: <b>{answer_text}</b>")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message,state: FSMContext):
    if str(message.from_user.id) != admin:
        await message.answer("Извините. Вы не являетесь админом")
        return
    await state.clear()

    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        text_to_send = args[1]
    else:
        await message.answer("формат: /broadcast [текст] \nНапример: /broadcast в пятницу совещания на улице абобной в 17:00")
        return
    success_count = 0
    for user_id in active_users.keys():
        try:
            await bot.send_message(user_id, f"Задача : {text_to_send}")
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            print(e)
    await message.answer(f"Рассылка завершена. Отправлено {success_count} работникам.")

async def send_shift_request_to_user(user_id: int):
    try:
        await bot.send_message(
            user_id,
            "Напоминание : ты вышел на смену?",
            reply_markup=get_shift_keyboard(),
        )
    except Exception as e:
        print(e)

async def scheduled_shift_broadcast():
    for user_id in active_users.keys():
        await send_shift_request_to_user(user_id)

@dp.message(Command("my_shifts"))
async def cmd_my_shifts(message: Message):
    user_id = str(message.from_user.id)
    shifts_data = load_shifts()
    if user_id not in shifts_data or not shifts_data[user_id]:
        await message.answer("У вас нету записей о сменах")
        return
    user_shifts = shifts_data[user_id][-10:]
    text = "<b>Твои последнии смены:</b>\n \n"
    for shift_time in user_shifts:
        text += f"<b>{shift_time}</b>\n"

    await message.answer(text)

@dp.message(Command("setrole"))
async def cmd_setrole(message: Message):
    if str(message.from_user.id) != admin:
        await message.answer("извините но менять роль может только админ")
        return

    for user_id, user_data in active_users.items():
        await message.answer(f"<b>user_id : {user_id}</b> \n <b>username : {user_data.get('name','без юзернейма')}</b> \n <b>name : {user_data.get("username", "Без ника")}</b> \n <b>role : {user_data.get("role", "работник")}</b>")
        await asyncio.sleep(0.1)

    args = message.text.split(maxsplit=2)
    if len(args) <3:
        await message.answer("Формат: /setrole [ID] [роль]\nНапример: /setrole 12345 3д дизайнер")
        return

    target_id, new_role = args[1], args[2]
    if target_id in active_users:
        active_users[target_id]["role"] = new_role
        save_users(active_users)
        await message.answer(f"✅ Роль '{new_role}' назначена.")
    else:
        await message.answer("Пользователь с таким ID не найден.")

@dp.message(Command("task"))
async def cmd_task(message: Message):
    if str(message.from_user.id) != admin:
        await  message.answer("Извините вы не можете назначать задания")
        return

    for user_id, user_data in active_users.items():
        await message.answer(f"<b>user_id : {user_id}</b> \n <b>username : {user_data.get('name','без юзернейма')}</b> \n <b>name : {user_data.get("username", "Без ника")}</b> \n <b>role : {user_data.get("role", "работник")}</b>")
        await asyncio.sleep(0.1)

    args = message.text.split(maxsplit=2)
    if len(args) <3:
        await message.answer("формат: /task [роль_или_юзернейм] [текст]\nНапример: /task монтажер Сделай нарезку")
        return

    target,text_to_send = args[1].lower(), args[2]
    suces = 0

    for uid,data in active_users.items():
        if target in data.get("role","").lower() or target == data.get("username","").lower():
            try:
                await bot.send_message(uid, f"Персональная задача:\n{text_to_send}")
                suces += 1
            except Exception as e:
                print(e)
    await message.answer(f"отправленно : {suces}. сотрудникам")

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if str(message.from_user.id) != admin:
        await message.answer("извините вы не админ")
        return
    text="Админ комманды: \n \n"
    for aboba in admin_command:
        text+=f"<b>{aboba}</b> \n"

    await message.answer(text)


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