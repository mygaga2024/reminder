import time
import datetime
import os
import smtplib
import logging
import json
import requests
import re
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 数据目录与文件
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

app = Flask(__name__)
CORS(app)
scheduler = BackgroundScheduler(timezone=os.getenv("TZ", "Asia/Shanghai"))

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")
        return False

# --- Core Data Structures ---
# current_config keys: reminders (list), settings (dict)
current_config = load_json(CONFIG_FILE, {
    "reminders": [],
    "settings": {
        "language": "zh",
        "dark_mode": True,
        "email": {"enabled": False, "server": "", "port": 587, "user": "", "pass": "", "to": ""},
        "webhooks": {"wecom": "", "dingtalk": "", "lark": "", "custom": ""},
        "sms": {"enabled": False, "api_key": ""},
        "time_format": "24h"
    }
})

# logs: list of {id, reminder_id, title, triggered_at, completed_at, mood, notes, status}
reminder_logs = load_json(LOGS_FILE, [])

def notify_all_channels(reminder):
    """Notify via multiple configured channels."""
    s = current_config["settings"]
    title = reminder["title"]
    msg = f"【提醒】{title}\n时间: {datetime.datetime.now().strftime('%H:%M:%S')}\n备注: {reminder.get('notes', '无')}"
    
    # 1. Email
    if s["email"]["enabled"]:
        send_email(f"Reminder: {title}", msg, s["email"])
    
    # 2. Webhooks
    for key, url in s["webhooks"].items():
        if url:
            try:
                if "dingtalk" in key:
                    requests.post(url, json={"msgtype": "text", "text": {"content": msg}})
                elif "wecom" in key or "lark" in key:
                    requests.post(url, json={"msgtype": "text", "text": {"content": msg}})
                else:
                    requests.post(url, json={"message": msg})
            except: pass

    # Log to backend logs
    log_entry = {
        "id": str(uuid.uuid4()),
        "reminder_id": reminder["id"],
        "title": title,
        "triggered_at": datetime.datetime.now().isoformat(),
        "completed_at": None,
        "status": "triggered"
    }
    reminder_logs.append(log_entry)
    save_json(LOGS_FILE, reminder_logs)

def send_email(subject, message, conf):
    try:
        msg = MIMEMultipart()
        msg["From"] = conf["user"]
        msg["To"] = conf["to"]
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))
        with smtplib.SMTP(conf["server"], conf["port"]) as server:
            server.starttls()
            server.login(conf["user"], conf["pass"])
            server.send_message(msg)
    except Exception as e:
        logger.error(f"Email error: {e}")

def parse_to_trigger(reminder):
    t_str = reminder["time"]  # Expecting "HH:mm" or "YYYY-MM-DD HH:mm:ss"
    rep = reminder.get("repeat", "none")
    
    if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$', t_str):
        return DateTrigger(run_date=t_str)

    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', t_str):
        parts = t_str.split(':')
        h, m = parts[0], parts[1]
        s = parts[2] if len(parts) > 2 else "00"
        
        if rep == "daily":
            return CronTrigger(hour=h, minute=m, second=s)
        elif rep.startswith("weekly:"):
            days = rep.split(":")[1]
            return CronTrigger(day_of_week=days, hour=h, minute=m, second=s)
        elif rep.startswith("monthly:"):
            day = rep.split(":")[1]
            return CronTrigger(day=day, hour=h, minute=m, second=s)
        elif rep == "none":
            # Just target today's date
            return DateTrigger(run_date=f"{datetime.date.today().isoformat()} {t_str}")
    return None

def update_scheduler():
    scheduler.remove_all_jobs()
    for r in current_config["reminders"]:
        if r.get("status") == "completed": continue
        try:
            trigger = parse_to_trigger(r)
            if trigger:
                scheduler.add_job(notify_all_channels, trigger, args=[r], id=f"job_{r['id']}")
        except: pass
    if not scheduler.running:
        scheduler.start()

# --- API Routes ---

@app.route('/')
def index():
    try:
        with open('templates/index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except: return "Error: templates/index.html missing"

@app.route('/api/data', methods=['GET'])
def get_data():
    return jsonify({
        "config": current_config,
        "logs": reminder_logs[-50:] # Limit to last 50
    })

@app.route('/api/reminders', methods=['POST'])
def add_rem():
    r = request.json
    r["id"] = str(uuid.uuid4())
    r["status"] = "pending"
    current_config["reminders"].append(r)
    save_json(CONFIG_FILE, current_config)
    update_scheduler()
    return jsonify(r)

@app.route('/api/reminders/<rid>', methods=['PUT', 'DELETE'])
def handle_rem(rid):
    if request.method == 'DELETE':
        current_config["reminders"] = [r for r in current_config["reminders"] if r["id"] != rid]
    else:
        data = request.json
        for i, r in enumerate(current_config["reminders"]):
            if r["id"] == rid:
                # If marking as completed, update logs
                if data.get("status") == "completed" and r["status"] != "completed":
                    # Find matching log entry to update
                    for log in reversed(reminder_logs):
                        if log["reminder_id"] == rid and log["completed_at"] is None:
                            log["completed_at"] = datetime.datetime.now().isoformat()
                            log["mood"] = data.get("mood", "😊")
                            log["notes"] = data.get("log_notes", "")
                            break
                    save_json(LOGS_FILE, reminder_logs)
                
                current_config["reminders"][i].update(data)
                break
    save_json(CONFIG_FILE, current_config)
    update_scheduler()
    return jsonify({"success": True})

@app.route('/api/settings', methods=['POST'])
def save_settings():
    current_config["settings"].update(request.json)
    save_json(CONFIG_FILE, current_config)
    update_scheduler()
    return jsonify({"success": True})

@app.route('/api/logs', methods=['GET'])
def get_logs():
    return jsonify(reminder_logs)

if __name__ == "__main__":
    from waitress import serve
    update_scheduler()
    port = int(os.getenv("APP_PORT", 5000))
    logger.info(f"Starting Pro Reminder Server on port {port}...")
    serve(app, host="0.0.0.0", port=port)