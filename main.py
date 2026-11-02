import asyncio
import json
import logging
import os
import random
import sys

import datetime
import time

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from KeyBoards import get_shift_keyboard, get_task_keyboard, admin_keyboard

admin = ["админ айди через запятую"]
USERS_FILE = "Users.json"
WORK_FILE = "Work.json"
TASKS_FILE = "Task.json"
BLOCK_FILE = "Blocked.json"
TOKEN = "токен бота"

dp = Dispatcher()
bot = Bot(token=TOKEN)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

admin_command = {"/setrole : меняет роли работникам","/task : задача для определенного сотрудника","/broadcast : рассылка задач по всем сотрудникам","not_task_broadcast : Рассылка пользователям обьявления без задачи"}


def load_block() -> set:
    if os.path.exists(BLOCK_FILE):
        try:
            with open(BLOCK_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_block(block_set: set):
    with open(BLOCK_FILE, "w", encoding="utf-8") as f:
        json.dump(list(block_set), f, ensure_ascii=False, indent=4)

def load_tasks() -> dict:
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_tasks(tasks_dict: dict):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks_dict, f, ensure_ascii=False, indent=4)

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

pending_users = {}
blocked_users = load_block()


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message):
            return await handler(event, data)
        user_id = str(event.from_user.id)
        if user_id in admin or user_id in active_users:
            return await handler(event, data)
        if event.text and event.text.startswith('/start') and user_id not in blocked_users:
            return await handler(event, data)
        return

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id

    if user_id in active_users or user_id in admin:
        await message.answer("С возвращением! Я бот для учета смен и задач.")
        return

    if user_id in pending_users:
        await message.answer("Твоя заявка уже отправлена администраторам. Пожалуйста, не спамь и дождись решения.")
        return

    if user_id in blocked_users:
        await message.answer("Вы заблокированны")
        return

    username = f"@{message.from_user.username}" if message.from_user.username else "Без ника"
    name = message.from_user.full_name
    pending_users[user_id] = {"name": name, "username": username}



    await message.answer("Твоя заявка отправлена администраторам! Ожидай подтверждения.")
    await asyncio.sleep(1)
    await message.answer(
        "Привет! Я бот для учета смен.\n"
        "Я буду присылать тебе опросники по графику. (если тебя примет администрация)"
    )

    for amd in admin:
        try:
            await bot.send_message(amd,f"Новая заявка на добавление!\n\nИмя: {name}\nЮзернейм: {username}\nID: {user_id}",reply_markup=admin_keyboard(user_id))
        except Exception as e:
            print(e)

@dp.callback_query(F.data.startswith("auth_"))
async def auth_callback(callback: CallbackQuery):
    if str(callback.from_user.id) not in admin:
        await callback.answer("У вас нет прав!", show_alert=True)
        return
    parts = callback.data.split("_")
    action = parts[1]
    target_id = parts[2]

    user_info = pending_users.get(target_id, {"name": "Неизвестно", "username": "Без ника"})
    if action =="yes":
        if target_id in active_users:
            await callback.answer("Пользователь уже был добавлен",show_alert=True)
            return

        active_users[target_id] = {
            "username": user_info["username"],
            "name": user_info["name"],
            "role":"работник"
        }
        save_users(active_users)
        await callback.message.edit_text(f"Пользователь {user_info['name']} ({user_info['username']}) принят и добавлен в базу!")
        try:
            await bot.send_message(target_id, "🎉Ваша заявка одобрена! Теперь вам доступен функционал бота.")
        except Exception:
            pass
    if action == "no":
        blocked_users.add(target_id)
        save_block(blocked_users)
        try:
            await bot.send_message(target_id, "Вы заблокированы!")
        except Exception as e:
            print(e)
        await callback.message.edit_text(f"Заявка от {user_info['name']} отклонена. Пользователь заблокирован.")

    if target_id in pending_users:
        del pending_users[target_id]

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
        # shifts_data[user_id] = shifts_data[user_id][-10:] ограничить до 10 строк
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
    if str(message.from_user.id) not in admin:
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

@dp.message(Command("not_task_broadcast"))
async def cmd_broadcast(message: Message,state: FSMContext):
    if str(message.from_user.id) not in admin:
        await message.answer("Извините. Вы не являетесь админом")
        return
    await state.clear()

    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        text_to_send = args[1]
    else:
        await message.answer("формат: /not_task_broadcast [текст] \nНапример: /not_task_broadcast в пятницу совещания на улице абобной в 17:00")
        return
    success_count = 0
    for user_id in active_users.keys():
        try:
            await bot.send_message(user_id, f"Обьявление : {text_to_send}")
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            print(e)
    await message.answer(f"Рассылка завершена. Отправлено {success_count} работникам.")

async def scheduled_shift_broadcast():
    for user_id in active_users.keys():
        await send_shift_request_to_user(user_id)

@dp.message(Command("my_last_shifts"))
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

@dp.message(Command("my_all_shifts"))
async def cmd_my_all_shifts(message: Message):
    user_id = str(message.from_user.id)
    shifts_data = load_shifts()
    if user_id not in shifts_data or not shifts_data[user_id]:
        await message.answer("У вас нету записей о сменах")
        return
    user_shifts = shifts_data[user_id]
    text = "<b>Твои последнии смены:</b>\n \n"
    for shift_time in user_shifts:
        text += f"<b>{shift_time}</b>\n"

    if len(text) > 4000:
        text = text[:4000] + "\n... (показана только часть записей)"

    await message.answer(text)

@dp.message(Command("setrole"))
async def cmd_setrole(message: Message):
    if str(message.from_user.id) not in admin:
        await message.answer("извините но менять роль может только админ")
        return

    for user_id, user_data in active_users.items():
        await message.answer(f"<b>user_id : {user_id}</b> \n <b>name : {user_data.get('name','без имени')}</b> \n <b>username : {user_data.get("username", "Без username")}</b> \n <b>role : {user_data.get("role", "работник")}</b>")
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
    if str(message.from_user.id) not in admin:
        await  message.answer("Извините вы не можете назначать задания")
        return

    for user_id, user_data in active_users.items():
        await message.answer(f"user_id : {user_id} \n name : {user_data.get('name','без имени')} \n username : {user_data.get("username", "без юзернейма")} \n role : {user_data.get("role", "работник")}")
        await asyncio.sleep(0.1)

    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer(
            "Формат: /task [роль или юзернейм] [ДД.ММ.ГГГГ] [текст]\nНапример: /task монтажер 15.11.2026 Сделай нарезку"
        )
        return

    target, deadline_str, text_to_send = args[1].lower(), args[2], args[3]
    tasks_data = load_tasks()
    suces = 0

    for uid,data in active_users.items():
        if target in data.get("role","").lower() or target == data.get("username","").lower():
            task_id = str(int(time.time() * 1000)) + str(uid)[-3:] + str(random.randint(1,1000000))
            tasks_data[task_id] = {
                "user_id": uid,
                "text": text_to_send,
                "deadline": deadline_str,
                "status": "pending"
            }
            save_tasks(tasks_data)
            try:
                await bot.send_message(uid,f"Новая задача!\n\nЗадание: {text_to_send}\nДедлайн: {deadline_str}\n\nпосле выполнение нажмите кнопку ниже.",reply_markup=get_task_keyboard(task_id))
                suces += 1
            except Exception as e:
                print(e)
    if suces == 0:
        await message.answer("не найдены сотрудники с такой ролью либо юзернейму")
        return
    await message.answer(f"отправленно : {suces}. сотрудникам")



@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if str(message.from_user.id) not in admin:
        await message.answer("извините вы не админ")
        return
    text="Админ комманды: \n \n"
    for aboba in admin_command:
        text+=f"<b>{aboba}</b> \n"

    await message.answer(text)

@dp.callback_query(F.data.startswith("taskdone_"))
async def task_done_callback(callback: CallbackQuery):
    task_id = callback.data.split("_")[1]
    tasks_data = load_tasks()


    if task_id not in tasks_data:
        await callback.answer("Эта задача уже недействительна или удалена.", show_alert=True)
        return
    task_info = tasks_data[task_id]
    if task_info["status"] == "completed":
        await callback.answer("Задача уже отмечена как выполненная!", show_alert=True)
        return

    task_info["status"] = "completed"
    save_tasks(tasks_data)

    user_id = str(callback.from_user.id)
    user_data = active_users.get(user_id,{})
    name = user_data.get("name",callback.from_user.full_name)

    await callback.message.edit_text(f"Задача выполнена \n{task_info['text']}\nдедлайн был до {task_info['deadline']}")
    await callback.answer("Отличная работа админы уведомленны")

    for adm in admin:
        try:
            await bot.send_message(adm,f"Задача выполнена сотрудником ( {name} ) \nзадача : ( {task_info['text']} ) \n\nдедлайн был до ( {task_info['deadline']} )")
        except Exception as e:
            print(e)

async def check_deadlines():
    tasks_data = load_tasks()
    today = datetime.datetime.now().date()
    changed = False

    for task_id,task_info in list(tasks_data.items()):
        if task_info['status'] == "completed":
            continue

        deadline_date = datetime.datetime.strptime(task_info['deadline'],"%Y-%m-%d").date()
        days_left = (deadline_date - today).days
        user_id = task_info["user_id"]

        try:
            if days_left > 0:
                await bot.send_message(user_id,f"<b>Напоминание о задаче!</b>\nДо дедлайна осталось <b>{days_left} дней</b>.\n\nЗадание: {task_info['text']}\nНе забудь нажать кнопку 'Выполнено' в оригинальном сообщении, когда закончишь!")
            elif days_left == 0:
                await bot.send_message(user_id,f"<b>ДЕДЛАЙН СЕГОДНЯ!</b>\n\nЗадание: {task_info['text']}\nПосле завершения задачи не забудь отчитаться о готовности")
            else:
                await bot.send_message(user_id,f"<b>ДЕЛАЙН ПРОСРОЧЕН на {abs(days_left)} дней!</b>\n\nЗадание: {task_info['text']}")
        except Exception as e:
            print(e)




async def main() -> None:
    scheduler.add_job(scheduled_shift_broadcast, 'cron', hour=9, minute=0)
    scheduler.add_job(scheduled_shift_broadcast, 'cron', hour=20, minute=0)

    scheduler.add_job(check_deadlines, 'cron', hour=10, minute=0)

    dp.message.middleware(AuthMiddleware())

    scheduler.start()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass