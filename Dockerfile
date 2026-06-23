FROM python:3.10-slim

WORKDIR /app

# Instala dependências de compilação essenciais para o Paramiko (criptografia)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot_router_control.py .

# Cria pasta temporária para armazenar os arquivos de backup gerados
RUN mkdir -p /tmp/backups

CMD ["python", "-u", "bot_router_control.py"]
