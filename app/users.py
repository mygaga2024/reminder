"""多账号模块：账号存储、密码校验、会话管理与数据作用域

设计约束：
- 本模块只做纯数据操作（dict 增删改查），不涉及 HTTP，也不直接读写磁盘
- 持久化统一由调用方（api.py / main.py）通过 persistence.save_json 完成
- config.json 顶层 reminders / settings 保持原有结构不变：
  - 未注册任何账号时 = 开放模式数据（遗留提醒不带 user 字段）
  - 注册账号后 = 调度器读取的「合并视图」，由 rebuild_flat_reminders() 维护
"""
import datetime
import hashlib
import hmac
import re
import secrets

from app.config import logger, TZ_ENV

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_\u4e00-\u9fa5-]{2,32}$')
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 128
PASSWORD_ITERATIONS = 200000
PASSWORD_SALT_BYTES = 16
SESSION_TTL_DAYS = 30
MAX_ACCOUNTS = 20
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 300

# 登录失败计数（仅内存，重启后清零；不属于持久化数据）
_login_failures = {}


def default_settings() -> dict:
    """默认账号设置（每次返回全新对象，避免共享可变引用）"""
    return {
        "language": "zh",
        "dark_mode": True,
        "webhooks": {"wecom": "", "dingtalk": "", "lark": ""}
    }


def _now() -> datetime.datetime:
    return datetime.datetime.now(TZ_ENV)


def _parse_iso(value):
    """解析 ISO 时间串，失败返回 None；无时区信息按本机时区补齐"""
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ_ENV)
    return parsed


# ═══════════════════════════════════════════
# 密码哈希与校验
# ═══════════════════════════════════════════

def hash_password(password: str, salt_hex: str = None, iterations: int = PASSWORD_ITERATIONS):
    """PBKDF2-HMAC-SHA256 派生密码哈希，返回 (hash_hex, salt_hex)"""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return digest.hex(), salt.hex()


def verify_password(password: str, user: dict) -> bool:
    """恒定时间比较密码哈希"""
    if not isinstance(user, dict):
        return False
    stored_hash = user.get("password_hash")
    salt_hex = user.get("salt")
    if not stored_hash or not salt_hex:
        return False
    try:
        iterations = int(user.get("iterations", PASSWORD_ITERATIONS))
    except (TypeError, ValueError, OverflowError):
        iterations = PASSWORD_ITERATIONS
    try:
        candidate, _ = hash_password(password or "", salt_hex, iterations)
    except ValueError as e:
        logger.error(f"密码校验失败（盐值异常）: {e}")
        return False
    return hmac.compare_digest(candidate, stored_hash)


def validate_username(username: str):
    """校验用户名格式，返回错误信息或 None"""
    if not username:
        return "用户名不能为空"
    if not USERNAME_PATTERN.match(username):
        return "用户名需为 2-32 位中文、字母、数字、下划线或短横线"
    return None


def validate_password(password: str, confirm: str = None):
    """校验密码格式与一致性，返回错误信息或 None"""
    if not password:
        return "密码不能为空"
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"密码长度不能少于{PASSWORD_MIN_LENGTH}位"
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"密码长度不能超过{PASSWORD_MAX_LENGTH}位"
    if confirm is not None and password != confirm:
        return "两次输入的密码不一致"
    return None


# ═══════════════════════════════════════════
# 账号存储
# ═══════════════════════════════════════════

def users_map(db: dict) -> dict:
    """返回账号字典（结构异常时就地纠正）"""
    users = db.get("users")
    if not isinstance(users, dict):
        logger.warning("users 结构异常，已重置为空字典")
        users = {}
        db["users"] = users
    return users


def get_user(db: dict, username: str):
    """读取账号记录"""
    if not username:
        return None
    return users_map(db).get(username)


def account_count(db: dict) -> int:
    """已注册（含密码）账号数量"""
    return sum(
        1 for user in users_map(db).values()
        if isinstance(user, dict) and user.get("password_hash")
    )


def has_accounts(db: dict) -> bool:
    """是否已启用多账号模式"""
    return account_count(db) > 0


def list_usernames(db: dict) -> list:
    """已注册账号名列表"""
    return sorted(
        name for name, user in users_map(db).items()
        if isinstance(user, dict) and user.get("password_hash")
    )


def ensure_user_shape(user: dict) -> dict:
    """补齐账号记录结构（增量，不覆盖已有字段）"""
    if not isinstance(user.get("reminders"), list):
        user["reminders"] = []
    settings = user.get("settings")
    if not isinstance(settings, dict):
        user["settings"] = default_settings()
    else:
        for key, value in default_settings().items():
            if key not in settings:
                settings[key] = value
        if not isinstance(settings.get("webhooks"), dict):
            settings["webhooks"] = {}
    return user


def create_user(db: dict, username: str, password: str, confirm: str = None):
    """创建账号，返回 (user, error)"""
    username = (username or "").strip()
    error = validate_username(username)
    if error:
        return None, error
    error = validate_password(password, confirm)
    if error:
        return None, error

    users = users_map(db)
    existing = users.get(username)
    if isinstance(existing, dict) and existing.get("password_hash"):
        return None, "该用户名已被注册"
    if account_count(db) >= MAX_ACCOUNTS:
        return None, f"账号数量已达上限（{MAX_ACCOUNTS} 个）"

    password_hash, salt_hex = hash_password(password)
    user = ensure_user_shape(existing if isinstance(existing, dict) else {})
    user.update({
        "username": username,
        "password_hash": password_hash,
        "salt": salt_hex,
        "iterations": PASSWORD_ITERATIONS,
        "created_at": _now().isoformat(),
    })
    users[username] = user
    logger.info(f"创建账号: {username}")
    return user, None


def change_password(db: dict, username: str, old_password: str, new_password: str, confirm: str = None):
    """修改密码，返回错误信息或 None"""
    user = get_user(db, username)
    if not isinstance(user, dict) or not user.get("password_hash"):
        return "账号不存在"
    if not verify_password(old_password or "", user):
        return "原密码不正确"
    error = validate_password(new_password, confirm)
    if error:
        return error

    password_hash, salt_hex = hash_password(new_password)
    user["password_hash"] = password_hash
    user["salt"] = salt_hex
    user["iterations"] = PASSWORD_ITERATIONS
    user["password_changed_at"] = _now().isoformat()
    logger.info(f"账号密码已更新: {username}")
    return None


# ═══════════════════════════════════════════
# 登录失败锁定（内存态，防暴力破解）
# ═══════════════════════════════════════════

def check_login_lock(username: str):
    """返回锁定提示或 None"""
    record = _login_failures.get(username)
    if not record:
        return None
    if record.get("count", 0) < LOGIN_MAX_FAILURES:
        return None
    locked_at = record.get("locked_at")
    elapsed = (_now() - locked_at).total_seconds() if locked_at else LOGIN_LOCK_SECONDS
    if elapsed < LOGIN_LOCK_SECONDS:
        remain = int(LOGIN_LOCK_SECONDS - elapsed) + 1
        return f"登录失败次数过多，请 {remain} 秒后再试"
    clear_login_failures(username)
    return None


def record_login_failure(username: str) -> None:
    """记录一次登录失败"""
    record = _login_failures.setdefault(username, {"count": 0, "locked_at": None})
    record["count"] = record.get("count", 0) + 1
    if record["count"] >= LOGIN_MAX_FAILURES:
        record["locked_at"] = _now()
    logger.warning(f"登录失败: {username} (累计 {record['count']} 次)")


def clear_login_failures(username: str) -> None:
    """清除登录失败计数"""
    _login_failures.pop(username, None)


def authenticate(db: dict, username: str, password: str):
    """校验账号密码，返回 (username, error)"""
    username = (username or "").strip()
    lock_message = check_login_lock(username)
    if lock_message:
        return None, lock_message

    user = get_user(db, username)
    if not isinstance(user, dict) or not user.get("password_hash") or not verify_password(password or "", user):
        record_login_failure(username)
        return None, "账号或密码错误"

    clear_login_failures(username)
    return username, None


# ═══════════════════════════════════════════
# 会话管理
# ═══════════════════════════════════════════

def sessions_map(db: dict) -> dict:
    """返回会话字典（结构异常时就地纠正）"""
    sessions = db.get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}
        db["sessions"] = sessions
    return sessions


def _token_key(token: str) -> str:
    """会话落盘只保存 token 的 SHA-256，避免明文泄露"""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def create_session(db: dict, username: str, days: int = SESSION_TTL_DAYS) -> str:
    """创建会话并返回明文 token（仅本次返回）"""
    token = secrets.token_urlsafe(32)
    now = _now()
    sessions_map(db)[_token_key(token)] = {
        "username": username,
        "created_at": now.isoformat(),
        "expires_at": (now + datetime.timedelta(days=days)).isoformat(),
        "last_seen": now.isoformat(),
    }
    return token


def resolve_session(db: dict, token: str):
    """校验会话 token，返回账号名或 None（过期会话就地清理）"""
    if not token:
        return None
    sessions = sessions_map(db)
    key = _token_key(token)
    record = sessions.get(key)
    if not isinstance(record, dict):
        return None

    expires_at = _parse_iso(record.get("expires_at"))
    if expires_at and expires_at <= _now():
        sessions.pop(key, None)
        logger.info(f"会话已过期: {record.get('username')}")
        return None

    username = record.get("username")
    if not username or not isinstance(get_user(db, username), dict):
        sessions.pop(key, None)
        return None

    record["last_seen"] = _now().isoformat()
    return username


def destroy_session(db: dict, token: str) -> bool:
    """注销单个会话"""
    if not token:
        return False
    return sessions_map(db).pop(_token_key(token), None) is not None


def destroy_user_sessions(db: dict, username: str) -> int:
    """注销某账号全部会话（修改密码后强制重新登录）"""
    sessions = sessions_map(db)
    keys = [k for k, v in sessions.items() if isinstance(v, dict) and v.get("username") == username]
    for key in keys:
        sessions.pop(key, None)
    return len(keys)


def purge_expired_sessions(db: dict) -> int:
    """清理失效会话，返回清理数量"""
    sessions = sessions_map(db)
    now = _now()
    expired = []
    for key, record in sessions.items():
        if not isinstance(record, dict):
            expired.append(key)
            continue
        expires_at = _parse_iso(record.get("expires_at"))
        if expires_at and expires_at <= now:
            expired.append(key)
    for key in expired:
        sessions.pop(key, None)
    return len(expired)


# ═══════════════════════════════════════════
# 数据作用域（账号隔离）
# ═══════════════════════════════════════════

def user_scope(db: dict, username: str):
    """返回账号数据作用域（reminders / settings 引用），账号不存在返回 None"""
    user = get_user(db, username)
    if not isinstance(user, dict):
        return None
    return ensure_user_shape(user)


def owned_settings(db: dict, reminder: dict) -> dict:
    """返回提醒归属账号的设置；无归属（开放模式）时回落顶层设置"""
    owner = reminder.get("user") if isinstance(reminder, dict) else None
    user = get_user(db, owner) if owner else None
    if isinstance(user, dict):
        return ensure_user_shape(user)["settings"]
    settings = db.get("settings")
    return settings if isinstance(settings, dict) else default_settings()


def rebuild_flat_reminders(db: dict) -> list:
    """重建调度器读取的合并视图：开放模式提醒 + 全部账号提醒"""
    legacy = [r for r in db.get("reminders", []) if isinstance(r, dict) and not r.get("user")]
    merged = list(legacy)
    for name, user in users_map(db).items():
        if not isinstance(user, dict):
            continue
        ensure_user_shape(user)
        for reminder in user["reminders"]:
            if not isinstance(reminder, dict):
                continue
            reminder["user"] = name
            merged.append(reminder)
    db["reminders"] = merged
    return merged


def remove_reminder(db: dict, reminder_id: str) -> int:
    """按 id 删除提醒（账号列表 + 合并视图），返回删除数量"""
    removed = 0
    for user in users_map(db).values():
        if not isinstance(user, dict):
            continue
        ensure_user_shape(user)
        before = len(user["reminders"])
        user["reminders"][:] = [
            r for r in user["reminders"] if not (isinstance(r, dict) and r.get("id") == reminder_id)
        ]
        removed += before - len(user["reminders"])

    current = db.get("reminders", [])
    before_flat = len(current)
    db["reminders"] = [
        r for r in current if not (isinstance(r, dict) and r.get("id") == reminder_id)
    ]
    removed += before_flat - len(db["reminders"])

    rebuild_flat_reminders(db)
    return removed


def legacy_stats(db: dict, logs: list = None) -> dict:
    """开放模式（未归属账号）数据统计，用于前端引导提示"""
    legacy_reminders = [
        r for r in db.get("reminders", [])
        if isinstance(r, dict) and not r.get("user")
    ]
    legacy_logs = [
        l for l in (logs or [])
        if isinstance(l, dict) and not l.get("user")
    ]
    return {
        "reminders": len(legacy_reminders),
        "logs": len(legacy_logs),
    }


def claim_legacy_data(db: dict, username: str) -> int:
    """把开放模式数据迁移到指定账号名下，返回迁移的提醒数量"""
    user = user_scope(db, username)
    if not isinstance(user, dict):
        return 0

    legacy = [
        r for r in db.get("reminders", [])
        if isinstance(r, dict) and not r.get("user")
    ]
    for reminder in legacy:
        reminder["user"] = username
        if reminder not in user["reminders"]:
            user["reminders"].append(reminder)

    # 开放模式的设置（含 Webhook）一并继承，仅当账号仍为默认设置时
    legacy_settings = db.get("settings")
    if isinstance(legacy_settings, dict) and legacy_settings:
        if user["settings"] == default_settings():
            merged = default_settings()
            for key, value in legacy_settings.items():
                if key != "webhooks":
                    merged[key] = value
            if isinstance(legacy_settings.get("webhooks"), dict):
                merged["webhooks"].update(legacy_settings["webhooks"])
            user["settings"] = merged

    rebuild_flat_reminders(db)
    logger.info(f"继承开放模式数据到账号 {username}: {len(legacy)} 条提醒")
    return len(legacy)


def public_user_info(db: dict, username: str):
    """账号公开信息（不含密码相关字段）"""
    user = user_scope(db, username)
    if not isinstance(user, dict):
        return None
    reminders = user["reminders"]
    return {
        "username": username,
        "created_at": user.get("created_at"),
        "reminders": len(reminders),
        "pending": len([r for r in reminders if r.get("status") != "completed"]),
    }


def migrate_db(db: dict) -> dict:
    """启动时结构迁移：补齐账号结构、清理过期会话、重建合并视图"""
    users = users_map(db)
    for name, user in list(users.items()):
        if not isinstance(user, dict):
            logger.warning(f"账号记录结构异常，已跳过补全: {name}")
            continue
        ensure_user_shape(user)
        for reminder in user["reminders"]:
            if isinstance(reminder, dict):
                reminder["user"] = name

    purged = purge_expired_sessions(db)
    merged = rebuild_flat_reminders(db)
    legacy = len([r for r in merged if not r.get("user")])

    info = {
        "accounts": account_count(db),
        "sessions": len(sessions_map(db)),
        "purged_sessions": purged,
        "reminders": len(merged),
        "legacy_reminders": legacy,
    }
    return info
