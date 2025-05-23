
# --- Imports ---
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import requests
import time
import schedule
import threading
from datetime import datetime
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
import os

TOKEN = os.getenv('8123262775:AAHEv43aS9dK8jXSjINqhDXbqxlHAfn4aTw')
CHAT_ID = os.getenv('7657570667')

# --- Configurações ---
CRIPTO_LISTA = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT','LDO-USDT', 'AAVE-USDT']
INTERVALO = '1hour'  # opções: '1min', '5min', '1hour', '1day', '1week'
analise_ativa = False

# --- Coletar dados da KuCoin ---
def obter_dados_kucoin(par, intervalo='1hour'):
    url = f"https://api.kucoin.com/api/v1/market/candles?type={intervalo}&symbol={par}"
    response = requests.get(url)
    data = response.json()

    if data['code'] != '200000':
        print(f"Erro ao obter dados da KuCoin para {par}: {data}")
        return None

    registros = data['data']
    df = pd.DataFrame(registros, columns=['timestamp', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
    df = df.iloc[::-1]  # inverter para ordem cronológica

    # Corrigido: timestamp em segundos
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('timestamp', inplace=True)
    df = df.astype(float)

    df['RSI'] = RSIIndicator(df['close']).rsi()
    bb = BollingerBands(close=df['close'])
    df['Upper'] = bb.bollinger_hband()
    df['Lower'] = bb.bollinger_lband()

    return df.dropna()

# --- Gerar gráfico ---
def gerar_grafico(df, par):
    fig, ax = plt.subplots(figsize=(12, 6))
    df['Data'] = df.index

    for i in range(len(df)):
        cor = 'green' if df['close'].iloc[i] > df['open'].iloc[i] else 'red'
        ax.plot([df['Data'].iloc[i], df['Data'].iloc[i]], [df['low'].iloc[i], df['high'].iloc[i]], color=cor)
        ax.plot([df['Data'].iloc[i], df['Data'].iloc[i]], [df['open'].iloc[i], df['close'].iloc[i]], linewidth=6, color=cor)

    ax.plot(df['Data'], df['Upper'], linestyle='--', color='blue', label='Banda Superior')
    ax.plot(df['Data'], df['Lower'], linestyle='--', color='blue', label='Banda Inferior')
    ax.set_title(f"{par} - Preço, RSI e Bandas de Bollinger")
    ax.set_xlabel("Data")
    ax.set_ylabel("Preço (USDT)")
    ax.legend()

    caminho = f"{par.replace('-', '_')}_grafico.png"
    plt.tight_layout()
    plt.savefig(caminho)
    plt.close()
    return caminho

# --- Enviar mensagem ---
def enviar_mensagem(bot, chat_id, texto, imagem=None):
    if imagem:
        bot.send_photo(chat_id=chat_id, photo=open(imagem, 'rb'), caption=texto)
    else:
        bot.send_message(chat_id=chat_id, text=texto)

# --- Lógica da análise ---
def analisar_todas(bot):
    for par in CRIPTO_LISTA:
        try:
            df = obter_dados_kucoin(par, INTERVALO)
            if df is None or df.empty:
                enviar_mensagem(bot, CHAT_ID, f"⚠️ Dados insuficientes para {par}")
                continue

            preco = df['close'].iloc[-1]
            rsi = df['RSI'].iloc[-1]
            upper = df['Upper'].iloc[-1]
            lower = df['Lower'].iloc[-1]

            status_bollinger = (
                "Acima da banda superior" if preco > upper else
                "Abaixo da banda inferior" if preco < lower else
                "Dentro das bandas"
            )

            rsi_msg = (
                "🟢 RSI indica sobrevenda (possível compra)" if rsi < 30 else
                "🔴 RSI indica sobrecompra (possível venda)" if rsi > 70 else
                "⚪ RSI neutro"
            )

            grafico_path = gerar_grafico(df, par)
            mensagem = (
                f"📊 Análise de {par}\n"
                f"💰 Preço atual: ${preco:,.2f}\n"
                f"📈 {rsi_msg} ({rsi:.2f})\n"
                f"📉 Bandas de Bollinger: {status_bollinger}\n"
                f"🕒 Intervalo: {INTERVALO}\n"
                f"🗓 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            )

            enviar_mensagem(bot, CHAT_ID, mensagem, grafico_path)

        except Exception as e:
            enviar_mensagem(bot, CHAT_ID, f"Erro na análise de {par}: {e}")

# --- Agendamento ---
def agendar(bot):
    schedule.every(30).minutes.do(lambda: analisar_todas(bot))
    while True:
        schedule.run_pending()
        time.sleep(1)

# --- Comandos do Bot ---
def start(update: Update, context: CallbackContext):
    global analise_ativa
    analise_ativa = True
    context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Análise ativada a cada 30 minutos.")

def stop(update: Update, context: CallbackContext):
    global analise_ativa
    analise_ativa = False
    context.bot.send_message(chat_id=update.effective_chat.id, text="🛑 Análise pausada.")

def agora(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text="⏳ Gerando análise agora...")
    analisar_todas(context.bot)

def add(update: Update, context: CallbackContext):
    if context.args:
        par = context.args[0].upper()
        if par not in CRIPTO_LISTA:
            CRIPTO_LISTA.append(par)
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ {par} adicionado à lista.")
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"⚠️ {par} já está na lista.")
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text="❗ Use: /add BTC-USDT")

def remove(update: Update, context: CallbackContext):
    if context.args:
        par = context.args[0].upper()
        if par in CRIPTO_LISTA:
            CRIPTO_LISTA.remove(par)
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ {par} removido da lista.")
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"⚠️ {par} não está na lista.")
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text="❗ Use: /remove BTC-USDT")

def intervalo(update: Update, context: CallbackContext):
    global INTERVALO
    if context.args:
        novo = context.args[0]
        if novo in ['1min', '5min', '1hour', '1day', '1week']:
            INTERVALO = novo
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔁 Intervalo alterado para {novo}.")
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text="❗ Intervalo inválido. Use: 1min, 5min, 1hour ou 1day.")
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text="❗ Use: /intervalo 1hour")

def menu(update: Update, context: CallbackContext):
    botoes = [
        [InlineKeyboardButton("📊 Enviar Análise Agora", callback_data='agora')],
        [InlineKeyboardButton("➕ Adicionar Cripto", callback_data='add')],
        [InlineKeyboardButton("➖ Remover Cripto", callback_data='remove')],
        [InlineKeyboardButton("🔁 Alterar Intervalo", callback_data='intervalo')]
    ]
    update.message.reply_text("📍 Menu Interativo:", reply_markup=InlineKeyboardMarkup(botoes))

def callback_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.data == 'agora':
        query.edit_message_text("⏳ Gerando análise agora...")
        analisar_todas(context.bot)
    elif query.data == 'add':
        query.edit_message_text("Use o comando: /add BTC-USDT")
    elif query.data == 'remove':
        query.edit_message_text("Use o comando: /remove BTC-USDT")
    elif query.data == 'intervalo':
        query.edit_message_text("Use o comando: /intervalo 1hour")

# --- Execução ---
updater = Updater(token=TOKEN, use_context=True)
dp = updater.dispatcher

# --- Registrar comandos ---
dp.add_handler(CommandHandler('start', start))
dp.add_handler(CommandHandler('stop', stop))
dp.add_handler(CommandHandler('agora', agora))
dp.add_handler(CommandHandler('menu', menu))
dp.add_handler(CommandHandler('add', add))
dp.add_handler(CommandHandler('remove', remove))
dp.add_handler(CommandHandler('intervalo', intervalo))
dp.add_handler(CallbackQueryHandler(callback_handler))

# --- Iniciar bot ---
threading.Thread(target=agendar, args=(updater.bot,), daemon=True).start()
updater.start_polling()
print("✅ Bot rodando...")
updater.idle()
