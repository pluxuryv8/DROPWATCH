from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from dropwatch.bot.keyboards import (
    confirm_keyboard,
    condition_keyboard,
    delivery_keyboard,
    edit_task_fields_keyboard,
    interval_keyboard,
    main_menu,
    seller_keyboard,
    settings_keyboard,
    skip_cancel_keyboard,
    task_actions_keyboard,
    tasks_keyboard,
    events_keyboard,
)
from dropwatch.bot.states import CreateTask, EditTask, QuickSearch, SettingsState
from dropwatch.bot.texts import (
    CANCEL_TEXT,
    HELP_TEXT,
    MAIN_MENU_TEXT,
    MENU_CREATE_TASK,
    MENU_FAVORITES,
    MENU_HELP,
    MENU_SETTINGS,
    MENU_TASKS,
    SKIP_TEXT,
    START_TEXT,
)
from dropwatch.common.avito_url import extract_task_name, is_avito_url, parse_search_url
from dropwatch.common.config import settings
from dropwatch.common.formatting import format_price
from dropwatch.db import crud
from dropwatch.db.database import get_sessionmaker
from dropwatch.db.models import Condition, Delivery, SellerType, TaskStatus


router = Router()
logger = logging.getLogger("bot")


def _parse_int(text: str) -> int | None:
    value = re.sub(r"[^0-9]", "", text or "")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def _cancel_flow(message: Message, state: FSMContext) -> None:
    logger.info(
        "Cancel flow: user_id=%s chat_id=%s state=%s",
        message.from_user.id,
        message.chat.id,
        await state.get_state(),
    )
    await state.clear()
    await message.answer("Ок, сбросил. Возвращаю на пульт.", reply_markup=main_menu())


async def _get_user_task(session, tg_id: int, task_id: int):
    user = await crud.get_user_by_tg(session, tg_id)
    if not user:
        return None
    return await crud.get_task(session, task_id, user.id)


def _task_summary(data: dict) -> str:
    lines = [
        "Проверь радар:",
        f"Название радара: {data.get('name')}",
        f"Ключевые слова: {data.get('keywords') or '—'}",
        f"Минус-слова: {data.get('minus_keywords') or '—'}",
        f"Город: {data.get('city') or '—'}",
        f"Радиус: {data.get('radius_km') or '—'} км",
        f"Цена от: {data.get('price_min') or '—'}",
        f"Цена до: {data.get('price_max') or '—'}",
        f"Категория: {data.get('category') or '—'}",
        f"Состояние: {data.get('condition')}",
        f"Доставка: {data.get('delivery')}",
        f"Продавец: {data.get('seller_type')}",
        f"Интервал: {data.get('interval_sec')} сек",
    ]
    return "\n".join(lines)


@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    logger.info("Command /start: user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    await state.clear()
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.get_or_create_user(
            session,
            tg_id=message.from_user.id,
            timezone_str=settings.default_timezone,
            default_interval=settings.default_task_interval_sec,
        )
    await state.set_state(QuickSearch.link)
    await message.answer(START_TEXT, reply_markup=skip_cancel_keyboard())
    await message.answer("Скидывай ссылку Avito из браузера.")


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    logger.info("Command /help: user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    await message.answer(HELP_TEXT)


@router.message(F.text == MENU_HELP)
async def help_menu(message: Message) -> None:
    logger.info("Help menu: user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    await message.answer(HELP_TEXT)


@router.message(StateFilter(None), F.text.contains("avito"))
async def quick_link_anywhere(message: Message, state: FSMContext) -> None:
    logger.info(
        "Quick link auto-detect: user_id=%s chat_id=%s text=%s",
        message.from_user.id,
        message.chat.id,
        message.text,
    )
    await state.set_state(QuickSearch.link)
    await quick_search_link(message, state)


@router.message(QuickSearch.link)
async def quick_search_link(message: Message, state: FSMContext) -> None:
    logger.info(
        "Quick link step: user_id=%s chat_id=%s state=%s text=%s",
        message.from_user.id,
        message.chat.id,
        await state.get_state(),
        message.text,
    )
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    url = (message.text or "").strip()
    if not url or message.text == SKIP_TEXT:
        await message.answer("Нужна ссылка Avito. Скопируй её из браузера.")
        return
    if not is_avito_url(url):
        logger.warning("Invalid Avito URL: user_id=%s url=%s", message.from_user.id, url)
        await message.answer("Похоже, это не ссылка Avito. Отправь корректную ссылку.")
        return
    parsed = parse_search_url(url)
    name = extract_task_name(url) or "Радар Avito"
    await state.update_data(
        name=name,
        keywords=parsed.get("keywords"),
        quick_flow=True,
        minus_keywords=None,
        price_min=parsed.get("price_min"),
        price_max=parsed.get("price_max"),
        category=parsed.get("category"),
        city=parsed.get("city"),
        radius_km=parsed.get("radius_km"),
        condition="any",
        delivery="any",
        seller_type="any",
        search_url=url,
    )
    await state.set_state(QuickSearch.max_price)
    await message.answer("Укажи максимальную цену (или Пропустить).", reply_markup=skip_cancel_keyboard())


@router.message(QuickSearch.max_price)
async def quick_search_max_price(message: Message, state: FSMContext) -> None:
    logger.info(
        "Quick max price step: user_id=%s chat_id=%s state=%s text=%s",
        message.from_user.id,
        message.chat.id,
        await state.get_state(),
        message.text,
    )
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    data = await state.get_data()
    price_max = data.get("price_max")
    if message.text != SKIP_TEXT:
        price_max = _parse_int(message.text or "")
        if price_max is None:
            await message.answer("Введи число, например 5000")
            return
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, message.from_user.id)
        if not user:
            logger.warning("Quick max price: user not found user_id=%s", message.from_user.id)
            await message.answer("Сначала нажми /start")
            return
        await state.update_data(interval_sec=30, price_max=price_max)
        data = await state.get_data()
        logger.info(
            "Creating task from quick flow: user_id=%s name=%s price_max=%s",
            message.from_user.id,
            data.get("name"),
            data.get("price_max"),
        )
        await crud.create_task(
            session,
            user_id=user.id,
            name=data.get("name") or "Радар",
            keywords=data.get("keywords"),
            minus_keywords=data.get("minus_keywords"),
            category=data.get("category"),
            city=data.get("city"),
            radius_km=data.get("radius_km"),
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            condition=Condition(data.get("condition", "any")),
            delivery=Delivery(data.get("delivery", "any")),
            seller_type=SellerType(data.get("seller_type", "any")),
            sort_new_first=True,
            interval_sec=int(data.get("interval_sec") or settings.default_task_interval_sec),
            status=TaskStatus.active,
            search_url=data.get("search_url"),
            source=settings.fetcher,
        )
    await state.clear()
    await message.answer("Радар включен. Я на дежурстве.", reply_markup=main_menu())


@router.message(F.text == MENU_CREATE_TASK)
async def create_task_start(message: Message, state: FSMContext) -> None:
    logger.info("Start full create: user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    await state.clear()
    await state.set_state(CreateTask.name)
    await message.answer("Как назовём радар?", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.name)
async def create_task_name(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.name: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым.")
        return
    await state.update_data(name=name)
    await state.set_state(CreateTask.keywords)
    await message.answer("Ключевые слова (пример: Stone Island Supreme худи)", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.keywords)
async def create_task_keywords(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.keywords: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    keywords = message.text if message.text != SKIP_TEXT else None
    await state.update_data(keywords=keywords)
    await state.set_state(CreateTask.search_url)
    await message.answer("Ссылка поиска Avito (обязательно)", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.search_url)
async def create_task_search_url(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.search_url: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    url = (message.text or "").strip()
    if not url or message.text == SKIP_TEXT:
        await message.answer("Нужна ссылка Avito. Скопируй её из браузера.")
        return
    if not is_avito_url(url):
        logger.warning("Invalid Avito URL: user_id=%s url=%s", message.from_user.id, url)
        await message.answer("Похоже, это не ссылка Avito. Отправь корректную ссылку.")
        return
    parsed = parse_search_url(url)
    data = await state.get_data()
    await state.update_data(
        search_url=url,
        keywords=data.get("keywords") or parsed.get("keywords"),
        price_min=data.get("price_min") or parsed.get("price_min"),
        price_max=data.get("price_max") or parsed.get("price_max"),
        category=data.get("category") or parsed.get("category"),
        city=data.get("city") or parsed.get("city"),
        radius_km=data.get("radius_km") or parsed.get("radius_km"),
    )
    await state.set_state(CreateTask.minus_keywords)
    await message.answer("Минус-слова (необязательно)", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.minus_keywords)
async def create_task_minus(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.minus_keywords: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    minus_keywords = message.text if message.text != SKIP_TEXT else None
    await state.update_data(minus_keywords=minus_keywords)
    await state.set_state(CreateTask.city)
    await message.answer("Город / регион", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.city)
async def create_task_city(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.city: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    if message.text == SKIP_TEXT:
        data = await state.get_data()
        city = data.get("city")
    else:
        city = message.text
    await state.update_data(city=city)
    await state.set_state(CreateTask.radius)
    await message.answer("Радиус, км (необязательно)", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.radius)
async def create_task_radius(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.radius: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    data = await state.get_data()
    radius = data.get("radius_km")
    if message.text != SKIP_TEXT:
        radius = _parse_int(message.text)
        if radius is None:
            await message.answer("Введи число, например 10")
            return
    await state.update_data(radius_km=radius)
    await state.set_state(CreateTask.price_min)
    await message.answer("Цена от", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.price_min)
async def create_task_price_min(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.price_min: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    data = await state.get_data()
    price_min = data.get("price_min")
    if message.text != SKIP_TEXT:
        price_min = _parse_int(message.text)
        if price_min is None:
            await message.answer("Введи число, например 5000")
            return
    await state.update_data(price_min=price_min)
    await state.set_state(CreateTask.price_max)
    await message.answer("Цена до", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.price_max)
async def create_task_price_max(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.price_max: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    data = await state.get_data()
    price_max = data.get("price_max")
    if message.text != SKIP_TEXT:
        price_max = _parse_int(message.text)
        if price_max is None:
            await message.answer("Введи число, например 15000")
            return
    await state.update_data(price_max=price_max)
    await state.set_state(CreateTask.category)
    await message.answer("Категория (необязательно)", reply_markup=skip_cancel_keyboard())


@router.message(CreateTask.category)
async def create_task_category(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.category: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    category = message.text if message.text != SKIP_TEXT else None
    await state.update_data(category=category)
    await state.set_state(CreateTask.condition)
    await message.answer("Состояние", reply_markup=condition_keyboard())


@router.callback_query(F.data.startswith("cond:"), CreateTask.condition)
async def create_task_condition(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("CreateTask.condition: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    await state.update_data(condition=value)
    await state.set_state(CreateTask.delivery)
    await callback.message.edit_text("Доставка", reply_markup=delivery_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("del:"), CreateTask.delivery)
async def create_task_delivery(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("CreateTask.delivery: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    await state.update_data(delivery=value)
    await state.set_state(CreateTask.seller)
    await callback.message.edit_text("Продавец", reply_markup=seller_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("seller:"), CreateTask.seller)
async def create_task_seller(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("CreateTask.seller: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    await state.update_data(seller_type=value)
    await state.set_state(CreateTask.interval)
    await callback.message.edit_text("Интервал проверки", reply_markup=interval_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("interval:"), CreateTask.interval)
async def create_task_interval(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("CreateTask.interval: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await state.update_data(interval_custom=True)
        await callback.message.edit_text("Введи интервал в минутах")
        await callback.answer()
        return
    interval_sec = int(value)
    await state.update_data(interval_sec=interval_sec)
    await _show_review(callback.message, state)
    await callback.answer()


@router.message(CreateTask.interval)
async def create_task_interval_custom(message: Message, state: FSMContext) -> None:
    logger.info("CreateTask.interval_custom: user_id=%s text=%s", message.from_user.id, message.text)
    data = await state.get_data()
    if not data.get("interval_custom"):
        return
    value = _parse_int(message.text or "")
    if value is None:
        await message.answer("Введи число минут, например 2")
        return
    await state.update_data(interval_sec=value * 60)
    await _show_review(message, state)


async def _show_review(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    data.setdefault("condition", "any")
    data.setdefault("delivery", "any")
    data.setdefault("seller_type", "any")
    data.setdefault("interval_sec", settings.default_task_interval_sec)
    await state.set_state(CreateTask.review)
    await message.answer(_task_summary(data), reply_markup=confirm_keyboard())


@router.callback_query(F.data == "task_confirm")
async def create_task_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("CreateTask.confirm: user_id=%s", callback.from_user.id)
    data = await state.get_data()
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_or_create_user(
            session,
            tg_id=callback.from_user.id,
            timezone_str=settings.default_timezone,
            default_interval=settings.default_task_interval_sec,
        )
        if data.get("quick_flow"):
            await crud.pause_tasks_for_user(session, user.id)
        await crud.create_task(
            session,
            user_id=user.id,
            name=data.get("name") or data.get("keywords") or "Поиск",
            keywords=data.get("keywords"),
            minus_keywords=data.get("minus_keywords"),
            category=data.get("category"),
            city=data.get("city"),
            radius_km=data.get("radius_km"),
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            condition=Condition(data.get("condition", "any")),
            delivery=Delivery(data.get("delivery", "any")),
            seller_type=SellerType(data.get("seller_type", "any")),
            sort_new_first=True,
            interval_sec=int(data.get("interval_sec") or settings.default_task_interval_sec),
            status=TaskStatus.active,
            search_url=data.get("search_url"),
            source=settings.fetcher,
        )
    await state.clear()
    await callback.message.edit_text("Готово! Радар запущен.")
    await callback.message.answer(MAIN_MENU_TEXT, reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "task_edit")
async def create_task_edit(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("CreateTask.edit: user_id=%s", callback.from_user.id)
    await state.clear()
    await state.set_state(CreateTask.name)
    await callback.message.edit_text("Начнём заново. Как назовём радар?")
    await callback.message.answer("Как назовём радар?", reply_markup=skip_cancel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "task_cancel")
async def create_task_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("CreateTask.cancel: user_id=%s", callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("Отменено.")
    await callback.message.answer(MAIN_MENU_TEXT, reply_markup=main_menu())
    await callback.answer()


@router.message(F.text == MENU_TASKS)
async def list_tasks(message: Message) -> None:
    logger.info("List tasks: user_id=%s chat_id=%s", message.from_user.id, message.chat.id)
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_or_create_user(
            session,
            tg_id=message.from_user.id,
            timezone_str=settings.default_timezone,
            default_interval=settings.default_task_interval_sec,
        )
        tasks = await crud.list_tasks(session, user.id)
    await message.answer("Твои радары:", reply_markup=tasks_keyboard(tasks))


@router.callback_query(F.data.startswith("task:"))
async def task_details(callback: CallbackQuery) -> None:
    logger.info("Task details: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден")
            return
        task = await crud.get_task(session, task_id, user.id)
        if not task:
            await callback.answer("Радар не найден")
            return
    status_label = "работает" if task.status == TaskStatus.active else "пауза" if task.status == TaskStatus.paused else "стоп"
    details = (
        f"📡 {task.name}\n"
        f"Статус: {status_label}\n"
        f"Интервал: {task.interval_sec} сек\n"
        f"Ключевые: {task.keywords or '—'}\n"
        f"Минус: {task.minus_keywords or '—'}\n"
        f"Город: {task.city or '—'}\n"
        f"Цена: {format_price(task.price_min)} - {format_price(task.price_max)}"
    )
    await callback.message.edit_text(details, reply_markup=task_actions_keyboard(task))
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("task_pause:"))
async def task_pause(callback: CallbackQuery) -> None:
    logger.info("Task pause: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        task = await _get_user_task(session, callback.from_user.id, task_id)
        if not task:
            await callback.answer("Радар не найден")
            return
        await crud.set_task_status(session, task.id, TaskStatus.paused)
    await callback.answer("Пауза")


@router.callback_query(F.data.startswith("task_resume:"))
async def task_resume(callback: CallbackQuery) -> None:
    logger.info("Task resume: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        task = await _get_user_task(session, callback.from_user.id, task_id)
        if not task:
            await callback.answer("Радар не найден")
            return
        await crud.set_task_status(session, task.id, TaskStatus.active)
    await callback.answer("Запущено")


@router.callback_query(F.data.startswith("task_stop:"))
async def task_stop(callback: CallbackQuery) -> None:
    logger.info("Task stop: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        task = await _get_user_task(session, callback.from_user.id, task_id)
        if not task:
            await callback.answer("Радар не найден")
            return
        await crud.set_task_status(session, task.id, TaskStatus.stopped)
    await callback.answer("Остановлено")


@router.callback_query(F.data.startswith("task_clear:"))
async def task_clear(callback: CallbackQuery) -> None:
    logger.info("Task clear: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        task = await _get_user_task(session, callback.from_user.id, task_id)
        if not task:
            await callback.answer("Радар не найден")
            return
        await crud.clear_seen_for_task(session, task.id)
    await callback.answer("История очищена")


@router.callback_query(F.data.startswith("task_delete:"))
async def task_delete(callback: CallbackQuery) -> None:
    logger.info("Task delete: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        task = await _get_user_task(session, callback.from_user.id, task_id)
        if not task:
            await callback.answer("Радар не найден")
            return
        await crud.delete_task(session, task.id)
    await callback.message.edit_text("Радар удален")
    await callback.answer()


@router.callback_query(F.data.startswith("task_interval:"))
async def task_interval(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("Task interval change: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        task = await _get_user_task(session, callback.from_user.id, task_id)
        if not task:
            await callback.answer("Радар не найден")
            return
    await state.set_state(EditTask.interval)
    await state.update_data(task_id=task_id)
    await callback.message.edit_text("Интервал проверки", reply_markup=interval_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("task_edit_menu:"))
async def task_edit_menu(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("Task edit menu: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        task = await _get_user_task(session, callback.from_user.id, task_id)
        if not task:
            await callback.answer("Радар не найден")
            return
    await state.set_state(EditTask.choose_field)
    await state.update_data(task_id=task_id)
    await callback.message.edit_text("Что изменить?", reply_markup=edit_task_fields_keyboard(task_id))
    await callback.answer()


@router.callback_query(F.data.startswith("task_price:"))
async def task_edit_price(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("Task edit price: user_id=%s data=%s", callback.from_user.id, callback.data)
    task_id = int(callback.data.split(":", 1)[1])
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        task = await _get_user_task(session, callback.from_user.id, task_id)
        if not task:
            await callback.answer("Радар не найден")
            return
    await state.set_state(EditTask.price_max)
    await state.update_data(task_id=task_id)
    await callback.message.edit_text("Введи максимальную цену (или Пропустить, чтобы убрать лимит).")
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field:"))
async def edit_task_field(callback: CallbackQuery, state: FSMContext) -> None:
    _, field, task_id = callback.data.split(":", 2)
    await state.update_data(task_id=int(task_id), field=field)

    if field == "condition":
        await callback.message.edit_text("Состояние", reply_markup=condition_keyboard())
        await callback.answer()
        return
    if field == "delivery":
        await callback.message.edit_text("Доставка", reply_markup=delivery_keyboard())
        await callback.answer()
        return
    if field == "seller":
        await callback.message.edit_text("Продавец", reply_markup=seller_keyboard())
        await callback.answer()
        return
    if field == "sort":
        session_maker = get_sessionmaker()
        async with session_maker() as session:
            task = await crud.get_task(session, int(task_id))
            if task:
                await crud.update_task(session, task.id, sort_new_first=not task.sort_new_first)
        await callback.answer("Сортировка обновлена")
        return

    await state.set_state(EditTask.text_value)
    await callback.message.edit_text("Введи новое значение (или 'Пропустить' чтобы очистить)")
    await callback.message.answer("Введи новое значение", reply_markup=skip_cancel_keyboard())
    await callback.answer()


@router.message(EditTask.text_value)
async def edit_task_text_value(message: Message, state: FSMContext) -> None:
    logger.info("EditTask.text_value: user_id=%s text=%s", message.from_user.id, message.text)
    data = await state.get_data()
    field = data.get("field")
    task_id = data.get("task_id")
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return

    value = message.text
    if message.text == SKIP_TEXT:
        value = None

    update_kwargs = {}
    if field in {"radius", "price_min", "price_max"}:
        parsed = _parse_int(value or "") if value else None
        update_kwargs = {field if field != "radius" else "radius_km": parsed}
    else:
        mapping = {
            "name": "name",
            "keywords": "keywords",
            "minus": "minus_keywords",
            "city": "city",
            "category": "category",
        }
        update_kwargs = {mapping.get(field, field): value}

    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.update_task(session, int(task_id), **update_kwargs)
    await message.answer("Обновлено", reply_markup=main_menu())
    await state.clear()


@router.callback_query(F.data.startswith("interval:"), EditTask.interval)
async def edit_interval_choice(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("EditTask.interval_choice: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    task_id = data.get("task_id")
    if value == "custom":
        await callback.message.edit_text("Введи интервал в минутах")
        await callback.answer()
        return
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.update_task(session, int(task_id), interval_sec=int(value))
    await state.clear()
    await callback.answer("Интервал обновлен")


@router.message(EditTask.interval)
async def edit_interval_custom(message: Message, state: FSMContext) -> None:
    logger.info("EditTask.interval_custom: user_id=%s text=%s", message.from_user.id, message.text)
    data = await state.get_data()
    task_id = data.get("task_id")
    value = _parse_int(message.text or "")
    if value is None:
        await message.answer("Введи число минут, например 2")
        return
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.update_task(session, int(task_id), interval_sec=value * 60)
    await state.clear()
    await message.answer("Интервал обновлен", reply_markup=main_menu())


@router.message(EditTask.price_max)
async def edit_price_max(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    task_id = data.get("task_id")
    if message.text == CANCEL_TEXT:
        await _cancel_flow(message, state)
        return
    if message.text == SKIP_TEXT:
        price_max = None
    else:
        price_max = _parse_int(message.text or "")
        if price_max is None:
            await message.answer("Введи число, например 5000")
            return
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.update_task(session, int(task_id), price_max=price_max)
    await state.clear()
    await message.answer("Максимальная цена обновлена", reply_markup=main_menu())


@router.callback_query(F.data.startswith("cond:"), EditTask.choose_field)
async def edit_condition(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("EditTask.condition: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    task_id = data.get("task_id")
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.update_task(session, int(task_id), condition=Condition(value))
    await state.clear()
    await callback.answer("Состояние обновлено")


@router.callback_query(F.data.startswith("del:"), EditTask.choose_field)
async def edit_delivery(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("EditTask.delivery: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    task_id = data.get("task_id")
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.update_task(session, int(task_id), delivery=Delivery(value))
    await state.clear()
    await callback.answer("Доставка обновлена")


@router.callback_query(F.data.startswith("seller:"), EditTask.choose_field)
async def edit_seller(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("EditTask.seller: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    task_id = data.get("task_id")
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.update_task(session, int(task_id), seller_type=SellerType(value))
    await state.clear()
    await callback.answer("Продавец обновлен")


@router.message(F.text == MENU_SETTINGS)
async def settings_menu(message: Message, state: FSMContext) -> None:
    logger.info("Settings menu: user_id=%s", message.from_user.id)
    await state.set_state(SettingsState.choose)
    await message.answer("Настройки", reply_markup=settings_keyboard())


@router.callback_query(F.data.startswith("settings:"))
async def settings_choice(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("Settings choice: user_id=%s data=%s", callback.from_user.id, callback.data)
    choice = callback.data.split(":", 1)[1]
    await state.update_data(settings_choice=choice)
    if choice == "interval":
        await callback.message.edit_text("Интервал по умолчанию", reply_markup=interval_keyboard())
    elif choice == "quiet":
        await state.set_state(SettingsState.quiet_start)
        await callback.message.edit_text("Тихие часы: начало (HH:MM) или Пропустить")
    elif choice == "limit":
        await state.set_state(SettingsState.notify_limit)
        await callback.message.edit_text("Лимит уведомлений в час (число или Пропустить)")
    elif choice == "events":
        session_maker = get_sessionmaker()
        async with session_maker() as session:
            user = await crud.get_user_by_tg(session, callback.from_user.id)
        await callback.message.edit_text(
            "События:",
            reply_markup=events_keyboard(user.event_new, user.event_price_drop, user.event_update),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("events:"))
async def settings_events_toggle(callback: CallbackQuery) -> None:
    logger.info("Settings events toggle: user_id=%s data=%s", callback.from_user.id, callback.data)
    choice = callback.data.split(":", 1)[1]
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден")
            return
        updates = {}
        if choice == "new":
            updates["event_new"] = not user.event_new
        elif choice == "price":
            updates["event_price_drop"] = not user.event_price_drop
        elif choice == "update":
            updates["event_update"] = not user.event_update
        await crud.update_user_settings(session, user.id, **updates)
        user = await crud.get_user_by_tg(session, callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=events_keyboard(user.event_new, user.event_price_drop, user.event_update)
    )
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith("interval:"), SettingsState.choose)
async def settings_interval(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("Settings interval: user_id=%s data=%s", callback.from_user.id, callback.data)
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await state.set_state(SettingsState.default_interval)
        await callback.message.edit_text("Введи интервал в минутах")
        await callback.answer()
        return
    interval_sec = int(value)
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if user:
            await crud.update_user_settings(session, user.id, default_interval_sec=interval_sec)
    await state.clear()
    await callback.answer("Интервал обновлен")


@router.message(SettingsState.default_interval)
async def settings_interval_custom(message: Message, state: FSMContext) -> None:
    logger.info("Settings interval custom: user_id=%s text=%s", message.from_user.id, message.text)
    value = _parse_int(message.text or "")
    if value is None:
        await message.answer("Введи число минут, например 2")
        return
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, message.from_user.id)
        if user:
            await crud.update_user_settings(session, user.id, default_interval_sec=value * 60)
    await state.clear()
    await message.answer("Интервал обновлен", reply_markup=main_menu())


@router.message(SettingsState.quiet_start)
async def settings_quiet_start(message: Message, state: FSMContext) -> None:
    logger.info("Settings quiet start: user_id=%s text=%s", message.from_user.id, message.text)
    text = message.text
    if text == SKIP_TEXT:
        await _save_quiet_hours(message, None, None)
        await state.clear()
        return
    await state.update_data(quiet_start=text)
    await state.set_state(SettingsState.quiet_end)
    await message.answer("Тихие часы: конец (HH:MM)")


@router.message(SettingsState.quiet_end)
async def settings_quiet_end(message: Message, state: FSMContext) -> None:
    logger.info("Settings quiet end: user_id=%s text=%s", message.from_user.id, message.text)
    data = await state.get_data()
    start = data.get("quiet_start")
    end = message.text
    await _save_quiet_hours(message, start, end)
    await state.clear()


async def _save_quiet_hours(message: Message, start: str | None, end: str | None) -> None:
    logger.info(
        "Save quiet hours: user_id=%s start=%s end=%s", message.from_user.id, start, end
    )
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, message.from_user.id)
        if user:
            await crud.update_user_settings(session, user.id, quiet_hours_start=start, quiet_hours_end=end)
    await message.answer("Тихие часы обновлены", reply_markup=main_menu())


@router.message(SettingsState.notify_limit)
async def settings_limit(message: Message, state: FSMContext) -> None:
    logger.info("Settings limit: user_id=%s text=%s", message.from_user.id, message.text)
    if message.text == SKIP_TEXT:
        limit = None
    else:
        limit = _parse_int(message.text or "")
        if limit is None:
            await message.answer("Введи число, например 20")
            return
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, message.from_user.id)
        if user:
            await crud.update_user_settings(session, user.id, notify_limit_per_hour=limit)
    await state.clear()
    await message.answer("Лимит обновлен", reply_markup=main_menu())


@router.message(F.text == MENU_FAVORITES)
async def favorites_list(message: Message) -> None:
    logger.info("Favorites list: user_id=%s", message.from_user.id)
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, message.from_user.id)
        if not user:
            await message.answer("Сначала нажми /start")
            return
        favorites = await crud.list_favorites(session, user.id)
    if not favorites:
        await message.answer("Избранное пусто")
        return
    lines = ["⭐ Избранное:"]
    for fav in favorites[:20]:
        lines.append(f"• {fav.title or 'Объявление'} — {format_price(fav.price)} ₽")
        if fav.url:
            lines.append(fav.url)
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("seen:"))
async def mark_seen(callback: CallbackQuery) -> None:
    logger.info("Mark seen: user_id=%s data=%s", callback.from_user.id, callback.data)
    _, task_id, listing_id = callback.data.split(":", 2)
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        await crud.mute_seen_listing(session, int(task_id), listing_id)
    await callback.answer("Отмечено")


@router.callback_query(F.data.startswith("fav:"))
async def add_favorite(callback: CallbackQuery) -> None:
    logger.info("Add favorite: user_id=%s data=%s", callback.from_user.id, callback.data)
    _, task_id, listing_id = callback.data.split(":", 2)
    session_maker = get_sessionmaker()
    async with session_maker() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if not user:
            await callback.answer("Сначала нажми /start")
            return
        seen = await crud.get_seen_listing(session, int(task_id), listing_id)
        if seen:
            await crud.add_favorite(
                session,
                user_id=user.id,
                listing_id=listing_id,
                title=seen.last_title,
                price=seen.last_price,
                url=seen.last_url,
                location=seen.last_location,
            )
            await callback.answer("Добавил в избранное")
            return
    await callback.answer("Не нашёл объявление")


@router.message()
async def log_any_message(message: Message, state: FSMContext) -> None:
    logger.info(
        "Raw message: user_id=%s chat_id=%s type=%s state=%s text=%s",
        message.from_user.id if message.from_user else None,
        message.chat.id if message.chat else None,
        message.content_type,
        await state.get_state(),
        message.text,
    )


@router.callback_query()
async def log_any_callback(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info(
        "Raw callback: user_id=%s data=%s state=%s message_id=%s",
        callback.from_user.id if callback.from_user else None,
        callback.data,
        await state.get_state(),
        callback.message.message_id if callback.message else None,
    )
