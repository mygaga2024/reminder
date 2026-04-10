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

# --- Logging setup ---
class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = []
    def emit(self, record):
        try:
            msg = self.format(record)
            self.logs.append(msg)
            if len(self.logs) > 50: self.logs.pop(0)
        except Exception:
            self.handleError(record)

# 修复关键点：%(message)s 才是正确的占位符
log_handler = ListHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger()
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

app = Flask(__name__)
CORS(app)
scheduler = BackgroundScheduler(timezone=os.getenv("TZ", "Asia/Shanghai"))

# --- DB Persistence ---
def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e: logger.error(f"保存配置失败: {e}")

db = load_json(CONFIG_FILE, {
    "reminders": [],
    "settings": {
        "language": "zh",
        "dark_mode": True,
        "webhooks": {"wecom": "", "dingtalk": "", "lark": ""}
    }
})
logs = load_json(LOGS_FILE, [])

def notify_engine(reminder):
    s = db["settings"]
    title = reminder["title"]
    now_str = datetime.datetime.now().strftime('%H:%M:%S')
    msg = f"⏰ 提醒: {title}\n触发时间: {now_str}"
    
    for platform, url in s["webhooks"].items():
        if url:
            try: requests.post(url, json={"msgtype": "text", "text": {"content": msg}}, timeout=5)
            except Exception as e: logger.error(f"推送失败 ({platform}): {e}")

    log_entry = {
        "id": str(uuid.uuid4()), "reminder_id": reminder["id"], "title": title,
        "triggered_at": datetime.datetime.now().isoformat(), "completed_at": None, "status": "triggered"
    }
    logs.append(log_entry)
    save_json(LOGS_FILE, logs)
    logger.info(f"提醒已触发: {title}")

def update_scheduler():
    scheduler.remove_all_jobs()
    for r in db["reminders"]:
        if r.get("status") == "completed": continue
        try:
            t_str, rep = r["time"], r.get("repeat", "none")
            trigger = None
            if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}', t_str): trigger = DateTrigger(run_date=t_str)
            elif re.match(r'^\d{1,2}:\d{2}', t_str):
                h, m = t_str.split(':')[:2]
                if rep == "daily": trigger = CronTrigger(hour=h, minute=m)
                elif rep.startswith("weekly:"): trigger = CronTrigger(day_of_week=rep.split(":")[1], hour=h, minute=m)
                else: trigger = DateTrigger(run_date=f"{datetime.date.today()} {t_str}")
            if trigger: scheduler.add_job(notify_engine, trigger, args=[r], id=r['id'])
        except Exception as e: logger.error(f"调度任务失败: {e}")
    if not scheduler.running: scheduler.start()

# --- API ---
@app.route('/')
def home():
    with open('templates/index.html', 'r', encoding='utf-8') as f: return render_template_string(f.read())

@app.route('/api/state')
def get_state():
    return jsonify({"db": db, "logs": logs[-100:], "syslogs": log_handler.logs[::-1]})

@app.route('/api/reminders', methods=['POST'])
def add_reminder():
    r = request.json
    r.update({"id": str(uuid.uuid4()), "status": "pending", "created_at": datetime.datetime.now().isoformat()})
    db["reminders"].append(r)
    save_json(CONFIG_FILE, db); update_scheduler()
    return jsonify(r)

@app.route('/api/reminders/<rid>', methods=['PUT', 'DELETE'])
def mod_reminder(rid):
    if request.method == 'DELETE':
        db["reminders"] = [r for r in db["reminders"] if r["id"] != rid]
    else:
        update = request.json
        for i, r in enumerate(db["reminders"]):
            if r["id"] == rid:
                if update.get("status") == "completed" and r["status"] != "completed":
                    for l in reversed(logs):
                        if l["reminder_id"] == rid and not l["completed_at"]:
                            l["completed_at"] = datetime.datetime.now().isoformat()
                            save_json(LOGS_FILE, logs); break
                db["reminders"][i].update(update); break
    save_json(CONFIG_FILE, db); update_scheduler()
    return jsonify({"status": "ok"})

@app.route('/api/settings', methods=['POST'])
def mod_settings():
    db["settings"].update(request.json)
    save_json(CONFIG_FILE, db)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    from waitress import serve
    update_scheduler()
    logger.info("Life Reminder Engine v3.0.0 Started.")
    serve(app, host="0.0.0.0", port=int(os.getenv("APP_PORT", 5000)))