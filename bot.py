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
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import os
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CRIPTO_LISTA = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT']
INTERVALO = '1hour'
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
    df = df.iloc[::-1]
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
async def enviar_mensagem(bot, texto, imagem=None):
    if imagem:
        await bot.send_photo(chat_id=CHAT_ID, photo=open(imagem, 'rb'), caption=texto)
    else:
        await bot.send_message(chat_id=CHAT_ID, text=texto)

# --- Lógica de análise ---
async def analisar_todas(bot):
    for par in CRIPTO_LISTA:
        try:
            df = obter_dados_kucoin(par, INTERVALO)
            if df is None or df.empty:
                await enviar_mensagem(bot, f"⚠️ Dados insuficientes para {par}")
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
            await enviar_mensagem(bot, mensagem, grafico_path)
        except Exception as e:
            await enviar_mensagem(bot, f"Erro na análise de {par}: {e}")

# --- Comandos do Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global analise_ativa
    analise_ativa = True
    await update.message.reply_text("✅ Análise ativada a cada 30 minutos.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global analise_ativa
    analise_ativa = False
    await update.message.reply_text("🛑 Análise pausada.")

async def agora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Gerando análise agora...")
    await analisar_todas(context.bot)

async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📋 Criptomoedas monitoradas:\n{', '.join(CRIPTO_LISTA)}")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        nova = context.args[0].upper()
        if nova in CRIPTO_LISTA:
            await update.message.reply_text(f"⚠️ {nova} já está na lista.")
        else:
            CRIPTO_LISTA.append(nova)
            await update.message.reply_text(f"✅ {nova} adicionada à lista.")
    else:
        await update.message.reply_text("❗ Use: /add BTC-USDT")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        alvo = context.args[0].upper()
        if alvo in CRIPTO_LISTA:
            CRIPTO_LISTA.remove(alvo)
            await update.message.reply_text(f"🗑 {alvo} removida da lista.")
        else:
            await update.message.reply_text(f"⚠️ {alvo} não está na lista.")
    else:
        await update.message.reply_text("❗ Use: /remove BTC-USDT")

# --- Agendamento ---
def agendar(app):
    async def job():
        if analise_ativa:
            await analisar_todas(app.bot)
    schedule.every(30).minutes.do(lambda: asyncio.run(job()))
    while True:
        schedule.run_pending()
        time.sleep(1)

# --- Execução principal ---
if __name__ == '__main__':
    import asyncio
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('stop', stop))
    app.add_handler(CommandHandler('agora', agora))
    app.add_handler(CommandHandler('lista', lista))
    app.add_handler(CommandHandler('add', add))
    app.add_handler(CommandHandler('remove', remove))
    threading.Thread(target=agendar, args=(app,), daemon=True).start()
    print("✅ Bot rodando...")
    app.run_polling()
