# config.py
import os
import re
from dotenv import load_dotenv

load_dotenv()

# --- BOT CONFIGURATION ---
TOKEN = os.getenv('TOKEN', '8180059887:AAEw69nvSCb-nqVvaPiQjAbfrJfDt1eYC-w')
OWNER_ID = int(os.getenv('OWNER_ID', 6893661111))
ADMIN_ID = int(os.getenv('ADMIN_ID', 6893661111))
YOUR_USERNAME = os.getenv('YOUR_USERNAME', '@M7S_BOT')
UPDATE_CHANNEL = os.getenv('UPDATE_CHANNEL', '@M7S_TECH_LAB')

# --- DIRECTORY CONFIGURATION ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
DATABASE_DIR = os.path.join(BASE_DIR, 'database')
BACKUPS_DIR = os.path.join(BASE_DIR, 'backups')
DATABASE_PATH = os.path.join(DATABASE_DIR, 'master_hosting.db')

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(DATABASE_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)

# --- PAYMENT GATEWAYS ---
ZAPUPI_API_KEY = os.getenv('zape278b00e89030860bcf0db12638f1d76', '')
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY', '')

# --- LIMITS & DEFAULTS ---
FREE_TRIAL_HOURS = 1
MAX_FREE_TRIAL_BOTS = 1

# --- BADGES ---
BADGES = {
    "OWNER": "👑",
    "DEVELOPER": "👨‍💻",
    "ADMIN": "🛡️",
    "STAFF": "📋",
    "PARTNER": "🤝",
    "LEGEND": "🏆",
    "GOLD": "🌟",
    "VIP": "💎",
    "PREMIUM": "⭐"
}

# --- SECURITY SCANNER CONFIGURATION ---
MAX_FILE_SIZE = 50 * 1024 * 1024  # Increased to 50MB for Enterprise
MAX_UPLOAD_RATE = 5  # Files per minute
BLOCKED_EXTENSIONS = ['.exe', '.sh', '.bat', '.cmd', '.dll', '.so', '.bin']

# Extended Regex Patterns including Malware & Miner Detection
DANGEROUS_PATTERNS = [
    # OS & System
    r'\bos\.system\b', r'\bos\.popen\b', r'\bos\.(remove|unlink|rmdir|removedirs)\b',
    r'\bsubprocess\.Popen\b', r'\bsubprocess\.call\b', r'\bsubprocess\.run\b',
    r'rm\s+-rf', r'format\s+[c-z]:', r'mkfs', r'dd\s+if=', r'chmod\s+777',
    
    # Process Killing & Destruction
    r'\bkillall\b', r'\bpkill\b', r'shutdown\s+-h', r'reboot', r'>\s*/dev/null',
    
    # Execution & Reflection
    r'\beval\s*\(', r'\bexec\s*\(', r'\b__import__\b', r'\bcompile\s*\(',
    
    # Malware & Miner Specific
    r'\bxmrig\b', r'\bminerd\b', r'\bcgminer\b', r'\bstratum\+tcp\b', r'\bpool\.support\b',
    r'\bminergate\b', r'\bnicehash\b', r'\bcrypto-loot\b', r'\bcoinhive\b',
    r'\bcoin-hive\b', r'\bmonero\b', r'\bxmr\b', r'\bethminer\b', r'\bcpuminer\b',
    r'socket\.socket', r'nc\s+-e', r'reverse_tcp', r'meterpreter', r'payload',
    
    # File Stealing / Keylogging
    r'/etc/shadow', r'/etc/passwd', r'id_rsa', r'\.ssh/id_',
    r'\bpynput\b', r'\bkeyboard\.hook\b', r'\bpyHook\b',
    
    # System Overload / Fork Bomb
    r':\(\)\{\s*:\s*\|\s*:&\s*\};\s*:'
]