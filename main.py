import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

BOT_TOKEN = "8443070084:AAH78ZonMHZmFFfmSBk9IeiNKyGm1RAsp00"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

def start(update: Update, context: CallbackContext):
    update.message.reply_text("✅ Bot is running successfully!")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))

    print("🤖 Bot started successfully")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
