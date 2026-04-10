import time
import datetime
import os
import logging
import json
import requests
import re
import uuid
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

# --- Logging & Env ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

app = Flask(__name__)
CORS(app)
scheduler = BackgroundScheduler(timezone=os.getenv("TZ", "Asia/Shanghai"))

# --- Persistence Helpers ---
def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save error: {e}")

# --- Data State ---
# reminders: {id, title, time, repeat, priority, channels, category, status, created_at}
# settings: {language, theme, webhooks, email}
db = load_json(CONFIG_FILE, {
    "reminders": [],
    "settings": {
        "language": "zh",
        "theme": "auto",
        "webhooks": {"wecom": "", "dingtalk": "", "lark": ""},
        "email": {"enabled": False, "server": "", "port": 587, "user": "", "pass": "", "to": ""}
    }
})

logs = load_json(LOGS_FILE, [])

# --- Business Logic ---
def notify_engine(reminder):
    """Integrated notification engine across all enterprise channels."""
    s = db["settings"]
    title = reminder["title"]
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = f"🔔 【{reminder.get('category', '提醒')}】{title}\n触发时间: {now_str}\n优先级: {reminder.get('priority', 'low').upper()}"
    
    # Webhooks Dispatcher
    for platform, url in s["webhooks"].items():
        if url:
            try:
                payload = {"msgtype": "text", "text": {"content": msg}}
                requests.post(url, json=payload, timeout=5)
            except: pass

    # Record Log
    log_entry = {
        "id": str(uuid.uuid4()),
        "reminder_id": reminder["id"],
        "title": title,
        "category": reminder.get("category", "default"),
        "triggered_at": datetime.datetime.now().isoformat(),
        "completed_at": None,
        "status": "triggered"
    }
    logs.append(log_entry)
    save_json(LOGS_FILE, logs)
    logger.info(f"Notification sent for: {title}")

def update_scheduler():
    scheduler.remove_all_jobs()
    for r in db["reminders"]:
        if r.get("status") == "completed": continue
        try:
            # Parse triggers (same logic as before but cleaner)
            t_str = r["time"]
            rep = r.get("repeat", "none")
            trigger = None
            if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}', t_str):
                trigger = DateTrigger(run_date=t_str)
            elif re.match(r'^\d{1,2}:\d{2}', t_str):
                h, m = t_str.split(':')[:2]
                if rep == "daily": trigger = CronTrigger(hour=h, minute=m)
                elif rep.startswith("weekly:"): trigger = CronTrigger(day_of_week=rep.split(":")[1], hour=h, minute=m)
                else: trigger = DateTrigger(run_date=f"{datetime.date.today()} {t_str}")
            
            if trigger:
                scheduler.add_job(notify_engine, trigger, args=[r], id=r['id'])
        except Exception as e:
            logger.error(f"Schedule error for {r['id']}: {e}")
    if not scheduler.running:
        scheduler.start()

# --- API Layer ---
@app.route('/')
def home():
    with open('templates/index.html', 'r', encoding='utf-8') as f:
        return render_template_string(f.read())

@app.route('/api/state')
def get_state():
    return jsonify({"db": db, "logs": logs[-100:]})

@app.route('/api/reminders', methods=['POST'])
def add_reminder():
    r = request.json
    r.update({
        "id": str(uuid.uuid4()),
        "status": "pending",
        "created_at": datetime.datetime.now().isoformat()
    })
    db["reminders"].append(r)
    save_json(CONFIG_FILE, db)
    update_scheduler()
    return jsonify(r)

@app.route('/api/reminders/<rid>', methods=['PUT', 'DELETE'])
def mod_reminder(rid):
    if request.method == 'DELETE':
        db["reminders"] = [r for r in db["reminders"] if r["id"] != rid]
    else:
        update = request.json
        for i, r in enumerate(db["reminders"]):
            if r["id"] == rid:
                # Handle Completion Logic
                if update.get("status") == "completed" and r["status"] != "completed":
                    for log in reversed(logs):
                        if log["reminder_id"] == rid and not log["completed_at"]:
                            log["completed_at"] = datetime.datetime.now().isoformat()
                            save_json(LOGS_FILE, logs)
                            break
                db["reminders"][i].update(update)
                break
    save_json(CONFIG_FILE, db)
    update_scheduler()
    return jsonify({"status": "ok"})

@app.route('/api/settings', methods=['POST'])
def mod_settings():
    db["settings"].update(request.json)
    save_json(CONFIG_FILE, db)
    update_scheduler()
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    from waitress import serve
    update_scheduler()
    logger.info("Initializing Life Reminder v2.0.0 Engine...")
    serve(app, host="0.0.0.0", port=int(os.getenv("APP_PORT", 5000)))