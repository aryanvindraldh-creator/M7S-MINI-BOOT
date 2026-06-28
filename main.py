# -*- coding: utf-8 -*-
import telebot
from telebot import types
import subprocess
import os
import zipfile
import tempfile
import shutil
import time
from datetime import datetime, timedelta
import psutil
import json
import logging
import signal
import threading
import re
import sys
import atexit
import requests
import hashlib
from flask import Flask
from threading import Thread

# Import local modules
from config import *
from database import db

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "master_hosting.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MasterHosting")

# --- FLASK KEEP ALIVE (DAEMON) ---
app = Flask(__name__)
@app.route('/')
def home():
    return "🚀 MASTER HOSTING ENTERPRISE SERVER IS RUNNING"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    logger.info("Flask Keep-Alive server started.")

# --- INITIALIZE TELEGRAM BOT ---
bot = telebot.TeleBot(TOKEN, parse_mode='Markdown')
bot_locked = False

# --- PROCESS MANAGER DICTIONARY ---
# Structure: { "user_id_filename": {"process": Popen_obj, "log_file": File_obj, "start_time": datetime, "pid": int, "type": str} }
active_processes = {}
process_lock = threading.Lock()

# --- SECURITY SCANNER ---
def hash_file(filepath):
    """Generate SHA-256 hash of a file for malware detection."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def scan_script_security(filepath):
    """Scan code for dangerous and destructive commands."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        found_patterns = []
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                found_patterns.append(pattern)
        
        if found_patterns:
            logger.warning(f"Security Alert in {filepath}: {found_patterns}")
            return False, f"Dangerous patterns detected: {', '.join(found_patterns[:3])}"
        return True, "Safe"
    except Exception as e:
        logger.error(f"Scanner error: {e}")
        return False, "Scanner encountered an error."

def scan_zip_security(zip_path):
    """Scan all files inside a ZIP archive."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                if any(file_info.filename.endswith(ext) for ext in BLOCKED_EXTENSIONS):
                    return False, f"Blocked file extension found: {file_info.filename}"
                
                if file_info.filename.endswith(('.py', '.js', '.txt', '.json')):
                    with zip_ref.open(file_info.filename) as f:
                        content = f.read().decode('utf-8', errors='ignore')
                        for pattern in DANGEROUS_PATTERNS:
                            if re.search(pattern, content, re.IGNORECASE):
                                return False, f"Dangerous pattern in archived file {file_info.filename}"
        return True, "Safe"
    except Exception as e:
        return False, f"Archive read error: {str(e)}"

# --- DEPENDENCY INSTALLERS ---
def install_python_deps(req_path, message):
    """Install requirements.txt dependencies."""
    bot.reply_to(message, "🔄 Installing Python dependencies from `requirements.txt`...")
    try:
        command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        bot.reply_to(message, "✅ Python dependencies installed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        bot.reply_to(message, f"❌ Dependency Installation Failed.\n```\n{e.stderr[-500:]}\n```")
        return False

def install_node_deps(pkg_path, message, user_folder):
    """Install package.json dependencies."""
    bot.reply_to(message, "🔄 Installing Node.js dependencies from `package.json`...")
    try:
        command = ['npm', 'install']
        result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=user_folder)
        bot.reply_to(message, "✅ Node.js dependencies installed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        bot.reply_to(message, f"❌ NPM Installation Failed.\n```\n{e.stderr[-500:]}\n```")
        return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ `npm` is not installed on the host server.")
        return False

# --- ADVANCED PROCESS MANAGER ---
def get_user_folder(user_id):
    path = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

def kill_process_tree(pid):
    """Strictly kill a process and all child processes to prevent memory leaks."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=3)
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        logger.error(f"Error killing process tree for PID {pid}: {e}")

def run_script(user_id, file_name, file_type, message=None):
    """Start a user's bot securely and track it."""
    process_key = f"{user_id}_{file_name}"
    user_folder = get_user_folder(user_id)
    file_path = os.path.join(user_folder, file_name)
    log_path = os.path.join(user_folder, f"{file_name}.log")

    if not os.path.exists(file_path):
        if message: bot.send_message(user_id, f"❌ File `{file_name}` not found. Please re-upload.")
        return False

    with process_lock:
        if process_key in active_processes:
            if message: bot.send_message(user_id, f"⚠️ Script `{file_name}` is already running.")
            return False

        try:
            log_file = open(log_path, 'a', encoding='utf-8')
            if file_type == 'py':
                cmd = [sys.executable, file_path]
            elif file_type == 'js':
                cmd = ['node', file_path]
            else:
                return False

            process = subprocess.Popen(
                cmd,
                cwd=user_folder,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.PIPE,
                text=True
            )

            active_processes[process_key] = {
                "process": process,
                "log_file": log_file,
                "pid": process.pid,
                "start_time": datetime.now(),
                "type": file_type
            }

            db.update_bot_status(user_id, file_name, "running")
            if message: bot.send_message(user_id, f"✅ `{file_name}` started successfully. (PID: {process.pid})")
            logger.info(f"Started {process_key} (PID: {process.pid})")
            return True

        except Exception as e:
            logger.error(f"Failed to start {process_key}: {e}")
            if message: bot.send_message(user_id, f"❌ Failed to start script: {str(e)}")
            return False

def stop_script(user_id, file_name, message=None):
    """Stop a running script safely."""
    process_key = f"{user_id}_{file_name}"
    with process_lock:
        if process_key in active_processes:
            proc_info = active_processes[process_key]
            kill_process_tree(proc_info['pid'])
            try:
                proc_info['log_file'].close()
            except:
                pass
            del active_processes[process_key]
            db.update_bot_status(user_id, file_name, "stopped")
            if message: bot.send_message(user_id, f"🔴 `{file_name}` has been stopped.")
            logger.info(f"Stopped {process_key}")
            return True
        else:
            db.update_bot_status(user_id, file_name, "stopped")
            if message: bot.send_message(user_id, f"⚠️ `{file_name}` is not currently running.")
            return False

# --- BACKGROUND AUTOMATION DAEMONS ---
def resource_monitor_daemon():
    """Monitors CPU and RAM usage of user scripts against their plan limits."""
    logger.info("Resource Monitor Daemon Started.")
    while True:
        try:
            with process_lock:
                keys = list(active_processes.keys())
            
            for key in keys:
                user_id_str, file_name = key.split('_', 1)
                user_id = int(user_id_str)
                
                # Fetch Plan Limits
                plan = db.get_user_subscription(user_id)
                if not plan:
                    continue # Free tier fallback handled during checks
                
                ram_limit_mb = plan.get('ram_limit', 100)
                cpu_limit_percent = plan.get('cpu_limit', 20)

                proc_info = active_processes.get(key)
                if not proc_info: continue
                
                pid = proc_info['pid']
                try:
                    p = psutil.Process(pid)
                    if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                        continue
                        
                    mem_usage_mb = p.memory_info().rss / (1024 * 1024)
                    cpu_usage = p.cpu_percent(interval=0.1)

                    if mem_usage_mb > ram_limit_mb:
                        logger.warning(f"Killing {key}: RAM Exceeded ({mem_usage_mb:.1f}MB > {ram_limit_mb}MB)")
                        stop_script(user_id, file_name)
                        bot.send_message(user_id, f"🚨 **RESOURCE LIMIT EXCEEDED**\nYour script `{file_name}` used {mem_usage_mb:.1f}MB RAM (Limit: {ram_limit_mb}MB) and was forcefully stopped.\nUpgrade your plan to get more resources.")
                        
                except psutil.NoSuchProcess:
                    pass
        except Exception as e:
            logger.error(f"Resource monitor error: {e}")
            
        time.sleep(15)

def crash_recovery_daemon():
    """Detects crashed bots and auto-restarts them if enabled."""
    logger.info("Crash Recovery Daemon Started.")
    while True:
        try:
            with process_lock:
                keys = list(active_processes.keys())
                for key in keys:
                    proc_info = active_processes[key]
                    p = proc_info['process']
                    if p.poll() is not None:
                        # Process died
                        user_id_str, file_name = key.split('_', 1)
                        user_id = int(user_id_str)
                        
                        try:
                            proc_info['log_file'].close()
                        except: pass
                        del active_processes[key]
                        
                        bots = db.get_user_bots(user_id)
                        bot_data = next((b for b in bots if b[0] == file_name), None)
                        
                        if bot_data and bot_data[3] == 1: # auto_restart == 1
                            db.increment_crash_count(user_id, file_name)
                            logger.info(f"Auto-recovering {key}...")
                            bot.send_message(user_id, f"⚠️ Your bot `{file_name}` crashed. Auto-Restarting...")
                            run_script(user_id, file_name, proc_info['type'])
                        else:
                            db.update_bot_status(user_id, file_name, "stopped")
                            bot.send_message(user_id, f"🔴 Your bot `{file_name}` has stopped unexpectedly. Check logs.")
        except Exception as e:
            logger.error(f"Crash recovery error: {e}")
        time.sleep(5)

def subscription_expiry_daemon():
    """Checks for expired subscriptions and stops bots."""
    logger.info("Subscription Expiry Daemon Started.")
    while True:
        try:
            conn = db._get_conn()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("SELECT user_id, plan_id FROM subscriptions WHERE status = 'active' AND expiry < ?", (now,))
            expired_subs = c.fetchall()
            
            for uid, pid in expired_subs:
                c.execute("UPDATE subscriptions SET status = 'expired' WHERE user_id = ? AND plan_id = ?", (uid, pid))
                bot.send_message(uid, "⚠️ **SUBSCRIPTION EXPIRED**\nYour active plan has expired. Your bots are being stopped. Please renew your plan.")
                
                # Stop all running bots for user
                with process_lock:
                    user_keys = [k for k in active_processes.keys() if k.startswith(f"{uid}_")]
                    for k in user_keys:
                        _, fname = k.split('_', 1)
                        stop_script(uid, fname)
                        
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Expiry daemon error: {e}")
        time.sleep(3600) # Run every hour

# --- PAYMENT INTEGRATIONS (DUAL GATEWAYS) ---
def create_zapupi_invoice(user_id, amount, plan_id):
    """Simulates Zapupi Gateway API creation."""
    # In a real scenario, this makes a POST request to Zapupi API
    txid = f"ZAP_{int(time.time())}_{user_id}"
    payment_url = f"https://zapupi.com/pay/{txid}?amount={amount}"
    
    conn = db._get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO payments (user_id, gateway, amount, currency, status, txid, created_at) VALUES (?, 'Zapupi', ?, 'USD', 'pending', ?, ?)", 
              (user_id, amount, txid, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    return payment_url, txid

def create_binance_invoice(user_id, amount, plan_id):
    """Simulates Binance Pay API creation."""
    txid = f"BIN_{int(time.time())}_{user_id}"
    payment_url = f"https://pay.binance.com/checkout/{txid}"
    
    conn = db._get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO payments (user_id, gateway, amount, currency, status, txid, created_at) VALUES (?, 'Binance', ?, 'USDT', 'pending', ?, ?)", 
              (user_id, amount, txid, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    return payment_url, txid

def verify_payment_status(txid):
    """Simulates checking payment status from gateway."""
    # Simulating a successful payment verification
    conn = db._get_conn()
    c = conn.cursor()
    c.execute("SELECT status, user_id FROM payments WHERE txid = ?", (txid,))
    res = c.fetchone()
    
    if res and res[0] == 'pending':
        # Simulate gateway success logic here (In production, replace with actual requests.get())
        c.execute("UPDATE payments SET status = 'completed' WHERE txid = ?", (txid,))
        conn.commit()
        conn.close()
        return True, res[1]
    
    conn.close()
    return False, None

# --- MIDDLEWARE DEFINITIONS ---
def check_mandatory_channels(user_id):
    """Checks if the user has joined all required channels."""
    channels = db.get_mandatory_channels()
    if not channels:
        return True, []
    
    not_joined = []
    for ch in channels:
        try:
            member = bot.get_chat_member(ch['id'], user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                not_joined.append(ch)
        except:
            not_joined.append(ch)
            
    return len(not_joined) == 0, not_joined

def get_mandatory_channel_markup(not_joined):
    """Generates inline keyboard for missing channels."""
    markup = types.InlineKeyboardMarkup()
    for ch in not_joined:
        url = f"https://t.me/{ch['username'].replace('@', '')}" if ch['username'] else f"https://t.me/c/{ch['id'].replace('-100', '')}"
        markup.add(types.InlineKeyboardButton(f"📢 Join {ch['name']}", url=url))
    markup.add(types.InlineKeyboardButton("✅ I Have Joined", callback_data="verify_channels"))
    return markup

# --- UI BUILDERS (KEYBOARDS) ---
def get_main_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🖥️ Dashboard", callback_data="open_dashboard"),
        types.InlineKeyboardButton("📂 File Manager", callback_data="open_file_manager")
    )
    markup.add(
        types.InlineKeyboardButton("🛒 Store (Buy Plans)", callback_data="open_store"),
        types.InlineKeyboardButton("🎁 Redeem Code", callback_data="open_redeem")
    )
    markup.add(
        types.InlineKeyboardButton("👥 Referral System", callback_data="open_referral"),
        types.InlineKeyboardButton("🎫 Support Tickets", callback_data="open_tickets")
    )
    
    admin_list = db.get_admins()
    if user_id in admin_list or user_id == OWNER_ID:
        markup.add(types.InlineKeyboardButton("⚙️ Advanced Admin Panel ⚙️", callback_data="open_admin_panel"))
        
    markup.add(types.InlineKeyboardButton("📢 Updates Channel", url=f"https://t.me/{UPDATE_CHANNEL.replace('@', '')}"))
    return markup

# CONTINUATION OF FILE IN NEXT BLOCK...
# --- DASHBOARD & UI HELPERS ---
def get_dashboard_text(user_id):
    user_data = db.get_user(user_id)
    sub_data = db.get_user_subscription(user_id)
    user_bots = db.get_user_bots(user_id)
    
    if not user_data:
        return "❌ User data not found. Please /start again."

    coins = user_data.get('coins', 0)
    badges = user_data.get('badges', '')
    
    running_bots = sum(1 for b in user_bots if b[2] == 'running')
    total_bots = len(user_bots)
    
    if sub_data:
        plan_name = sub_data['plan_name']
        slots = sub_data['bot_slots']
        ram_limit = sub_data['ram_limit']
        cpu_limit = sub_data['cpu_limit']
        storage_limit = sub_data['storage_limit']
        days_left = (sub_data['expiry'] - datetime.now()).days
    else:
        # Free Tier Fallback
        plan_name = "Free Tier"
        slots = 1
        ram_limit = 100
        cpu_limit = 20
        storage_limit = 50
        days_left = "Lifetime (Free)"

    # Server Stats
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent
    uptime_seconds = time.time() - psutil.boot_time()
    uptime_string = str(timedelta(seconds=int(uptime_seconds)))

    text = f"🖥️ **MASTER HOSTING DASHBOARD** 🖥️\n\n"
    text += f"👤 **User ID:** `{user_id}` {badges}\n"
    text += f"🪙 **Master Coins:** `{coins}`\n"
    text += f"📦 **Active Plan:** `{plan_name}`\n"
    text += f"⏳ **Days Remaining:** `{days_left}`\n\n"
    
    text += f"🤖 **Bot Slots:** `{total_bots}/{slots}`\n"
    text += f"🟢 **Running Bots:** `{running_bots}`\n\n"
    
    text += f"📊 **Resource Limits:**\n"
    text += f"   RAM: `{ram_limit} MB`\n"
    text += f"   CPU: `{cpu_limit}%`\n"
    text += f"   Storage: `{storage_limit} MB`\n\n"
    
    text += f"🌐 **Server Status:**\n"
    text += f"   Uptime: `{uptime_string}`\n"
    text += f"   Global CPU: `{cpu_usage}%`\n"
    text += f"   Global RAM: `{ram_usage}%`\n"
    
    return text

def get_file_manager_markup(user_id):
    user_bots = db.get_user_bots(user_id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if not user_bots:
        markup.add(types.InlineKeyboardButton("📤 Upload New Bot (.py, .js, .zip)", callback_data="upload_instructions"))
    else:
        for bot_data in user_bots:
            file_name, file_type, status, auto_restart, _ = bot_data
            status_emoji = "🟢" if status == "running" else "🔴"
            auto_emoji = "🔄" if auto_restart else ""
            markup.add(types.InlineKeyboardButton(f"{status_emoji} {file_name} {auto_emoji}", callback_data=f"manage_bot_{file_name}"))
            
    markup.add(types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="open_dashboard"))
    return markup

def get_bot_control_markup(user_id, file_name):
    bots = db.get_user_bots(user_id)
    bot_data = next((b for b in bots if b[0] == file_name), None)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    if not bot_data:
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="open_file_manager"))
        return markup
        
    status = bot_data[2]
    auto_restart = bot_data[3]
    
    if status == "running":
        markup.add(
            types.InlineKeyboardButton("🔴 Stop", callback_data=f"stop_bot_{file_name}"),
            types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_bot_{file_name}")
        )
    else:
        markup.add(
            types.InlineKeyboardButton("🟢 Start", callback_data=f"start_bot_{file_name}"),
        )
        
    ar_text = "🔕 Disable Auto-Restart" if auto_restart else "🔔 Enable Auto-Restart"
    markup.add(types.InlineKeyboardButton(ar_text, callback_data=f"toggle_ar_{file_name}"))
    
    markup.add(
        types.InlineKeyboardButton("📜 View Logs", callback_data=f"view_logs_{file_name}"),
        types.InlineKeyboardButton("🗑️ Delete Bot", callback_data=f"delete_bot_{file_name}")
    )
    markup.add(types.InlineKeyboardButton("🔙 Back to Files", callback_data="open_file_manager"))
    return markup

# --- CORE COMMANDS ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if db.is_banned(user_id):
        bot.reply_to(message, "🚫 You have been banned from Master Hosting Enterprise.")
        return

    # Check Mandatory Channels
    is_joined, not_joined = check_mandatory_channels(user_id)
    if not is_joined and user_id not in db.get_admins() and user_id != OWNER_ID:
        markup = get_mandatory_channel_markup(not_joined)
        bot.send_message(user_id, "⚠️ **Action Required**\nYou must join our official channels to use this enterprise bot.", reply_markup=markup)
        return

    # Referral Check
    referrer_id = None
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('ref_'):
        try:
            ref = int(args[1].replace('ref_', ''))
            if ref != user_id:
                referrer_id = ref
                # Reward referrer logic handled inside DB or trigger here
                db.update_coins(ref, 50)
                try: bot.send_message(ref, f"🎉 You earned 50 Coins! New user joined via your referral link.")
                except: pass
        except: pass

    db.add_user(user_id, referrer_id)
    db.update_last_seen(user_id)

    welcome_text = (
        f"👋 **Welcome to MASTER HOSTING ENTERPRISE 2026**\n\n"
        f"The most advanced Telegram bot hosting platform.\n"
        f"Deploy Python and Node.js bots instantly.\n\n"
        f"Use the menu below to navigate."
    )
    bot.send_message(user_id, welcome_text, reply_markup=get_main_menu(user_id))

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
📚 **Master Hosting Knowledge Base**

**Commands:**
/start - Open Main Menu
/dashboard - View Server & Resource Stats
/files - Manage Your Bots

**Supported Formats:**
• Single `.py` or `.js` scripts.
• `.zip` archives containing multiple files.
• Auto-installs `requirements.txt` or `package.json`.

**Limits & Security:**
• Free tier: 1 Bot, 100MB RAM, 20% CPU.
• Max file size: 50MB.
• Strict malware and miner detection active.
    """
    bot.reply_to(message, help_text)

# --- FILE UPLOAD SYSTEM ---
@bot.message_handler(content_types=['document'])
def handle_document_upload(message):
    user_id = message.from_user.id
    
    if db.is_banned(user_id): return
    
    is_joined, _ = check_mandatory_channels(user_id)
    if not is_joined and user_id not in db.get_admins() and user_id != OWNER_ID:
        bot.reply_to(message, "⚠️ You must join the mandatory channels first. Type /start.")
        return

    # Check Slots Limit
    sub_data = db.get_user_subscription(user_id)
    max_slots = sub_data['bot_slots'] if sub_data else 1
    current_bots = len(db.get_user_bots(user_id))
    
    if current_bots >= max_slots:
        bot.reply_to(message, f"❌ Limit Reached! You have {current_bots}/{max_slots} bots. Please delete old bots or upgrade your plan.")
        return

    doc = message.document
    file_name = doc.file_name
    file_size = doc.file_size
    
    # Check Extensions
    if any(file_name.endswith(ext) for ext in BLOCKED_EXTENSIONS):
        bot.reply_to(message, "❌ Upload blocked. This file type is restricted by our security policies.")
        return
        
    if not (file_name.endswith('.py') or file_name.endswith('.js') or file_name.endswith('.zip')):
        bot.reply_to(message, "❌ Invalid file type. We only support `.py`, `.js`, and `.zip` files.")
        return

    # Check Size
    if file_size > MAX_FILE_SIZE:
        bot.reply_to(message, f"❌ File too large. Maximum allowed size is {MAX_FILE_SIZE // (1024*1024)}MB.")
        return

    status_msg = bot.reply_to(message, "⏳ Downloading file...")
    try:
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        user_folder = get_user_folder(user_id)
        
        if file_name.endswith('.zip'):
            bot.edit_message_text("🔍 Scanning archive for malware...", chat_id=user_id, message_id=status_msg.message_id)
            temp_zip = os.path.join(tempfile.gettempdir(), f"{user_id}_{file_name}")
            with open(temp_zip, 'wb') as f:
                f.write(downloaded_file)
                
            safe, reason = scan_zip_security(temp_zip)
            if not safe:
                os.remove(temp_zip)
                bot.edit_message_text(f"🚨 **SECURITY ALERT** 🚨\n{reason}", chat_id=user_id, message_id=status_msg.message_id)
                return
                
            bot.edit_message_text("📦 Extracting files...", chat_id=user_id, message_id=status_msg.message_id)
            
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(user_folder)
            os.remove(temp_zip)
            
            # Find Main Script
            extracted_files = os.listdir(user_folder)
            main_file = None
            f_type = None
            
            # Detect Dependencies
            if 'requirements.txt' in extracted_files:
                install_python_deps(os.path.join(user_folder, 'requirements.txt'), message)
            if 'package.json' in extracted_files:
                install_node_deps(os.path.join(user_folder, 'package.json'), message, user_folder)
                
            # Priority detection
            for priority in ['main.py', 'bot.py', 'app.py', 'index.js', 'main.js', 'server.js']:
                if priority in extracted_files:
                    main_file = priority
                    f_type = 'py' if priority.endswith('.py') else 'js'
                    break
                    
            if not main_file:
                for f in extracted_files:
                    if f.endswith('.py'):
                        main_file = f; f_type = 'py'; break
                    elif f.endswith('.js'):
                        main_file = f; f_type = 'js'; break
            
            if main_file:
                db.add_bot_file(user_id, main_file, f_type)
                bot.edit_message_text(f"✅ Archive uploaded and deployed.\nMain file detected: `{main_file}`", chat_id=user_id, message_id=status_msg.message_id, reply_markup=get_bot_control_markup(user_id, main_file))
            else:
                bot.edit_message_text("❌ Extraction successful, but no `.py` or `.js` main script was found.", chat_id=user_id, message_id=status_msg.message_id)

        else:
            bot.edit_message_text("🔍 Scanning script for malware...", chat_id=user_id, message_id=status_msg.message_id)
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file)
                
            safe, reason = scan_script_security(file_path)
            if not safe:
                os.remove(file_path)
                bot.edit_message_text(f"🚨 **SECURITY ALERT** 🚨\n{reason}", chat_id=user_id, message_id=status_msg.message_id)
                return
                
            f_type = 'py' if file_name.endswith('.py') else 'js'
            db.add_bot_file(user_id, file_name, f_type)
            
            bot.edit_message_text(f"✅ Script `{file_name}` uploaded successfully.", chat_id=user_id, message_id=status_msg.message_id, reply_markup=get_bot_control_markup(user_id, file_name))

    except Exception as e:
        logger.error(f"Upload error: {e}")
        bot.edit_message_text(f"❌ Upload processing failed: {str(e)}", chat_id=user_id, message_id=status_msg.message_id)

# --- CALLBACK QUERY HANDLERS (USER SIDE) ---
@bot.callback_query_handler(func=lambda call: not call.data.startswith('admin_'))
def handle_user_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    if db.is_banned(user_id):
        bot.answer_callback_query(call.id, "🚫 You are banned.", show_alert=True)
        return
        
    db.update_last_seen(user_id)
    
    try:
        # Channels Verification
        if data == "verify_channels":
            is_joined, not_joined = check_mandatory_channels(user_id)
            if is_joined:
                bot.answer_callback_query(call.id, "✅ Verification Successful!")
                bot.edit_message_text("✅ Thank you for joining. Welcome to Master Hosting!", chat_id=user_id, message_id=call.message.message_id, reply_markup=get_main_menu(user_id))
            else:
                bot.answer_callback_query(call.id, "❌ You have not joined all channels yet.", show_alert=True)
            return

        # Main Navigation
        if data == "open_dashboard":
            bot.edit_message_text(get_dashboard_text(user_id), chat_id=user_id, message_id=call.message.message_id, reply_markup=get_main_menu(user_id))
            
        elif data == "open_file_manager":
            bot.edit_message_text("📂 **Master File Manager**\nSelect a bot to manage:", chat_id=user_id, message_id=call.message.message_id, reply_markup=get_file_manager_markup(user_id))
            
        elif data == "upload_instructions":
            bot.answer_callback_query(call.id, "Send a file to upload.", show_alert=True)
            
        # Store & Plans
        elif data == "open_store":
            plans = db.get_all_plans()
            markup = types.InlineKeyboardMarkup(row_width=1)
            for p in plans:
                markup.add(types.InlineKeyboardButton(f"{p['name']} - ${p['price']} ({p['duration_days']} Days)", callback_data=f"buy_plan_{p['id']}"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="open_dashboard"))
            bot.edit_message_text("🛒 **Master Hosting Store**\nChoose a plan to upgrade your resources:", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data.startswith("buy_plan_"):
            plan_id = int(data.split('_')[2])
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("💳 Zapupi", callback_data=f"pay_zapupi_{plan_id}"),
                types.InlineKeyboardButton("🪙 Binance Pay", callback_data=f"pay_binance_{plan_id}")
            )
            markup.add(types.InlineKeyboardButton("💰 Pay with Master Coins", callback_data=f"pay_coins_{plan_id}"))
            markup.add(types.InlineKeyboardButton("🔙 Back to Store", callback_data="open_store"))
            bot.edit_message_text("💳 **Select Payment Method:**", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        # Payment Routing
        elif data.startswith("pay_zapupi_"):
            plan_id = int(data.split('_')[2])
            plan = next((p for p in db.get_all_plans() if p['id'] == plan_id), None)
            url, txid = create_zapupi_invoice(user_id, plan['price'], plan_id)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔗 Pay via Zapupi", url=url))
            markup.add(types.InlineKeyboardButton("✅ Check Payment", callback_data=f"check_pay_{txid}_{plan_id}"))
            markup.add(types.InlineKeyboardButton("🔙 Cancel", callback_data="open_store"))
            bot.edit_message_text(f"🧾 **Invoice Created**\nAmount: `${plan['price']}`\nTXID: `{txid}`", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data.startswith("pay_binance_"):
            plan_id = int(data.split('_')[2])
            plan = next((p for p in db.get_all_plans() if p['id'] == plan_id), None)
            url, txid = create_binance_invoice(user_id, plan['price'], plan_id)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔗 Pay via Binance", url=url))
            markup.add(types.InlineKeyboardButton("✅ Check Payment", callback_data=f"check_pay_{txid}_{plan_id}"))
            markup.add(types.InlineKeyboardButton("🔙 Cancel", callback_data="open_store"))
            bot.edit_message_text(f"🧾 **Invoice Created**\nAmount: `${plan['price']} USDT`\nTXID: `{txid}`", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
            
        elif data.startswith("check_pay_"):
            parts = data.split('_')
            txid = f"{parts[2]}_{parts[3]}_{parts[4]}" # Reconstruct TXID
            plan_id = int(parts[5])
            plan = next((p for p in db.get_all_plans() if p['id'] == plan_id), None)
            
            success, uid = verify_payment_status(txid)
            if success:
                db.add_subscription(user_id, plan_id, plan['duration_days'])
                bot.answer_callback_query(call.id, "✅ Payment Verified! Plan Activated.", show_alert=True)
                bot.edit_message_text("🎉 **Upgrade Successful!** Check your dashboard.", chat_id=user_id, message_id=call.message.message_id, reply_markup=get_main_menu(user_id))
            else:
                bot.answer_callback_query(call.id, "⏳ Payment not detected yet. Please wait.", show_alert=True)

        # Redeem Codes
        elif data == "open_redeem":
            msg = bot.send_message(user_id, "🎁 Send me your Redeem Code:\n(Type /cancel to abort)")
            bot.register_next_step_handler(msg, process_redeem_code)

        # Referrals
        elif data == "open_referral":
            bot_username = bot.get_me().username
            ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
            
            conn = db._get_conn()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
            ref_count = c.fetchone()[0]
            conn.close()
            
            text = f"👥 **Referral Program**\n\nInvite friends and earn **50 Master Coins** for each join!\n\n🔗 Your Link: `{ref_link}`\n📈 Total Referrals: `{ref_count}`"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="open_dashboard"))
            bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        # Support Tickets
        elif data == "open_tickets":
            tickets = db.get_user_tickets(user_id)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("➕ Create New Ticket", callback_data="create_ticket"))
            for t in tickets[:5]: # Show last 5
                markup.add(types.InlineKeyboardButton(f"🎫 #{t[0]} - {t[1]} ({t[2]})", callback_data=f"view_ticket_{t[0]}"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="open_dashboard"))
            bot.edit_message_text("🎫 **Support Center**\nNeed help? Create a ticket.", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
            
        elif data == "create_ticket":
            msg = bot.send_message(user_id, "🎫 Enter the subject of your support ticket:\n(Type /cancel to abort)")
            bot.register_next_step_handler(msg, process_ticket_subject)
            
        elif data.startswith("view_ticket_"):
            ticket_id = int(data.split('_')[2])
            msgs = db.get_ticket_messages(ticket_id)
            text = f"🎫 **Ticket #{ticket_id} History**\n\n"
            for m in msgs[-5:]: # Last 5 messages
                sender = "You" if m[0] == user_id else "Admin Support"
                text += f"**{sender}:** {m[1]}\n\n"
                
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("✍️ Reply", callback_data=f"reply_ticket_{ticket_id}"))
            markup.add(types.InlineKeyboardButton("🔒 Close Ticket", callback_data=f"close_ticket_{ticket_id}"))
            markup.add(types.InlineKeyboardButton("🔙 Back to Tickets", callback_data="open_tickets"))
            bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data.startswith(
        
        
        # --- ADVANCED ADMIN PANEL UI & ROUTING ---
def get_admin_panel_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👥 Users", callback_data="admin_users"),
        types.InlineKeyboardButton("📦 Plans", callback_data="admin_plans"),
        types.InlineKeyboardButton("💳 Payments", callback_data="admin_payments"),
        types.InlineKeyboardButton("🎫 Tickets", callback_data="admin_tickets")
    )
    markup.add(
        types.InlineKeyboardButton("📢 Channels", callback_data="admin_channels"),
        types.InlineKeyboardButton("🎁 Redeem Codes", callback_data="admin_codes"),
        types.InlineKeyboardButton("⚙️ Server Monitor", callback_data="admin_server"),
        types.InlineKeyboardButton("🚨 Broadcast", callback_data="admin_broadcast")
    )
    markup.add(
        types.InlineKeyboardButton("🛡️ Admins", callback_data="admin_manage_admins"),
        types.InlineKeyboardButton("🛑 Lock Bot", callback_data="admin_lock_bot")
    )
    markup.add(types.InlineKeyboardButton("🔙 Back to User Menu", callback_data="open_dashboard"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    if user_id not in db.get_admins() and user_id != OWNER_ID:
        bot.answer_callback_query(call.id, "🚫 Unauthorized Access.", show_alert=True)
        return

    try:
        # Main Admin Menu
        if data == "admin_panel" or data == "open_admin_panel":
            text = f"⚙️ **MASTER HOSTING - ADMIN PANEL**\n\nWelcome back, Commander `{user_id}`.\nSelect a module to manage:"
            try:
                bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=get_admin_panel_markup())
            except:
                bot.send_message(user_id, text, reply_markup=get_admin_panel_markup())

        # 1. User Management
        elif data == "admin_users":
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("🔍 Find User", callback_data="admin_find_user"),
                types.InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban_user"),
                types.InlineKeyboardButton("✅ Unban User", callback_data="admin_unban_user"),
                types.InlineKeyboardButton("🪙 Add Coins", callback_data="admin_add_coins")
            )
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
            bot.edit_message_text("👥 **User Management Module**", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data == "admin_find_user":
            msg = bot.send_message(user_id, "🔍 Send the Telegram User ID to look up:\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_find_user)
            
        elif data == "admin_ban_user":
            msg = bot.send_message(user_id, "🚫 Send `UserID Reason` to ban:\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_ban)

        elif data == "admin_unban_user":
            msg = bot.send_message(user_id, "✅ Send `UserID` to unban:\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_unban)

        elif data == "admin_add_coins":
            msg = bot.send_message(user_id, "🪙 Send `UserID Amount` to add coins:\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_add_coins)

        # 2. Server Monitor
        elif data == "admin_server":
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            with process_lock:
                running_bots = len(active_processes)
                
            text = (
                f"⚙️ **VPS MONITOR**\n\n"
                f"💻 **CPU Usage:** `{cpu}%`\n"
                f"🧠 **RAM Usage:** `{ram.percent}%` ({ram.used//(1024*1024)}MB / {ram.total//(1024*1024)}MB)\n"
                f"💾 **Storage:** `{disk.percent}%` ({disk.used//(1024*1024)}MB / {disk.total//(1024*1024)}MB)\n"
                f"🤖 **Running Bots:** `{running_bots}`\n"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_server"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
            bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        # 3. Broadcast System
        elif data == "admin_broadcast":
            msg = bot.send_message(user_id, "🚨 **Broadcast Module**\nSend the text, photo, or video you want to broadcast to ALL users:\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_broadcast)

        # 4. Mandatory Channels Management
        elif data == "admin_channels":
            channels = db.get_mandatory_channels()
            text = "📢 **Mandatory Channels**\n\n"
            for c in channels:
                text += f"• {c['name']} (`{c['id']}`)\n"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("➕ Add Channel", callback_data="admin_add_channel"),
                types.InlineKeyboardButton("➖ Remove Channel", callback_data="admin_remove_channel")
            )
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
            bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data == "admin_add_channel":
            msg = bot.send_message(user_id, "➕ Send the Channel ID or Username (Must add bot as admin first!):\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_add_channel)

        elif data == "admin_remove_channel":
            msg = bot.send_message(user_id, "➖ Send the Channel ID to remove:\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_remove_channel)

        # 5. Tickets
        elif data == "admin_tickets":
            # Simplified: fetches recent open tickets
            conn = db._get_conn()
            c = conn.cursor()
            c.execute("SELECT id, user_id, subject FROM tickets WHERE status = 'open' ORDER BY id ASC LIMIT 10")
            open_tickets = c.fetchall()
            conn.close()
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            for t in open_tickets:
                markup.add(types.InlineKeyboardButton(f"🎫 #{t[0]} (User: {t[1]})", callback_data=f"admin_view_ticket_{t[0]}"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
            
            bot.edit_message_text(f"🎫 **Open Support Tickets** ({len(open_tickets)})", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data.startswith("admin_view_ticket_"):
            ticket_id = int(data.split('_')[3])
            msgs = db.get_ticket_messages(ticket_id)
            
            text = f"🎫 **Admin Ticket View #{ticket_id}**\n\n"
            for m in msgs[-5:]:
                sender = "Admin" if m[0] in db.get_admins() else f"User {m[0]}"
                text += f"**{sender}:** {m[1]}\n\n"
                
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("✍️ Reply", callback_data=f"admin_reply_ticket_{ticket_id}"))
            markup.add(types.InlineKeyboardButton("🔒 Close Ticket", callback_data=f"admin_close_ticket_{ticket_id}"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_tickets"))
            bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data.startswith("admin_reply_ticket_"):
            ticket_id = int(data.split('_')[3])
            msg = bot.send_message(user_id, "✍️ Send your reply to the user:\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_ticket_reply, ticket_id)

        elif data.startswith("admin_close_ticket_"):
            ticket_id = int(data.split('_')[3])
            db.close_ticket(ticket_id)
            bot.answer_callback_query(call.id, "Ticket closed successfully.", show_alert=True)
            handle_admin_callbacks(types.CallbackQuery(call.id, call.from_user, call.message, call.chat_instance, "admin_tickets"))

        # 6. Redeem Codes Manager
        elif data == "admin_codes":
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Create Code", callback_data="admin_create_code"))
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
            bot.edit_message_text("🎁 **Redeem Codes Manager**", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data == "admin_create_code":
            msg = bot.send_message(user_id, "➕ Enter details format:\n`CODE | reward_type | reward_value | max_uses`\nTypes: `coins`, `premium_days`\nExample: `SUMMER2026 | coins | 500 | 100`\n(/cancel to abort)")
            bot.register_next_step_handler(msg, admin_process_create_code)

        # 7. Admin Manager (Owner Only)
        elif data == "admin_manage_admins":
            if user_id != OWNER_ID:
                bot.answer_callback_query(call.id, "🚫 Only the OWNER can manage admins.", show_alert=True)
                return
            
            admins = db.get_admins()
            text = "🛡️ **Current Admins**\n"
            for a in admins:
                text += f"• `{a}`\n"
                
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("➕ Add Admin", callback_data="admin_add_admin"),
                types.InlineKeyboardButton("➖ Remove Admin", callback_data="admin_remove_admin")
            )
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
            bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

        elif data == "admin_add_admin":
            msg = bot.send_message(user_id, "➕ Send UserID to promote to Admin:")
            bot.register_next_step_handler(msg, admin_process_add_admin)
            
        elif data == "admin_remove_admin":
            msg = bot.send_message(user_id, "➖ Send UserID to remove from Admin:")
            bot.register_next_step_handler(msg, admin_process_remove_admin)

    except Exception as e:
        logger.error(f"Admin Callback Error: {e}", exc_info=True)

# --- ADMIN NEXT STEP HANDLERS ---
def admin_process_find_user(message):
    if message.text == '/cancel': return
    try:
        uid = int(message.text)
        user = db.get_user(uid)
        if not user:
            bot.reply_to(message, "❌ User not found.")
            return
            
        sub = db.get_user_subscription(uid)
        plan_name = sub['plan_name'] if sub else "Free"
        
        text = (f"👤 **USER INFO**\nID: `{uid}`\n"
                f"Coins: `{user['coins']}`\n"
                f"Plan: `{plan_name}`\n"
                f"Joined: `{user['join_date'][:10]}`\n"
                f"Banned: `{db.is_banned(uid)}`")
        bot.reply_to(message, text, reply_markup=get_admin_panel_markup())
    except:
        bot.reply_to(message, "❌ Invalid ID.")

def admin_process_ban(message):
    if message.text == '/cancel': return
    try:
        parts = message.text.split(' ', 1)
        uid = int(parts[0])
        reason = parts[1] if len(parts) > 1 else "Violation of ToS"
        if uid == OWNER_ID:
            bot.reply_to(message, "❌ Cannot ban owner.")
            return
        db.ban_user(uid, reason, message.from_user.id)
        
        # Kill their bots immediately
        with process_lock:
            user_keys = [k for k in active_processes.keys() if k.startswith(f"{uid}_")]
            for k in user_keys:
                _, fname = k.split('_', 1)
                stop_script(uid, fname)
                
        bot.reply_to(message, f"✅ User {uid} banned successfully.")
        try: bot.send_message(uid, f"🚫 **YOU HAVE BEEN BANNED**\nReason: {reason}")
        except: pass
    except:
        bot.reply_to(message, "❌ Format error.")

def admin_process_unban(message):
    if message.text == '/cancel': return
    try:
        uid = int(message.text)
        db.unban_user(uid)
        bot.reply_to(message, f"✅ User {uid} unbanned.")
        try: bot.send_message(uid, "✅ Your ban has been lifted.")
        except: pass
    except:
        bot.reply_to(message, "❌ Format error.")

def admin_process_add_coins(message):
    if message.text == '/cancel': return
    try:
        uid, amt = map(int, message.text.split())
        db.update_coins(uid, amt)
        bot.reply_to(message, f"✅ Added {amt} coins to {uid}.")
        try: bot.send_message(uid, f"🎉 Admin added `{amt}` Master Coins to your balance!")
        except: pass
    except:
        bot.reply_to(message, "❌ Format error. Expected: `UserID Amount`")

def admin_process_broadcast(message):
    if message.text and message.text == '/cancel': return
    
    bot.reply_to(message, "🚨 Starting broadcast in background...")
    
    def do_broadcast():
        conn = db._get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        users = [r[0] for r in c.fetchall()]
        conn.close()
        
        sent = 0
        failed = 0
        for u in users:
            try:
                if message.text:
                    bot.send_message(u, message.text, entities=message.entities)
                elif message.photo:
                    bot.send_photo(u, message.photo[-1].file_id, caption=message.caption, caption_entities=message.caption_entities)
                elif message.video:
                    bot.send_video(u, message.video.file_id, caption=message.caption, caption_entities=message.caption_entities)
                elif message.document:
                    bot.send_document(u, message.document.file_id, caption=message.caption, caption_entities=message.caption_entities)
                sent += 1
            except:
                failed += 1
            time.sleep(0.05) # Prevent flood wait
            
        bot.send_message(message.from_user.id, f"✅ **Broadcast Complete**\nSent: `{sent}`\nFailed: `{failed}`")
        
    threading.Thread(target=do_broadcast).start()

def admin_process_add_channel(message):
    if message.text == '/cancel': return
    try:
        ch_id = message.text.strip()
        chat = bot.get_chat(ch_id)
        username = f"@{chat.username}" if chat.username else ""
        db.add_mandatory_channel(str(chat.id), username, chat.title, message.from_user.id)
        bot.reply_to(message, f"✅ Channel {chat.title} added to mandatory requirements.")
    except Exception as e:
        bot.reply_to(message, f"❌ Failed. Make sure the bot is an admin in the channel. Error: {e}")

def admin_process_remove_channel(message):
    if message.text == '/cancel': return
    db.remove_mandatory_channel(message.text.strip())
    bot.reply_to(message, "✅ Channel removed (if it existed).")

def admin_process_ticket_reply(message, ticket_id):
    if message.text == '/cancel': return
    db.reply_ticket(ticket_id, message.from_user.id, message.text)
    bot.reply_to(message, "✅ Reply sent.")
    
    # Notify User
    conn = db._get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
    uid = c.fetchone()[0]
    conn.close()
    
    try: bot.send_message(uid, f"📩 **ADMIN REPLY ON TICKET #{ticket_id}**\n\n{message.text}")
    except: pass

def admin_process_create_code(message):
    if message.text == '/cancel': return
    try:
        parts = [p.strip() for p in message.text.split('|')]
        if len(parts) != 4: raise ValueError("Format error")
        
        code, rw_type, rw_val, mx_uses = parts[0], parts[1], parts[2], int(parts[3])
        # No expiry set in basic UI, default to 30 days
        expiry = (datetime.now() + timedelta(days=30)).isoformat()
        
        db.create_redeem_code(code, "public", rw_type, rw_val, mx_uses, expiry)
        bot.reply_to(message, f"✅ Code Created!\nCode: `{code}`\nReward: `{rw_val} {rw_type}`\nUses: `{mx_uses}`")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}. Check formatting.")

def admin_process_add_admin(message):
    if message.text == '/cancel': return
    try:
        new_admin = int(message.text)
        db.add_admin(new_admin, message.from_user.id)
        bot.reply_to(message, f"✅ User `{new_admin}` is now an Admin.")
        try: bot.send_message(new_admin, "🎉 You have been promoted to Admin.")
        except: pass
    except:
        bot.reply_to(message, "❌ Invalid ID.")

def admin_process_remove_admin(message):
    if message.text == '/cancel': return
    try:
        rm_admin = int(message.text)
        if rm_admin == OWNER_ID:
            bot.reply_to(message, "❌ Cannot remove OWNER.")
            return
        db.remove_admin(rm_admin)
        bot.reply_to(message, f"✅ Admin `{rm_admin}` removed.")
    except:
        bot.reply_to(message, "❌ Invalid ID.")

# --- CLEANUP ON EXIT ---
def cleanup_on_exit():
    logger.warning("Shutdown initiated. Killing all managed bot processes...")
    with process_lock:
        keys = list(active_processes.keys())
        for key in keys:
            proc_info = active_processes[key]
            logger.info(f"Killing process {key} (PID: {proc_info['pid']})")
            kill_process_tree(proc_info['pid'])
            try: proc_info['log_file'].close()
            except: pass
    logger.warning("All processes killed. Shutdown complete.")

atexit.register(cleanup_on_exit)

# --- EXECUTION & INITIALIZATION ---
if __name__ == '__main__':
    print("="*60)
    print("🚀 BOOTING MASTER HOSTING ENTERPRISE 2026 🚀")
    print("="*60)
    
    # Create DB backups on boot
    db.backup_database()
    
    # Start Keep-Alive Web Server
    keep_alive()

    # Start Daemons
    threading.Thread(target=resource_monitor_daemon, daemon=True).start()
    threading.Thread(target=crash_recovery_daemon, daemon=True).start()
    threading.Thread(target=subscription_expiry_daemon, daemon=True).start()

    logger.info("Daemons running. Connecting to Telegram API...")

    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout:
            logger.warning("ReadTimeout. Retrying...")
            time.sleep(3)
        except requests.exceptions.ConnectionError:
            logger.error("ConnectionError. Retrying in 10s...")
            time.sleep(10)
        except Exception as e:
            logger.critical(f"Critical Polling Error: {e}", exc_info=True)
            time.sleep(30)