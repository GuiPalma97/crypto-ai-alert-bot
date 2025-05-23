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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
import joblib
from sklearn.tree import DecisionTreeClassifier  # só pra type hint, o treino fica separado

# --- Configurações ---
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

CRIPTO_LISTA = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'LDO-USDT', 'AAVE-USDT']
INTERVALO = '1hour'  # '1min', '5min', '1hour', '1day', '1week'
analise_ativa = False

# --- Carrega modelo treinado ---
try:
    modelo = joblib.load('modelo_decision_tree.pkl')
except Exception as e:
    print("⚠️ Erro ao carregar modelo ML:", e)
    modelo = None

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

    df['pct_change'] = df['close'].pct_change()

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

# --- Comando /insights com ML integrado ---
async def insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Use o comando com o par desejado. Exemplo:\n/insights BTC-USDT")
        return
    
    par = context.args[0].upper()
    if par not in CRIPTO_LISTA:
        await update.message.reply_text(f"⚠️ {par} não está na lista. Use /add para adicioná-la primeiro.")
        return

    await update.message.reply_text(f"🔍 Gerando insights para {par}...")

    df = obter_dados_kucoin(par, INTERVALO)
    if df is None or df.empty:
        await update.message.reply_text(f"⚠️ Não foi possível obter dados para {par}.")
        return

    preco_atual = df['close'].iloc[-1]
    rsi_atual = df['RSI'].iloc[-1]
    upper = df['Upper'].iloc[-1]
    lower = df['Lower'].iloc[-1]
    volume_medio = df['volume'].rolling(window=10).mean().iloc[-1]
    volume_atual = df['volume'].iloc[-1]

    mov_volume = (volume_atual > 2 * volume_medio)

    status_bollinger = (
        "Preço acima da banda superior (possível sobrecompra)" if preco_atual > upper else
        "Preço abaixo da banda inferior (possível sobrevenda)" if preco_atual < lower else
        "Preço dentro das bandas de Bollinger"
    )

    if rsi_atual < 30:
        status_rsi = "RSI indica sobrevenda (potencial oportunidade de compra)."
    elif rsi_atual > 70:
        status_rsi = "RSI indica sobrecompra (potencial momento de venda)."
    else:
        status_rsi = "RSI está neutro."

    df['MA20'] = df['close'].rolling(window=20).mean()
    ma20_atual = df['MA20'].iloc[-1]

    tendencia = "indefinida"
    if preco_atual > ma20_atual:
        tendencia = "tendência de alta"
    elif preco_atual < ma20_atual:
        tendencia = "tendência de baixa"

    variacao_ultimo = ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100

    # Prever recomendação com modelo ML, se disponível
    recomendacao = "Modelo ML não disponível."
    if modelo is not None:
        features = [[
            preco_atual,
            rsi_atual,
            upper,
            lower,
            df['pct_change'].iloc[-1]
        ]]
        pred = modelo.predict(features)[0]
        recomendacao = {
            0: "Manter a posição.",
            1: "Recomendação: Comprar.",
            2: "Recomendação: Vender."
        }.get(pred, "Sem recomendação.")

    texto = (
        f"📊 Insights para *{par}*\n\n"
        f"💰 Preço atual: ${preco_atual:,.2f}\n"
        f"🔻 Variação última hora: {variacao_ultimo:.2f}%\n"
        f"📈 {status_rsi}\n"
        f"📉 {status_bollinger}\n"
        f"📊 Volume {'alto 📈' if mov_volume else 'normal'}\n"
        f"📅 Média móvel 20 períodos indica *{tendencia}*.\n\n"
        f"🤖 {recomendacao}"
    )

    grafico_path = gerar_grafico(df, par)

    await update.message.reply_photo(photo=open(grafico_path, 'rb'), caption=texto, parse_mode='Markdown')

# --- Comandos para iniciar/parar análise agendada ---
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
    schedule.every(1).hours.do(job)

    while True:
        schedule.run_pending()
        time.sleep(5)

# --- Função principal ---
async def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("insights", insights))

    # Roda o agendador em thread paralela para não travar o bot
    threading.Thread(target=agendar_analise, args=(application,), daemon=True).start()

    print("Bot iniciado...")
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
