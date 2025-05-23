import os
import pandas as pd
import matplotlib.pyplot as plt
import requests
import time
import schedule
import threading
from datetime import datetime
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# --- Configurações ---
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or 'SEU_TOKEN_AQUI'
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID') or 'SEU_CHAT_ID_AQUI'

CRIPTO_LISTA = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'LDO-USDT', 'AAVE-USDT']
INTERVALO = '1hour'  # '1min', '5min', '1hour', '1day', '1week'
analise_ativa = False

# --- Função para obter dados da KuCoin ---
def obter_dados_kucoin(par, intervalo='1hour'):
    url = f"https://api.kucoin.com/api/v1/market/candles?type={intervalo}&symbol={par}"
    response = requests.get(url)
    data = response.json()

    if data['code'] != '200000':
        print(f"Erro ao obter dados da KuCoin para {par}: {data}")
        return None

    registros = data['data']
    df = pd.DataFrame(registros, columns=['timestamp', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
    df = df.iloc[::-1]  # ordem cronológica

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('timestamp', inplace=True)
    df = df.astype(float)

    # Calcula indicadores
    df['RSI'] = RSIIndicator(df['close']).rsi()
    bb = BollingerBands(df['close'])
    df['Upper'] = bb.bollinger_hband()
    df['Lower'] = bb.bollinger_lband()

    return df.dropna()

# --- Função para gerar gráfico ---
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

# --- Função para enviar mensagem ---
async def enviar_mensagem(bot, chat_id, texto, imagem=None):
    if imagem:
        with open(imagem, 'rb') as f:
            await bot.send_photo(chat_id=chat_id, photo=f, caption=texto)
    else:
        await bot.send_message(chat_id=chat_id, text=texto)

# --- Função para análise de todos os pares ---
async def analisar_todas(bot):
    for par in CRIPTO_LISTA:
        try:
            df = obter_dados_kucoin(par, INTERVALO)
            if df is None or df.empty:
                await enviar_mensagem(bot, CHAT_ID, f"⚠️ Dados insuficientes para {par}")
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

            await enviar_mensagem(bot, CHAT_ID, mensagem, grafico_path)

        except Exception as e:
            await enviar_mensagem(bot, CHAT_ID, f"Erro na análise de {par}: {e}")

# --- Comandos adicionais ---
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CRIPTO_LISTA
    if not context.args:
        await update.message.reply_text("❗ Use /add seguido do par. Exemplo: /add XRP-USDT")
        return

    par = context.args[0].upper()
    if par in CRIPTO_LISTA:
        await update.message.reply_text(f"⚠️ {par} já está na lista de análise.")
    else:
        CRIPTO_LISTA.append(par)
        await update.message.reply_text(f"✅ {par} adicionado à lista de análise.")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CRIPTO_LISTA
    if not context.args:
        await update.message.reply_text("❗ Use /remove seguido do par. Exemplo: /remove SOL-USDT")
        return

    par = context.args[0].upper()
    if par in CRIPTO_LISTA:
        CRIPTO_LISTA.remove(par)
        await update.message.reply_text(f"✅ {par} removido da lista de análise.")
    else:
        await update.message.reply_text(f"⚠️ {par} não está na lista.")

async def interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global INTERVALO
    if not context.args:
        await update.message.reply_text("⏱ Intervalo atual: " + INTERVALO)
        return

    novo = context.args[0]
    if novo not in ['1min', '5min', '1hour', '1day', '1week']:
        await update.message.reply_text("⚠️ Intervalo inválido. Use: 1min, 5min, 1hour, 1day ou 1week.")
    else:
        INTERVALO = novo
        await update.message.reply_text(f"✅ Intervalo alterado para {INTERVALO}.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global analise_ativa
    if analise_ativa:
        await update.message.reply_text("🚦 A análise já está ativa.")
        return
    analise_ativa = True
    await update.message.reply_text("✅ Análise automática iniciada.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global analise_ativa
    if not analise_ativa:
        await update.message.reply_text("⛔ A análise não está ativa.")
        return
    analise_ativa = False
    await update.message.reply_text("🛑 Análise automática parada.")

# --- Agendador de análises ---
def agendar_analise(application):
    def job():
        if analise_ativa:
            print("Executando análise automática...")
            application.create_task(analisar_todas(application.bot))
        else:
            print("Análise automática está desativada.")
    schedule.every(30).minutes.do(job)

    while True:
        schedule.run_pending()
        time.sleep(5)

# --- Função principal ---
async def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("add", add))
    application.add_handler(CommandHandler("remove", remove))
    application.add_handler(CommandHandler("interval", interval))

    threading.Thread(target=agendar_analise, args=(application,), daemon=True).start()

    print("Bot iniciado...")
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
