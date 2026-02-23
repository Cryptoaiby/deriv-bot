import asyncio
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# ----------------------------
# Conversation states
# ----------------------------
INSTRUMENT, CONDITION, PRICE = range(3)
DELETE_SELECT = range(1)

# ----------------------------
# Supabase PostgreSQL connection
# ----------------------------
DB_HOST = "aws-1-eu-west-2.pooler.supabase.com"
DB_NAME = "postgres"
DB_USER = "postgres.maplplayraamuqnoicqn"
DB_PASS = "Iwipntakgrace"
DB_PORT = 6543

conn = psycopg2.connect(
    host=DB_HOST,
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASS,
    port=DB_PORT,
    sslmode="require"
)
cursor = conn.cursor(cursor_factory=RealDictCursor)

# Create table if not exists
cursor.execute("""
CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    instrument TEXT NOT NULL,
    condition TEXT NOT NULL,
    price NUMERIC NOT NULL,
    triggered BOOLEAN DEFAULT FALSE
);
""")
conn.commit()

# ----------------------------
# Set Alert Conversation
# ----------------------------
async def start_setalert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 Which Deriv synthetic index do you want to track? (e.g., Volatility 100)"
    )
    return INSTRUMENT

async def instrument(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["instrument"] = update.message.text
    await update.message.reply_text(
        "Do you want the alert when the price goes 'above' or 'below'?"
    )
    return CONDITION

async def condition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["condition"] = update.message.text.lower()
    await update.message.reply_text("Enter the price level for the alert:")
    return PRICE

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    instrument = context.user_data["instrument"]
    condition_val = context.user_data["condition"]
    try:
        price_val = float(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number for the price.")
        return PRICE

    cursor.execute(
        "INSERT INTO alerts (user_id, instrument, condition, price) VALUES (%s, %s, %s, %s)",
        (user_id, instrument, condition_val, price_val)
    )
    conn.commit()

    await update.message.reply_text(
        f"✅ Alert set for {instrument} when price is {condition_val} {price_val}"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Alert setup cancelled.")
    return ConversationHandler.END

# ----------------------------
# View Alerts
# ----------------------------
async def myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute(
        "SELECT id, instrument, condition, price FROM alerts WHERE user_id=%s AND triggered=false",
        (user_id,)
    )
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("You have no active alerts.")
        return
    msg = "📋 Your active alerts:\n"
    for row in rows:
        msg += f"{row['id']}. {row['instrument']} {row['condition']} {row['price']}\n"
    await update.message.reply_text(msg)

# ----------------------------
# Delete Alert
# ----------------------------
async def deletealert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute(
        "SELECT id, instrument, condition, price FROM alerts WHERE user_id=%s AND triggered=false",
        (user_id,)
    )
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("You have no alerts to delete.")
        return ConversationHandler.END

    msg = "Select the alert number to delete:\n"
    for row in rows:
        msg += f"{row['id']}. {row['instrument']} {row['condition']} {row['price']}\n"
    await update.message.reply_text(msg)
    return DELETE_SELECT

async def delete_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        alert_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid alert number.")
        return DELETE_SELECT

    cursor.execute(
        "SELECT id FROM alerts WHERE id=%s AND user_id=%s AND triggered=false",
        (alert_id, user_id)
    )
    if cursor.fetchone() is None:
        await update.message.reply_text("❌ Alert not found.")
        return DELETE_SELECT

    cursor.execute(
        "DELETE FROM alerts WHERE id=%s AND user_id=%s",
        (alert_id, user_id)
    )
    conn.commit()
    await update.message.reply_text(f"✅ Alert {alert_id} deleted.")
    return ConversationHandler.END

# ----------------------------
# Fetch Deriv Synthetic Index Price
# ----------------------------
def get_deriv_price(instrument):
    try:
        resp = requests.get(f"https://frontend.deriv.com/api/ticks?symbol={instrument}")
        data = resp.json()
        price = float(data["tick"]["quote"])
        return price
    except Exception as e:
        print("Error fetching price for", instrument, e)
        return None

# ----------------------------
# Background Price Checker
# ----------------------------
async def price_checker(app):
    while True:
        try:
            cursor.execute("SELECT * FROM alerts WHERE triggered=false")
            alerts = cursor.fetchall()
            if not alerts:
                await asyncio.sleep(5)
                continue

            instruments = set(alert['instrument'] for alert in alerts)
            latest_prices = {}
            for instr in instruments:
                price = get_deriv_price(instr)
                if price is not None:
                    latest_prices[instr] = price

            for alert in alerts:
                current_price = latest_prices.get(alert['instrument'])
                if current_price is None:
                    continue
                triggered = False
                if alert['condition'] == 'above' and current_price >= alert['price']:
                    triggered = True
                elif alert['condition'] == 'below' and current_price <= alert['price']:
                    triggered = True

                if triggered:
                    try:
                        await app.bot.send_message(
                            chat_id=alert['user_id'],
                            text=f"⚡ Alert! {alert['instrument']} is {alert['condition']} {alert['price']}\nCurrent price: {current_price}"
                        )
                    except Exception as e:
                        print("Failed to send message:", e)

                    cursor.execute(
                        "UPDATE alerts SET triggered=true WHERE id=%s",
                        (alert['id'],)
                    )
                    conn.commit()

            await asyncio.sleep(5)
        except Exception as e:
            print("Error in price_checker:", e)
            await asyncio.sleep(5)

# ----------------------------
# Main
# ----------------------------
def main():
    bot_token = "7396670450:AAGG8qCuc5PH9ZXsMg_sMySddFuHnq8eCQQ"
    app = ApplicationBuilder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("setalert", start_setalert)],
        states={
            INSTRUMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, instrument)],
            CONDITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, condition)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    delete_conv = ConversationHandler(
        entry_points=[CommandHandler("deletealert", deletealert)],
        states={
            DELETE_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_selected)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(delete_conv)

    app.add_handler(CommandHandler("myalerts", myalerts))

    app.job_queue.run_repeating(lambda ctx: asyncio.create_task(price_checker(app)), interval=1, first=1)

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

