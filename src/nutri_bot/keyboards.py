from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📊 Сегодня"),
            KeyboardButton(text="🗑 Удалить"),
        ],
        [
            KeyboardButton(text="⚙️ Настройки"),
            KeyboardButton(text="❓ Помощь"),
        ],
    ],
    resize_keyboard=True,
)
