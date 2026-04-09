import time
import datetime
import os
import smtplib
import logging
import json
import requests
import re
import threading
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
    """从文件或环境变量加载配置"""
    default_config = {
        "reminder_rules": os.getenv("REMINDER_RULES", "09:00:00,12:00:00,18:00:00").split(","),
        "email": {
            "enabled": os.getenv("EMAIL_ENABLED", "False").lower() == "true",
            "smtp_server": os.getenv("SMTP_SERVER", "smtp.example.com"),
            "smtp_port": int(os.getenv("SMTP_PORT", "587")),
            "sender": os.getenv("EMAIL_SENDER", ""),
            "password": os.getenv("EMAIL_PASSWORD", ""),
            "recipient": os.getenv("EMAIL_RECIPIENT", "")
        },
        "push": {
            "enabled": os.getenv("PUSH_ENABLED", "False").lower() == "true",
            "webhook_url": os.getenv("PUSH_WEBHOOK_URL", "")
        }
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                # 简单合并默认值
                for key in default_config:
                    if key not in loaded:
                        loaded[key] = default_config[key]
                return loaded
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            
    return default_config

def save_config(config):
    """保存配置到文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        return False

# 初始化全局配置
current_config = load_config()

def save_reminder_history(trigger_info, message):
    """保存提醒历史到数据文件"""
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            logger.error(f"读取历史文件失败: {e}")
    
    new_record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "trigger": trigger_info,
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
    if not current_config["email"]["enabled"]:
        return
    try:
        msg = MIMEMultipart()
        msg["From"] = current_config["email"]["sender"]
        msg["To"] = current_config["email"]["recipient"]
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))
        with smtplib.SMTP(current_config["email"]["smtp_server"], current_config["email"]["smtp_port"]) as server:
            server.starttls()
            server.login(current_config["email"]["sender"], current_config["email"]["password"])
            server.send_message(msg)
        logger.info(f"邮件发送成功: {subject}")
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")

def send_push_notification(message):
    if not current_config["push"]["enabled"]:
        return
    try:
        payload = {"message": message, "timestamp": datetime.datetime.now().isoformat()}
        response = requests.post(current_config["push"]["webhook_url"], json=payload, timeout=10)
        logger.info(f"推送通知发送状态: {response.status_code}")
    except Exception as e:
        logger.error(f"推送通知发送失败: {e}")

def trigger_reminder(rule_str):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"提醒助手：当前时间 {now_str}，触发规则 [{rule_str}]"
    logger.info(f"触发提醒: {message}")
    save_reminder_history(rule_str, message)
    send_email("定时提醒", message)
    send_push_notification(message)

def parse_rule(rule):
    rule = rule.strip()
    # 1. 匹配 Cron 表达式 (以 "cron:" 开头或包含 5-6 个空格分隔的字段)
    if rule.startswith("cron:"):
        cron_expr = rule.replace("cron:", "").strip()
        return CronTrigger.from_crontab(cron_expr)
    
    if len(rule.split()) >= 5:
        try:
            return CronTrigger.from_crontab(rule)
        except:
            pass

    # 2. 匹配特定日期格式: "2026-04-10 18:30:00"
    if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', rule):
        return DateTrigger(run_date=rule)
    
    # 3. 匹配 星期+时间 格式: "mon-fri 09:00:00"
    week_match = re.match(r'^([a-zA-Z\-,*]+)\s+(\d{2}:\d{2}(:\d{2})?)$', rule)
    if week_match:
        day_of_week, time_str = week_match.groups()
        parts = time_str.split(':')
        h = parts[0]
        m = parts[1]
        s = parts[2] if len(parts) > 2 else "00"
        return CronTrigger(day_of_week=day_of_week, hour=h, minute=m, second=s)
    
    # 4. 匹配 纯时间 格式: "09:00:00" 或 "09:00" (每日)
    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', rule):
        parts = rule.split(':')
        h = parts[0]
        m = parts[1]
        s = parts[2] if len(parts) > 2 else "00"
        return CronTrigger(hour=h, minute=m, second=s)
    
    return None

def update_scheduler():
    scheduler.remove_all_jobs()
    for rule in current_config["reminder_rules"]:
        trigger = parse_rule(rule)
        if trigger:
            scheduler.add_job(trigger_reminder, trigger, args=[rule], id=f"job_{rule}")
            logger.info(f"已添加任务: {rule}")
    if not scheduler.running:
        scheduler.start()

# --- Flask Routes ---

@app.route('/')
def index():
    with open('templates/index.html', 'r', encoding='utf-8') as f:
        return render_template_string(f.read())

@app.route('/api/config', methods=['GET'])
def get_api_config():
    return jsonify(current_config)

@app.route('/api/config', methods=['POST'])
def update_api_config():
    global current_config
    new_config = request.json
    if save_config(new_config):
        current_config = new_config
        update_scheduler()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify([])

if __name__ == "__main__":
    update_scheduler()
    port = int(os.getenv("APP_PORT", 5000))
    app.run(host="0.0.0.0", port=port)