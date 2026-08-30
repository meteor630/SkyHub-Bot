FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libpq5 -- клиент PostgreSQL; ffmpeg -- нужен плагину radio для
# декодирования аудио при воспроизведении в голосовом канале; gcc +
# python3-dev -- на некоторых архитектурах (напр. arm64) для psutil нет
# готового wheel, и pip собирает его из исходников (без них сборка
# образа падает -- найдено при аудите).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 ffmpeg gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Не запускаем процесс от root внутри контейнера (аудит безопасности) --
# даже если код скомпрометируют через уязвимость в зависимости, у
# процесса не будет root-прав внутри контейнера. /app/logs и /app/data
# создаём заранее и отдаём этому пользователю, т.к. они смонтированы
# как volume поверх docker-compose.yml -- владелец файла на хосте
# должен совпадать с UID 1000 в контейнере (см. README/docs/DEPLOYMENT.md).
RUN useradd --create-home --uid 1000 skyhub \
    && mkdir -p /app/logs /app/data \
    && chown -R skyhub:skyhub /app
USER skyhub

CMD ["python", "-m", "app"]
