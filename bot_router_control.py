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
        "⚙️ Bot de Controle MikroTik\n\n"
        "⚡ Monitoramento:\n"
        "/status - Exibe CPU, RAM, Uptime e Versao\n"
        "/clientes - Lista conexoes PPPoE e DHCP ativas por bloco\n"
        "/ping IP_OU_HOST - Dispara pings da RB\n"
        "/tracert IP_OU_HOST - Rastreia rota\n\n"
        "🛠️ Acoes Operacionais:\n"
        "/desativar_porta INTERFACE - Forca desligamento\n"
        "/ativar_porta INTERFACE - Forca ativacao\n"
        "/mudar_link INTERFACE - Alterna status\n"
        "/limpar_conntrack - Limpa conexoes ativas\n"
        "/backup - Gera e envia arquivos de backup\n"
        "/reboot - Reinicia a RB\n"
        "/agendar_reboot DIAS - Agenda reboot as 03:00\n"
    )
    bot.send_message(message.chat.id, texto_menu)

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
    
    cmd = ':foreach i in=[/interface ethernet find] do={:local run [/interface get $i running]; :local nome [/interface get $i name]; :if ($run) do={/interface ethernet monitor $i once do={:put ("\E2\9C\85 " . $nome . " | UP | " . $rate)}} else={:put ("\E2\9D\8C " . $nome . " | DOWN | Sem Link")}}'
    saida = executar_comando_ssh(cmd)
    
    bot.send_message(message.chat.id, f"*Status das Portas Físicas:*\n\n`{saida}`", parse_mode="Markdown")

@bot.message_handler(commands=['trafego'])
def cmd_trafego(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "📈 Coletando consumo em tempo real...")
    
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
                rx_mbps = int(partes[1].strip()) / 1000000
                tx_mbps = int(partes[2].strip()) / 1000000
                total_mbps = rx_mbps + tx_mbps
                
                if total_mbps > 0.1:
                    resultado.append(f"🌐 *{nome}*: ⬇️ {rx_mbps:.1f} Mbps | ⬆️ {tx_mbps:.1f} Mbps")
                
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
    
    saida = executar_comando_ssh(f"/tool traceroute address={alvo} count=4")
    bot.send_message(message.chat.id, f"```\n{saida}\n```", parse_mode="Markdown")

@bot.message_handler(commands=['clientes'])
def cmd_clientes(message):
    if not verificar_usuario(message): return
    bot.reply_to(message, "👥 Coletando e separando clientes ativos por bloco de IP... Isso pode levar alguns segundos.")
    
    # 1. Busca os clientes PPPoE
    count_pppoe = executar_comando_ssh(":put [:len [/ppp active find]]")
    
    # 2. Script MikroTik: Varre todos os blocos de IP e agrupa apenas os leases ativos (bound)
    script_routeros = (
        ':local out ""; '
        ':foreach a in=[/ip address find dynamic=no disabled=no] do={'
            ':local cidr [/ip address get $a address]; '
            ':local net [/ip address get $a network]; '
            ':local comment [/ip address get $a comment]; '
            ':local titulo ""; '
            # Usa o comentário da interface caso exista (Ex: WI-FI_CASA), senão usa a Rede
            ':if ([:len $comment] > 0) do={ :set titulo ($comment . " (" . $net . ")") } else={ :set titulo ("Rede " . $net) }; '
            ':local leases ""; '
            ':local count 0; '
            # Busca todos os leases que estao "bound" e fazem parte do bloco de rede verificado
            ':foreach l in=[/ip dhcp-server lease find status=bound address in $cidr] do={'
                ':local lip [/ip dhcp-server lease get $l address]; '
                ':local lhost [/ip dhcp-server lease get $l host-name]; '
                ':if ([:len $lhost] = 0) do={ :set lhost "Desconhecido" }; '
                ':set leases ($leases . "  🔹 `" . $lip . "` - " . $lhost . "\\n"); '
                ':set count ($count + 1); '
            '}; '
            # Se encontrou leases nesse bloco, adiciona ao relatório
            ':if ($count > 0) do={'
                ':set out ($out . "🗂️ *" . $titulo . "* - Ativos: " . $count . "\\n" . $leases . "\\n"); '
            '} '
        '}; '
        ':put $out'
    )
    
    redes_dhcp = executar_comando_ssh(script_routeros)
    
    if not redes_dhcp or "syntax error" in redes_dhcp.lower():
         redes_dhcp = "Nenhum cliente DHCP ativo encontrado nas redes ou erro de processamento."

    relatorio = f"📡 *Clientes Conectados Agora:*\n\n🔒 *PPPoE Ativos:* `{count_pppoe}`\n\n{redes_dhcp}"
    
    # Prevenção: O Telegram aceita no máximo 4096 caracteres por mensagem
    if len(relatorio) > 4000:
        for i in range(0, len(relatorio), 4000):
            bot.send_message(message.chat.id, relatorio[i:i+4000], parse_mode="Markdown")
    else:
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
