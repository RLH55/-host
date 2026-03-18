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
from flask import Flask, send_from_directory, request, jsonify, session, redirect, url_for, make_response, render_template_string

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "USERS")
os.makedirs(USERS_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Global State
USERS_FILE = os.path.join(BASE_DIR, "users.json")
SUPPORT_CHAT_FILE = os.path.join(BASE_DIR, "support_chat.json")
ADMIN_USERNAME = "OMAR_ADMIN"
ADMIN_PASSWORD = "OMAR_2026_BRO"

# HTML Templates (Embedded for guaranteed deployment)
LOGIN_HTML = """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OMAR BRO HOST — استضافة المستقبل</title>
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap" rel="stylesheet">
  <style>
    :root { --primary: #00d4ff; --bg: #05060a; --text: #ffffff; --border: rgba(0, 212, 255, 0.15); }
    * { margin: 0; padding: 0; box-sizing: border-box; scroll-behavior: smooth; }
    body { font-family: 'Tajawal', sans-serif; background: var(--bg); color: var(--text); overflow-x: hidden; }
    .hero { height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 20px; }
    .hero-title { font-size: 3.5rem; font-weight: 900; background: linear-gradient(135deg, #00d4ff, #0066ff); -webkit-background-clip: text; color: transparent; margin-bottom: 10px; }
    .hero-subtitle { font-size: 1.2rem; color: #8899aa; max-width: 600px; margin-bottom: 30px; }
    .btn-scroll { padding: 12px 30px; background: var(--primary); color: #000; border-radius: 30px; text-decoration: none; font-weight: 700; cursor: pointer; }
    .section { padding: 100px 20px; max-width: 1200px; margin: 0 auto; text-align: center; }
    .features-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 30px; margin-top: 50px; }
    .feature-card { background: rgba(12, 17, 29, 0.95); padding: 40px; border-radius: 20px; border: 1px solid var(--border); }
    .login-section { min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 40px 20px; }
    .login-card { width: 100%; max-width: 450px; background: rgba(12, 17, 29, 0.95); padding: 40px; border-radius: 30px; border: 1px solid var(--border); box-shadow: 0 30px 60px rgba(0,0,0,0.5); }
    .omar-brand { display: flex; align-items: center; justify-content: center; gap: 10px; margin-bottom: 20px; }
    .omar-name { font-size: 2rem; font-weight: 900; color: var(--primary); }
    .input-group { margin-bottom: 20px; text-align: right; }
    .input-group label { display: block; margin-bottom: 8px; color: #8899aa; }
    .input-group input { width: 100%; padding: 14px; background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 12px; color: #fff; outline: none; }
    .btn-login { width: 100%; padding: 16px; background: linear-gradient(135deg, #00d4ff, #0066ff); border: none; border-radius: 12px; color: #000; font-weight: 900; cursor: pointer; }
  </style>
</head>
<body>
  <section class="hero">
    <h1 class="hero-title">OMAR BRO HOST</h1>
    <p class="hero-subtitle">المنصة الأقوى لاستضافة البوتات والسيرفرات بأداء أسطوري وحماية متكاملة.</p>
    <a class="btn-scroll" onclick="document.getElementById('login').scrollIntoView()">تسجيل الدخول 🚀</a>
  </section>

  <section class="section" id="features">
    <h2 style="font-size: 2.5rem; color: var(--primary);">لماذا تختار OMAR BRO HOST؟</h2>
    <div class="features-grid">
      <div class="feature-card"><h3>🚀 سرعة فائقة</h3><p>سيرفراتنا تعمل بأحدث التقنيات لضمان استجابة فورية.</p></div>
      <div class="feature-card"><h3>🛡️ حماية قصوى</h3><p>نظام حماية متطور ضد هجمات DDoS وتشفير كامل.</p></div>
      <div class="feature-card"><h3>💎 لوحة تحكم ذكية</h3><p>واجهة مستخدم بسيطة واحترافية لإدارة كل شيء.</p></div>
    </div>
  </section>

  <section class="login-section" id="login">
    <div class="login-card">
      <div class="omar-brand">
        <span class="omar-name">OMAR</span>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="#0088cc"><path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM10 17L5 12L6.41 10.59L10 14.17L17.59 6.58L19 8L10 17Z"/></svg>
      </div>
      <form id="loginForm">
        <div class="input-group"><label>اسم المستخدم</label><input type="text" id="username" required></div>
        <div class="input-group"><label>كلمة المرور</label><input type="password" id="password" required></div>
        <button type="submit" class="btn-login" id="loginBtn">دخول أسطوري 🚀</button>
      </form>
      <div id="alert" style="margin-top: 15px; text-align: center; display: none; padding: 10px; border-radius: 8px;"></div>
    </div>
  </section>

  <script>
    document.getElementById('loginForm').onsubmit = async (e) => {
      e.preventDefault();
      const btn = document.getElementById('loginBtn');
      const alert = document.getElementById('alert');
      const username = document.getElementById('username').value;
      const password = document.getElementById('password').value;
      btn.disabled = true; btn.textContent = 'جاري التحقق...';
      try {
        const res = await fetch('/api/login', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({username, password})
        });
        const data = await res.json();
        if (data.success) {
          alert.style.display = 'block'; alert.style.color = '#00ff88'; alert.textContent = '✅ تم تسجيل الدخول!';
          setTimeout(() => window.location.href = '/', 1000);
        } else { throw new Error(data.message); }
      } catch (err) {
        alert.style.display = 'block'; alert.style.color = '#ff4444'; alert.textContent = '❌ ' + err.message;
        btn.disabled = false; btn.textContent = 'دخول أسطوري 🚀';
      }
    };
  </script>
</body>
</html>
"""

INDEX_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OMAR BRO HOST | لوحة التحكم</title>
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --primary: #00d4ff; --accent: #00d4ff; --accent-light: #70eaff;
            --bg: #050810; --panel: rgba(13, 18, 33, 0.95);
            --panel-border: rgba(0, 212, 255, 0.15); --text: #e0e6ed;
            --muted: #8899aa; --success: #00ff88; --error: #ff4444;
            --gradient: linear-gradient(135deg, #00d4ff, #0066ff);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Tajawal', sans-serif; background: var(--bg); color: var(--text); overflow-x: hidden; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { display: flex; justify-content: space-between; align-items: center; padding: 20px 0; margin-bottom: 30px; border-bottom: 1px solid var(--panel-border); }
        .logo { font-size: 1.8rem; font-weight: 900; color: var(--primary); display: flex; align-items: center; gap: 10px; }
        .logout-btn { padding: 8px 20px; background: rgba(255, 68, 68, 0.1); color: var(--error); border: 1px solid rgba(255, 68, 68, 0.2); border-radius: 8px; cursor: pointer; text-decoration: none; font-weight: 700; }
        .dashboard-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 25px; }
        @media (max-width: 900px) { .dashboard-grid { grid-template-columns: 1fr; } }
        .card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 20px; padding: 25px; box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
        .card-title { font-size: 1.2rem; font-weight: 800; color: var(--primary); margin-bottom: 20px; display: flex; align-items: center; gap: 10px; }
        .metrics-container { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 25px; }
        .metric-card { background: rgba(255,255,255,0.03); padding: 15px; border-radius: 15px; border: 1px solid var(--panel-border); }
        .metric-value { font-size: 1.4rem; font-weight: 800; color: var(--primary); }
        .upload-box { border: 2px dashed var(--panel-border); border-radius: 15px; padding: 40px; text-align: center; cursor: pointer; transition: 0.3s; background: rgba(0, 212, 255, 0.02); }
        .upload-box:hover { border-color: var(--primary); background: rgba(0, 212, 255, 0.05); }
        table { width: 100%; border-collapse: collapse; text-align: right; margin-top: 20px; }
        th { padding: 15px; color: var(--muted); border-bottom: 1px solid var(--panel-border); }
        td { padding: 15px; border-bottom: 1px solid rgba(255,255,255,0.03); }
        .btn-action { padding: 5px 12px; border-radius: 6px; border: none; cursor: pointer; font-size: 0.8rem; font-weight: 700; margin-right: 5px; }
        .btn-view { background: rgba(0, 212, 255, 0.1); color: var(--primary); }
        .chat-widget { position: fixed; bottom: 30px; left: 30px; z-index: 1000; }
        .chat-btn { width: 60px; height: 60px; background: var(--gradient); border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; }
        .chat-window { position: absolute; bottom: 80px; left: 0; width: 350px; height: 450px; background: var(--panel); border: 1px solid var(--panel-border); border-radius: 20px; display: none; flex-direction: column; overflow: hidden; }
        .chat-header { padding: 15px; background: var(--gradient); color: #000; font-weight: 800; display: flex; justify-content: space-between; }
        .chat-messages { flex: 1; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .chat-input { padding: 15px; border-top: 1px solid var(--panel-border); display: flex; gap: 10px; }
        .chat-input input { flex: 1; background: rgba(0,0,0,0.3); border: 1px solid var(--panel-border); padding: 10px; border-radius: 10px; color: #fff; outline: none; }
        .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.9); display: none; align-items: center; justify-content: center; z-index: 2000; padding: 20px; }
        .modal-content { width: 100%; max-width: 900px; height: 80vh; background: #0a0d14; border-radius: 20px; border: 1px solid var(--panel-border); display: flex; flex-direction: column; overflow: hidden; }
        .modal-header { padding: 20px; border-bottom: 1px solid var(--panel-border); display: flex; justify-content: space-between; align-items: center; }
        .modal-body { flex: 1; padding: 20px; overflow: auto; }
        pre { font-family: 'Courier New', monospace; color: #9ab5c7; line-height: 1.6; font-size: 14px; white-space: pre-wrap; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo"><span>OMAR BRO HOST</span></div>
            <div class="user-info"><span id="userNameDisplay">مرحباً</span> <a href="/api/logout" class="logout-btn">خروج</a></div>
        </header>
        <div class="dashboard-grid">
            <div class="main-col">
                <div class="card">
                    <div class="card-title">📂 إدارة الملفات والرفع</div>
                    <div class="upload-box" onclick="document.getElementById('fileInput').click()">
                        <div style="font-size: 40px">☁️</div>
                        <div>اضغط هنا لرفع ملفاتك (PY, HTML, TXT, JSON)</div>
                        <input type="file" id="fileInput" style="display: none" multiple onchange="handleUpload(this.files)">
                    </div>
                    <table>
                        <thead><tr><th>اسم الملف</th><th>الحجم</th><th>الإجراءات</th></tr></thead>
                        <tbody id="filesList"></tbody>
                    </table>
                </div>
            </div>
            <div class="side-col">
                <div class="card">
                    <div class="card-title">📊 استهلاك الموارد</div>
                    <div class="metrics-container">
                        <div class="metric-card"><div>CPU</div><div class="metric-value" id="cpuVal">0%</div></div>
                        <div class="metric-card"><div>RAM</div><div class="metric-value" id="ramVal">0%</div></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <div class="chat-widget">
        <div class="chat-window" id="chatWindow">
            <div class="chat-header"><span>الدعم الفني 💬</span><span onclick="toggleChat()">✖</span></div>
            <div class="chat-messages" id="chatMsgs"></div>
            <div class="chat-input"><input type="text" id="chatInput" placeholder="اكتب رسالتك..."><button onclick="sendMsg()">إرسال</button></div>
        </div>
        <div class="chat-btn" onclick="toggleChat()">💬</div>
    </div>
    <div class="modal" id="fileModal">
        <div class="modal-content">
            <div class="modal-header"><h3 id="modalFileName">اسم الملف</h3><button onclick="closeModal()">إغلاق</button></div>
            <div class="modal-body"><pre id="fileContent">جاري التحميل...</pre></div>
        </div>
    </div>
    <script>
        function toggleChat() { const win = document.getElementById('chatWindow'); win.style.display = win.style.display === 'flex' ? 'none' : 'flex'; }
        async function loadFiles() {
            const res = await fetch('/api/files/list'); const data = await res.json();
            document.getElementById('filesList').innerHTML = data.files.map(f => `
                <tr>
                    <td style="color: var(--primary)">${f.name}</td><td>${f.size}</td>
                    <td><button class="btn-action btn-view" onclick="viewFile('${f.name}')">قراءة</button></td>
                </tr>`).join('');
        }
        async function viewFile(name) {
            document.getElementById('modalFileName').textContent = name;
            document.getElementById('fileModal').style.display = 'flex';
            const res = await fetch('/api/files/read', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({filename: name}) });
            const data = await res.json(); document.getElementById('fileContent').textContent = data.content || data.error;
        }
        function closeModal() { document.getElementById('fileModal').style.display = 'none'; }
        async function updateMetrics() {
            const res = await fetch('/api/system/metrics'); const data = await res.json();
            document.getElementById('cpuVal').textContent = data.cpu + '%'; document.getElementById('ramVal').textContent = data.memory + '%';
        }
        setInterval(updateMetrics, 5000); updateMetrics(); loadFiles();
    </script>
</body>
</html>
"""

# Helper Functions
def load_users():
    if not os.path.exists(USERS_FILE): return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f: return json.load(f)

def is_admin(username):
    return username == ADMIN_USERNAME

# Routes
@app.route('/')
def index():
    if 'username' not in session: return redirect(url_for('login_page'))
    return render_template_string(INDEX_HTML)

@app.route('/login')
def login_page():
    return render_template_string(LOGIN_HTML)

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    u, p = data.get('username'), data.get('password')
    if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
        session['username'] = u
        return jsonify({"success": True, "redirect": "/admin"})
    users = load_users()
    if u in users and users[u]['password'] == p:
        session['username'] = u
        return jsonify({"success": True, "redirect": "/"})
    return jsonify({"success": False, "message": "بيانات غير صحيحة"})

@app.route('/api/logout')
def api_logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/api/files/list')
def list_files():
    if 'username' not in session: return jsonify({"files": []})
    user_dir = os.path.join(USERS_DIR, session['username'])
    os.makedirs(user_dir, exist_ok=True)
    files = []
    for f in os.listdir(user_dir):
        path = os.path.join(user_dir, f)
        if os.path.isfile(path):
            stat = os.stat(path)
            files.append({"name": f, "size": f"{stat.st_size / 1024:.1f} KB"})
    return jsonify({"files": files})

@app.route('/api/files/read', methods=['POST'])
def read_file():
    if 'username' not in session: return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    filename = data.get('filename')
    user_dir = os.path.join(USERS_DIR, session['username'])
    path = os.path.join(user_dir, filename)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return jsonify({"content": f.read()})
    except:
        return jsonify({"error": "Could not read file"}), 500

@app.route('/api/system/metrics')
def get_metrics():
    return jsonify({"cpu": psutil.cpu_percent(), "memory": psutil.virtual_memory().percent})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
