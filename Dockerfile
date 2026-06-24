# Usa uma imagem base moderna (Bookworm) com repositórios ativos para ARM
FROM python:3.11-slim-bookworm

WORKDIR /app

# Instala dependências de compilação essenciais para o Paramiko (criptografia)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o script principal do bot
COPY bot_router_control.py .

# Cria pasta temporária para armazenar os arquivos de backup gerados
RUN mkdir -p /tmp/backups

# Executa o bot com -u para garantir que os logs apareçam no Portainer em tempo real
CMD ["python", "-u", "bot_router_control.py"]
