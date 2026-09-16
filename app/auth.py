import re
import datetime
from functools import wraps
from flask import request, jsonify, g, current_app

from app.config import API_KEY, VALID_REPEAT_MODES, VALID_PRIORITIES
from app.config import TITLE_MAX_LENGTH, TIME_MAX_LENGTH, WEBHOOK_URL_MAX_LENGTH
from app.config import DATETIME_PATTERN, TIME_PATTERN
from app import users

SESSION_HEADER = "X-Auth-Token"


def require_api_key(f):
    """API Key 认证中间件"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY:
            return f(*args, **kwargs)
        key = request.headers.get("X-API-Key", "") or request.args.get("api_key", "")
        if key != API_KEY:
            return jsonify({"error": "Unauthorized: Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated


def current_token() -> str:
    """读取请求携带的会话 token"""
    return (request.headers.get(SESSION_HEADER) or "").strip()


def require_login(f):
    """多账号会话中间件

    - 尚未注册任何账号时保持开放模式：g.username = None，数据落在顶层 db
    - 已注册账号后必须携带有效 X-Auth-Token，否则返回 401 (code=unauthenticated)
    - 校验通过后注入 g.username / g.auth_token，供 api.py 做账号数据隔离
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        db = current_app.config.get('GLOBAL_DB') or {}
        token = current_token()
        username = users.resolve_session(db, token) if token else None
        if not username and users.has_accounts(db):
            return jsonify({"error": "未登录或会话已过期", "code": "unauthenticated"}), 401
        g.username = username
        g.auth_token = token if username else ""
        return f(*args, **kwargs)
    return decorated


def validate_reminder_input(data: dict) -> list:
    """校验提醒输入，返回错误列表"""
    errors = []

    title = data.get("title", "").strip()
    if not title:
        errors.append("任务名称不能为空")
    elif len(title) > TITLE_MAX_LENGTH:
        errors.append(f"任务名称长度不能超过{TITLE_MAX_LENGTH}")

    time_val = data.get("time", "").strip()
    if not time_val:
        errors.append("提醒时间不能为空")
    elif len(time_val) > TIME_MAX_LENGTH:
        errors.append("提醒时间格式无效")
    else:
        errors.extend(validate_time_value(time_val))

    repeat = data.get("repeat", "daily")
    if repeat.startswith("weekly:"):
        days = repeat.split(":")[1].split(",") if ":" in repeat else []
        valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        if not days or not all(d in valid_days for d in days):
            errors.append("每周重复的星期格式无效")
    elif repeat not in VALID_REPEAT_MODES:
        errors.append(f"重复模式无效，允许的值: {', '.join(VALID_REPEAT_MODES)}")

    priority = data.get("priority", "low")
    if priority not in VALID_PRIORITIES:
        errors.append(f"优先级无效，允许的值: {', '.join(VALID_PRIORITIES)}")

    return errors


def validate_time_value(time_val: str) -> list:
    """校验提醒时间值，返回错误列表

    支持两种格式：
    - HH:MM        （每日/每周/工作日/每月/每年等重复模式）
    - YYYY-MM-DD HH:MM（一次性任务，以及每年/农历每年的月日来源）
    """
    errors = []

    if DATETIME_PATTERN.match(time_val):
        try:
            datetime.datetime.strptime(time_val, "%Y-%m-%d %H:%M")
        except ValueError:
            errors.append("提醒日期无效，请检查日期是否存在")
        return errors

    if TIME_PATTERN.match(time_val):
        hour, minute = time_val.split(":")[:2]
        try:
            hour_val = int(hour)
            minute_val = int(minute)
        except (ValueError, TypeError, OverflowError):
            errors.append("提醒时间格式无效")
            return errors
        if not (0 <= hour_val <= 23 and 0 <= minute_val <= 59):
            errors.append("提醒时间超出范围，应为 00:00 - 23:59")
        return errors

    errors.append("提醒时间格式无效，应为 HH:MM 或 YYYY-MM-DD HH:MM")
    return errors


def validate_webhook_url(url: str) -> bool:
    """校验 Webhook URL 格式"""
    if not url:
        return True
    if len(url) > WEBHOOK_URL_MAX_LENGTH:
        return False
    return bool(re.match(r'^https?://', url))


def sanitize_log_message(msg: str) -> str:
    """脱敏日志消息中的敏感信息 (如 wx secret)"""
    return re.sub(r'secret=([^&\s]+)', r'secret=***', msg)
