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
HISTORY_FILE = os.path.join(DATA_DIR, "reminder_history.json")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

app = Flask(__name__)
CORS(app)
scheduler = BackgroundScheduler(timezone=os.getenv("TZ", "Asia/Shanghai"))

def load_config():
    """加载配置与提醒项"""
    default_config = {
        "reminders": [], # [{id, title, time, repeat, status, notes, notification_types}]
        "settings": {
            "email_enabled": False,
            "smtp_server": "smtp.example.com",
            "smtp_port": 587,
            "sender": "",
            "password": "",
            "recipient": "",
            "push_enabled": False,
            "webhook_url": "",
            "language": "zh",
            "time_format": "24h"
        }
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                # 兼容旧版本数据
                if "reminder_rules" in loaded:
                    new_reminders = []
                    for rule in loaded["reminder_rules"]:
                        new_reminders.append({
                            "id": str(uuid.uuid4()),
                            "title": "迁移提醒",
                            "time": rule.split()[-1] if ' ' in rule else rule,
                            "repeat": "daily",
                            "status": "pending",
                            "notes": f"来自旧版规则: {rule}"
                        })
                    loaded["reminders"] = new_reminders
                    del loaded["reminder_rules"]
                return loaded
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            
    return default_config

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        return False

current_config = load_config()

def trigger_reminder(reminder_id):
    """提醒触发时的回调函数"""
    reminders = current_config.get("reminders", [])
    reminder = next((r for r in reminders if r["id"] == reminder_id), None)
    
    if not reminder:
        return
        
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"【{reminder['title']}】时间到了！({now_str})\n备注: {reminder.get('notes', '无')}"
    logger.info(f"触发提醒: {message}")
    
    # 记录历史
    save_reminder_history(reminder['id'], message)
    
    # 发送通知
    if current_config["settings"].get("email_enabled"):
        send_email(f"提醒: {reminder['title']}", message)
    if current_config["settings"].get("push_enabled"):
        send_push_notification(message)

def save_reminder_history(reminder_id, message):
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            logger.error(f"读取历史文件失败: {e}")
    
    new_record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "reminder_id": reminder_id,
        "message": message
    }
    history.append(new_record)
    if len(history) > 100:
        history = history[-100:]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存历史文件失败: {e}")

def send_email(subject, message):
    s = current_config["settings"]
    if not s.get("email_enabled"): return
    try:
        msg = MIMEMultipart()
        msg["From"] = s["sender"]
        msg["To"] = s["recipient"]
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))
        with smtplib.SMTP(s["smtp_server"], s["smtp_port"]) as server:
            server.starttls()
            server.login(s["sender"], s["password"])
            server.send_message(msg)
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")

def send_push_notification(message):
    s = current_config["settings"]
    if not s.get("push_enabled"): return
    url = s.get("webhook_url")
    if not url: return
    try:
        requests.post(url, json={"message": message}, timeout=10)
    except Exception as e:
        logger.error(f"推送失败: {e}")

def parse_to_trigger(reminder):
    t_str = reminder["time"]
    rep = reminder.get("repeat", "daily")
    
    # 纯时间 HH:MM:SS 或 HH:MM
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
            
    # 特定日期
    if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', t_str):
        return DateTrigger(run_date=t_str)
        
    return None

def update_scheduler():
    scheduler.remove_all_jobs()
    for r in current_config["reminders"]:
        if r.get("status") == "completed": continue
        try:
            trigger = parse_to_trigger(r)
            if trigger:
                scheduler.add_job(trigger_reminder, trigger, args=[r["id"]], id=f"job_{r['id']}")
        except Exception as e:
            logger.error(f"添加提醒失败 [{r['title']}]: {e}")
            
    if not scheduler.running:
        scheduler.start()

# --- API ---

@app.route('/')
def index():
    try:
        with open('templates/index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except:
        return "Internal Error: templates/index.html missing"

@app.route('/api/data', methods=['GET'])
def get_all_data():
    return jsonify(current_config)

@app.route('/api/reminders', methods=['POST'])
def add_reminder():
    reminder = request.json
    reminder["id"] = str(uuid.uuid4())
    reminder["status"] = reminder.get("status", "pending")
    current_config["reminders"].append(reminder)
    save_config(current_config)
    update_scheduler()
    return jsonify(reminder)

@app.route('/api/reminders/<rid>', methods=['PUT'])
def update_reminder(rid):
    data = request.json
    for i, r in enumerate(current_config["reminders"]):
        if r["id"] == rid:
            current_config["reminders"][i].update(data)
            break
    save_config(current_config)
    update_scheduler()
    return jsonify({"status": "success"})

@app.route('/api/reminders/<rid>', methods=['DELETE'])
def delete_reminder(rid):
    current_config["reminders"] = [r for r in current_config["reminders"] if r["id"] != rid]
    save_config(current_config)
    update_scheduler()
    return jsonify({"status": "success"})

@app.route('/api/settings', methods=['POST'])
def update_settings():
    current_config["settings"].update(request.json)
    save_config(current_config)
    update_scheduler()
    return jsonify({"status": "success"})

@app.route('/api/history', methods=['GET'])
def get_hist():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify([])

if __name__ == "__main__":
    update_scheduler()
    port = int(os.getenv("APP_PORT", 5000))
    app.run(host="0.0.0.0", port=port)