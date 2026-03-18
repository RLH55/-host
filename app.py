import os
import json
import re
import subprocess
import psutil
import socket
import sys
import hashlib
import secrets
import time
import threading
import requests
from datetime import datetime, timedelta
from flask import Flask, send_from_directory, request, jsonify, session, redirect, url_for, make_response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "USERS")
os.makedirs(USERS_DIR, exist_ok=True)

app = Flask(__name__, static_folder=BASE_DIR)
app.secret_key = secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

running_procs = {}
TELEGRAM_BOTS = {}
# قاموس لتتبع البوتات التي أوقفها المستخدم يدوياً (لا تُعاد تلقائياً)
manually_stopped_bots = set()
USERS_FILE = os.path.join(BASE_DIR, "users.json")
REMEMBER_TOKENS_FILE = os.path.join(BASE_DIR, "remember_tokens.json")
BOTS_CONFIG_FILE = os.path.join(BASE_DIR, "bots_config.json")
PIDS_FILE = os.path.join(BASE_DIR, "pids.json")

# الحساب الرئيسي (المسؤول)
ADMIN_USERNAME = "OMAR_ADMIN"
ADMIN_PASSWORD = "OMAR_2026_BRO"

# ============== Keep-Alive System ==============

def keep_alive_ping():
    """نظام Keep-Alive صامت تماماً - يعمل في الخلفية فقط ولا يؤثر على الواجهة"""
    while True:
        try:
            # الانتظار لمدة 10 دقائق
            time.sleep(600)
            
            # الحصول على رابط الموقع من متغيرات البيئة الخاصة بـ Render
            own_url = os.environ.get("RENDER_EXTERNAL_URL")
            if own_url:
                if not own_url.startswith("http"):
                    own_url = f"https://{own_url}"
                
                # إرسال طلب صامت تماماً مع User-Agent مخصص
                # هذا الطلب يتم من السيرفر إلى نفسه ولا يراه المتصفح أبداً
                requests.get(
                    f"{own_url}/api/ping", 
                    headers={"User-Agent": "Internal-Keep-Alive-System-Silent"}, 
                    timeout=10,
                    verify=False # لتجنب مشاكل SSL في بعض البيئات
                )
        except Exception:
            pass

# ============== Bot Auto-Restart System ==============

def bot_watchdog():
    """مراقب البوتات - يعيد تشغيلها تلقائياً إذا توقفت بدون أمر من المستخدم"""
    while True:
        try:
            time.sleep(30)  # فحص كل 30 ثانية
            config = load_bots_config()
            
            for bot_name, bot_info in list(config.items()):
                # تخطي البوتات التي أوقفها المستخدم يدوياً
                if bot_name in manually_stopped_bots:
                    continue
                
                # تخطي البوتات التي حالتها "stopped" في الإعدادات
                if bot_info.get("status") == "stopped":
                    continue
                
                # التحقق من أن البوت يجب أن يكون شغالاً
                if bot_info.get("status") != "running":
                    continue
                
                # فحص إذا كان البوت متوقفاً
                is_running = False
                if bot_name in TELEGRAM_BOTS:
                    proc_info = TELEGRAM_BOTS[bot_name]
                    proc = proc_info.get("process")
                    if proc and proc.poll() is None:
                        is_running = True
                
                # إعادة التشغيل إذا كان متوقفاً
                if not is_running:
                    token = bot_info.get("token", "")
                    script_path = bot_info.get("script_path", "")
                    
                    if token or script_path:
                        try:
                            restart_bot(bot_name, token, script_path)
                        except Exception as e:
                            pass
        except Exception:
            pass

def restart_bot(bot_name, token="", script_path=""):
    """إعادة تشغيل بوت محدد"""
    try:
        log_path = os.path.join(BASE_DIR, f"{bot_name}.log")
        
        with open(log_path, "a", encoding='utf-8') as log_file:
            log_file.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WATCHDOG] إعادة تشغيل البوت تلقائياً...\n")
        
        log_file = open(log_path, "a", encoding='utf-8')
        
        if script_path and os.path.exists(script_path):
            proc = subprocess.Popen(
                [sys.executable, "-u", script_path],
                stdout=log_file,
                stderr=log_file,
                cwd=os.path.dirname(script_path)
            )
        elif token:
            runner_path = os.path.join(BASE_DIR, "telegram_bot_runner.py")
            if os.path.exists(runner_path):
                proc = subprocess.Popen(
                    [sys.executable, "-u", runner_path, token, bot_name],
                    stdout=log_file,
                    stderr=log_file
                )
            else:
                return
        else:
            return
        
        TELEGRAM_BOTS[bot_name] = {
            "process": proc,
            "token": token,
            "log": log_path,
            "script_path": script_path
        }
        
        # تحديث الإعدادات
        config = load_bots_config()
        if bot_name in config:
            config[bot_name]["status"] = "running"
            config[bot_name]["last_restart"] = datetime.now().isoformat()
            save_bots_config(config)
            
    except Exception as e:
        pass

# ============== PID Management ==============

def save_pids():
    """حفظ أرقام العمليات"""
    pids = {}
    for key, proc in running_procs.items():
        try:
            if proc.poll() is None:
                pids[key] = proc.pid
        except:
            pass
    with open(PIDS_FILE, "w") as f:
        json.dump(pids, f)

# ============== Helper Functions ==============

def init_users_db():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            admin_data = {
                ADMIN_USERNAME: {
                    "password": hash_password(ADMIN_PASSWORD),
                    "created_at": datetime.now().isoformat(),
                    "last_login": None,
                    "theme": "premium",
                    "is_admin": True,
                    "can_create_users": True
                }
            }
            json.dump(admin_data, f, indent=2)
    else:
        # التحقق من وجود حساب المسؤول وتحديثه إذا لزم
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        
        # إضافة حساب المسؤول الجديد إذا لم يكن موجوداً
        if ADMIN_USERNAME not in users:
            users[ADMIN_USERNAME] = {
                "password": hash_password(ADMIN_PASSWORD),
                "created_at": datetime.now().isoformat(),
                "last_login": None,
                "theme": "premium",
                "is_admin": True,
                "can_create_users": True
            }
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=2)

def init_tokens_db():
    if not os.path.exists(REMEMBER_TOKENS_FILE):
        with open(REMEMBER_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_remember_token(username):
    init_tokens_db()
    with open(REMEMBER_TOKENS_FILE, "r", encoding="utf-8") as f:
        tokens = json.load(f)
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=30)).isoformat()
    tokens[token] = {
        "username": username,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires,
        "last_used": datetime.now().isoformat()
    }
    with open(REMEMBER_TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    return token

def validate_remember_token(token):
    if not os.path.exists(REMEMBER_TOKENS_FILE):
        return None
    with open(REMEMBER_TOKENS_FILE, "r", encoding="utf-8") as f:
        tokens = json.load(f)
    if token not in tokens:
        return None
    token_data = tokens[token]
    expires_at = datetime.fromisoformat(token_data["expires_at"])
    if datetime.now() > expires_at:
        del tokens[token]
        with open(REMEMBER_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)
        return None
    token_data["last_used"] = datetime.now().isoformat()
    tokens[token] = token_data
    with open(REMEMBER_TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    return token_data["username"]

def delete_remember_token(token):
    if not os.path.exists(REMEMBER_TOKENS_FILE):
        return
    with open(REMEMBER_TOKENS_FILE, "r", encoding="utf-8") as f:
        tokens = json.load(f)
    if token in tokens:
        del tokens[token]
        with open(REMEMBER_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)

def delete_all_user_tokens(username):
    if not os.path.exists(REMEMBER_TOKENS_FILE):
        return
    with open(REMEMBER_TOKENS_FILE, "r", encoding="utf-8") as f:
        tokens = json.load(f)
    tokens_to_delete = [t for t, d in tokens.items() if d["username"] == username]
    for t in tokens_to_delete:
        del tokens[t]
    with open(REMEMBER_TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)

def register_user(username, password, created_by_admin=False):
    init_users_db()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    if username in users:
        return False, "المستخدم موجود بالفعل"
    if len(password) < 6:
        return False, "كلمة المرور يجب أن تكون 6 أحرف على الأقل"
    users[username] = {
        "password": hash_password(password),
        "created_at": datetime.now().isoformat(),
        "last_login": None,
        "theme": "blue",
        "is_admin": username == ADMIN_USERNAME,
        "created_by_admin": created_by_admin,
        "created_by": session.get('username') if 'username' in session else None
    }
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    user_dir = os.path.join(USERS_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    return True, "تم إنشاء الحساب بنجاح"

def authenticate_user(username, password):
    init_users_db()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    if username not in users:
        return False, "المستخدم غير موجود"
    if users[username]["password"] != hash_password(password):
        return False, "كلمة المرور غير صحيحة"
    users[username]["last_login"] = datetime.now().isoformat()
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    return True, "تم تسجيل الدخول بنجاح"

def is_admin(username):
    init_users_db()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    if username in users:
        return users[username].get("is_admin", False)
    return False

def get_user_servers_dir(username):
    return os.path.join(USERS_DIR, username, "SERVERS")

def ensure_user_servers_dir():
    if 'username' not in session:
        return None
    user_dir = get_user_servers_dir(session['username'])
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def sanitize_folder_name(name):
    if not name: return ""
    name = name.strip()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^A-Za-z0-9\-\_\.]", "", name)
    return name[:200]

def sanitize_filename(name):
    if not name: return ""
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9\-\_\.]", "", name)
    return name[:200]

def ensure_meta(folder):
    user_servers_dir = ensure_user_servers_dir()
    if not user_servers_dir:
        return None
    meta_path = os.path.join(user_servers_dir, folder, "meta.json")
    if not os.path.exists(meta_path):
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"display_name": folder, "startup_file": ""}, f)
    return meta_path

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def load_servers_list():
    if 'username' not in session:
        return []
    user_servers_dir = ensure_user_servers_dir()
    if not user_servers_dir or not os.path.exists(user_servers_dir):
        return []
    try:
        entries = [d for d in os.listdir(user_servers_dir)
                   if os.path.isdir(os.path.join(user_servers_dir, d))]
    except:
        entries = []
    servers = []
    for i, folder in enumerate(entries, start=1):
        ensure_meta(folder)
        meta_path = os.path.join(user_servers_dir, folder, "meta.json")
        display_name, startup_file = folder, ""
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                display_name = meta.get("display_name", folder)
                startup_file = meta.get("startup_file", "")
        except:
            pass
        servers.append({
            "id": i,
            "title": display_name,
            "folder": folder,
            "subtitle": f"Node-{i} · Local",
            "startup_file": startup_file
        })
    return servers

# ============== Routes ==============

@app.before_request
def check_remember_token():
    if 'username' in session:
        return
    remember_token = request.cookies.get('remember_token')
    if remember_token:
        username = validate_remember_token(remember_token)
        if username:
            session['username'] = username
            session.permanent = True

@app.route("/")
def home():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    if is_admin(session['username']):
        return send_from_directory(BASE_DIR, "admin_panel.html")
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/index.html")
def serve_index():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    if is_admin(session['username']):
        return redirect(url_for('home'))
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/login")
def login_page():
    if 'username' in session:
        return redirect(url_for('home'))
    return send_from_directory(BASE_DIR, "login.html")

@app.route("/admin")
def admin_panel():
    if 'username' not in session or not is_admin(session['username']):
        return redirect(url_for('login_page'))
    return send_from_directory(BASE_DIR, "admin_panel.html")

# ============== Keep-Alive API ==============

@app.route("/api/ping")
def ping():
    """نقطة نهاية Keep-Alive - تمنع الموقع من النوم"""
    return jsonify({
        "status": "alive",
        "timestamp": datetime.now().isoformat(),
        "uptime": "running"
    })

# ============== Auth APIs ==============

@app.route("/api/register", methods=["POST"])
def api_register():
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"success": False, "message": "يرجى ملء جميع الحقول"})
    success, message = register_user(username, password, created_by_admin=True)
    return jsonify({"success": success, "message": message})

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    remember = data.get("remember", False)
    if not username or not password:
        return jsonify({"success": False, "message": "يرجى ملء جميع الحقول"})
    success, message = authenticate_user(username, password)
    if success:
        session['username'] = username
        session.permanent = True
        response = make_response(jsonify({
            "success": True,
            "message": message,
            "is_admin": is_admin(username)
        }))
        if remember:
            token = create_remember_token(username)
            response.set_cookie(
                'remember_token', token,
                max_age=30*24*60*60,
                httponly=True,
                samesite='Lax'
            )
        return response
    return jsonify({"success": False, "message": message})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    remember_token = request.cookies.get('remember_token')
    if remember_token:
        delete_remember_token(remember_token)
    session.clear()
    response = make_response(jsonify({"success": True}))
    response.delete_cookie('remember_token')
    return response

@app.route("/api/current_user")
def api_current_user():
    if 'username' not in session:
        return jsonify({"success": False, "logged_in": False}), 200
    return jsonify({
        "success": True,
        "logged_in": True,
        "username": session['username'],
        "is_admin": is_admin(session['username'])
    })

@app.route("/api/me")
def api_me():
    return api_current_user()

# ============== Server Management ==============

@app.route("/servers/list")
def servers_list():
    if 'username' not in session:
        return jsonify([]), 401
    servers = load_servers_list()
    user_servers_dir = ensure_user_servers_dir()
    for s in servers:
        proc_key = f"{session['username']}_{s['folder']}"
        is_running = False
        if proc_key in running_procs:
            try:
                p = running_procs[proc_key]
                if p.poll() is None:
                    is_running = True
                else:
                    del running_procs[proc_key]
            except:
                pass
        s["running"] = is_running
        if user_servers_dir:
            log_path = os.path.join(user_servers_dir, s['folder'], "server.log")
            s["has_log"] = os.path.exists(log_path)
    return jsonify(servers)

@app.route("/servers/create", methods=["POST"])
def create_server():
    if 'username' not in session:
        return jsonify({"success": False}), 401
    data = request.get_json()
    name = sanitize_folder_name(data.get("name", ""))
    if not name:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    user_servers_dir = ensure_user_servers_dir()
    server_dir = os.path.join(user_servers_dir, name)
    if os.path.exists(server_dir):
        return jsonify({"success": False, "message": "السيرفر موجود بالفعل"})
    os.makedirs(server_dir, exist_ok=True)
    with open(os.path.join(server_dir, "meta.json"), "w") as f:
        json.dump({"display_name": data.get("name", name), "startup_file": ""}, f)
    return jsonify({"success": True})

@app.route("/servers/delete/<folder>", methods=["POST"])
def delete_server(folder):
    if 'username' not in session:
        return jsonify({"success": False}), 401
    user_servers_dir = ensure_user_servers_dir()
    server_dir = os.path.join(user_servers_dir, folder)
    if not server_dir.startswith(user_servers_dir):
        return jsonify({"success": False}), 403
    proc_key = f"{session['username']}_{folder}"
    if proc_key in running_procs:
        try:
            p = psutil.Process(running_procs[proc_key].pid)
            for child in p.children(recursive=True):
                child.kill()
            p.kill()
        except:
            pass
        del running_procs[proc_key]
    import shutil
    if os.path.exists(server_dir):
        shutil.rmtree(server_dir)
    return jsonify({"success": True})

@app.route("/server/control/<folder>/<act>", methods=["POST"])
def server_control(folder, act):
    if 'username' not in session:
        return jsonify({"success": False, "message": "غير مصرح"}), 401
    proc_key = f"{session['username']}_{folder}"
    if proc_key in running_procs:
        try:
            p = psutil.Process(running_procs[proc_key].pid)
            for child in p.children(recursive=True):
                child.kill()
            p.kill()
        except:
            pass
        if act == "stop":
            del running_procs[proc_key]
    if act == "stop":
        return jsonify({"success": True})
    user_servers_dir = ensure_user_servers_dir()
    log_path = os.path.join(user_servers_dir, folder, "server.log")
    open(log_path, "w").close()
    meta_path = ensure_meta(folder)
    if not meta_path:
        return jsonify({"success": False, "message": "مجلد غير موجود"})
    with open(meta_path, "r") as f:
        startup = json.load(f).get("startup_file")
    if not startup:
        return jsonify({"success": False, "message": "No main file set."})
    if not os.path.exists(os.path.join(user_servers_dir, folder, startup)):
        return jsonify({"success": False, "message": "الملف غير موجود"})
    log_file = open(log_path, "a")
    proc = subprocess.Popen(
        [sys.executable, "-u", startup],
        cwd=os.path.join(user_servers_dir, folder),
        stdout=log_file,
        stderr=log_file
    )
    running_procs[proc_key] = proc
    save_pids()
    return jsonify({"success": True})

@app.route("/server/log/<folder>")
def server_log(folder):
    if 'username' not in session:
        return jsonify({"content": ""}), 401
    user_servers_dir = ensure_user_servers_dir()
    log_path = os.path.join(user_servers_dir, folder, "server.log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return jsonify({"content": content})
    except:
        return jsonify({"content": ""})

@app.route("/server/status/<folder>")
def server_status(folder):
    if 'username' not in session:
        return jsonify({"running": False}), 401
    proc_key = f"{session['username']}_{folder}"
    is_running = False
    if proc_key in running_procs:
        try:
            if running_procs[proc_key].poll() is None:
                is_running = True
        except:
            pass
    return jsonify({"running": is_running})

# ============== File Management ==============

@app.route("/files/list/<folder>")
def list_files(folder):
    if 'username' not in session:
        return jsonify([]), 401
    user_servers_dir = ensure_user_servers_dir()
    p = os.path.join(user_servers_dir, folder)
    files = []
    if os.path.exists(p):
        for f in os.listdir(p):
            if f in ["meta.json", "server.log"]:
                continue
            f_path = os.path.join(p, f)
            if os.path.isfile(f_path):
                files.append({"name": f, "size": f"{os.path.getsize(f_path) / 1024:.1f} KB"})
    return jsonify(files)

@app.route("/files/content/<folder>/<filename>")
def get_file_content(folder, filename):
    if 'username' not in session:
        return jsonify({"content": ""}), 401
    user_servers_dir = ensure_user_servers_dir()
    file_path = os.path.join(user_servers_dir, folder, filename)
    if not file_path.startswith(user_servers_dir):
        return jsonify({"content": ""}), 403
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return jsonify({"content": f.read()})
    except:
        return jsonify({"content": ""})

@app.route("/files/save/<folder>/<filename>", methods=["POST"])
def save_file_content(folder, filename):
    if 'username' not in session:
        return jsonify({"success": False}), 401
    user_servers_dir = ensure_user_servers_dir()
    file_path = os.path.join(user_servers_dir, folder, filename)
    if not file_path.startswith(user_servers_dir):
        return jsonify({"success": False}), 403
    data = request.json
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(data.get('content', ''))
    return jsonify({"success": True})

@app.route("/files/upload/<folder>", methods=["POST"])
def upload_file(folder):
    if 'username' not in session:
        return jsonify({"success": False}), 401
    user_servers_dir = ensure_user_servers_dir()
    uploaded_files = request.files.getlist('files[]')
    results = []
    for f in uploaded_files:
        if f and f.filename:
            safe_name = sanitize_filename(f.filename)
            save_path = os.path.join(user_servers_dir, folder, safe_name)
            f.save(save_path)
            results.append({"name": safe_name, "size": f"{os.path.getsize(save_path) / 1024:.2f} KB"})
    return jsonify({"success": True, "message": f"تم رفع {len(results)} ملف بنجاح", "uploaded_files": results})

@app.route("/files/upload-single/<folder>", methods=["POST"])
def upload_single_file(folder):
    if 'username' not in session:
        return jsonify({"success": False}), 401
    user_servers_dir = ensure_user_servers_dir()
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "لم يتم اختيار ملف"})
    f = request.files['file']
    if f and f.filename:
        safe_name = sanitize_filename(f.filename)
        save_path = os.path.join(user_servers_dir, folder, safe_name)
        f.save(save_path)
        return jsonify({"success": True, "message": "تم رفع الملف بنجاح", "file": {"name": safe_name, "size": f"{os.path.getsize(save_path) / 1024:.2f} KB"}})
    return jsonify({"success": False, "message": "فشل رفع الملف"})

@app.route("/files/rename/<folder>", methods=["POST"])
def rename_file(folder):
    if 'username' not in session:
        return jsonify({"success": False}), 401
    user_servers_dir = ensure_user_servers_dir()
    data = request.get_json()
    old_path = os.path.join(user_servers_dir, folder, data['old'])
    new_path = os.path.join(user_servers_dir, folder, data['new'])
    if not old_path.startswith(user_servers_dir) or not new_path.startswith(user_servers_dir):
        return jsonify({"success": False}), 403
    os.rename(old_path, new_path)
    return jsonify({"success": True})

@app.route("/files/delete/<folder>", methods=["POST"])
def delete_file(folder):
    if 'username' not in session:
        return jsonify({"success": False}), 401
    user_servers_dir = ensure_user_servers_dir()
    data = request.get_json()
    file_path = os.path.join(user_servers_dir, folder, data['name'])
    if not file_path.startswith(user_servers_dir):
        return jsonify({"success": False}), 403
    os.remove(file_path)
    return jsonify({"success": True})

@app.route("/files/install/<folder>", methods=["POST"])
def install_req(folder):
    if 'username' not in session:
        return jsonify({"success": False}), 401
    user_servers_dir = ensure_user_servers_dir()
    req_path = os.path.join(user_servers_dir, folder, "requirements.txt")
    if not os.path.exists(req_path):
        return jsonify({"success": False, "message": "ملف requirements.txt غير موجود"})
    log_path = os.path.join(user_servers_dir, folder, "server.log")
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("[SYSTEM] Starting Installation...\n")
        log_file.write(f"[SYSTEM] Installing packages from: {req_path}\n")
        log_file.write("="*50 + "\n")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=os.path.join(user_servers_dir, folder),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        with open(log_path, "a", encoding="utf-8") as log_file:
            for line in proc.stdout:
                log_file.write(line)
                log_file.flush()
        proc.wait()
        with open(log_path, "a", encoding="utf-8") as log_file:
            if proc.returncode == 0:
                log_file.write("\n" + "="*50 + "\n")
                log_file.write("[SYSTEM] Installation completed successfully!\n")
            else:
                log_file.write(f"\n[SYSTEM] Installation failed with exit code: {proc.returncode}\n")
        return jsonify({"success": True, "message": "تم بدء التثبيت"})
    except Exception as e:
        return jsonify({"success": False, "message": f"فشل: {str(e)}"})

@app.route("/server/set-startup/<folder>", methods=["POST"])
def set_startup(folder):
    if 'username' not in session:
        return jsonify({"success": False}), 401
    meta_path = ensure_meta(folder)
    if not meta_path:
        return jsonify({"success": False}), 404
    with open(meta_path, "r", encoding="utf-8") as f:
        m = json.load(f)
    m["startup_file"] = request.get_json().get('file', '')
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(m, f)
    return jsonify({"success": True})

# ============== Admin APIs ==============

@app.route("/api/admin/users", methods=["GET"])
def get_all_users():
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    init_users_db()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    user_list = []
    for username, data in users.items():
        if username != ADMIN_USERNAME:
            user_list.append({
                "username": username,
                "created_at": data.get("created_at"),
                "last_login": data.get("last_login"),
                "created_by": data.get("created_by", "system")
            })
    return jsonify({"success": True, "users": user_list})

@app.route("/api/admin/delete-user", methods=["POST"])
def delete_user():
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    data = request.get_json()
    username_to_delete = data.get("username", "").strip()
    if not username_to_delete or username_to_delete == ADMIN_USERNAME:
        return jsonify({"success": False, "message": "لا يمكن حذف هذا المستخدم"})
    init_users_db()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    if username_to_delete not in users:
        return jsonify({"success": False, "message": "المستخدم غير موجود"})
    del users[username_to_delete]
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    user_dir = os.path.join(USERS_DIR, username_to_delete)
    if os.path.exists(user_dir):
        import shutil
        shutil.rmtree(user_dir)
    return jsonify({"success": True, "message": "تم حذف المستخدم بنجاح"})

# ============== Telegram Bot Management ==============

def load_bots_config():
    if os.path.exists(BOTS_CONFIG_FILE):
        with open(BOTS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_bots_config(config):
    with open(BOTS_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

@app.route("/api/telegram/start", methods=["POST"])
def start_telegram_bot():
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    data = request.get_json()
    token = data.get('token', '').strip()
    bot_name = data.get('name', 'telegram_bot').strip()
    script_path = data.get('script_path', '').strip()
    if not token and not script_path:
        return jsonify({"success": False, "message": "التوكن أو مسار السكربت مطلوب"})
    try:
        log_path = os.path.join(BASE_DIR, f"{bot_name}.log")
        log_file = open(log_path, "a", encoding='utf-8')
        if script_path and os.path.exists(script_path):
            proc = subprocess.Popen(
                [sys.executable, "-u", script_path],
                stdout=log_file,
                stderr=log_file,
                cwd=os.path.dirname(script_path)
            )
        else:
            proc = subprocess.Popen(
                [sys.executable, "-u", os.path.join(BASE_DIR, "telegram_bot_runner.py"), token, bot_name],
                stdout=log_file,
                stderr=log_file
            )
        TELEGRAM_BOTS[bot_name] = {"process": proc, "token": token, "log": log_path, "script_path": script_path}
        # إزالة من قائمة المتوقفة يدوياً عند التشغيل
        manually_stopped_bots.discard(bot_name)
        config = load_bots_config()
        config[bot_name] = {
            "token": token,
            "script_path": script_path,
            "status": "running",
            "started_at": datetime.now().isoformat()
        }
        save_bots_config(config)
        return jsonify({"success": True, "message": f"تم بدء البوت {bot_name}"})
    except Exception as e:
        return jsonify({"success": False, "message": f"خطأ: {str(e)}"})

@app.route("/api/telegram/stop", methods=["POST"])
def stop_telegram_bot():
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    data = request.get_json()
    bot_name = data.get('name', 'telegram_bot').strip()
    try:
        if bot_name in TELEGRAM_BOTS:
            proc = TELEGRAM_BOTS[bot_name]["process"]
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except:
                proc.kill()
            del TELEGRAM_BOTS[bot_name]
        # تسجيل أن المستخدم أوقفه يدوياً (لا يُعاد تلقائياً)
        manually_stopped_bots.add(bot_name)
        config = load_bots_config()
        if bot_name in config:
            config[bot_name]["status"] = "stopped"
            save_bots_config(config)
        return jsonify({"success": True, "message": f"تم إيقاف البوت {bot_name}"})
    except Exception as e:
        return jsonify({"success": False, "message": f"خطأ: {str(e)}"})

@app.route("/api/telegram/list", methods=["GET"])
def list_telegram_bots():
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    config = load_bots_config()
    bots_list = []
    for bot_name, bot_info in config.items():
        is_running = False
        if bot_name in TELEGRAM_BOTS:
            proc = TELEGRAM_BOTS[bot_name].get("process")
            if proc and proc.poll() is None:
                is_running = True
        bots_list.append({
            "name": bot_name,
            "status": "running" if is_running else "stopped",
            "started_at": bot_info.get("started_at"),
            "token": (bot_info.get("token", "")[:20] + "...") if bot_info.get("token") else "",
            "manually_stopped": bot_name in manually_stopped_bots
        })
    return jsonify({"success": True, "bots": bots_list})

@app.route("/api/telegram/logs/<bot_name>", methods=["GET"])
def get_bot_logs(bot_name):
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"content": ""}), 403
    log_path = os.path.join(BASE_DIR, f"{bot_name}.log")
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"content": content})
    except:
        return jsonify({"content": ""})

@app.route("/proxy/<int:port>/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy(port, path):
    try:
        if port < 1024 or port > 65535:
            return jsonify({"error": "Invalid port"}), 400
        query_string = request.query_string.decode('utf-8')
        url = f"http://localhost:{port}/{path}"
        if query_string:
            url += f"?{query_string}"
        headers = {key: value for key, value in request.headers if key != 'Host'}
        if request.method == "GET":
            resp = requests.get(url, headers=headers, timeout=30)
        elif request.method == "POST":
            resp = requests.post(url, data=request.get_data(), headers=headers, timeout=30)
        elif request.method == "PUT":
            resp = requests.put(url, data=request.get_data(), headers=headers, timeout=30)
        elif request.method == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=30)
        elif request.method == "PATCH":
            resp = requests.patch(url, data=request.get_data(), headers=headers, timeout=30)
        response = make_response(resp.content)
        response.status_code = resp.status_code
        for key, value in resp.headers.items():
            if key.lower() not in ['content-encoding', 'content-length']:
                response.headers[key] = value
        return response
    except ValueError:
        return jsonify({"error": "Invalid port number"}), 400
    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timeout"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Connection refused"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============== Startup ==============

def startup():
    """تهيئة النظام عند البدء"""
    init_users_db()
    init_tokens_db()
    
    # بدء نظام Keep-Alive في خيط منفصل
    ka_thread = threading.Thread(target=keep_alive_ping, daemon=True)
    ka_thread.start()
    
    # بدء مراقب البوتات في خيط منفصل
    watchdog_thread = threading.Thread(target=bot_watchdog, daemon=True)
    watchdog_thread.start()
    
    # إعادة تشغيل البوتات التي كانت تعمل قبل إعادة التشغيل
    config = load_bots_config()
    for bot_name, bot_info in config.items():
        if bot_info.get("status") == "running":
            token = bot_info.get("token", "")
            script_path = bot_info.get("script_path", "")
            try:
                restart_bot(bot_name, token, script_path)
            except:
                pass

# تشغيل startup عند بدء التطبيق
startup()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("SERVER_PORT", 21910)))
    app.run(host="0.0.0.0", port=port, debug=False)
