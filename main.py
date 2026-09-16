#!/usr/bin/env python3
"""Life Reminder Engine - Main Entry Point"""
from flask import Flask
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import (
    VERSION, APP_PORT, TZ, TZ_ENV, logger, log_handler,
    CONFIG_FILE, LOGS_FILE, PERSISTENCE_HEALTH, API_KEY, ALLOW_REGISTRATION
)
from app.persistence import run_health_check, load_json, save_json, init_db
from app.scheduler import update_scheduler
from app.notifier import notify_engine
from app.calendar_utils import check_calendar_coverage
from app.api import register_routes
from app import users

run_health_check()

db = load_json(CONFIG_FILE, {
    "reminders": [],
    "settings": {
        "language": "zh",
        "dark_mode": True,
        "webhooks": {"wecom": "", "dingtalk": "", "lark": ""}
    },
    "users": {},
    "sessions": {}
})
logs = load_json(LOGS_FILE, [])
db, logs = init_db(db, logs)
# 多账号结构迁移：补齐账号字段、清理过期会话、重建调度器合并视图
account_info = users.migrate_db(db)

logger.info("=== 系统启动摘要 ===")
logger.info(f"时区: {TZ}")
logger.info(f"配置文件路径: {CONFIG_FILE}")
logger.info(f"配置文件存在: {True}")
logger.info(f"加载提醒数量: {len(db.get('reminders', []))}")
logger.info(f"加载日志数量: {len(logs)}")
if account_info["accounts"]:
    logger.info(
        f"多账号模式: 已启用 ({account_info['accounts']} 个账号, "
        f"{account_info['sessions']} 个活跃会话, 数据按账号隔离)"
    )
else:
    logger.warning("多账号模式: 未注册账号（开放模式，注册后自动启用数据隔离）")
logger.info(f"数据结构版本: v{account_info['schema_version']}")
if account_info["legacy_reminders"]:
    logger.info(f"开放模式提醒: {account_info['legacy_reminders']} 条（可被首个账号继承）")
if account_info["purged_sessions"]:
    logger.info(f"已清理过期会话: {account_info['purged_sessions']} 个")
logger.info(f"自助注册: {'已开放' if ALLOW_REGISTRATION else '已关闭（ALLOW_REGISTRATION=false）'}")
if API_KEY:
    logger.info("API Key 认证: 已启用")
else:
    logger.warning("API Key 认证: 未启用（建议设置 API_KEY 环境变量）")
cal_coverage = check_calendar_coverage()
if "缺失" in cal_coverage or "不支持" in cal_coverage or "未安装" in cal_coverage:
    logger.warning(f"中国节假日库: {cal_coverage}")
else:
    logger.info(f"中国节假日库: {cal_coverage}")
logger.info("=====================")

app = Flask(__name__)
CORS(app)
app.config['LIST_HANDLER'] = log_handler
app.config['GLOBAL_DB'] = db
app.config['GLOBAL_LOGS'] = logs

scheduler = BackgroundScheduler(timezone=TZ)
app.config['GLOBAL_SCHEDULER'] = scheduler

register_routes(app, db, logs, scheduler)

# 创建闭包包装 notify_engine，注入 db/logs/scheduler 参数
_notify_fn = lambda r: notify_engine(r, db, logs, scheduler)
update_scheduler(scheduler, db, _notify_fn)

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
