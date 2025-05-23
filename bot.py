import asyncio
import logging
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import requests
from datetime import datetime
from ta.momentum import RSIIndicator
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters)

# --- Configurações ---
TOKEN = '8123262775:AAHEv43aS9dK8jXSjINqhDXbqxlHAfn4aTw'
CHAT_ID = '7657570667'
CRIPTO_LISTA = ['bitcoin', 'ethereum', 'solana', 'lido-dao', 'aave']
INTERVALO = '7'  # Análise semanal (7 dias)

# --- Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Coletar dados da CoinGecko ---
def obter_dados_criptomoeda(nome):
    url = f"https://api.coingecko.com/api/v3/coins/{nome}/market_chart?vs_currency=usd&days={INTERVALO}&interval=daily"
    response = requests.get(url)
    if response.status_code != 200:
        logger.warning(f"Erro ao buscar dados para {nome}: {response.text}")
        return None
    data = response.json()
    precos = data['prices']
    df = pd.DataFrame(precos, columns=['timestamp', 'price'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['RSI'] = RSIIndicator(df['price']).rsi()
    return df.dropna()

# --- Gerar gráfico ---
def gerar_grafico(df, nome):
    fig, ax = plt.subplots(figsize=(10, 4))
    df['price'].plot(ax=ax, label='Preço')
    ax.set_title(f'{nome.capitalize()} - Preço e RSI')
    ax.set_ylabel("USDT")
    ax.legend()
    caminho = f"{nome}_grafico.png"
    plt.tight_layout()
    plt.savefig(caminho)
    plt.close()
    return caminho

# --- Análise com sugestão ---
def sugestao_rsi(rsi):
    if rsi < 30:
        return "🟢 RSI sugere COMPRA"
    elif rsi > 70:
        return "🔴 RSI sugere VENDA"
    else:
        return "⚪ RSI sugere HOLD"

async def analisar_todas(bot):
    for cripto in CRIPTO_LISTA:
        df = obter_dados_criptomoeda(cripto)
        if df is None or df.empty:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Dados insuficientes para {cripto}.")
            continue

        preco_atual = df['price'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        sugestao = sugestao_rsi(rsi)
        grafico = gerar_grafico(df, cripto)

        texto = (
            f"📊 Análise de {cripto.capitalize()}\n"
            f"💰 Preço atual: ${preco_atual:,.2f}\n"
            f"📈 RSI: {rsi:.2f}\n"
            f"💡 Sugestão: {sugestao}\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )

        await bot.send_photo(chat_id=CHAT_ID, photo=open(grafico, 'rb'), caption=texto)

# --- Menu e Comandos ---
CRIPTO_TEMP = set(CRIPTO_LISTA)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot ativo. Use /menu para opções.")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    botoes = [
        [InlineKeyboardButton("📊 Analisar agora", callback_data='analisar')],
        [InlineKeyboardButton("➕ Adicionar cripto", callback_data='adicionar')],
        [InlineKeyboardButton("➖ Remover cripto", callback_data='remover')],
    ]
    await update.message.reply_text("📋 Menu de opções:", reply_markup=InlineKeyboardMarkup(botoes))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'analisar':
        await query.edit_message_text("⏳ Analisando...")
        await analisar_todas(context.bot)

    elif query.data == 'adicionar':
        await query.edit_message_text("Envie o nome da criptomoeda para adicionar (ex: cardano):")
        context.user_data['acao'] = 'add'

    elif query.data == 'remover':
        await query.edit_message_text("Envie o nome da criptomoeda para remover:")
        context.user_data['acao'] = 'remove'

async def texto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip().lower()
    acao = context.user_data.get('acao')

    if acao == 'add':
        if texto not in CRIPTO_TEMP:
            CRIPTO_TEMP.add(texto)
            await update.message.reply_text(f"✅ {texto} adicionado à lista de análise.")
        else:
            await update.message.reply_text("⚠️ Criptomoeda já está na lista.")
    elif acao == 'remove':
        if texto in CRIPTO_TEMP:
            CRIPTO_TEMP.remove(texto)
            await update.message.reply_text(f"✅ {texto} removido da lista.")
        else:
            await update.message.reply_text("⚠️ Criptomoeda não encontrada na lista.")
    else:
        await update.message.reply_text("⚠️ Use /menu para selecionar uma ação antes de digitar.")

    context.user_data['acao'] = None

# --- Loop de análise ---
async def loop_analise(app):
    while True:
        await analisar_todas(app.bot)
        await asyncio.sleep(1800)  # 30 minutos

async def on_startup(app):
    app.create_task(loop_analise(app))

# --- Inicialização do Bot ---
app = (
    Application.builder()
    .token(TOKEN)
    .post_init(on_startup)
    .build()
)

app.add_handler(CommandHandler('start', start))
app.add_handler(CommandHandler('menu', menu))
app.add_handler(CallbackQueryHandler(callback_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_handler))

app.run_polling()

