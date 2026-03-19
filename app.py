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
import signal
import shutil
import zipfile
from datetime import datetime, timedelta
from flask import Flask, send_from_directory, request, jsonify, session, redirect, url_for, render_template_string

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "USERS")
os.makedirs(USERS_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB

DB_FILE = os.path.join(BASE_DIR, "db.json")
ADMIN_USERNAME = "OMAR_ADMIN"
ADMIN_PASSWORD = "OMAR_2026_BRO"

# ============== PORT MANAGEMENT ==============
USED_PORTS = set()
PORT_RANGE_START = 8100
PORT_RANGE_END = 9000

def get_assigned_port():
    """يعطي port ثابت ومخصص لكل سيرفر من نطاق محدد"""
    # جمع البورتات المستخدمة من قاعدة البيانات
    used = set()
    for srv in db.get("servers", {}).values():
        if srv.get("port"):
            used.add(srv["port"])
    
    for port in range(PORT_RANGE_START, PORT_RANGE_END):
        if port not in used:
            # تحقق أن البورت غير مستخدم فعلياً
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.1)
                result = s.connect_ex(('127.0.0.1', port))
                s.close()
                if result != 0:  # البورت حر
                    return port
            except:
                return port
    
    # fallback: بورت عشوائي
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def is_port_in_use(port):
    """فحص إذا كان البورت مستخدماً"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.1)
        result = s.connect_ex(('127.0.0.1', port))
        s.close()
        return result == 0
    except:
        return False

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "users": {
            ADMIN_USERNAME: {
                "password": hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest(),
                "is_admin": True,
                "created_at": str(datetime.now()),
                "max_servers": 10,
                "expiry_days": 365
            }
        },
        "servers": {},
        "logs": []
    }

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4)

db = load_db()

# Keep-Alive
def keep_alive():
    while True:
        try:
            time.sleep(300)
            requests.get("http://127.0.0.1:5000/api/ping", timeout=5)
        except:
            pass

threading.Thread(target=keep_alive, daemon=True).start()

# Process Monitor
def monitor_processes():
    while True:
        try:
            for folder, srv in list(db["servers"].items()):
                if srv.get("status") == "Running" and srv.get("pid"):
                    try:
                        p = psutil.Process(srv["pid"])
                        if not p.is_running():
                            db["servers"][folder]["status"] = "Stopped"
                            db["servers"][folder]["pid"] = None
                            save_db(db)
                    except:
                        db["servers"][folder]["status"] = "Stopped"
                        db["servers"][folder]["pid"] = None
                        save_db(db)
        except:
            pass
        time.sleep(10)

threading.Thread(target=monitor_processes, daemon=True).start()

def get_current_user():
    if "username" in session:
        return db["users"].get(session["username"])
    return None

def get_user_servers_dir(username):
    path = os.path.join(USERS_DIR, username, "SERVERS")
    os.makedirs(path, exist_ok=True)
    return path

def is_admin(username):
    u = db["users"].get(username)
    return u.get("is_admin", False) if u else False

def get_ip():
    try:
        return socket.gethostbyname(socket.gethostname())
    except:
        return "127.0.0.1"

# ============== ROUTES ==============

@app.route('/')
def home():
    if 'username' not in session:
        return redirect('/login')
    user = get_current_user()
    if user and user.get("is_admin"):
        return redirect('/admin')
    return redirect('/dashboard')

@app.route('/login')
def login_page():
    if 'username' in session:
        return redirect('/')
    with open(os.path.join(BASE_DIR, 'login.html'), 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect('/login')
    with open(os.path.join(BASE_DIR, 'index.html'), 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/admin')
def admin_panel():
    if 'username' not in session or not is_admin(session['username']):
        return redirect('/login')
    with open(os.path.join(BASE_DIR, 'admin_panel.html'), 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/api/ping')
def ping():
    return jsonify({"status": "alive", "time": str(datetime.now())})

# ============== AUTH APIs ==============

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    user = db["users"].get(username)
    if user and user["password"] == hashlib.sha256(password.encode()).hexdigest():
        session['username'] = username
        session.permanent = True
        user["last_login"] = str(datetime.now())
        save_db(db)
        return jsonify({
            "success": True,
            "redirect": "/admin" if user.get("is_admin") else "/dashboard"
        })
    return jsonify({"success": False, "message": "خطأ في البيانات"})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('username', None)
    return jsonify({"success": True})

@app.route('/api/current_user')
def api_current_user():
    if "username" in session:
        u = db["users"].get(session["username"])
        if u:
            return jsonify({
                "success": True,
                "username": session["username"],
                "is_admin": u.get("is_admin", False)
            })
    return jsonify({"success": False})

# ============== SERVER MANAGEMENT ==============

@app.route('/api/servers')
def list_servers():
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    user_servers = []
    for folder, srv in db["servers"].items():
        if srv["owner"] == session["username"]:
            uptime_str = "0 ثانية"
            if srv.get("status") == "Running" and srv.get("start_time"):
                diff = time.time() - srv["start_time"]
                days = int(diff // 86400)
                hours = int((diff % 86400) // 3600)
                mins = int((diff % 3600) // 60)
                parts = []
                if days > 0: parts.append(f"{days} يوم")
                if hours > 0: parts.append(f"{hours} ساعة")
                if mins > 0: parts.append(f"{mins} دقيقة")
                uptime_str = " و ".join(parts) if parts else "أقل من دقيقة"
                
            user_servers.append({
                "folder": folder,
                "title": srv["name"],
                "subtitle": f"سيرفر {srv.get('type', 'Python')}",
                "startup_file": srv.get("startup_file"),
                "status": srv.get("status", "Stopped"),
                "uptime": uptime_str,
                "port": srv.get("port", "N/A")
            })
    
    user = db["users"][session["username"]]
    max_srv = user.get("max_servers", 3)
    
    return jsonify({
        "success": True,
        "servers": user_servers,
        "stats": {
            "used": len(user_servers),
            "total": max_srv,
            "expiry": user.get("expiry_days", 30)
        }
    })

@app.route('/api/server/add', methods=['POST'])
def add_server():
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    user = db["users"][session["username"]]
    user_srv_count = len([s for s in db["servers"].values() if s["owner"] == session["username"]])
    if user_srv_count >= user.get("max_servers", 3):
        return jsonify({"success": False, "message": "وصلت للحد الأقصى من السيرفرات"})
    
    data = request.get_json()
    name = data.get("name", "New Server").strip()
    if not name: name = "Server_" + secrets.token_hex(2)
    
    folder = f"{session['username']}_{re.sub(r'[^a-zA-Z0-9]', '', name)}_{int(time.time())}"
    path = os.path.join(get_user_servers_dir(session["username"]), folder)
    os.makedirs(path, exist_ok=True)
    
    # تعيين بورت خاص ومخصص لهذا السيرفر
    assigned_port = get_assigned_port()
    
    db["servers"][folder] = {
        "name": name,
        "owner": session["username"],
        "path": path,
        "type": "Python",
        "status": "Stopped",
        "created_at": str(datetime.now()),
        "startup_file": "main.py",
        "pid": None,
        "port": assigned_port
    }
    save_db(db)
    return jsonify({"success": True, "message": f"تم إنشاء السيرفر على البورت {assigned_port}"})

@app.route('/api/server/action/<folder>/<action>', methods=['POST'])
def server_action(folder, action):
    if "username" not in session:
        return jsonify({"success": False}), 401
    
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]:
        return jsonify({"success": False, "message": "غير مصرح"})
    
    if action == "start":
        if srv.get("status") == "Running":
            return jsonify({"success": False, "message": "السيرفر يعمل بالفعل"})
        
        main_file = srv.get("startup_file", "main.py")
        file_path = os.path.join(srv["path"], main_file)
        
        if not os.path.exists(file_path):
            for f in ["app.py", "main.py", "index.js", "index.php", "index.html"]:
                if os.path.exists(os.path.join(srv["path"], f)):
                    main_file = f
                    srv["startup_file"] = f
                    file_path = os.path.join(srv["path"], f)
                    break
            else:
                return jsonify({"success": False, "message": "لم يتم العثور على ملف تشغيل"})
        
        # البورت المخصص لهذا السيرفر
        port = srv.get("port")
        if not port:
            port = get_assigned_port()
            srv["port"] = port
            save_db(db)
        
        # التحقق من أن البورت المخصص غير مستخدم من سيرفر آخر
        if is_port_in_use(port):
            # البورت مشغول، تحقق إذا كان من نفس السيرفر
            if not srv.get("pid") or not psutil.pid_exists(srv.get("pid", 0)):
                # البورت مشغول من مصدر آخر، أعطه بورت جديد
                new_port = get_assigned_port()
                srv["port"] = new_port
                port = new_port
                save_db(db)
        
        env = os.environ.copy()
        env["PORT"] = str(port)
        env["SERVER_PORT"] = str(port)
        env["HOST_PORT"] = str(port)
        
        cmd = []
        if main_file.endswith('.py'):
            cmd = ["python3", "-u", main_file]
            srv["type"] = "Python"
        elif main_file.endswith('.js'):
            cmd = ["node", main_file]
            srv["type"] = "Node.js"
        elif main_file.endswith('.php'):
            cmd = ["php", "-S", f"0.0.0.0:{port}", main_file]
            srv["type"] = "PHP"
        elif main_file.endswith('.html'):
            cmd = ["python3", "-m", "http.server", str(port)]
            srv["type"] = "Static HTML"
        else:
            cmd = ["python3", "-u", main_file]
            
        try:
            log_file = open(os.path.join(srv["path"], "out.log"), "w", encoding='utf-8')
            p = subprocess.Popen(cmd, cwd=srv["path"], stdout=log_file, stderr=subprocess.STDOUT, env=env)
            srv["status"] = "Running"
            srv["pid"] = p.pid
            srv["start_time"] = time.time()
            save_db(db)
            return jsonify({"success": True, "message": f"✅ تم تشغيل السيرفر على البورت {port}"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
            
    elif action == "stop":
        if srv.get("pid"):
            try:
                parent = psutil.Process(srv["pid"])
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()
            except:
                pass
            srv["status"] = "Stopped"
            srv["pid"] = None
            srv["start_time"] = None
            save_db(db)
        return jsonify({"success": True, "message": "⏹ تم إيقاف السيرفر"})
        
    elif action == "restart":
        server_action(folder, "stop")
        time.sleep(1)
        return server_action(folder, "start")
        
    elif action == "delete":
        server_action(folder, "stop")
        try:
            shutil.rmtree(srv["path"])
            del db["servers"][folder]
            save_db(db)
            return jsonify({"success": True, "message": "🗑️ تم حذف السيرفر نهائياً"})
        except:
            return jsonify({"success": False, "message": "فشل الحذف"})
            
    return jsonify({"success": False})

@app.route('/api/server/stats/<folder>')
def server_stats(folder):
    if "username" not in session: return jsonify({}), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify({})
    
    logs = ""
    log_path = os.path.join(srv["path"], "out.log")
    if os.path.exists(log_path):
        with open(log_path, "r", errors='ignore') as f:
            logs = f.read()[-8000:]
            
    mem = "0 MB"
    cpu = "0%"
    if srv.get("pid"):
        try:
            p = psutil.Process(srv["pid"])
            mem = f"{p.memory_info().rss / 1024 / 1024:.1f} MB"
            cpu = f"{p.cpu_percent(interval=0.1):.1f}%"
        except:
            pass
    
    # حالة Online/Offline
    status = srv.get("status", "Stopped")
    online_status = "Online" if status == "Running" else "Offline"
            
    return jsonify({
        "status": status,
        "online_status": online_status,
        "logs": logs,
        "mem": mem,
        "cpu": cpu,
        "ip": get_ip(),
        "port": srv.get("port", "N/A"),
        "uptime": srv.get("start_time")
    })

# ============== FILE MANAGER ==============

@app.route('/api/files/list/<folder>')
def list_files(folder):
    if "username" not in session: return jsonify([]), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify([])
    
    files = []
    for f in os.listdir(srv["path"]):
        if f == "out.log": continue
        path = os.path.join(srv["path"], f)
        files.append({
            "name": f,
            "size": f"{os.path.getsize(path) / 1024:.1f} KB",
            "is_dir": os.path.isdir(path),
            "modified": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        })
    return jsonify(files)

@app.route('/api/files/upload/<folder>', methods=['POST'])
def upload_files(folder):
    if "username" not in session: return jsonify({"success": False}), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify({"success": False})
    
    files = request.files.getlist("files[]")
    uploaded = []
    extracted = []
    
    for file in files:
        if file:
            filename = re.sub(r'[^a-zA-Z0-9._\-]', '', file.filename)
            if not filename:
                filename = f"file_{int(time.time())}"
            file_path = os.path.join(srv["path"], filename)
            file.save(file_path)
            uploaded.append(filename)
            
            # فك ضغط ملفات ZIP تلقائياً
            if filename.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(srv["path"])
                    os.remove(file_path)  # حذف ملف ZIP بعد الفك
                    extracted.append(filename)
                except Exception as e:
                    pass

            if filename in ["main.py", "app.py", "index.js", "index.php", "index.html"]:
                srv["startup_file"] = filename
    
    save_db(db)
    msg = f"✅ تم رفع {len(uploaded)} ملف"
    if extracted:
        msg += f" وفك ضغط {len(extracted)} ملف ZIP"
    return jsonify({"success": True, "message": msg, "uploaded_files": uploaded, "extracted": extracted})

@app.route('/api/files/content/<folder>/<filename>')
def file_content(folder, filename):
    if "username" not in session: return jsonify({}), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify({})
    
    path = os.path.join(srv["path"], re.sub(r'[^a-zA-Z0-9._\-]', '', filename))
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return jsonify({"content": f.read()})
        except:
            return jsonify({"content": "لا يمكن قراءة هذا النوع من الملفات"})
    return jsonify({"content": ""})

@app.route('/api/files/save/<folder>/<filename>', methods=['POST'])
def save_file(folder, filename):
    if "username" not in session: return jsonify({"success": False}), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify({"success": False})
    
    data = request.get_json()
    path = os.path.join(srv["path"], re.sub(r'[^a-zA-Z0-9._\-]', '', filename))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(data.get("content", ""))
    return jsonify({"success": True, "message": "✅ تم حفظ الملف بنجاح"})

@app.route('/api/files/delete/<folder>', methods=['POST'])
def delete_file(folder):
    if "username" not in session: return jsonify({"success": False}), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify({"success": False})
    
    data = request.get_json()
    filenames = data.get("names", [])
    if not filenames and data.get("name"):
        filenames = [data.get("name")]
        
    deleted = []
    for filename in filenames:
        safe_name = re.sub(r'[^a-zA-Z0-9._\-]', '', filename)
        path = os.path.join(srv["path"], safe_name)
        if os.path.exists(path):
            if os.path.isdir(path): shutil.rmtree(path)
            else: os.remove(path)
            deleted.append(filename)
            
    return jsonify({"success": True, "message": f"🗑️ تم حذف {len(deleted)} ملف"})

@app.route('/api/files/rename/<folder>', methods=['POST'])
def rename_file(folder):
    if "username" not in session: return jsonify({"success": False}), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify({"success": False})
    
    data = request.get_json()
    old_name = re.sub(r'[^a-zA-Z0-9._\-]', '', data.get("old_name", ""))
    new_name = re.sub(r'[^a-zA-Z0-9._\-]', '', data.get("new_name", ""))
    
    if not old_name or not new_name:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    
    old_path = os.path.join(srv["path"], old_name)
    new_path = os.path.join(srv["path"], new_name)
    
    if os.path.exists(old_path) and not os.path.exists(new_path):
        os.rename(old_path, new_path)
        return jsonify({"success": True, "message": f"✅ تم تغيير الاسم إلى {new_name}"})
    return jsonify({"success": False, "message": "فشل تغيير الاسم"})

@app.route('/api/files/create/<folder>', methods=['POST'])
def create_file(folder):
    if "username" not in session: return jsonify({"success": False}), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify({"success": False})
    
    data = request.get_json()
    filename = re.sub(r'[^a-zA-Z0-9._\-]', '', data.get("filename", ""))
    content = data.get("content", "")
    
    if not filename:
        return jsonify({"success": False, "message": "اسم الملف غير صالح"})
    
    path = os.path.join(srv["path"], filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return jsonify({"success": True, "message": f"✅ تم إنشاء الملف {filename}"})

@app.route('/api/server/install/<folder>', methods=['POST'])
def install_requirements(folder):
    if "username" not in session: return jsonify({"success": False}), 401
    srv = db["servers"].get(folder)
    if not srv or srv["owner"] != session["username"]: return jsonify({"success": False})
    
    req_file = os.path.join(srv["path"], "requirements.txt")
    if os.path.exists(req_file):
        try:
            log_path = os.path.join(srv["path"], "out.log")
            log_file = open(log_path, "a", encoding='utf-8')
            log_file.write("\n📦 جاري تثبيت المكتبات...\n")
            log_file.flush()
            subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
                cwd=srv["path"],
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            return jsonify({"success": True, "message": "📦 بدأ تثبيت المكتبات في الخلفية، تابع الكونسول"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
    return jsonify({"success": False, "message": "❌ ملف requirements.txt غير موجود"})

# ============== ADMIN APIs ==============
@app.route('/api/admin/all-servers')
def admin_all_servers():
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({}), 403
    
    servers_list = []
    for folder, srv in db["servers"].items():
        servers_list.append({
            "folder": folder,
            "name": srv.get("name", folder),
            "owner": srv.get("owner", "unknown"),
            "status": srv.get("status", "Stopped"),
            "type": srv.get("type", "Python"),
            "port": srv.get("port"),
            "created_at": srv.get("created_at", ""),
            "pid": srv.get("pid")
        })
    return jsonify({"success": True, "servers": servers_list})

@app.route('/api/admin/server-stats/<folder>')
def admin_server_stats(folder):
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({}), 403
    
    srv = db["servers"].get(folder)
    if not srv:
        return jsonify({"success": False, "message": "السيرفر غير موجود"}), 404
    
    logs = ""
    log_path = os.path.join(srv["path"], "out.log")
    if os.path.exists(log_path):
        with open(log_path, "r", errors='ignore') as f:
            logs = f.read()[-8000:]
    
    mem = "0 MB"
    cpu = "0%"
    if srv.get("pid"):
        try:
            p = psutil.Process(srv["pid"])
            mem = f"{p.memory_info().rss / 1024 / 1024:.1f} MB"
            cpu = f"{p.cpu_percent(interval=0.1):.1f}%"
        except:
            pass
    
    status = srv.get("status", "Stopped")
    online_status = "Online" if status == "Running" else "Offline"
    
    return jsonify({
        "success": True,
        "status": status,
        "online_status": online_status,
        "logs": logs,
        "mem": mem,
        "cpu": cpu,
        "ip": get_ip(),
        "port": srv.get("port", "N/A"),
        "uptime": srv.get("start_time"),
        "owner": srv.get("owner"),
        "name": srv.get("name", folder)
    })

@app.route('/api/admin/server-action/<folder>/<action>', methods=['POST'])
def admin_server_action(folder, action):
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({"success": False}), 403
    
    srv = db["servers"].get(folder)
    if not srv:
        return jsonify({"success": False, "message": "السيرفر غير موجود"})
    
    if action == "start":
        if srv.get("status") == "Running":
            return jsonify({"success": False, "message": "السيرفر يعمل بالفعل"})
        
        main_file = srv.get("startup_file", "main.py")
        file_path = os.path.join(srv["path"], main_file)
        
        if not os.path.exists(file_path):
            for f in ["app.py", "main.py", "index.js", "index.php", "index.html"]:
                if os.path.exists(os.path.join(srv["path"], f)):
                    main_file = f
                    srv["startup_file"] = f
                    file_path = os.path.join(srv["path"], f)
                    break
            else:
                return jsonify({"success": False, "message": "لم يتم العثور على ملف تشغيل"})
        
        port = srv.get("port")
        if not port:
            port = get_assigned_port()
            srv["port"] = port
            save_db(db)
        
        env = os.environ.copy()
        env["PORT"] = str(port)
        env["SERVER_PORT"] = str(port)
        
        cmd = []
        if main_file.endswith('.py'):
            cmd = ["python3", "-u", main_file]
        elif main_file.endswith('.js'):
            cmd = ["node", main_file]
        elif main_file.endswith('.html'):
            cmd = ["python3", "-m", "http.server", str(port)]
        else:
            cmd = ["python3", "-u", main_file]
        
        try:
            log_file = open(os.path.join(srv["path"], "out.log"), "w", encoding='utf-8')
            p = subprocess.Popen(cmd, cwd=srv["path"], stdout=log_file, stderr=subprocess.STDOUT, env=env)
            srv["status"] = "Running"
            srv["pid"] = p.pid
            srv["start_time"] = time.time()
            save_db(db)
            return jsonify({"success": True, "message": f"✅ تم تشغيل السيرفر على البورت {port}"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
    
    elif action == "stop":
        if srv.get("pid"):
            try:
                parent = psutil.Process(srv["pid"])
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()
            except:
                pass
        srv["status"] = "Stopped"
        srv["pid"] = None
        srv["start_time"] = None
        save_db(db)
        return jsonify({"success": True, "message": "⏹ تم إيقاف السيرفر"})
    
    elif action == "restart":
        admin_server_action(folder, "stop")
        time.sleep(1)
        return admin_server_action(folder, "start")
    
    return jsonify({"success": False, "message": "إجراء غير معروف"})

@app.route('/api/admin/users')
def admin_users():
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({}), 403
    
    users_list = []
    for uname, udata in db["users"].items():
        users_list.append({
            "username": uname,
            "is_admin": udata.get("is_admin", False),
            "created_at": udata.get("created_at"),
            "last_login": udata.get("last_login"),
            "max_servers": udata.get("max_servers", 3),
            "expiry_days": udata.get("expiry_days", 30)
        })
    return jsonify({"success": True, "users": users_list})

@app.route('/api/admin/create-user', methods=['POST'])
def admin_create_user():
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({}), 403
    
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    max_servers = int(data.get("max_servers", 3))
    expiry_days = int(data.get("expiry_days", 30))
    
    if username in db["users"]:
        return jsonify({"success": False, "message": "المستخدم موجود بالفعل"})
        
    db["users"][username] = {
        "password": hashlib.sha256(password.encode()).hexdigest(),
        "is_admin": False,
        "created_at": str(datetime.now()),
        "max_servers": max_servers,
        "expiry_days": expiry_days
    }
    save_db(db)
    return jsonify({"success": True, "message": "✅ تم إنشاء الحساب"})

@app.route('/api/admin/delete-user', methods=['POST'])
def admin_delete_user():
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({}), 403
    
    data = request.get_json()
    username = data.get("username")
    if username == ADMIN_USERNAME: return jsonify({"success": False, "message": "لا يمكن حذف المسؤول"})
    
    if username in db["users"]:
        for folder, srv in list(db["servers"].items()):
            if srv["owner"] == username:
                server_action(folder, "delete")
        
        del db["users"][username]
        save_db(db)
        return jsonify({"success": True, "message": "✅ تم حذف المستخدم"})
    return jsonify({"success": False, "message": "المستخدم غير موجود"})

@app.route('/api/system/metrics')
def system_metrics():
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
