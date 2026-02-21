################################################################
# Projekt: BridgeSurfer
# Autor: Emanuel Vogt
# Organisation: 8gent.Harness
# Erstellt am: 2026-02-21
# Beschreibung: Hauptanwendung für den BridgeSurfer Urlaubsplaner (JSON-basiert)
# Lizenz: Alle Rechte vorbehalten
# Status: In Entwicklung
################################################################

import os
import sys
import io
import socket
import glob
import traceback
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, send_file, session, jsonify, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd

# --- PFAD-MANAGEMENT ---
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
DATA_FILE = os.path.join(BASE_DIR, 'data.json')
LOG_FILE = os.path.join(BASE_DIR, 'debug_log.txt')

def log_to_file(message):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except: pass

# --- DATA MANAGER ---
class JsonDataManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"users": [], "antraege": [], "settings": {"current_period": "J1"}}

    def save(self):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def get_users(self): return [ObjectWrapper(u) for u in self.data['users']]
    def get_user_by_id(self, user_id):
        for u in self.data['users']:
            if u['id'] == user_id: return ObjectWrapper(u)
        return None
    def get_user_by_username(self, username):
        for u in self.data['users']:
            if u['username'] == username: return ObjectWrapper(u)
        return None
    def add_user(self, user_dict):
        user_dict['id'] = max([u['id'] for u in self.data['users']] + [0]) + 1
        self.data['users'].append(user_dict); self.save()
    def update_user(self, user_id, updates):
        for u in self.data['users']:
            if u['id'] == user_id: u.update(updates); break
        self.save()
    def delete_user(self, user_id):
        self.data['users'] = [u for u in self.data['users'] if u['id'] != user_id]
        self.data['antraege'] = [a for a in self.data['antraege'] if a['user_id'] != user_id]
        self.save()

    def get_antraege(self, user_id=None):
        res = self.data['antraege']
        if user_id: res = [a for a in res if a['user_id'] == user_id]
        return [ObjectWrapper(a) for a in res]
    def get_antrag_by_id(self, antrag_id):
        for a in self.data['antraege']:
            if a['id'] == antrag_id: return ObjectWrapper(a)
        return None
    def add_antrag(self, antrag_dict):
        antrag_dict['id'] = max([a['id'] for a in self.data['antraege']] + [0]) + 1
        self.data['antraege'].append(antrag_dict); self.save(); return antrag_dict['id']
    def update_antrag(self, antrag_id, updates):
        for a in self.data['antraege']:
            if a['id'] == antrag_id: a.update(updates); break
        self.save()

    def get_setting(self, key, default=None): return self.data['settings'].get(key, default)
    def set_setting(self, key, value): self.data['settings'][key] = value; self.save()
    def get_all_settings(self): return self.data['settings']

class ObjectWrapper:
    def __init__(self, d): self.__dict__ = d
    def __getattr__(self, name): return self.__dict__.get(name)
    @property
    def full_name(self): return f"{self.vorname} {self.nachname}" if self.vorname and self.nachname else self.username
    @property
    def resturlaub_wert(self):
        current_period = dm.get_setting('current_period', 'J1')
        verbraucht = sum(a.tage_anzahl for a in dm.get_antraege(self.id) if a.status == 'Genehmigt' and a.kategorie == 'Urlaub' and a.period == current_period)
        return (self.jahresurlaub + self.resturlaub_vorjahr) - verbraucht

dm = JsonDataManager(DATA_FILE)

# --- E-MAIL SIMULATION / WRAPPER ---
try:
    from flask_mail import Mail, Message
    MAIL_AVAILABLE = True
except ImportError:
    MAIL_AVAILABLE = False
    class Message: 
        def __init__(self, *args, **kwargs): pass
        def attach(self, *args, **kwargs): pass
    class Mail: 
        def __init__(self, app=None): pass
        def send(self, msg): pass
        def init_app(self, app): pass

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = 'BS_DOCKER_SECURE_KEY_123'
mail = Mail(app) if MAIL_AVAILABLE else Mail()

# --- HILFSFUNKTIONEN ---
def get_current_period(): return dm.get_setting('current_period', 'J1')
def berechne_arbeitstage(s, e):
    try:
        start, end = datetime.strptime(s, '%Y-%m-%d'), datetime.strptime(e, '%Y-%m-%d')
        days = 0; curr = start
        while curr <= end:
            if curr.weekday() < 5: days += 1
            curr += timedelta(days=1)
        return days
    except: return 0

def erstelle_ics_datei(antrag):
    s = antrag.start.replace('-', '')
    try: e = (datetime.strptime(antrag.ende, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y%m%d')
    except: e = s
    return f"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nSUMMARY:{antrag.kategorie}: {antrag.name}\nDTSTART;VALUE=DATE:{s}\nDTEND;VALUE=DATE:{e}\nSTATUS:CONFIRMED\nEND:VEVENT\nEND:VCALENDAR"

def get_auto_server_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]
    except: ip = "127.0.0.1"
    finally: s.close()
    return f"http://{ip}:5000"

def load_mail_config():
    if not MAIL_AVAILABLE: return False
    s = dm.get_all_settings()
    if s.get('mail_server'):
        app.config.update(MAIL_SERVER=s['mail_server'], MAIL_PORT=int(s.get('port', 587)), MAIL_USE_TLS=(s.get('use_tls')=='True'), MAIL_USERNAME=s.get('username'), MAIL_PASSWORD=s.get('password'))
        mail.init_app(app); return True
    return False

# --- MAIL FUNKTIONEN ---
def sende_mail(recipients, subject, template, **kwargs):
    if not load_mail_config(): return
    try:
        msg = Message(subject, recipients=recipients)
        msg.html = render_template(template, logo_url="cid:logo", **kwargs)
        logo_path = os.path.join(STATIC_DIR, 'BridgeSurfer_Logo.png')
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f: msg.attach('logo.png', 'image/png', f.read(), 'inline', headers={'Content-ID': '<logo>'})
        if 'ics' in kwargs: msg.attach("termin.ics", "text/calendar", kwargs['ics'])
        mail.send(msg)
    except Exception as e: log_to_file(f"Mail Fehler: {e}")

# --- SETUP ---
if not dm.get_user_by_username('admin'):
    dm.add_user({"username": "admin", "vorname": "System", "nachname": "Admin", "password": generate_password_hash('Admin123', method='pbkdf2:sha256'), "role": "Admin", "jahresurlaub": 30, "resturlaub_vorjahr": 0, "email": ""})

# --- ROUTEN ---
@app.route('/')
def index():
    if 'user_id' not in session: return redirect('/login_page')
    user = dm.get_user_by_id(session['user_id'])
    if not user: return redirect('/logout')
    antraege = dm.get_antraege() if user.role == 'Admin' else dm.get_antraege(user.id)
    period = get_current_period()
    genehmigte = [a for a in dm.get_antraege(user.id) if a.status == 'Genehmigt' and a.kategorie == 'Urlaub' and a.period == period]
    verbraucht = sum(a.tage_anzahl for a in genehmigte)
    rest = (user.jahresurlaub + user.resturlaub_vorjahr) - verbraucht
    return render_template('index.html', antraege=antraege, user=user, all_users=dm.get_users() if user.role == 'Admin' else [], resturlaub=rest, verbraucht=verbraucht, current_period=period)

@app.route('/login', methods=['POST'])
def login():
    u = dm.get_user_by_username(request.form.get('username'))
    if u and check_password_hash(u.password, request.form.get('password')):
        session['user_id'] = u.id; return redirect('/')
    flash("Login fehlgeschlagen"); return redirect('/login_page')

@app.route('/login_page')
def login_page(): return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect('/login_page')

@app.route('/beantragen', methods=['POST'])
def beantragen():
    user = dm.get_user_by_id(session['user_id'])
    s, e = request.form.get('start'), request.form.get('ende')
    tage = berechne_arbeitstage(s, e)
    aid = dm.add_antrag({"user_id": user.id, "name": user.full_name, "start": s, "ende": e, "tage_anzahl": tage, "status": "Wartend", "kategorie": request.form.get('kategorie'), "bemerkung": request.form.get('bemerkung'), "period": get_current_period()})
    return redirect('/')

@app.route('/status/<int:id>/<neuer_status>')
def status_aendern(id, neuer_status):
    user = dm.get_user_by_id(session.get('user_id'))
    if not user or user.role != 'Admin': return redirect('/login_page')
    dm.update_antrag(id, {"status": neuer_status})
    return redirect('/')

@app.route('/user/create', methods=['POST'])
def create_user():
    pw = generate_password_hash(request.form.get('password'), method='pbkdf2:sha256')
    dm.add_user({"username": request.form.get('nachname'), "vorname": request.form.get('vorname'), "nachname": request.form.get('nachname'), "password": pw, "role": "Mitarbeiter", "jahresurlaub": 30, "resturlaub_vorjahr": 0, "email": request.form.get('email')})
    return redirect('/')

@app.route('/user/delete/<int:user_id>')
def delete_user(user_id):
    dm.delete_user(user_id); return redirect('/')

@app.route('/export')
def export():
    data = [{"Mitarbeiter": a.name, "Start": a.start, "Ende": a.ende, "Tage": a.tage_anzahl, "Kategorie": a.kategorie, "Status": a.status} for a in dm.get_antraege()]
    df = pd.DataFrame(data); out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer: df.to_excel(writer, index=False)
    out.seek(0); return send_file(out, download_name="BS-Export.xlsx", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)