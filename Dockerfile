FROM python:3.11-slim-bookworm
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Instala apenas o essencial e limpa o cache imediatamente
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot_router_control.py .
RUN mkdir -p /tmp/backups

CMD ["python", "-u", "bot_router_control.py"]
