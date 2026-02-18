from aiogram.fsm.state import State, StatesGroup


class CreateTask(StatesGroup):
    name = State()
    keywords = State()
    search_url = State()
    minus_keywords = State()
    city = State()
    radius = State()
    price_min = State()
    price_max = State()
    category = State()
    condition = State()
    delivery = State()
    seller = State()
    interval = State()
    review = State()


class QuickSearch(StatesGroup):
    link = State()
    max_price = State()


class EditTask(StatesGroup):
    choose_field = State()
    text_value = State()
    city = State()
    radius = State()
    price_min = State()
    price_max = State()
    interval = State()


class SettingsState(StatesGroup):
    choose = State()
    quiet_start = State()
    quiet_end = State()
    notify_limit = State()
    default_interval = State()
