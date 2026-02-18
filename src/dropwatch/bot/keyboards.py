from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from dropwatch.bot.texts import (
    BACK_TEXT,
    CANCEL_TEXT,
    MENU_CREATE_TASK,
    MENU_FAVORITES,
    MENU_HELP,
    MENU_SETTINGS,
    MENU_TASKS,
    SKIP_TEXT,
)
from dropwatch.db.models import Task, TaskStatus


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_CREATE_TASK), KeyboardButton(text=MENU_TASKS)],
            [KeyboardButton(text=MENU_SETTINGS), KeyboardButton(text=MENU_FAVORITES)],
            [KeyboardButton(text=MENU_HELP)],
        ],
        resize_keyboard=True,
    )


def quick_setup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌐 Прокси", callback_data="quickcfg:proxy"),
                InlineKeyboardButton(text="🔄 Смена IP", callback_data="quickcfg:ip"),
            ],
            [
                InlineKeyboardButton(text="🍪 Cookies API", callback_data="quickcfg:cookies"),
                InlineKeyboardButton(text="🔗 Добавить ссылку", callback_data="quickcfg:link"),
            ],
            [
                InlineKeyboardButton(text="🧰 Фильтры", callback_data="quickcfg:filters"),
            ],
            [
                InlineKeyboardButton(text="▶️ Старт мониторинга", callback_data="quickcfg:start"),
                InlineKeyboardButton(text="⏹ Стоп мониторинга", callback_data="quickcfg:stop"),
            ],
        ]
    )


def skip_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=SKIP_TEXT), KeyboardButton(text=CANCEL_TEXT)]],
        resize_keyboard=True,
    )


def back_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BACK_TEXT), KeyboardButton(text=CANCEL_TEXT)]],
        resize_keyboard=True,
    )


def quick_location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геопозицию", request_location=True)],
            [KeyboardButton(text=SKIP_TEXT), KeyboardButton(text=CANCEL_TEXT)],
        ],
        resize_keyboard=True,
    )


def radius_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 км", callback_data="radius:1"),
                InlineKeyboardButton(text="3 км", callback_data="radius:3"),
                InlineKeyboardButton(text="5 км", callback_data="radius:5"),
            ],
            [
                InlineKeyboardButton(text="10 км", callback_data="radius:10"),
                InlineKeyboardButton(text="20 км", callback_data="radius:20"),
                InlineKeyboardButton(text="50 км", callback_data="radius:50"),
            ],
            [InlineKeyboardButton(text="Без ограничения", callback_data="radius:none")],
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Запустить радар", callback_data="task_confirm")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="task_edit")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="task_cancel")],
        ]
    )


def condition_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Любое", callback_data="cond:any"),
                InlineKeyboardButton(text="Новое", callback_data="cond:new"),
                InlineKeyboardButton(text="Б/у", callback_data="cond:used"),
            ]
        ]
    )


def delivery_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Любая", callback_data="del:any"),
                InlineKeyboardButton(text="Да", callback_data="del:yes"),
                InlineKeyboardButton(text="Нет", callback_data="del:no"),
            ]
        ]
    )


def seller_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Любой", callback_data="seller:any"),
                InlineKeyboardButton(text="Частник", callback_data="seller:private"),
                InlineKeyboardButton(text="Магазин", callback_data="seller:shop"),
            ]
        ]
    )


def interval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="30 сек", callback_data="interval:30"),
                InlineKeyboardButton(text="1 мин", callback_data="interval:60"),
                InlineKeyboardButton(text="2 мин", callback_data="interval:120"),
            ],
            [
                InlineKeyboardButton(text="5 мин", callback_data="interval:300"),
                InlineKeyboardButton(text="10 мин", callback_data="interval:600"),
                InlineKeyboardButton(text="Кастом", callback_data="interval:custom"),
            ],
        ]
    )


def tasks_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    rows = []
    for task in tasks:
        status_icon = "✅" if task.status == TaskStatus.active else "⏸" if task.status == TaskStatus.paused else "🛑"
        rows.append([InlineKeyboardButton(text=f"{status_icon} {task.name}", callback_data=f"task:{task.id}")])
        if task.status == TaskStatus.active:
            status_button = InlineKeyboardButton(text="⏸️", callback_data=f"task_pause:{task.id}")
        else:
            status_button = InlineKeyboardButton(text="▶️", callback_data=f"task_resume:{task.id}")
        rows.append(
            [
                status_button,
                InlineKeyboardButton(text="✏️", callback_data=f"task_price:{task.id}"),
                InlineKeyboardButton(text="🗑️", callback_data=f"task_delete:{task.id}"),
            ]
        )
    if not rows:
        rows = [[InlineKeyboardButton(text="Нет радаров", callback_data="noop")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task_actions_keyboard(task: Task) -> InlineKeyboardMarkup:
    status_button = (
        InlineKeyboardButton(text="⏸ Пауза", callback_data=f"task_pause:{task.id}")
        if task.status == TaskStatus.active
        else InlineKeyboardButton(text="▶️ Запуск", callback_data=f"task_resume:{task.id}")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [status_button],
            [InlineKeyboardButton(text="✏️ Изменить цену", callback_data=f"task_price:{task.id}")],
            [InlineKeyboardButton(text="⚙️ Изменить фильтры", callback_data=f"task_edit_menu:{task.id}")],
            [InlineKeyboardButton(text="🔁 Изменить интервал", callback_data=f"task_interval:{task.id}")],
            [InlineKeyboardButton(text="🧹 Очистить историю", callback_data=f"task_clear:{task.id}")],
            [InlineKeyboardButton(text="🗑 Удалить радар", callback_data=f"task_delete:{task.id}")],
        ]
    )


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Интервал по умолчанию", callback_data="settings:interval")],
            [InlineKeyboardButton(text="Тихие часы", callback_data="settings:quiet")],
            [InlineKeyboardButton(text="Лимит уведомлений", callback_data="settings:limit")],
            [InlineKeyboardButton(text="События", callback_data="settings:events")],
        ]
    )


def events_keyboard(event_new: bool, event_price: bool, event_update: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_flag("Новые", event_new), callback_data="events:new")],
            [InlineKeyboardButton(text=_flag("Снижение цены", event_price), callback_data="events:price")],
            [InlineKeyboardButton(text=_flag("Изменение", event_update), callback_data="events:update")],
        ]
    )


def listing_actions_keyboard(task_id: int, listing_id: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Открыть на Авито", url=url)],
            [InlineKeyboardButton(text="✅ Отметить как просмотрено", callback_data=f"seen:{task_id}:{listing_id}")],
            [InlineKeyboardButton(text="⏸ Пауза радара", callback_data=f"task_pause:{task_id}")],
            [InlineKeyboardButton(text="🛑 Стоп радар", callback_data=f"task_stop:{task_id}")],
            [InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav:{task_id}:{listing_id}")],
        ]
    )


def _flag(label: str, enabled: bool) -> str:
    return f"{label}: {'✅' if enabled else '❌'}"


def edit_task_fields_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Название", callback_data=f"edit_field:name:{task_id}")],
            [InlineKeyboardButton(text="Ключевые слова", callback_data=f"edit_field:keywords:{task_id}")],
            [InlineKeyboardButton(text="Минус-слова", callback_data=f"edit_field:minus:{task_id}")],
            [InlineKeyboardButton(text="Город", callback_data=f"edit_field:city:{task_id}")],
            [InlineKeyboardButton(text="Радиус", callback_data=f"edit_field:radius:{task_id}")],
            [InlineKeyboardButton(text="Цена от", callback_data=f"edit_field:price_min:{task_id}")],
            [InlineKeyboardButton(text="Цена до", callback_data=f"edit_field:price_max:{task_id}")],
            [InlineKeyboardButton(text="Категория", callback_data=f"edit_field:category:{task_id}")],
            [InlineKeyboardButton(text="Состояние", callback_data=f"edit_field:condition:{task_id}")],
            [InlineKeyboardButton(text="Доставка", callback_data=f"edit_field:delivery:{task_id}")],
            [InlineKeyboardButton(text="Продавец", callback_data=f"edit_field:seller:{task_id}")],
            [InlineKeyboardButton(text="Сортировка (новые)", callback_data=f"edit_field:sort:{task_id}")],
        ]
    )
