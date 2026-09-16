import datetime
import uuid
import os
import json
from flask import request, jsonify, g
from app.config import logger, VERSION, PERSISTENCE_HEALTH, API_KEY
from app.config import CONFIG_FILE, LOGS_FILE, TZ_ENV, ALLOW_REGISTRATION
from app.persistence import save_json, db_lock
from app.auth import (
    require_api_key, require_login, current_token,
    validate_reminder_input, validate_webhook_url, sanitize_log_message
)
from app.scheduler import update_scheduler
from app import users


def register_routes(app, db: dict, logs: list, scheduler):
    """注册所有 API 路由"""

    # ─── 多账号数据作用域辅助 ───

    def _username():
        """当前请求的账号名（开放模式为 None）"""
        return getattr(g, "username", None)

    def _scope_reminders() -> list:
        """当前账号可见的提醒列表引用（开放模式为顶层列表）"""
        username = _username()
        if username:
            scope = users.user_scope(db, username)
            if scope is not None:
                return scope["reminders"]
        return db["reminders"]

    def _scope_settings() -> dict:
        """当前账号的设置引用（开放模式为顶层设置）"""
        username = _username()
        if username:
            scope = users.user_scope(db, username)
            if scope is not None:
                return scope["settings"]
        return db["settings"]

    def _log_visible(entry: dict) -> bool:
        """通知记录是否属于当前账号（无归属的记录归开放模式）"""
        username = _username()
        owner = entry.get("user") if isinstance(entry, dict) else None
        return owner == username if username else not owner

    def _visible_logs() -> list:
        """当前账号可见的通知记录（元素为原对象引用）"""
        return [l for l in app.config['GLOBAL_LOGS'] if _log_visible(l)]

    def _persist(persist_logs: bool = False) -> None:
        """落盘：重建调度器合并视图后写入 config.json"""
        users.rebuild_flat_reminders(db)
        save_json(CONFIG_FILE, db)
        if persist_logs:
            save_json(LOGS_FILE, app.config['GLOBAL_LOGS'])

    def _auth_status_payload() -> dict:
        """账号体系状态（供登录页与前端引导使用，不含敏感信息）"""
        legacy = users.legacy_stats(db, app.config['GLOBAL_LOGS'])
        return {
            "login_required": users.has_accounts(db),
            "registration_enabled": ALLOW_REGISTRATION or not users.has_accounts(db),
            "max_accounts": users.MAX_ACCOUNTS,
            "accounts": users.account_count(db),
            "legacy": legacy,
            "version": VERSION,
        }

    def _issue_session(username: str) -> str:
        """创建会话并清理过期会话"""
        token = users.create_session(db, username)
        users.purge_expired_sessions(db)
        return token

    @app.route('/')
    def home():
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

    # ═══════════════════════════════════════════
    # 账号体系（注册 / 登录 / 登出 / 改密）
    # ═══════════════════════════════════════════

    @app.route('/api/auth/status')
    @require_api_key
    def auth_status():
        """账号体系状态（未登录也可访问，用于渲染登录/注册界面）"""
        with db_lock:
            try:
                return jsonify(_auth_status_payload())
            except Exception as e:
                logger.error(f"获取账号状态失败: {e}")
                return jsonify({"error": "获取账号状态失败"}), 500

    @app.route('/api/auth/register', methods=['POST'])
    @require_api_key
    def auth_register():
        """自助注册账号（首个账号可继承开放模式下的现有数据）"""
        with db_lock:
            try:
                payload = request.json or {}
                if users.has_accounts(db) and not ALLOW_REGISTRATION:
                    return jsonify({"error": "系统未开放注册，请联系管理员"}), 403

                user, error = users.create_user(
                    db,
                    payload.get("username", ""),
                    payload.get("password", ""),
                    payload.get("confirm")
                )
                if error:
                    return jsonify({"error": error}), 400

                username = user["username"]
                claimed = 0
                if payload.get("claim_legacy"):
                    claimed = users.claim_legacy_data(db, username)
                    claimed_logs = 0
                    for entry in app.config['GLOBAL_LOGS']:
                        if isinstance(entry, dict) and not entry.get("user"):
                            entry["user"] = username
                            claimed_logs += 1
                    if claimed_logs:
                        save_json(LOGS_FILE, app.config['GLOBAL_LOGS'])

                token = _issue_session(username)
                _persist()
                logger.info(f"注册新账号: {username} (继承提醒 {claimed} 条)")
                return jsonify({"username": username, "token": token, "claimed": claimed})
            except Exception as e:
                logger.error(f"注册失败: {e}")
                return jsonify({"error": "注册失败"}), 500

    @app.route('/api/auth/login', methods=['POST'])
    @require_api_key
    def auth_login():
        with db_lock:
            try:
                payload = request.json or {}
                username, error = users.authenticate(
                    db,
                    payload.get("username", ""),
                    payload.get("password", "")
                )
                if error:
                    return jsonify({"error": error}), 401

                token = _issue_session(username)
                save_json(CONFIG_FILE, db)
                logger.info(f"账号登录: {username}")
                return jsonify({"username": username, "token": token})
            except Exception as e:
                logger.error(f"登录失败: {e}")
                return jsonify({"error": "登录失败"}), 500

    @app.route('/api/auth/logout', methods=['POST'])
    @require_api_key
    def auth_logout():
        with db_lock:
            try:
                token = current_token()
                username = users.resolve_session(db, token)
                removed = users.destroy_session(db, token)
                if removed:
                    save_json(CONFIG_FILE, db)
                logger.info(f"账号退出登录: {username or 'unknown'}")
                return jsonify({"status": "ok", "removed": removed})
            except Exception as e:
                logger.error(f"退出登录失败: {e}")
                return jsonify({"error": "退出登录失败"}), 500

    @app.route('/api/auth/password', methods=['POST'])
    @require_api_key
    @require_login
    def auth_change_password():
        """修改密码：改密后旧会话全部失效，并返回新会话 token"""
        with db_lock:
            try:
                username = _username()
                if not username:
                    return jsonify({"error": "当前为开放模式，请先注册账号"}), 403

                payload = request.json or {}
                error = users.change_password(
                    db,
                    username,
                    payload.get("old_password", ""),
                    payload.get("new_password", ""),
                    payload.get("confirm")
                )
                if error:
                    return jsonify({"error": error}), 400

                users.destroy_user_sessions(db, username)
                token = users.create_session(db, username)
                save_json(CONFIG_FILE, db)
                return jsonify({"status": "ok", "token": token})
            except Exception as e:
                logger.error(f"修改密码失败: {e}")
                return jsonify({"error": "修改密码失败"}), 500

    @app.route('/api/auth/claim-legacy', methods=['POST'])
    @require_api_key
    @require_login
    def auth_claim_legacy():
        """把开放模式（未归属）的遗留数据迁移到当前账号"""
        with db_lock:
            try:
                username = _username()
                if not username:
                    return jsonify({"error": "当前为开放模式，请先注册账号"}), 403

                claimed = users.claim_legacy_data(db, username)
                claimed_logs = 0
                for entry in app.config['GLOBAL_LOGS']:
                    if isinstance(entry, dict) and not entry.get("user"):
                        entry["user"] = username
                        claimed_logs += 1

                if claimed == 0 and claimed_logs == 0:
                    return jsonify({"error": "没有可继承的遗留数据"}), 400

                if claimed_logs:
                    save_json(LOGS_FILE, app.config['GLOBAL_LOGS'])
                _persist()
                update_scheduler(scheduler, db, _make_notify_fn(app))
                logger.info(f"账号 {username} 继承遗留数据: 提醒 {claimed} 条, 历史 {claimed_logs} 条")
                return jsonify({"status": "ok", "reminders": claimed, "logs": claimed_logs})
            except Exception as e:
                logger.error(f"继承遗留数据失败: {e}")
                return jsonify({"error": "继承遗留数据失败"}), 500

    # ═══════════════════════════════════════════
    # 数据接口（按账号隔离）
    # ═══════════════════════════════════════════

    @app.route('/api/state')
    @require_api_key
    @require_login
    def get_state():
        with db_lock:
            try:
                username = _username()
                if username:
                    scope = users.user_scope(db, username)
                else:
                    scope = {"reminders": db["reminders"], "settings": db["settings"]}

                status = _auth_status_payload()
                status["user"] = username
                if username:
                    status["profile"] = users.public_user_info(db, username)

                return jsonify({
                    "db": {
                        "reminders": scope["reminders"],
                        "settings": scope["settings"],
                        "users": {}
                    },
                    "logs": _visible_logs()[-100:],
                    "syslogs": app.config['LIST_HANDLER'].logs[::-1],
                    "version": VERSION,
                    "persistence": PERSISTENCE_HEALTH,
                    "auth_required": bool(API_KEY),
                    "account": status
                })
            except Exception as e:
                logger.error(f"获取状态失败: {e}")
                return jsonify({"error": "获取状态失败"}), 500

    @app.route('/api/reminders', methods=['POST'])
    @require_api_key
    @require_login
    def add_reminder():
        with db_lock:
            try:
                r = request.json
                if not r:
                    return jsonify({"error": "请求数据为空"}), 400

                errors = validate_reminder_input(r)
                if errors:
                    return jsonify({"error": "; ".join(errors)}), 400

                username = _username()
                r.update({
                    "id": str(uuid.uuid4()),
                    "status": "pending",
                    "created_at": datetime.datetime.now(TZ_ENV).isoformat()
                })
                if username:
                    r["user"] = username
                _scope_reminders().append(r)
                _persist()
                update_scheduler(scheduler, db, _make_notify_fn(app))
                logger.info(f"添加提醒: {r.get('title')}")
                return jsonify(r)
            except Exception as e:
                logger.error(f"添加提醒失败: {e}")
                return jsonify({"error": "添加提醒失败"}), 500

    @app.route('/api/reminders/<rid>', methods=['PUT', 'DELETE'])
    @require_api_key
    @require_login
    def mod_reminder(rid):
        with db_lock:
            try:
                scope = _scope_reminders()
                target = next((r for r in scope if r.get("id") == rid), None)
                if target is None:
                    return jsonify({"error": "任务不存在或无权操作"}), 404

                if request.method == 'DELETE':
                    scope[:] = [r for r in scope if r.get("id") != rid]
                    try:
                        scheduler.remove_job(rid)
                    except Exception as e:
                        logger.warning(f"移除调度任务失败: {rid} - {e}")
                    logger.info(f"删除提醒: {rid}")
                else:
                    update = request.json
                    if not update:
                        return jsonify({"error": "请求数据为空"}), 400

                    errors = validate_reminder_input(update)
                    if errors:
                        return jsonify({"error": "; ".join(errors)}), 400

                    if update.get("status") == "completed" and target.get("status") != "completed":
                        for l in reversed(app.config['GLOBAL_LOGS']):
                            if l.get("reminder_id") == rid and _log_visible(l) and not l.get("completed_at"):
                                l["completed_at"] = datetime.datetime.now(TZ_ENV).isoformat()
                                break
                        save_json(LOGS_FILE, app.config['GLOBAL_LOGS'])
                    target.update(update)
                    logger.info(f"更新提醒: {target.get('title')}")

                _persist()
                update_scheduler(scheduler, db, _make_notify_fn(app))
                return jsonify({"status": "ok"})
            except Exception as e:
                logger.error(f"修改提醒失败: {e}")
                return jsonify({"error": "修改提醒失败"}), 500

    @app.route('/api/settings', methods=['POST'])
    @require_api_key
    @require_login
    def mod_settings():
        with db_lock:
            try:
                update = request.json
                if not update:
                    return jsonify({"error": "请求数据为空"}), 400

                webhooks = update.get("webhooks")
                if webhooks:
                    for url in webhooks.values():
                        if url and not validate_webhook_url(url):
                            return jsonify({"error": f"Webhook URL 格式无效: {url}"}), 400

                _scope_settings().update(update)
                save_json(CONFIG_FILE, db)
                logger.info(f"更新设置: {_username() or '开放模式'}")
                return jsonify({"status": "ok"})
            except Exception as e:
                logger.error(f"修改设置失败: {e}")
                return jsonify({"error": "修改设置失败"}), 500

    @app.route('/api/logs/<log_id>', methods=['DELETE'])
    @require_api_key
    @require_login
    def delete_log(log_id):
        """删除通知日志记录（持久化删除，仅限当前账号）"""
        with db_lock:
            try:
                g_logs = app.config['GLOBAL_LOGS']
                before = len(g_logs)
                g_logs[:] = [
                    l for l in g_logs
                    if not (l.get("id") == log_id and _log_visible(l))
                ]
                after = len(g_logs)
                save_json(LOGS_FILE, g_logs)
                logger.info(f"删除日志记录: {log_id} (删除 {before - after} 条)")
                return jsonify({"status": "ok", "deleted": before - after})
            except Exception as e:
                logger.error(f"删除日志失败: {e}")
                return jsonify({"error": "删除日志失败"}), 500

    @app.route('/api/logs/hide/<log_id>', methods=['POST'])
    @require_api_key
    @require_login
    def hide_log(log_id):
        """标记日志为已隐藏（仅限当前账号）"""
        with db_lock:
            try:
                g_logs = app.config['GLOBAL_LOGS']
                for l in g_logs:
                    if l.get("id") == log_id and _log_visible(l):
                        l["hidden"] = True
                        break
                save_json(LOGS_FILE, g_logs)
                return jsonify({"status": "ok"})
            except Exception as e:
                logger.error(f"隐藏日志失败: {e}")
                return jsonify({"error": "隐藏日志失败"}), 500

    @app.route('/api/reminders/clear-completed', methods=['POST'])
    @require_api_key
    @require_login
    def clear_completed():
        with db_lock:
            try:
                scope = _scope_reminders()
                completed_ids = {r["id"] for r in scope if r.get("status") == "completed"}
                before_reminders = len(scope)

                for rid in completed_ids:
                    try:
                        scheduler.remove_job(rid)
                    except Exception as e:
                        logger.warning(f"移除调度任务失败: {rid} - {e}")

                scope[:] = [r for r in scope if r.get("status") != "completed"]
                after_reminders = len(scope)

                g_logs = app.config['GLOBAL_LOGS']
                before_logs = len(g_logs)
                g_logs[:] = [
                    l for l in g_logs
                    if not (_log_visible(l) and l.get("reminder_id") in completed_ids)
                ]
                after_logs = len(g_logs)

                _persist(persist_logs=True)
                update_scheduler(scheduler, db, _make_notify_fn(app))
                logger.info(
                    f"清空已完成任务: 删除 {before_reminders - after_reminders} 条提醒, "
                    f"{before_logs - after_logs} 条日志"
                )
                return jsonify({
                    "status": "ok",
                    "deleted": before_reminders - after_reminders,
                    "logs_deleted": before_logs - after_logs
                })
            except Exception as e:
                logger.error(f"清空已完成任务失败: {e}")
                return jsonify({"error": "清空已完成任务失败"}), 500

    @app.route('/api/wxlogin', methods=['POST'])
    @require_api_key
    def wx_login():
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
                url = f"https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={'***'}&js_code={code}&grant_type=authorization_code"
                actual_url = url.replace("secret=***", f"secret={secret}")
                logger.info(f"微信登录请求: {sanitize_log_message(url)}")

                with urllib.request.urlopen(actual_url, timeout=10) as resp:
                    data = json.loads(resp.read().decode())

                if "openid" in data:
                    wxid = data["openid"]
                    if "users" not in db:
                        db["users"] = {}
                    if wxid not in db["users"]:
                        db["users"][wxid] = {
                            "openid": wxid,
                            "created_at": datetime.datetime.now(TZ_ENV).isoformat()
                        }
                    save_json(CONFIG_FILE, db)
                    logger.info(f"微信用户登录: {wxid}")
                    return jsonify({"openid": wxid, "status": "ok"})
                else:
                    logger.error(f"微信接口返回错误: {data.get('errmsg', 'unknown')}")
                    return jsonify({"error": "微信接口错误"}), 400
            except Exception as e:
                logger.error(f"微信登录失败: {sanitize_log_message(str(e))}")
                return jsonify({"error": "微信登录失败"}), 500

    return app


def _make_notify_fn(app):
    """创建一个闭包，使通知函数能访问全局 db 和 logs"""
    from app.notifier import notify_engine

    def _notify_with_state(reminder):
        global_db = app.config['GLOBAL_DB']
        global_logs = app.config['GLOBAL_LOGS']
        global_scheduler = app.config['GLOBAL_SCHEDULER']
        notify_engine(reminder, global_db, global_logs, global_scheduler)

    return _notify_with_state
