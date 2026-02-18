FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . /app

CMD ["sh", "-lc", "PYTHONPATH=src python -m dropwatch.bot & PYTHONPATH=src python -m dropwatch.monitor & wait -n"]
