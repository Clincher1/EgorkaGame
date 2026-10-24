FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY game ./game
COPY web ./web

EXPOSE 8080

# PORT может переопределяться хостингом (Render и др.)
CMD ["python", "-m", "game.main"]
