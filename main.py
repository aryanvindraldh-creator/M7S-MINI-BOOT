import os
import time
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# 🔑 PUT YOUR REAL BOT TOKEN HERE
BOT_TOKEN = "8443070084:AAH78ZonMHZmFFfmSBk9IeiNKyGm1RAsp00"

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ───────── START ─────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    keyboard = [
        ["📤 Upload File", "📂 Check Files"],
        ["⚡ Bot Speed", "📊 Statistics"],
        ["📞 Contact Owner"]
    ]

    await update.message.reply_text(
        f"""
⚡ Welcome to Hosting Bot!

🆔 User ID: {user.id}
👤 Username: @{user.username}
⭐ Status: Free User
📁 Max Files: 3

👇 Use buttons below
""",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

# ───────── UPLOAD BUTTON ─────────
async def upload_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📤 Send your Python (.py), JS (.js), or ZIP (.zip) file."
    )

# ───────── FILE HANDLER ─────────
async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_folder = os.path.join(UPLOAD_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    document = update.message.document
    file_path = os.path.join(user_folder, document.file_name)

    await document.get_file().download_to_drive(file_path)
    await update.message.reply_text("✅ File uploaded successfully!")

# ───────── CHECK FILES ─────────
async def check_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_folder = os.path.join(UPLOAD_DIR, str(user_id))

    if not os.path.exists(user_folder) or not os.listdir(user_folder):
        await update.message.reply_text("📂 No files uploaded yet.")
        return

    files = "\n".join(os.listdir(user_folder))
    await update.message.reply_text(f"📂 Your Files:\n\n{files}")

# ───────── BOT SPEED ─────────
async def bot_speed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    msg = await update.message.reply_text("⚡ Testing speed...")
    end_time = time.time()

    await msg.edit_text(
        f"""
⚡ Bot Speed & Status

⏱ API Response Time: {round((end_time - start_time)*1000, 2)} ms
🔓 Bot Status: Online
"""
    )

# ───────── STATISTICS ─────────
async def statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        """
📊 Bot Statistics

👥 Total Users: 1
📂 Total Files: 0
🟢 Active Bots: 0
"""
    )

# ───────── MAIN ─────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("Upload File"), upload_button))
    app.add_handler(MessageHandler(filters.Regex("Check Files"), check_files))
    app.add_handler(MessageHandler(filters.Regex("Bot Speed"), bot_speed))
    app.add_handler(MessageHandler(filters.Regex("Statistics"), statistics))
    app.add_handler(MessageHandler(filters.Document.ALL, file_handler))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
