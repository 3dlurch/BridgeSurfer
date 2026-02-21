################################################################
# Projekt: BridgeSurfer
# Autor: Emanuel Vogt
# Organisation: 8gent.Harness
# Erstellt am: 2026-02-21
# Beschreibung: Hauptanwendung für den BridgeSurfer Urlaubsplaner (JSON-basiert)
# Lizenz: Alle Rechte vorbehalten
# Status: In Entwicklung (Bugfix-Version)
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
from flask_wtf.csrf import CSRFProtect
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
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                log_to_file(f"JSON Ladefehler: {e}")
        return {"users": [], "antraege": [], "settings": {"current_period": "J1"}}

    def save(self):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            log_to_file(f"JSON Speicherfehler: {e}")

    def get_users(self): return [ObjectWrapper(u, self) for u in self.data['users']]
    
    def get_user_by_id(self, user_id):
        for u in self.data['users']:
            if u.get('id') == user_id: return ObjectWrapper(u, self)
        return None
    
    def get_user_by_username(self, username):
        for u in self.data['users']:
            if u.get('username') == username: return ObjectWrapper(u, self)
        return None
    
    def add_user(self, user_dict):
        max_id = 0
        if self.data['users']:
            max_id = max([u.get('id', 0) for u in self.data['users']])
        user_dict['id'] = max_id + 1
        self.data['users'].append(user_dict)
        self.save()
        return user_dict['id']

    def update_user(self, user_id, updates):
        for u in self.data['users']:
            if u.get('id') == user_id: 
                u.update(updates)
                break
        self.save()

    def delete_user(self, user_id):
        self.data['users'] = [u for u in self.data['users'] if u.get('id') != user_id]
        self.data['antraege'] = [a for a in self.data['antraege'] if a.get('user_id') != user_id]
        self.save()

    def get_antraege(self, user_id=None):
        antraege = self.data['antraege']
        if user_id:
            antraege = [a for a in antraege if a.get('user_id') == user_id]
        return [ObjectWrapper(a, self) for a in antraege]

    def get_antrag_by_id(self, antrag_id):
        for a in self.data['antraege']:
            if a.get('id') == antrag_id: return ObjectWrapper(a, self)
        return None

    def add_antrag(self, antrag_dict):
        max_id = 0
        if self.data['antraege']:
            max_id = max([a.get('id', 0) for a in self.data['antraege']])
        antrag_dict['id'] = max_id + 1
        self.data['antraege'].append(antrag_dict)
        self.save()
        return antrag_dict['id']

    def update_antrag(self, antrag_id, updates):
        for a in self.data['antraege']:
            if a.get('id') == antrag_id: 
                a.update(updates)
                break
        self.save()

    def get_setting(self, key, default=None): return self.data['settings'].get(key, default)
    def set_setting(self, key, value): self.data['settings'][key] = value; self.save()
    def get_all_settings(self): return self.data['settings']

class ObjectWrapper:
    def __init__(self, d, dm):
        self.__dict__ = d
        self._dm = dm
    
    def __getattr__(self, name):
        # Dynamische Verknüpfung: antrag.user
        if name == 'user' and 'user_id' in self.__dict__:
            return self._dm.get_user_by_id(self.user_id)
        return self.__dict__.get(name)

    @property
    def full_name(self): 
        v = self.__dict__.get('vorname', '')
        n = self.__dict__.get('nachname', '')
        if v and n: return f"{v} {n}"
        return self.__dict__.get('username', 'Unbekannt')

    @property
    def resturlaub_wert(self):
        current_period = self._dm.get_setting('current_period', 'J1')
        verbraucht = sum(a.tage_anzahl for a in self._dm.get_antraege(self.id) 
                        if a.status == 'Genehmigt' and a.kategorie == 'Urlaub' and a.period == current_period)
        return (self.jahresurlaub + self.resturlaub_vorjahr) - verbraucht

dm = JsonDataManager(DATA_FILE)

# --- APP SETUP ---
app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = 'BS_DOCKER_SECURE_KEY_982374_X#Y!'
csrf = CSRFProtect(app)

# --- E-MAIL SIMULATION ---
try:
    from flask_mail import Mail, Message
    MAIL_AVAILABLE = True
    mail = Mail(app)
except ImportError:
    MAIL_AVAILABLE = False
    class Message: 
        def __init__(self, *args, **kwargs): pass
        def attach(self, *args, **kwargs): pass
    class Mail: 
        def __init__(self, app=None): pass
        def send(self, msg): pass
        def init_app(self, app): pass
    mail = Mail()

# --- HILFSFUNKTIONEN ---
def get_current_period(): return dm.get_setting('current_period', 'J1')

def berechne_arbeitstage(s, e):
    try:
        start = datetime.strptime(s, '%Y-%m-%d')
        end = datetime.strptime(e, '%Y-%m-%d')
        days = 0; curr = start
        while curr <= end:
            if curr.weekday() < 5: days += 1
            curr += timedelta(days=1)
        return days
    except: return 0

def check_monthly_backup_exists():
    try:
        target_folder = os.path.join(BACKUP_DIR, get_current_period())
        if not os.path.exists(target_folder): return False
        pattern = os.path.join(target_folder, f"BS-Backup_Urlaubsdaten_{datetime.now().strftime('%Y-%m')}*.xlsx")
        return len(glob.glob(pattern)) > 0
    except: return False

# --- SETUP DATABASE / ADMIN ---
def setup():
    if not dm.get_user_by_username('admin'):
        dm.add_user({
            "username": "admin", 
            "vorname": "System", 
            "nachname": "Admin", 
            "password": generate_password_hash('Admin123', method='pbkdf2:sha256'), 
            "role": "Admin", 
            "jahresurlaub": 30, 
            "resturlaub_vorjahr": 0, 
            "email": ""
        })
    if not dm.get_setting('current_period'):
        dm.set_setting('current_period', 'J1')
setup()

# --- ROUTEN ---
@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    user = dm.get_user_by_id(session['user_id'])
    if not user: return redirect(url_for('logout'))
    
    antraege = dm.get_antraege() if user.role == 'Admin' else dm.get_antraege(user.id)
    period = get_current_period()
    genehmigte = [a for a in dm.get_antraege(user.id) if a.status == 'Genehmigt' and a.kategorie == 'Urlaub' and a.period == period]
    verbraucht = sum(a.tage_anzahl for a in genehmigte)
    rest = (user.jahresurlaub + user.resturlaub_vorjahr) - verbraucht
    
    return render_template('index.html', 
                           antraege=antraege, 
                           user=user, 
                           all_users=dm.get_users() if user.role == 'Admin' else [], 
                           resturlaub=rest, 
                           verbraucht=verbraucht, 
                           current_period=period,
                           backup_done=check_monthly_backup_exists(),
                           msg=session.pop('flash_message', None),
                           msg_type=session.pop('flash_type', None))

@app.route('/login_page')
def login_page():
    return render_template('login.html', 
                           msg=session.pop('flash_message', None),
                           msg_type=session.pop('flash_type', None))

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    user = dm.get_user_by_username(username)
    if user and check_password_hash(user.password, password):
        session['user_id'] = user.id
        session.permanent = True
        return redirect(url_for('index'))
    session['flash_message'] = "Login fehlgeschlagen. Bitte Daten prüfen."
    session['flash_type'] = "error"
    return redirect(url_for('login_page'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/beantragen', methods=['POST'])
def beantragen():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    user = dm.get_user_by_id(session['user_id'])
    s = request.form.get('start')
    e = request.form.get('ende')
    if not s or not e or e < s:
        session['flash_message'] = "Ungültiger Zeitraum."; session['flash_type'] = "error"
        return redirect(url_for('index'))
    
    tage = berechne_arbeitstage(s, e)
    dm.add_antrag({
        "user_id": user.id, 
        "name": user.full_name, 
        "start": s, 
        "ende": e, 
        "tage_anzahl": tage, 
        "status": "Wartend", 
        "kategorie": request.form.get('kategorie'), 
        "bemerkung": request.form.get('bemerkung'), 
        "period": get_current_period()
    })
    session['flash_message'] = "Antrag erfolgreich gestellt."; session['flash_type'] = "success"
    return redirect(url_for('index'))

@app.route('/status/<int:id>/<neuer_status>')
def status_aendern(id, neuer_status):
    if 'user_id' not in session: return redirect(url_for('login_page'))
    user = dm.get_user_by_id(session['user_id'])
    if user.role != 'Admin': return "Zugriff verweigert", 403
    dm.update_antrag(id, {"status": neuer_status})
    session['flash_message'] = f"Status auf {neuer_status} geändert."; session['flash_type'] = "success"
    return redirect(url_for('index'))

@app.route('/user/create', methods=['POST'])
def create_user():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    admin = dm.get_user_by_id(session['user_id'])
    if admin.role != 'Admin': return "Zugriff verweigert", 403
    
    vn, nn = request.form.get('vorname'), request.form.get('nachname')
    if dm.get_user_by_username(nn):
        session['flash_message'] = "Benutzername bereits vergeben."; session['flash_type'] = "error"
        return redirect(url_for('index'))
        
    pw = generate_password_hash(request.form.get('password'), method='pbkdf2:sha256')
    dm.add_user({
        "username": nn, 
        "vorname": vn, 
        "nachname": nn, 
        "password": pw, 
        "role": "Mitarbeiter", 
        "jahresurlaub": 30, 
        "resturlaub_vorjahr": 0, 
        "email": ""
    })
    session['flash_message'] = "Mitarbeiter angelegt."; session['flash_type'] = "success"
    return redirect(url_for('index'))

@app.route('/user/delete/<int:user_id>')
def delete_user(user_id):
    if 'user_id' not in session: return redirect(url_for('login_page'))
    admin = dm.get_user_by_id(session['user_id'])
    if admin.role != 'Admin': return "Zugriff verweigert", 403
    dm.delete_user(user_id)
    return redirect(url_for('index'))

@app.route('/api/kalender')
def kalender_daten():
    ev = []
    for a in dm.get_antraege():
        if a.status == 'Abgelehnt' or a.status == 'Storniert': continue
        c = '#27ae60' if a.status == 'Genehmigt' else '#f39c12'
        if a.kategorie == 'Krank': c = '#c0392b'
        
        # Datum exklusiv Ende für FullCalendar
        try:
            end_obj = datetime.strptime(a.ende, '%Y-%m-%d') + timedelta(days=1)
            end_str = end_obj.strftime('%Y-%m-%d')
        except: end_str = a.ende
            
        ev.append({
            'title': f"{a.name} ({a.kategorie})",
            'start': a.start,
            'end': end_str,
            'color': c,
            'allDay': True
        })
    return jsonify(ev)

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)