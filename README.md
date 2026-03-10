# DROPWATCH

Личный Telegram-бот для мониторинга Avito.

Проект рассчитан на одного заказчика: один сервер, один Telegram-владелец, управление только через бот. После первичной настройки клиенту не нужно заходить на сервер и что-то крутить руками.

## Как это работает

- `bot` принимает команды в Telegram и сохраняет настройки.
- `monitor` отдельно ходит в Avito, следит за объявлениями и отправляет уведомления.
- `postgres` хранит радары, уже виденные объявления, избранное и настройки.
- Если у объявления есть фото, бот старается прислать фото с подписью.
- Доступ можно ограничить одним Telegram ID через `OWNER_TG_ID`.

## Что нужно заполнить один раз

Минимальный `.env` для продакшена:

- `TELEGRAM_TOKEN`
- `OWNER_TG_ID`
- `AVITO_PROXY`
- `AVITO_PROXY_CHANGE_URL`

Опционально:

- `AVITO_COOKIES_API_KEY`

Шаблон уже есть в [.env.example](/C:/Users/gerog/Desktop/Алексею/DROPWATCH/.env.example).
`OWNER_TG_ID` удобно узнать через `@userinfobot` в Telegram.

## Быстрый деплой на сервер

1. Установить Docker и Docker Compose.
2. Скопировать проект на сервер.
3. Создать `.env` из шаблона:

```powershell
Copy-Item .env.example .env
```

4. Заполнить `.env`.
5. Запустить сервисы:

```powershell
docker compose up -d --build
```

После этого клиент открывает бота в Telegram, жмет `/start` и дальше управляет всем оттуда.

## Как запустить радар

В Telegram:

1. Нажать `/start`.
2. Задать прокси через `/set_proxy`.
3. Задать URL смены IP через `/set_proxy_change_url`.
4. Добавить ссылку поиска Avito через `/set_link` или просто отправить ссылку в чат.
5. Включить мониторинг через `/start_monitor`.
6. Проверить состояние через `/status`.

Если все нормально, новые объявления начнут приходить в этот же чат.

## Команды клиента

- `/start` открыть меню
- `/status` посмотреть состояние сервиса
- `/set_proxy` сохранить прокси
- `/set_proxy_change_url` сохранить URL смены IP
- `/set_link` добавить ссылку Avito
- `/set_filters` настроить фильтры
- `/start_monitor` включить мониторинг
- `/stop_monitor` остановить мониторинг
- `/help` краткая инструкция

## Docker Compose

В проекте есть [docker-compose.yml](/C:/Users/gerog/Desktop/Алексею/DROPWATCH/docker-compose.yml):

- `postgres`
- `bot`
- `monitor`

Оба Python-сервиса запускаются отдельно и автоматически перезапускаются через `restart: unless-stopped`.

## Локальная проверка

Для локальной проверки на Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\playwright install chromium
.\scripts\smoke-check.ps1
```

Запуск локально:

```powershell
.\scripts\start-local.ps1
```

Или по отдельности:

```powershell
.\scripts\start-bot.ps1
.\scripts\start-monitor.ps1
```

## Ограничения

- Стабильность Avito в первую очередь зависит от качества прокси.
- Если Avito меняет HTML или антибот-защиту, fetcher надо обновлять.
- Честные проверки каждые 30 секунд реальны для небольшого числа радаров. Для большого числа задач нужно отдельно тюнить интервалы и throttling.

## Структура

- `src/dropwatch/bot` — Telegram-интерфейс
- `src/dropwatch/monitor` — worker и fetcher Avito
- `src/dropwatch/db` — модели и CRUD
- `src/dropwatch/common` — конфиг, форматирование, утилиты
- `scripts` — локальные скрипты запуска и smoke-check
