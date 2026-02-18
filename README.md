# DROPWATCH — монитор Avito в Telegram

DROPWATCH — бот, который по ссылке Avito ищет новые объявления каждые N секунд и шлёт их в Telegram с кнопкой «Открыть».
Внутри уже встроена защита от банов: cookies через Playwright, прокси, повторные попытки, дедупликация.

## Что умеет
- Мониторит новые объявления по ссылке сохранённого поиска Avito.
- Уведомляет в Telegram с кнопками действий и краткой сводкой.
- Дедупликация: одно и то же объявление не повторяется.
- Фильтры: ключевые/минус‑слова, цена, город/радиус, категория.
- Глобальные фильтры: чёрные/белые слова, продавцы, резерв, промо, возраст.
- (Опционально) LLM‑оценка и сводка.

## Как это работает
1) Ты отправляешь ссылку Avito в бота.  
2) Бот сохраняет задачу.  
3) Монитор ходит по ссылке, вытаскивает JSON из `script[type="mime/invalid"]`.  
4) Новые объявления отправляются в Telegram.

## Быстрый старт
1) Создай `.env` по образцу `.env.example`.
2) Установи зависимости:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install
```
3) Запусти бота и монитор в двух терминалах:
```bash
PYTHONPATH=src python -m dropwatch.bot
PYTHONPATH=src python -m dropwatch.monitor
```

## Использование
Все управление теперь можно делать через команды бота (FSM):
- `/set_proxy` — прокси (`http://user:pass@ip:port` или `none`).
- `/set_proxy_change_url` — URL смены IP.
- `/set_cookies_api_key` — API key cookies (spfa.ru) или `none`.
- `/set_link` — добавить ссылку Avito + min/max цена + white/black слова.
- `/set_filters` — max age (сек), игнор резерва и промо.
- `/start_monitor` и `/stop_monitor` — общий запуск/стоп мониторинга пользователя.

Поддерживаются multiple links и multi-user: настройки и ссылки хранятся в БД отдельно на каждого пользователя.
Антибан обязателен: без заполненных `/set_proxy` + `/set_proxy_change_url` + `/set_cookies_api_key` мониторинг не включится.

## Настройки (.env)
### Базовые
- `TELEGRAM_TOKEN` — токен бота.
- `DEFAULT_TASK_INTERVAL_SEC` — интервал проверки по умолчанию (сек).
- `SCHEDULER_TICK_SEC` — шаг планировщика.
- `AGGREGATE_THRESHOLD` — если найдено больше N объявлений, пришлёт общий заголовок.

### Avito парсер
- `FETCHER=avito_search` — основной режим.
- `AVITO_PROXY` — fallback прокси из env (если не задан через бота).
- `AVITO_PROXY_CHANGE_URL` — fallback URL для смены IP.
- `AVITO_USE_WEBDRIVER` — авто‑обновление cookies через Playwright (`true/false`).
- `AVITO_COOKIES_PATH` — путь к файлу cookies.
- `AVITO_MAX_PAGES` — сколько страниц листать.
- `AVITO_PAUSE_SEC` — пауза между страницами.
- `AVITO_MAX_RETRIES` — попытки при ошибках.
- `AVITO_REQUEST_TIMEOUT_SEC` — таймаут запроса.
- `AVITO_IMPERSONATE` — профиль `curl_cffi` (например `chrome`).

### Фильтры
- `AVITO_PARSE_VIEWS` — парсить просмотры (медленно).
- `AVITO_VIEWS_DELAY_SEC` — задержка между запросами на просмотры.
- `AVITO_IGNORE_RESERVED` — игнорировать «в резерве».
- `AVITO_IGNORE_PROMOTION` — игнорировать «Продвинуто».
- `AVITO_MAX_AGE_SEC` — максимальный возраст объявления (0 = выкл).
- `AVITO_SELLER_BLACKLIST` — продавцы в чёрном списке (через запятую).
- `AVITO_KEYWORDS_WHITELIST`/`AVITO_KEYWORDS_BLACKLIST` — глобальные слова‑фильтры (через запятую).
- `AVITO_GEO_FILTER` — глобальный фильтр по адресу (подстрока).

### LLM (опционально)
- `LLM_ENABLED=true` — включить краткую сводку и оценку.
- `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` — параметры доступа.

## Частые проблемы
- **429 / бан / капча**: используй `/set_proxy`, `/set_proxy_change_url`, `/set_cookies_api_key` и включи `AVITO_USE_WEBDRIVER=true`.
- **Нет объявлений**: проверь ссылку, фильтры и лимиты.
- **Не ставится Playwright**: `playwright install` после `pip install`.

## Docker
```bash
docker compose up --build
```

## Структура проекта
- `src/dropwatch/bot` — Telegram‑бот.
- `src/dropwatch/monitor` — монитор (парсер + логика задач).
- `src/dropwatch/db` — БД и модели.
- `src/dropwatch/common` — конфиг, форматирование, матчинг.
