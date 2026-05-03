#!/usr/bin/env python3
"""Life Reminder Engine - Main Entry Point"""
from flask import Flask
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import (
    VERSION, APP_PORT, TZ, TZ_ENV, logger, log_handler,
    CONFIG_FILE, LOGS_FILE, PERSISTENCE_HEALTH, API_KEY
)
from app.persistence import run_health_check, load_json, save_json, init_db
from app.scheduler import update_scheduler
from app.notifier import notify_engine
from app.api import register_routes

run_health_check()

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
db, logs = init_db(db, logs)

logger.info("=== 系统启动摘要 ===")
logger.info(f"时区: {TZ}")
logger.info(f"配置文件路径: {CONFIG_FILE}")
logger.info(f"配置文件存在: {True}")
logger.info(f"加载提醒数量: {len(db.get('reminders', []))}")
logger.info(f"加载日志数量: {len(logs)}")
if API_KEY:
    logger.info("API Key 认证: 已启用")
else:
    logger.warning("API Key 认证: 未启用（建议设置 API_KEY 环境变量）")
logger.info("=====================")

app = Flask(__name__)
CORS(app)
app.config['LIST_HANDLER'] = log_handler
app.config['GLOBAL_DB'] = db
app.config['GLOBAL_LOGS'] = logs

scheduler = BackgroundScheduler(timezone=TZ)
app.config['GLOBAL_SCHEDULER'] = scheduler

register_routes(app, db, logs, scheduler)

update_scheduler(scheduler, db, notify_engine)

if __name__ == "__main__":
    try:
        from waitress import serve
        logger.info(f"Life Reminder Engine v{VERSION} 启动中...")
        logger.info(f"服务端口: {APP_PORT}")
        logger.info(f"时区: {TZ}")
        logger.info("服务启动成功，监听 0.0.0.0:%d" % APP_PORT)
        serve(app, host="0.0.0.0", port=APP_PORT)
    except ImportError as e:
        logger.error(f"缺少依赖: {e}")
        print(f"错误: 缺少依赖 - {e}")
        print("请运行: pip install -r requirements.txt")
    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        print(f"错误: 服务启动失败 - {e}")
