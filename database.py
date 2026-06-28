# database.py
import sqlite3
import threading
import os
import shutil
import logging
from datetime import datetime, timedelta
from config import DATABASE_PATH, BACKUPS_DIR, OWNER_ID, ADMIN_ID

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.db_path = DATABASE_PATH
        self.lock = threading.Lock()
        self._init_db()
        self._run_auto_migrations()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            
            # 1. Users Table (Upgraded)
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (user_id INTEGER PRIMARY KEY, 
                          join_date TEXT, 
                          last_seen TEXT, 
                          coins INTEGER DEFAULT 0,
                          referrer_id INTEGER,
                          trial_used INTEGER DEFAULT 0,
                          badges TEXT DEFAULT '')''')

            # 2. Plans Table
            c.execute('''CREATE TABLE IF NOT EXISTS plans
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          name TEXT UNIQUE,
                          price REAL,
                          duration_days INTEGER,
                          bot_slots INTEGER,
                          ram_limit_mb INTEGER,
                          cpu_limit_percent INTEGER,
                          storage_limit_mb INTEGER,
                          priority_level INTEGER DEFAULT 1,
                          visibility INTEGER DEFAULT 1,
                          features TEXT)''')

            # 3. Subscriptions (Upgraded)
            c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id INTEGER,
                          plan_id INTEGER,
                          expiry TEXT,
                          status TEXT DEFAULT 'active',
                          auto_renew INTEGER DEFAULT 0,
                          FOREIGN KEY(user_id) REFERENCES users(user_id),
                          FOREIGN KEY(plan_id) REFERENCES plans(id))''')

            # 4. Bots/Files (Upgraded from user_files)
            c.execute('''CREATE TABLE IF NOT EXISTS bots
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id INTEGER,
                          file_name TEXT,
                          file_type TEXT,
                          status TEXT DEFAULT 'stopped',
                          auto_restart INTEGER DEFAULT 0,
                          crash_count INTEGER DEFAULT 0,
                          upload_date TEXT,
                          UNIQUE(user_id, file_name))''')

            # 5. Payments
            c.execute('''CREATE TABLE IF NOT EXISTS payments
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id INTEGER,
                          gateway TEXT,
                          amount REAL,
                          currency TEXT,
                          status TEXT,
                          txid TEXT UNIQUE,
                          created_at TEXT)''')

            # 6. Redeem Codes
            c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes
                         (code TEXT PRIMARY KEY,
                          type TEXT,
                          reward_type TEXT,
                          reward_value TEXT,
                          max_uses INTEGER,
                          current_uses INTEGER DEFAULT 0,
                          expires_at TEXT)''')

            # 7. Redeem Logs
            c.execute('''CREATE TABLE IF NOT EXISTS redeem_logs
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id INTEGER,
                          code TEXT,
                          redeemed_at TEXT)''')

            # 8. Referrals
            c.execute('''CREATE TABLE IF NOT EXISTS referrals
                         (referrer_id INTEGER,
                          referred_id INTEGER PRIMARY KEY,
                          reward_paid INTEGER DEFAULT 0,
                          joined_at TEXT)''')

            # 9. Support Tickets
            c.execute('''CREATE TABLE IF NOT EXISTS tickets
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id INTEGER,
                          subject TEXT,
                          status TEXT DEFAULT 'open',
                          created_at TEXT)''')

            # 10. Support Ticket Messages
            c.execute('''CREATE TABLE IF NOT EXISTS ticket_messages
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          ticket_id INTEGER,
                          sender_id INTEGER,
                          message TEXT,
                          created_at TEXT,
                          FOREIGN KEY(ticket_id) REFERENCES tickets(id))''')

            # 11. Legacy / Core Tables (Preserved & Enhanced)
            c.execute('''CREATE TABLE IF NOT EXISTS admins
                         (user_id INTEGER PRIMARY KEY, added_by INTEGER, added_date TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                         (user_id INTEGER PRIMARY KEY, reason TEXT, banned_by INTEGER, ban_date TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS user_limits
                         (user_id INTEGER PRIMARY KEY, file_limit INTEGER, set_by INTEGER, set_date TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS mandatory_channels
                         (channel_id TEXT PRIMARY KEY, channel_username TEXT, channel_name TEXT, added_by INTEGER, added_date TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS install_logs
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, module_name TEXT, package_name TEXT, status TEXT, log TEXT, install_date TEXT)''')

            # Insert Default Admin & Owner
            now = datetime.now().isoformat()
            c.execute('INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)', (OWNER_ID, OWNER_ID, now))
            if ADMIN_ID != OWNER_ID:
                c.execute('INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)', (ADMIN_ID, OWNER_ID, now))
            
            # Insert Default Free & Premium Plans if not exist
            c.execute('SELECT COUNT(*) FROM plans')
            if c.fetchone()[0] == 0:
                c.execute('''INSERT INTO plans (name, price, duration_days, bot_slots, ram_limit_mb, cpu_limit_percent, storage_limit_mb, priority_level) 
                             VALUES ('Free Tier', 0, 9999, 1, 100, 20, 50, 1)''')
                c.execute('''INSERT INTO plans (name, price, duration_days, bot_slots, ram_limit_mb, cpu_limit_percent, storage_limit_mb, priority_level) 
                             VALUES ('Premium Pro', 10.0, 30, 5, 512, 100, 500, 10)''')
                c.execute('''INSERT INTO plans (name, price, duration_days, bot_slots, ram_limit_mb, cpu_limit_percent, storage_limit_mb, priority_level) 
                             VALUES ('Enterprise X', 25.0, 30, 20, 2048, 200, 2048, 100)''')

            conn.commit()
            conn.close()

    def _run_auto_migrations(self):
        """Seamlessly migrates data from the old bot version to the new Enterprise architecture."""
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            
            # Check if old active_users table exists to migrate to 'users'
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='active_users'")
            if c.fetchone():
                logger.info("Migrating old 'active_users' to new 'users' table...")
                c.execute("SELECT user_id, join_date, last_seen FROM active_users")
                old_users = c.fetchall()
                for uid, jd, ls in old_users:
                    c.execute("INSERT OR IGNORE INTO users (user_id, join_date, last_seen) VALUES (?, ?, ?)", (uid, jd, ls))
                c.execute("DROP TABLE active_users")
                logger.info("Migration of users complete.")

            # Check if old user_files table exists to migrate to 'bots'
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_files'")
            if c.fetchone():
                logger.info("Migrating old 'user_files' to new 'bots' table...")
                c.execute("SELECT user_id, file_name, file_type FROM user_files")
                old_files = c.fetchall()
                now = datetime.now().isoformat()
                for uid, fn, ft in old_files:
                    c.execute("INSERT OR IGNORE INTO bots (user_id, file_name, file_type, upload_date) VALUES (?, ?, ?, ?)", (uid, fn, ft, now))
                c.execute("DROP TABLE user_files")
                logger.info("Migration of bots complete.")
            
            conn.commit()
            conn.close()

    def backup_database(self):
        """Create an automatic SQLite backup."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(BACKUPS_DIR, f"db_backup_{timestamp}.sqlite")
            with self.lock:
                shutil.copy2(self.db_path, backup_file)
            logger.info(f"Database backed up successfully to {backup_file}")
            return True, backup_file
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            return False, str(e)

    # ------------------ USERS & COINS ------------------
    def add_user(self, user_id, referrer_id=None):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('INSERT OR IGNORE INTO users (user_id, join_date, last_seen, referrer_id) VALUES (?, ?, ?, ?)', 
                      (user_id, now, now, referrer_id))
            conn.commit()
            conn.close()

    def get_user(self, user_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('SELECT user_id, join_date, last_seen, coins, referrer_id, trial_used, badges FROM users WHERE user_id = ?', (user_id,))
            res = c.fetchone()
            conn.close()
            if res:
                return {"user_id": res[0], "join_date": res[1], "last_seen": res[2], "coins": res[3], 
                        "referrer_id": res[4], "trial_used": res[5], "badges": res[6]}
            return None

    def update_last_seen(self, user_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('UPDATE users SET last_seen = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
            conn.commit()
            conn.close()

    def update_coins(self, user_id, amount):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('UPDATE users SET coins = coins + ? WHERE user_id = ?', (amount, user_id))
            conn.commit()
            conn.close()

    # ------------------ PLANS & SUBSCRIPTIONS ------------------
    def get_all_plans(self):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('SELECT * FROM plans WHERE visibility = 1 ORDER BY price ASC')
            columns = [column[0] for column in c.description]
            res = [dict(zip(columns, row)) for row in c.fetchall()]
            conn.close()
            return res

    def get_user_subscription(self, user_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('''SELECT s.id, s.expiry, s.status, p.name, p.bot_slots, p.ram_limit_mb, p.cpu_limit_percent, p.storage_limit_mb
                         FROM subscriptions s
                         JOIN plans p ON s.plan_id = p.id
                         WHERE s.user_id = ? AND s.status = 'active'
                         ORDER BY s.expiry DESC LIMIT 1''', (user_id,))
            row = c.fetchone()
            conn.close()
            if row:
                return {
                    "sub_id": row[0], "expiry": datetime.fromisoformat(row[1]), "status": row[2],
                    "plan_name": row[3], "bot_slots": row[4], "ram_limit": row[5], "cpu_limit": row[6], "storage_limit": row[7]
                }
            return None

    def add_subscription(self, user_id, plan_id, days):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("SELECT expiry FROM subscriptions WHERE user_id = ? AND status = 'active' AND plan_id = ?", (user_id, plan_id))
            existing = c.fetchone()
            
            if existing:
                new_expiry = datetime.fromisoformat(existing[0]) + timedelta(days=days)
                c.execute("UPDATE subscriptions SET expiry = ? WHERE user_id = ? AND plan_id = ? AND status = 'active'",
                          (new_expiry.isoformat(), user_id, plan_id))
            else:
                new_expiry = datetime.now() + timedelta(days=days)
                c.execute("INSERT INTO subscriptions (user_id, plan_id, expiry) VALUES (?, ?, ?)",
                          (user_id, plan_id, new_expiry.isoformat()))
            conn.commit()
            conn.close()

    # ------------------ FILE & BOT MANAGER ------------------
    def add_bot_file(self, user_id, file_name, file_type):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('''INSERT OR REPLACE INTO bots (user_id, file_name, file_type, upload_date) 
                         VALUES (?, ?, ?, ?)''', (user_id, file_name, file_type, now))
            conn.commit()
            conn.close()

    def get_user_bots(self, user_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('SELECT file_name, file_type, status, auto_restart, crash_count FROM bots WHERE user_id = ?', (user_id,))
            res = c.fetchall()
            conn.close()
            return res

    def delete_bot_file(self, user_id, file_name):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('DELETE FROM bots WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            conn.close()

    def update_bot_status(self, user_id, file_name, status):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('UPDATE bots SET status = ? WHERE user_id = ? AND file_name = ?', (status, user_id, file_name))
            conn.commit()
            conn.close()

    def toggle_auto_restart(self, user_id, file_name):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('UPDATE bots SET auto_restart = CASE WHEN auto_restart = 1 THEN 0 ELSE 1 END WHERE user_id = ? AND file_name = ?', 
                      (user_id, file_name))
            conn.commit()
            conn.close()

    def increment_crash_count(self, user_id, file_name):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('UPDATE bots SET crash_count = crash_count + 1 WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            conn.close()

    # ------------------ REDEEM CODES ------------------
    def create_redeem_code(self, code, code_type, reward_type, reward_value, max_uses, expires_at):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('''INSERT INTO redeem_codes (code, type, reward_type, reward_value, max_uses, expires_at)
                         VALUES (?, ?, ?, ?, ?, ?)''', (code, code_type, reward_type, reward_value, max_uses, expires_at))
            conn.commit()
            conn.close()

    def use_redeem_code(self, user_id, code):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            # Check if used
            c.execute('SELECT 1 FROM redeem_logs WHERE user_id = ? AND code = ?', (user_id, code))
            if c.fetchone():
                conn.close()
                return False, "Code already used by you."
            
            c.execute('SELECT reward_type, reward_value, max_uses, current_uses, expires_at FROM redeem_codes WHERE code = ?', (code,))
            res = c.fetchone()
            if not res:
                conn.close()
                return False, "Invalid Code."
            
            reward_type, reward_value, max_uses, current_uses, expires_at = res
            
            if expires_at and datetime.fromisoformat(expires_at) < datetime.now():
                conn.close()
                return False, "Code Expired."
            
            if current_uses >= max_uses:
                conn.close()
                return False, "Code maximum uses reached."
                
            c.execute('UPDATE redeem_codes SET current_uses = current_uses + 1 WHERE code = ?', (code,))
            c.execute('INSERT INTO redeem_logs (user_id, code, redeemed_at) VALUES (?, ?, ?)', (user_id, code, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            
            return True, {"reward_type": reward_type, "reward_value": reward_value}

    # ------------------ SUPPORT TICKETS ------------------
    def create_ticket(self, user_id, subject, initial_message):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('INSERT INTO tickets (user_id, subject, created_at) VALUES (?, ?, ?)', (user_id, subject, now))
            ticket_id = c.lastrowid
            c.execute('INSERT INTO ticket_messages (ticket_id, sender_id, message, created_at) VALUES (?, ?, ?, ?)',
                      (ticket_id, user_id, initial_message, now))
            conn.commit()
            conn.close()
            return ticket_id

    def get_user_tickets(self, user_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('SELECT id, subject, status, created_at FROM tickets WHERE user_id = ? ORDER BY id DESC', (user_id,))
            res = c.fetchall()
            conn.close()
            return res

    def get_ticket_messages(self, ticket_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('SELECT sender_id, message, created_at FROM ticket_messages WHERE ticket_id = ? ORDER BY id ASC', (ticket_id,))
            res = c.fetchall()
            conn.close()
            return res

    def reply_ticket(self, ticket_id, sender_id, message):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('INSERT INTO ticket_messages (ticket_id, sender_id, message, created_at) VALUES (?, ?, ?, ?)',
                      (ticket_id, sender_id, message, datetime.now().isoformat()))
            c.execute("UPDATE tickets SET status = 'open' WHERE id = ?", (ticket_id,))
            conn.commit()
            conn.close()

    def close_ticket(self, ticket_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
            conn.commit()
            conn.close()

    # ------------------ ADMIN & BAN METHODS ------------------
    def add_admin(self, admin_id, added_by):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)', 
                      (admin_id, added_by, datetime.now().isoformat()))
            conn.commit()
            conn.close()

    def remove_admin(self, admin_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
            conn.commit()
            conn.close()
            
    def get_admins(self):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('SELECT user_id FROM admins')
            res = [row[0] for row in c.fetchall()]
            conn.close()
            return res

    def ban_user(self, user_id, reason, admin_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO banned_users (user_id, reason, banned_by, ban_date) VALUES (?, ?, ?, ?)',
                      (user_id, reason, admin_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()

    def unban_user(self, user_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()

    def is_banned(self, user_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('SELECT 1 FROM banned_users WHERE user_id = ?', (user_id,))
            res = c.fetchone()
            conn.close()
            return bool(res)

    # ------------------ CHANNELS & LOGS ------------------
    def get_mandatory_channels(self):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('SELECT channel_id, channel_username, channel_name FROM mandatory_channels')
            res = c.fetchall()
            conn.close()
            return [{"id": r[0], "username": r[1], "name": r[2]} for r in res]

    def add_mandatory_channel(self, channel_id, username, name, admin_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO mandatory_channels (channel_id, channel_username, channel_name, added_by, added_date) VALUES (?, ?, ?, ?, ?)',
                      (channel_id, username, name, admin_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()

    def remove_mandatory_channel(self, channel_id):
        with self.lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute('DELETE FROM mandatory_channels WHERE channel_id = ?', (channel_id,))
            conn.commit()
            conn.close()

# Initialize Global Database instance
db = DatabaseManager()