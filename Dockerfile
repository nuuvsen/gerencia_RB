# Usa uma versão um pouco mais leve e estável
FROM python:3.11-slim

WORKDIR /app

# Instala as dependências via pip (o --only-binary previne a necessidade de compilar na placa)
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# Copia o código
COPY bot_router_control.py .
RUN mkdir -p /tmp/backups

CMD ["python", "-u", "bot_router_control.py"]
