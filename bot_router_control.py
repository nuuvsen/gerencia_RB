import os
import sys
import time
import telebot
import paramiko

# --- VALIDAÇÃO DAS VARIÁVEIS DE AMBIENTE ---
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID_PERMITIDO = os.getenv("CHAT_ID_PERMITIDO")
IP_MIKROTIK = os.getenv("IP_MIKROTIK")
USER_MIKROTIK = os.getenv("USER_MIKROTIK")
SENHA_MIKROTIK = os.getenv("SENHA_MIKROTIK")

if not all([TOKEN_TELEGRAM, CHAT_ID_PERMITIDO, IP_MIKROTIK, USER_MIKROTIK, SENHA_MIKROTIK]):
    print("ERRO: Todas as variáveis de ambiente devem ser configuradas na Stack do Portainer.")
    sys.exit(1)

try:
    CHAT_ID_PERMITIDO = int(CHAT_ID_PERMITIDO)
except ValueError:
    print("ERRO: CHAT_ID_PERMITIDO deve ser um número inteiro válido.")
    sys.exit(1)

bot = telebot.TeleBot(TOKEN_TELEGRAM)

# --- FUNÇÃO AUXILIAR SSH ---
def executar_comando_ssh(comando, obter_output=True, sftp_operacao=False):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(IP_MIKROTIK, username=USER_MIKROTIK, password=SENHA_MIKROTIK, timeout=15)
        
        if sftp_operacao:
            return ssh.open_sftp(), ssh
            
        stdin, stdout, stderr = ssh.exec_command(comando)
        if obter_output:
            saida = stdout.read().decode('utf-8', errors='ignore').strip()
            erros = stderr.read().decode('utf-8', errors='ignore').strip()
            ssh.close()
            return saida if saida else erros
        else:
            ssh.close()
            return True
    except Exception as e:
        if 'ssh' in locals():
            ssh.close()
        return f"Erro de conexão/execução: {str(e)}"

# --- FILTRO DE SEGURANÇA ---
def verificar_usuario(message):
    if message.chat.id == CHAT_ID_PERMITIDO:
        return True
    bot.reply_to(message, "Acesso negado. Você não tem permissão para comandar esta RB. ❌")
    return False

# --- COMANDOS DO BOT ---

@bot.message_handler(commands=['start', 'ajuda'])
def cmd_ajuda(message):
    if not verificar_usuario(message): return
    texto_menu = (
        "⚙️ *Bot de Controle MikroTik*\n\n"
        "⚡ *Monitoramento:*\n"
        "/status - Exibe CPU, RAM, Uptime e Versão\n"
        "/clientes - Conta conexões PPPoE e DHCP\n"
        "/portas - Status físico e velocidade (1Gbps/100Mbps)\n"
        "/trafego - Consumo em tempo real e pico atual\n"
        "/ping [IP/Host] - Dispara pings a partir da RB\n"
        "/tracert [IP/Host] - Rastreia a rota até o destino\n\n"
        "🛠️ *Ações Operacionais:*\n"
        "/desativar_porta [interface] - Força o desligamento\n"
        "/ativar_porta [interface] - Força a ativação\n"
        "/mudar_link [interface] - Alterna o status do link\n"
        "/limpar_conntrack - Limpa a tabela de conexões\n"
        "/backup - Gera e envia os arquivos (.backup e .rsc)\n"
        "/reboot - Reinicia a RouterBoard IMEDIATAMENTE\n"
        "/agendar_reboot [dias] - Agenda reboot às 03:00\n"
    )
    bot.send_message(message.chat.id, texto_menu, parse_mode="Markdown")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "🔍 Coletando informações da RB...")
    
    info_cpu = executar_comando_ssh(":put [/system resource get cpu-load]")
    info_uptime = executar_comando_ssh(":put [/system resource get uptime]")
    info_ram_livre = executar_comando_ssh(":put [/system resource get free-memory]")
    info_versao = executar_comando_ssh(":put [/system resource get version]")
    
    try:
        ram_mb = round(int(info_ram_livre) / 1048576, 1)
        ram_texto = f"{ram_mb} MB"
    except:
        ram_texto = info_ram_livre

    relatorio = (
        f"📊 *Status Atual da RB-SOLANO*\n\n"
        f"🖥️ *CPU:* `{info_cpu}%`\n"
        f"⏳ *Uptime:* `{info_uptime}`\n"
        f"💾 *RAM Livre:* `{ram_texto}`\n"
        f"📦 *RouterOS:* `v{info_versao}`"
    )
    bot.send_message(message.chat.id, relatorio, parse_mode="Markdown")

@bot.message_handler(commands=['portas'])
def cmd_portas(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "🔌 Lendo os sensores das portas Ethernet...")
    
    # Script nativo do MikroTik para rodar interface por interface checando velocidade e status do link
    cmd = ':foreach i in=[/interface ethernet find] do={:local run [/interface get $i running]; :local nome [/interface get $i name]; :if ($run) do={/interface ethernet monitor $i once do={:put ("\E2\9C\85 " . $nome . " | UP | " . $rate)}} else={:put ("\E2\9D\8C " . $nome . " | DOWN | Sem Link")}}'
    saida = executar_comando_ssh(cmd)
    
    bot.send_message(message.chat.id, f"*Status das Portas Físicas:*\n\n`{saida}`", parse_mode="Markdown")

@bot.message_handler(commands=['trafego'])
def cmd_trafego(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "📈 Coletando consumo em tempo real...")
    
    # Executa o monitoramento de tráfego do MikroTik para todas as interfaces no momento exato e estrutura em CSV
    cmd = '/interface monitor-traffic [find] once do={:put ($name . "," . $"rx-bits-per-second" . "," . $"tx-bits-per-second")}'
    saida = executar_comando_ssh(cmd)
    
    linhas = saida.strip().split('\n')
    resultado = []
    max_consumo = 0
    interface_pico = "Nenhuma"
    
    for linha in linhas:
        partes = linha.split(',')
        if len(partes) == 3:
            nome = partes[0].strip()
            try:
                # O MikroTik devolve bps puro. Dividimos por 1.000.000 para achar os Megabits de rede (Mbps)
                rx_mbps = int(partes[1].strip()) / 1000000
                tx_mbps = int(partes[2].strip()) / 1000000
                total_mbps = rx_mbps + tx_mbps
                
                # Ignora interfaces zeradas ou de loopback irrelevante
                if total_mbps > 0.1:
                    resultado.append(f"🌐 *{nome}*: ⬇️ {rx_mbps:.1f} Mbps | ⬆️ {tx_mbps:.1f} Mbps")
                
                # Verifica se é a interface de maior consumo
                if total_mbps > max_consumo:
                    max_consumo = total_mbps
                    interface_pico = f"*{nome}*\n(Tráfego Somado: `{total_mbps:.1f} Mbps`)"
            except:
                pass
                
    if not resultado:
        texto = "Sem tráfego significativo trafegando no momento."
    else:
        texto = "\n".join(resultado)
        texto += f"\n\n🔥 *Pico de Consumo Atual:*\nA interface mais exigida neste instante é a {interface_pico}"
        
    bot.send_message(message.chat.id, texto, parse_mode="Markdown")

@bot.message_handler(commands=['tracert'])
def cmd_tracert(message):
    if not verificar_usuario(message): return
    argumentos = message.text.split(maxsplit=1)
    if len(argumentos) < 2:
        bot.reply_to(message, "⚠️ Informe o IP ou domínio de destino. Ex: `/tracert 8.8.8.8`", parse_mode="Markdown")
        return
        
    alvo = argumentos[1].strip()
    bot.reply_to(message, f"🛤️ Realizando Traceroute para *{alvo}*... Aguarde, isso leva alguns segundos.", parse_mode="Markdown")
    
    # O count=4 garante que o processo vai encerrar e enviar de volta
    saida = executar_comando_ssh(f"/tool traceroute address={alvo} count=4")
    bot.send_message(message.chat.id, f"```\n{saida}\n```", parse_mode="Markdown")

@bot.message_handler(commands=['clientes'])
def cmd_clientes(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "👥 Contando clientes ativos...")
    
    count_pppoe = executar_comando_ssh(":put [:len [/ppp active find]]")
    count_dhcp = executar_comando_ssh(":put [:len [/ip dhcp-server lease find status=bound]]")
    
    relatorio = (
        f"📡 *Clientes Conectados Agora:*\n\n"
        f"🔒 *PPPoE Ativos:* `{count_pppoe}`\n"
        f"🌐 *DHCP Ativos:* `{count_dhcp}`"
    )
    bot.send_message(message.chat.id, relatorio, parse_mode="Markdown")

@bot.message_handler(commands=['desativar_porta'])
def cmd_desativar_porta(message):
    if not verificar_usuario(message): return
    try:
        porta = message.text.split()[1].strip()
        executar_comando_ssh(f"/interface disable [find name=\"{porta}\"]", obter_output=False)
        bot.reply_to(message, f"🔴 Porta *{porta}* foi **DESATIVADA** com sucesso!", parse_mode="Markdown")
    except:
        bot.reply_to(message, "⚠️ Especifique a interface! Exemplo: `/desativar_porta ether1`", parse_mode="Markdown")

@bot.message_handler(commands=['ativar_porta'])
def cmd_ativar_porta(message):
    if not verificar_usuario(message): return
    try:
        porta = message.text.split()[1].strip()
        executar_comando_ssh(f"/interface enable [find name=\"{porta}\"]", obter_output=False)
        bot.reply_to(message, f"🟢 Porta *{porta}* foi **ATIVADA** com sucesso!", parse_mode="Markdown")
    except:
        bot.reply_to(message, "⚠️ Especifique a interface! Exemplo: `/ativar_porta ether1`", parse_mode="Markdown")

@bot.message_handler(commands=['mudar_link', 'Mudar_link'])
def cmd_mudar_link(message):
    if not verificar_usuario(message): return
    argumentos = message.text.split(maxsplit=1)
    if len(argumentos) < 2:
        bot.reply_to(message, "⚠️ Use o comando informando a interface. Ex:\n`/mudar_link ether1`", parse_mode="Markdown")
        return
        
    interface = argumentos[1].strip()
    bot.reply_to(message, f"🔍 Verificando estado atual da interface *{interface}*...", parse_mode="Markdown")
    
    status_output = executar_comando_ssh(f"/interface print file=status; :put [/interface get [find name=\"{interface}\"] disabled]")
    
    if "no such item" in status_output.lower() or "error" in status_output.lower():
        bot.send_message(message.chat.id, f"❌ Interface '{interface}' não foi localizada na RB.")
        return

    if "true" in status_output.lower():
        executar_comando_ssh(f"/interface enable [find name=\"{interface}\"]", obter_output=False)
        bot.send_message(message.chat.id, f"🟢 Interface *{interface}* foi **ATIVADA** com sucesso!", parse_mode="Markdown")
    else:
        executar_comando_ssh(f"/interface disable [find name=\"{interface}\"]", obter_output=False)
        bot.send_message(message.chat.id, f"🔴 Interface *{interface}* foi **DESATIVADA** com sucesso!", parse_mode="Markdown")

@bot.message_handler(commands=['agendar_reboot'])
def cmd_agendar_reboot(message):
    if not verificar_usuario(message): return
    argumentos = message.text.split(maxsplit=1)
    
    if len(argumentos) < 2:
        bot.reply_to(message, "⚠️ Informe a cada quantos dias a RB deve reiniciar. Ex:\n`/agendar_reboot 20`\nPara cancelar o agendamento, digite: `/agendar_reboot 0`", parse_mode="Markdown")
        return
        
    try:
        dias = int(argumentos[1].strip())
    except ValueError:
        bot.reply_to(message, "❌ Use apenas números para os dias.")
        return

    if dias == 0:
        executar_comando_ssh("/system scheduler remove [find name=\"Reboot_Telegram\"]")
        bot.send_message(message.chat.id, "✅ Agendamento de Reboot Automático **CANCELADO**.", parse_mode="Markdown")
        return

    bot.reply_to(message, f"⚙️ Configurando a RB para reiniciar a cada {dias} dias, sempre às 03:00 da manhã...")
    executar_comando_ssh("/system scheduler remove [find name=\"Reboot_Telegram\"]")
    comando_agendamento = f'/system scheduler add name="Reboot_Telegram" start-time=03:00:00 interval={dias}d on-event="/system reboot"'
    executar_comando_ssh(comando_agendamento, obter_output=False)
    bot.send_message(message.chat.id, f"📅 **Sucesso!** A sua RouterBoard agora vai reiniciar sozinha a cada `{dias} dias`, sempre no horário de menor movimento (03:00 AM).", parse_mode="Markdown")

@bot.message_handler(commands=['reboot'])
def cmd_reboot(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "Iniciando processo de reboot na RB... Aguarde🔄")
    executar_comando_ssh("/system reboot\ny", obter_output=False)

@bot.message_handler(commands=['backup'])
def cmd_backup(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "⏳ Gerando arquivos de backup dentro da RB (Isso pode levar alguns segundos)...")
    
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    nome_arquivo = f"Backup_Telegram_{timestamp}"
    
    executar_comando_ssh(f"/system backup save name={nome_arquivo} password=tony", obter_output=False)
    executar_comando_ssh(f"/export file={nome_arquivo}", obter_output=False)
    
    time.sleep(3) 
    bot.send_message(CHAT_ID_PERMITIDO, "📥 Baixando e enviando arquivos para você...")
    
    try:
        sftp, ssh = executar_comando_ssh("", sftp_operacao=True)
        path_backup_local = f"/tmp/backups/{nome_arquivo}.backup"
        path_rsc_local = f"/tmp/backups/{nome_arquivo}.rsc"
        
        sftp.get(f"{nome_arquivo}.backup", path_backup_local)
        sftp.get(f"{nome_arquivo}.rsc", path_rsc_local)
        
        sftp.remove(f"{nome_arquivo}.backup")
        sftp.remove(f"{nome_arquivo}.rsc")
        sftp.close()
        ssh.close()
        
        with open(path_backup_local, 'rb') as f_backup:
            bot.send_document(CHAT_ID_PERMITIDO, f_backup, caption="📁 Arquivo de Backup (.backup)")
        with open(path_rsc_local, 'rb') as f_rsc:
            bot.send_document(CHAT_ID_PERMITIDO, f_rsc, caption="📄 Arquivo de Script/Export (.rsc)")
            
        os.remove(path_backup_local)
        os.remove(path_rsc_local)
        
    except Exception as e:
        bot.send_message(CHAT_ID_PERMITIDO, f"❌ Falha no processamento ou envio do backup: {str(e)}")

@bot.message_handler(commands=['limpar_conntrack'])
def cmd_limpar_conntrack(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "⏳ Limpando conexões tracking ativas da RB...")
    executar_comando_ssh("/ip firewall connection remove [find]")
    bot.send_message(CHAT_ID_PERMITIDO, "💥 Tabela Conntrack limpa com sucesso!")

@bot.message_handler(commands=['ping'])
def cmd_ping(message):
    if not verificar_usuario(message): return
    argumentos = message.text.split(maxsplit=1)
    if len(argumentos) < 2:
        bot.reply_to(message, "⚠️ Informe o IP ou domínio de destino. Ex: `/ping 8.8.8.8`", parse_mode="Markdown")
        return
        
    alvo = argumentos[1].strip()
    bot.reply_to(message, f"📡 Disparando ping do MikroTik para *{alvo}*... Aguarde as respostas.", parse_mode="Markdown")
    
    resposta_ping = executar_comando_ssh(f"/ping count=5 {alvo}")
    bot.send_message(CHAT_ID_PERMITIDO, f"```\n{resposta_ping}\n```", parse_mode="Markdown")

if __name__ == "__main__":
    print("Bot de controle iniciado no Docker e escutando...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Erro no polling do Telegram, reconectando em 5s: {e}")
            time.sleep(5)
