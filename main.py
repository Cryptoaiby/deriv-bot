import os
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, ConversationHandler, MessageHandler, Filters

# -------------------------
# Environment variables
# -------------------------
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME")
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")
DB_PORT = int(os.environ.get("DB_PORT", 5432))

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# -------------------------
# Database setup
# -------------------------
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT,
        cursor_factory=RealDictCursor
    )

# -------------------------
# Conversation states
# -------------------------
SET_ALERT_PRICE = 1

# -------------------------
# /setalert command
# -------------------------
def start_setalert(update: Update, context: CallbackContext):
    update.message.reply_text("Enter the synthetic index symbol (e.g., 'Volatility 100 Index'):")
    return SET_ALERT_PRICE

def receive_alert_symbol(update: Update, context: CallbackContext):
    context.user_data['symbol'] = update.message.text
    update.message.reply_text("Enter the price to be alerted at (e.g., 10500):")
    return SET_ALERT_PRICE + 1

def receive_alert_price(update: Update, context: CallbackContext):
    price = update.message.text
    symbol = context.user_data.get('symbol')

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO alerts (user_id, symbol, price) VALUES (%s, %s, %s)",
            (update.effective_user.id, symbol, price)
        )
        conn.commit()
        cur.close()
        conn.close()
        update.message.reply_text(f"✅ Alert set for {symbol} at price {price}.")
    except Exception as e:
        update.message.reply_text(f"❌ Error saving alert: {e}")

    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# -------------------------
# /myalerts command
# -------------------------
def myalerts(update: Update, context: CallbackContext):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT symbol, price FROM alerts WHERE user_id = %s", (update.effective_user.id,))
        alerts = cur.fetchall()
        cur.close()
        conn.close()

        if alerts:
            msg = "📌 Your active alerts:\n" + "\n".join([f"{a['symbol']} at {a['price']}" for a in alerts])
        else:
            msg = "You have no active alerts."
        update.message.reply_text(msg)
    except Exception as e:
        update.message.reply_text(f"❌ Error retrieving alerts: {e}")

# -------------------------
# /deletealert command
# -------------------------
def deletealert(update: Update, context: CallbackContext):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM alerts WHERE user_id = %s", (update.effective_user.id,))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()

        update.message.reply_text(f"🗑️ Deleted {deleted} alert(s).")
    except Exception as e:
        update.message.reply_text(f"❌ Error deleting alerts: {e}")

# -------------------------
# Main function
# -------------------------
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Conversation handler for /setalert
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('setalert', start_setalert)],
        states={
            SET_ALERT_PRICE: [MessageHandler(Filters.text & ~Filters.command, receive_alert_symbol)],
            SET_ALERT_PRICE + 1: [MessageHandler(Filters.text & ~Filters.command, receive_alert_price)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    dp.add_handler(conv_handler)
    dp.add_handler(CommandHandler('myalerts', myalerts))
    dp.add_handler(CommandHandler('deletealert', deletealert))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()