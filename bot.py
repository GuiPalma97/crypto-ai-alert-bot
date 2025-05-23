import os
import asyncio
import logging
import matplotlib.pyplot as plt
import pandas as pd
import ta
from ta.momentum import RSIIndicator
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, filters
from kucoin.client import Market
from datetime import datetime

# Configurações iniciais
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CRIPTO_LISTA = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AAVE-USDT']
INTERVALO = '1hour'
analise_ativa = False

logging.basicConfig(level=logging.INFO)

client = Market()

# Função para obter dados da KuCoin
from kucoin.client import Market

# --- Inicializar o cliente de mercado KuCoin ---
kucoin_client = Market()

# --- Coletar dados com o SDK da KuCoin ---
def obter_dados_kucoin(par, intervalo='1hour'):
    intervalo_map = {
        '1min': '1min',
        '5min': '5min',
        '1hour': '1hour',
        '1day': '1day',
        '1week': '1week',
    }

    if intervalo not in intervalo_map:
        intervalo = '1hour'

    try:
        candles = kucoin_client.get_kline(symbol=par, kline_type=intervalo_map[intervalo])

        if not candles:
            print(f"Nenhum dado de candle retornado para {par}")
            return None

        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
        df = df.sort_values('timestamp')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('timestamp', inplace=True)
        df = df.astype(float)

        df['RSI'] = RSIIndicator(df['close']).rsi()
        bb = BollingerBands(close=df['close'])
        df['Upper'] = bb.bollinger_hband()
        df['Lower'] = bb.bollinger_lband()

        return df.dropna()

    except Exception as e:
        print(f"Erro ao obter dados da KuCoin para {par}: {e}")
        return None
# Função para gerar gráfico e RSI
def gerar_grafico(df, par):
    rsi = RSIIndicator(df["close"])
    df["RSI"] = rsi.rsi()

    plt.figure(figsize=(10, 6))
    plt.subplot(2, 1, 1)
    plt.plot(df["close"], label="Preço")
    plt.title(f"{par} Preço")
    plt.grid()

    plt.subplot(2, 1, 2)
    plt.plot(df["RSI"], label="RSI", color="orange")
    plt.axhline(70, color='red', linestyle='--')
    plt.axhline(30, color='green', linestyle='--')
    plt.title("RSI")
    plt.grid()

    plt.tight_layout()
    filepath = f"{par.replace('-', '')}.png"
    plt.savefig(filepath)
    plt.close()
    return filepath, df["RSI"].iloc[-1]

# Envia análises
async def analisar_todas(bot):
    for par in CRIPTO_LISTA:
        df = obter_dados_kucoin(par, '1hour')
        if df is not None and not df.empty:
            imagem, rsi = gerar_grafico(df, par)

            # Análise semanal para sugestão IA
            df_semanal = obter_dados_kucoin(par, '1week')
            if df_semanal is not None and not df_semanal.empty:
                rsi_sem = RSIIndicator(df_semanal['close']).rsi().iloc[-1]
                sugestao = (
                    "🤖 SUGESTÃO IA: 🟢 COMPRAR (RSI semanal baixo)" if rsi_sem < 30 else
                    "🤖 SUGESTÃO IA: 🔴 VENDER (RSI semanal alto)" if rsi_sem > 70 else
                    "🤖 SUGESTÃO IA: ⚪ MANTER (RSI semanal neutro)"
                )
            else:
                sugestao = "🤖 SUGESTÃO IA: RSI semanal indisponível"

            mensagem = f"📊 Análise {par}\nRSI: {rsi:.2f}\n{sugestao}"
            await bot.send_photo(chat_id=os.getenv("TELEGRAM_CHAT_ID"), photo=open(imagem, "rb"), caption=mensagem)

# Loop de análise automática
async def loop_analise(application):
    global analise_ativa
    while True:
        if analise_ativa:
            await analisar_todas(application.bot)
        await asyncio.sleep(3600)  # 1 hora

# Comando /start
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("🤖 Bot de Análise de Criptomoedas Ativado. Use /menu para ver opções.")

# Comando /menu
async def menu(update: Update, context: CallbackContext):
    botoes = [
        [InlineKeyboardButton("✅ Iniciar Análises", callback_data='start')],
        [InlineKeyboardButton("🛑 Parar Análises", callback_data='stop')],
        [InlineKeyboardButton("📊 Análise Agora", callback_data='agora')],
        [InlineKeyboardButton("➕ Adicionar Cripto", callback_data='add')],
        [InlineKeyboardButton("➖ Remover Cripto", callback_data='remove')],
    ]
    await update.message.reply_text("📍 Menu de Comandos:", reply_markup=InlineKeyboardMarkup(botoes))

# Callback interativo
def callback_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.data == 'start':
        global analise_ativa
        analise_ativa = True
        query.edit_message_text("✅ Análises ativadas.")
    elif query.data == 'stop':
        analise_ativa = False
        query.edit_message_text("🛑 Análises pausadas.")
    elif query.data == 'agora':
        query.edit_message_text("⏳ Gerando análise...")
        asyncio.create_task(analisar_todas(context.bot))
    elif query.data == 'add':
        context.bot.send_message(chat_id=query.message.chat_id, text="Digite o símbolo da cripto para adicionar (ex: XRP-USDT):")
        context.user_data['modo'] = 'adicionar'
    elif query.data == 'remove':
        context.bot.send_message(chat_id=query.message.chat_id, text="Digite o símbolo da cripto para remover (ex: ETH-USDT):")
        context.user_data['modo'] = 'remover'

# Texto após /add ou /remove
def mensagem_texto(update: Update, context: CallbackContext):
    texto = update.message.text.upper()
    if 'modo' in context.user_data:
        if context.user_data['modo'] == 'adicionar':
            if texto not in CRIPTO_LISTA:
                CRIPTO_LISTA.append(texto)
                update.message.reply_text(f"✅ {texto} adicionado à lista.")
            else:
                update.message.reply_text(f"⚠️ {texto} já está na lista.")
        elif context.user_data['modo'] == 'remover':
            if texto in CRIPTO_LISTA:
                CRIPTO_LISTA.remove(texto)
                update.message.reply_text(f"❌ {texto} removido da lista.")
            else:
                update.message.reply_text(f"⚠️ {texto} não encontrado na lista.")
        del context.user_data['modo']
    else:
        update.message.reply_text("❓ Comando não reconhecido. Use /menu.")

# Inicialização
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensagem_texto))

    app.create_task(loop_analise(app))
    app.run_polling()
