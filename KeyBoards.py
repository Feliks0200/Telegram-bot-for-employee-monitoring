from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


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

def get_task_keyboard(task_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Задача выполнена", callback_data=f"taskdone_{task_id}")]
    ])

def admin_keyboard(user_id : int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Принять", callback_data=f"auth_yes_{user_id}"),
            InlineKeyboardButton(text="Заблокировать", callback_data=f"auth_no_{user_id}")
        ]
    ])