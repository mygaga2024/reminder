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

try:
    import chinese_calendar
    CHINESE_CALENDAR_AVAILABLE = True
except ImportError:
    CHINESE_CALENDAR_AVAILABLE = False
    chinese_calendar = None

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

# 环境变量配置
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
APP_PORT = int(os.getenv("APP_PORT", 5000))
TZ = os.getenv("TZ", "Asia/Shanghai")

# 确保数据目录存在
logger.info(f"数据存储目录: {DATA_DIR}")
try:
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        logger.info(f"创建数据目录: {DATA_DIR}")
    # 检查目录权限
    if os.access(DATA_DIR, os.W_OK):
        logger.info("数据目录权限正常")
    else:
        logger.warning("数据目录无写入权限")
except Exception as e:
    logger.error(f"创建数据目录失败: {e}")

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")

app = Flask(__name__)
CORS(app)
scheduler = BackgroundScheduler(timezone=TZ)

# --- DB Persistence ---
def load_json(filepath, default):
    """加载JSON文件，添加详细的错误处理"""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"成功加载文件: {filepath}")
                return data
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败 ({filepath}): {e}")
        except Exception as e:
            logger.error(f"读取文件失败 ({filepath}): {e}")
    else:
        logger.info(f"文件不存在，使用默认值: {filepath}")
    return default

def save_json(filepath, data):
    """保存JSON文件，使用原子写入防止数据损坏"""
    try:
        dir_path = os.path.dirname(filepath)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            logger.info(f"创建目录: {dir_path}")
        
        temp_file = filepath + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        
        os.replace(temp_file, filepath)
        logger.info(f"成功保存文件: {filepath}")
    except Exception as e:
        logger.error(f"保存文件失败 ({filepath}): {e}")

# 加载数据
db = load_json(CONFIG_FILE, {
    "reminders": [],
    "settings": {
        "language": "zh",
        "dark_mode": True,
        "webhooks": {"wecom": "", "dingtalk": "", "lark": ""}
    }
})
logs = load_json(LOGS_FILE, [])

logger.info(f"=== 系统启动诊断 ===")
logger.info(f"数据存储目录: {DATA_DIR}")
logger.info(f"配置文件路径: {CONFIG_FILE}")
logger.info(f"日志文件路径: {LOGS_FILE}")
logger.info(f"配置文件存在: {os.path.exists(CONFIG_FILE)}")
logger.info(f"加载提醒数量: {len(db['reminders'])}")
logger.info(f"加载日志数量: {len(logs)}")
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r") as f:
            file_content = json.load(f)
            logger.info(f"配置文件中提醒数量: {len(file_content.get('reminders', []))}")
    except Exception as e:
        logger.error(f"读取配置文件内容失败: {e}")
logger.info(f"=====================")

def notify_engine(reminder):
    """通知引擎，添加详细的错误处理"""
    try:
        rep = reminder.get("repeat", "none")
        
        if rep == "workday":
            today = datetime.date.today()
            if not is_china_workday(today):
                logger.info(f"工作日任务跳过（非法定工作日）: {reminder.get('title')} - {today}")
                return
        
        s = db["settings"]
        title = reminder.get("title", "未命名提醒")
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        msg = f"⏰ 提醒: {title}\n触发时间: {now_str}"
        
        # 发送通知
        for platform, url in s.get("webhooks", {}).items():
            if not url: continue
            try:
                if platform in ["wecom", "dingtalk", "lark"]:
                    payload = {"msgtype": "text", "text": {"content": msg}}
                    if platform == "lark":
                        payload = {"msg_type": "text", "content": {"text": msg}}
                    
                    # 添加超时处理
                    resp = requests.post(url, json=payload, timeout=10)
                    if resp.status_code == 200:
                        logger.info(f"推送成功 ({platform})")
                    else:
                        logger.error(f"推送失败 ({platform}): HTTP {resp.status_code}")
            except requests.RequestException as e:
                logger.error(f"网络错误 ({platform}): {e}")
            except Exception as e:
                logger.error(f"推送异常 ({platform}): {e}")

        # 记录日志
        log_entry = {
            "id": str(uuid.uuid4()),
            "reminder_id": reminder.get("id", "unknown"),
            "title": title,
            "triggered_at": datetime.datetime.now().isoformat(),
            "completed_at": None,
            "status": "triggered"
        }
        logs.append(log_entry)
        save_json(LOGS_FILE, logs)
        logger.info(f"提醒已触发: {title}")
    except Exception as e:
        logger.error(f"通知引擎错误: {e}")

def is_china_workday(check_date=None):
    """检查指定日期是否为工作日（考虑中国法定节假日）"""
    if check_date is None:
        check_date = datetime.date.today()
    
    if not CHINESE_CALENDAR_AVAILABLE:
        return check_date.weekday() < 5
    
    return chinese_calendar.is_workday(check_date)

def get_next_workday(from_date=None):
    """获取下一个工作日"""
    if from_date is None:
        from_date = datetime.date.today()
    
    if not CHINESE_CALENDAR_AVAILABLE:
        current = from_date
        while current.weekday() >= 5:
            current += datetime.timedelta(days=1)
        return current
    
    return chinese_calendar.get_next_workday(from_date)

def update_scheduler():
    """更新调度器，添加详细的错误处理"""
    try:
        scheduler.remove_all_jobs()
        logger.info("清空现有调度任务")
        
        if CHINESE_CALENDAR_AVAILABLE:
            logger.info("中国法定节假日支持已启用")
        else:
            logger.info("中国法定节假日支持未启用，使用简单工作日判断")
        
        for r in db["reminders"]:
            if r.get("status") == "completed":
                continue
            
            try:
                t_str = r.get("time")
                rep = r.get("repeat", "none")
                
                if not t_str:
                    logger.warning(f"提醒缺少时间配置: {r.get('title')}")
                    continue
                
                trigger = None
                if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}', t_str):
                    trigger = DateTrigger(run_date=t_str)
                elif re.match(r'^\d{1,2}:\d{2}', t_str):
                    h, m = t_str.split(':')[:2]
                    if rep == "daily":
                        trigger = CronTrigger(hour=h, minute=m)
                    elif rep.startswith("weekly:"):
                        days = rep.split(":")[1]
                        trigger = CronTrigger(day_of_week=days, hour=h, minute=m)
                    elif rep == "workday":
                        trigger = CronTrigger(hour=h, minute=m)
                    else:
                        target_datetime = datetime.datetime.combine(datetime.date.today(), datetime.time(int(h), int(m)))
                        if target_datetime <= datetime.datetime.now():
                            target_datetime += datetime.timedelta(days=1)
                        trigger = DateTrigger(run_date=target_datetime)
                
                if trigger:
                    scheduler.add_job(notify_engine, trigger, args=[r], id=r.get('id'))
                    logger.info(f"添加调度任务: {r.get('title')} - {t_str} (重复: {rep})")
                else:
                    logger.warning(f"无法创建触发器: {r.get('title')} - {t_str}")
            except Exception as e:
                logger.error(f"调度任务失败 ({r.get('title')}): {e}")
        
        if not scheduler.running:
            scheduler.start()
            logger.info("调度器已启动")
    except Exception as e:
        logger.error(f"更新调度器错误: {e}")

# --- API ---
@app.route('/')
def home():
    """首页，添加错误处理"""
    try:
        with open('templates/index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        logger.error("index.html文件不存在")
        return "错误：无法加载页面", 500
    except Exception as e:
        logger.error(f"加载首页失败: {e}")
        return "错误：加载页面失败", 500

@app.route('/api/state')
def get_state():
    """获取系统状态"""
    try:
        return jsonify({"db": db, "logs": logs[-100:], "syslogs": log_handler.logs[::-1]})
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/reminders', methods=['POST'])
def add_reminder():
    """添加提醒"""
    try:
        r = request.json
        if not r:
            return jsonify({"error": "请求数据为空"}), 400
        
        r.update({"id": str(uuid.uuid4()), "status": "pending", "created_at": datetime.datetime.now().isoformat()})
        db["reminders"].append(r)
        save_json(CONFIG_FILE, db)
        update_scheduler()
        logger.info(f"添加提醒: {r.get('title')}")
        return jsonify(r)
    except Exception as e:
        logger.error(f"添加提醒失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/reminders/<rid>', methods=['PUT', 'DELETE'])
def mod_reminder(rid):
    """修改或删除提醒"""
    try:
        if request.method == 'DELETE':
            db["reminders"] = [r for r in db["reminders"] if r["id"] != rid]
            logger.info(f"删除提醒: {rid}")
        else:
            update = request.json
            if not update:
                return jsonify({"error": "请求数据为空"}), 400
            
            for i, r in enumerate(db["reminders"]):
                if r["id"] == rid:
                    if update.get("status") == "completed" and r["status"] != "completed":
                        for l in reversed(logs):
                            if l["reminder_id"] == rid and not l["completed_at"]:
                                l["completed_at"] = datetime.datetime.now().isoformat()
                                save_json(LOGS_FILE, logs)
                                break
                    db["reminders"][i].update(update)
                    logger.info(f"更新提醒: {r.get('title')}")
                    break
        
        save_json(CONFIG_FILE, db)
        update_scheduler()
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"修改提醒失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/settings', methods=['POST'])
def mod_settings():
    """修改设置"""
    try:
        update = request.json
        if not update:
            return jsonify({"error": "请求数据为空"}), 400
        
        db["settings"].update(update)
        save_json(CONFIG_FILE, db)
        logger.info("更新设置")
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"修改设置失败: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    try:
        from waitress import serve
        logger.info(f"Life Reminder Engine v3.0.0 启动中...")
        logger.info(f"服务端口: {APP_PORT}")
        logger.info(f"时区: {TZ}")
        
        # 初始化调度器
        update_scheduler()
        
        # 启动服务
        logger.info("服务启动成功，监听 0.0.0.0:%d" % APP_PORT)
        serve(app, host="0.0.0.0", port=APP_PORT)
    except ImportError as e:
        logger.error(f"缺少依赖: {e}")
        print(f"错误: 缺少依赖 - {e}")
        print("请运行: pip install -r requirements.txt")
    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        print(f"错误: 服务启动失败 - {e}")