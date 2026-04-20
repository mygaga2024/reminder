import datetime
import os
import logging
import json
import requests
import re
import uuid
import zoneinfo
import random
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

DATETIME_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
TIME_PATTERN = re.compile(r'^\d{1,2}:\d{2}$')

TIPS_LIST = [
    "💡 每天一苹果，医生远离我！",
    "🌸 保持好心情，万事皆顺利！",
    "☀️ 新的一天，新的开始！",
    "🌈 今日份的小幸运正在派送中~",
    "🍀 愿你今天事事顺心！",
    "🌻 阳光正好，未来可期！",
    "✨ 生活明朗，万物可爱！",
    "🎯 今日目标：开心最重要！",
    "🦋 偶尔放慢脚步，看看身边的美好~",
    "📚 每天进步一点点，成就更好的自己！"
]

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

log_handler = ListHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger()
logger.addHandler(log_handler)
logger.addHandler(stream_handler)
logger.setLevel(logging.INFO)

db_lock = threading.RLock()

# 环境变量配置
VERSION = "3.2.14"
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
APP_PORT = int(os.getenv("APP_PORT", 5000))
TZ = os.getenv("TZ", "Asia/Shanghai")
TZ_ENV = zoneinfo.ZoneInfo(TZ)

# --- Persistence Health Check ---
PERSISTENCE_HEALTH = {"status": "ok", "error": None, "is_writable": False, "is_mount": False}

# 确保数据目录存在并检测权限
logger.info(f"=== 环境诊断 ===")
logger.info(f"当前用户 UID: {os.getuid()}, GID: {os.getgid()}")
logger.info(f"数据存储目录: {DATA_DIR}")

try:
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        logger.info(f"创建数据目录: {DATA_DIR}")
    
    # 检查目录权限和挂载状态
    PERSISTENCE_HEALTH["is_writable"] = os.access(DATA_DIR, os.W_OK)
    PERSISTENCE_HEALTH["is_mount"] = os.path.ismount(DATA_DIR)
    
    # 增加物理写入测试 (Real Write Test)
    test_file = os.path.join(DATA_DIR, ".write_test")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        PERSISTENCE_HEALTH["real_write_test"] = True
    except Exception as e:
        PERSISTENCE_HEALTH["real_write_test"] = False
        PERSISTENCE_HEALTH["error"] = str(e)
        PERSISTENCE_HEALTH["status"] = "error"

    logger.info(f"数据目录写入权限: {PERSISTENCE_HEALTH['is_writable']}")
    logger.info(f"数据目录是否为挂载点: {PERSISTENCE_HEALTH['is_mount']}")
    logger.info(f"物理写入测试: {PERSISTENCE_HEALTH.get('real_write_test')}")
    
    if PERSISTENCE_HEALTH["status"] == "error" or not PERSISTENCE_HEALTH["is_writable"]:
        logger.error(f"⚠️ 关键警告: 数据目录 {DATA_DIR} 持久化能力受限！原因: {PERSISTENCE_HEALTH['error']}")
        logger.error("极空间用户通过以下步骤修复：1. 开启合规目录最大读写权限；2. 调低 PUID/PGID 或设为 0。")
    
except Exception as e:
    logger.error(f"环境诊断失败: {e}")
    PERSISTENCE_HEALTH["status"] = "critical"
    PERSISTENCE_HEALTH["error"] = str(e)
logger.info(f"=====================")

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
            if os.path.getsize(filepath) == 0:
                logger.warning(f"文件存在但为空，将初始化: {filepath}")
                return default
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"成功加载文件: {filepath} (大小: {os.path.getsize(filepath)} bytes)")
                return data
        except json.JSONDecodeError as e:
            logger.error(f"💥 JSON解析失败 ({filepath}): {e}. 文件可能损坏，请检查！")
            # 不直接返回default，防止覆盖损坏的文件
            # 如果是重要配置，这里可以考虑备份损坏文件
            backup_path = filepath + ".bak_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            try:
                import shutil
                shutil.copy2(filepath, backup_path)
                logger.info(f"由于解析失败，已备份损坏文件至: {backup_path}")
            except Exception as be:
                logger.error(f"备份损坏文件失败: {be}")
        except Exception as e:
            logger.error(f"读取文件失败 ({filepath}): {e}")
    else:
        logger.info(f"文件不存在，将初始化: {filepath}")
    return default

def save_json(filepath, data):
    """保存JSON文件，使用原子写入防止数据损坏"""
    with db_lock:
        try:
            dir_path = os.path.dirname(filepath)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
            
            temp_file = filepath + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            os.replace(temp_file, filepath)
            # 记录最后成功写入时间，用于健康检查
            PERSISTENCE_HEALTH["last_save"] = datetime.datetime.now().isoformat()
            PERSISTENCE_HEALTH["status"] = "ok"
            logger.info(f"成功保存文件: {filepath}")
        except Exception as e:
            PERSISTENCE_HEALTH["status"] = "error"
            PERSISTENCE_HEALTH["error"] = str(e)
            logger.error(f"保存文件失败 ({filepath}): {e}")
            raise # 抛出异常，让API层感知到持久化失败

# 加载数据
db = load_json(CONFIG_FILE, {
    "reminders": [],
    "settings": {
        "language": "zh",
        "dark_mode": True,
        "webhooks": {"wecom": "", "dingtalk": "", "lark": ""}
    },
    "users": {}
})
logs = load_json(LOGS_FILE, [])

logger.info(f"=== 系统启动摘要 ===")
logger.info(f"时区: {TZ}")
logger.info(f"配置文件路径: {CONFIG_FILE}")
logger.info(f"配置文件存在: {os.path.exists(CONFIG_FILE)}")
logger.info(f"加载提醒数量: {len(db.get('reminders', []))}")
logger.info(f"加载日志数量: {len(logs)}")
logger.info(f"=====================")

def notify_engine(reminder):
    """通知引擎，添加详细的错误处理"""
    with db_lock:
        try:
            rep = reminder.get("repeat", "none")
            
            if rep == "workday":
                today = datetime.date.today()
                if not is_china_workday(today):
                    logger.info(f"工作日任务跳过（非法定工作日）: {reminder.get('title')} - {today}")
                    return
            
            s = db["settings"]
            title = reminder.get("title", "未命名提醒")
            now = datetime.datetime.now()
            date_str = now.strftime('%Y年%m月%d日')
            time_str = now.strftime('%H:%M')
            
            tip = random.choice(TIPS_LIST)
            
            rep_label = {"once": "一次性", "daily": "每天", "weekly": "每周", "workday": "工作日"}.get(rep, "每天")
            msg = f"""⏰ 您有一个提醒！

📝 提醒内容：{title}
📅 提醒时间：{date_str} {time_str}
🔄 重复类型：{rep_label}

{tip}"""

            # 发送通知
            for platform, url in s.get("webhooks", {}).items():
                if not url: continue
                try:
                    if platform in ["wecom", "dingtalk", "lark"]:
                        payload = {"msgtype": "text", "text": {"content": msg}}
                        if platform == "lark":
                            payload = {"msg_type": "text", "content": {"text": msg}}
                        
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
            
            # 清理超过30天的日志
            cutoff = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
            logs[:] = [l for l in logs if l.get("triggered_at", "") > cutoff]
            
            save_json(LOGS_FILE, logs)
            logger.info(f"提醒已触发: {title}")

            # 一次性任务触发后自动删除并从调度器移除
            if rep == "once":
                rid = reminder.get("id")
                try:
                    scheduler.remove_job(rid)
                    logger.info(f"调度任务已移除: {rid}")
                except Exception as e:
                    logger.warning(f"移除调度任务失败: {e}")
                db["reminders"] = [r for r in db["reminders"] if r.get("id") != rid]
                save_json(CONFIG_FILE, db)
                logger.info(f"一次性任务已自动删除: {title}")
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
    with db_lock:
        try:
            job_count = len(scheduler.get_jobs())
            if job_count > 0:
                scheduler.remove_all_jobs()
                logger.info(f"已清理旧调度任务 (共 {job_count} 个)")
            
            # 记录启用状态
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
                    if DATETIME_PATTERN.match(t_str):
                        target_dt = datetime.datetime.strptime(t_str, '%Y-%m-%d %H:%M')
                        target_dt = target_dt.replace(tzinfo=TZ_ENV)
                        if target_dt <= datetime.datetime.now(TZ_ENV):
                            target_dt += datetime.timedelta(days=1)
                        trigger = DateTrigger(run_date=target_dt)
                    elif TIME_PATTERN.match(t_str):
                        h, m = t_str.split(':')[:2]
                        if rep == "daily":
                            trigger = CronTrigger(hour=h, minute=m)
                        elif rep.startswith("weekly:"):
                            days = rep.split(":")[1]
                            trigger = CronTrigger(day_of_week=days, hour=h, minute=m)
                        elif rep == "workday":
                            trigger = CronTrigger(hour=h, minute=m, day_of_week='mon-fri')
                        else:
                            target_datetime = datetime.datetime.combine(datetime.date.today(), datetime.time(int(h), int(m)))
                            if target_datetime <= datetime.datetime.now(TZ_ENV):
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
    """首页"""
    try:
        with open('templates/index.html', 'r', encoding='utf-8') as f:
            content = f.read()
        return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
    except FileNotFoundError:
        logger.error("index.html文件不存在")
        return "错误：无法加载页面", 500
    except Exception as e:
        logger.error(f"加载首页失败: {e}")
        return "错误：加载页面失败", 500

@app.route('/api/state')
def get_state():
    """获取系统状态"""
    with db_lock:
        try:
            return jsonify({
                "db": db, 
                "logs": logs[-100:], 
                "syslogs": log_handler.logs[::-1], 
                "version": VERSION,
                "persistence": PERSISTENCE_HEALTH
            })
        except Exception as e:
            logger.error(f"获取状态失败: {e}")
            return jsonify({"error": "获取状态失败"}), 500

@app.route('/api/reminders', methods=['POST'])
def add_reminder():
    """添加提醒"""
    with db_lock:
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
            return jsonify({"error": "添加提醒失败"}), 500

@app.route('/api/reminders/<rid>', methods=['PUT', 'DELETE'])
def mod_reminder(rid):
    """修改或删除提醒"""
    with db_lock:
        try:
            if request.method == 'DELETE':
                db["reminders"] = [r for r in db["reminders"] if r["id"] != rid]
                try:
                    scheduler.remove_job(rid)
                except Exception:
                    pass
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
                                    break
                            save_json(LOGS_FILE, logs)
                        db["reminders"][i].update(update)
                        logger.info(f"更新提醒: {r.get('title')}")
                        break
            
            save_json(CONFIG_FILE, db)
            update_scheduler()
            return jsonify({"status": "ok"})
        except Exception as e:
            logger.error(f"修改提醒失败: {e}")
            return jsonify({"error": "修改提醒失败"}), 500

@app.route('/api/settings', methods=['POST'])
def mod_settings():
    """修改设置"""
    with db_lock:
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
            return jsonify({"error": "修改设置失败"}), 500

@app.route('/api/wxlogin', methods=['POST'])
def wx_login():
    """微信登录"""
    with db_lock:
        try:
            code = request.json.get('code')
            if not code:
                return jsonify({"error": "code 不能为空"}), 400

            appid = os.getenv("WX_APPID", "")
            secret = os.getenv("WX_SECRET", "")

            if not appid or not secret:
                return jsonify({"error": "未配置微信AppID和Secret，请检查环境变量"}), 400

            import urllib.request
            url = f"https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={secret}&js_code={code}&grant_type=authorization_code"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            if "openid" in data:
                wxid = data["openid"]
                if "users" not in db:
                    db["users"] = {}
                if wxid not in db["users"]:
                    db["users"][wxid] = {
                        "openid": wxid,
                        "created_at": datetime.datetime.now().isoformat()
                    }
                save_json(CONFIG_FILE, db)
                logger.info(f"微信用户登录: {wxid}")
                return jsonify({"openid": wxid, "status": "ok"})
            else:
                logger.error(f"微信接口返回错误: {data.get('errmsg', 'unknown')}")
                return jsonify({"error": "微信接口错误"}), 400
        except Exception as e:
            logger.error(f"微信登录失败: {e}")
            return jsonify({"error": "微信登录失败"}), 500

# 初始化数据库结构
def init_db():
    global db, logs
    if not isinstance(db.get("reminders"), list):
        db["reminders"] = []
    if "settings" not in db:
        db["settings"] = {"sound": True, "vibrate": True, "notify": True, "dark": True}
    if "users" not in db:
        db["users"] = {}
    if not isinstance(logs, list):
        logs = []

if __name__ == "__main__":
    try:
        from waitress import serve
        logger.info(f"Life Reminder Engine v{VERSION} 启动中...")
        logger.info(f"服务端口: {APP_PORT}")
        logger.info(f"时区: {TZ}")

        init_db()
        update_scheduler()

        logger.info("服务启动成功，监听 0.0.0.0:%d" % APP_PORT)
        serve(app, host="0.0.0.0", port=APP_PORT)
    except ImportError as e:
        logger.error(f"缺少依赖: {e}")
        print(f"错误: 缺少依赖 - {e}")
        print("请运行: pip install -r requirements.txt")
    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        print(f"错误: 服务启动失败 - {e}")
