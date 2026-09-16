import datetime
import uuid
import os
import json
from flask import request, jsonify, g
from app.config import logger, VERSION, PERSISTENCE_HEALTH, API_KEY
from app.config import CONFIG_FILE, LOGS_FILE, TZ_ENV, ALLOW_REGISTRATION, VALID_PRIORITIES
from app.persistence import save_json, db_lock
from app.auth import (
    require_api_key, require_login, current_token,
    validate_reminder_input, validate_webhook_url, sanitize_log_message
)
from app.scheduler import update_scheduler
from app.notifier import send_test_notification
from app import users

# 通知记录接口单次返回上限（历史统计仍按全量计算）
LOG_LIST_LIMIT = 100
# 「稍后提醒」默认延后分钟数与上限
SNOOZE_DEFAULT_MINUTES = 10
SNOOZE_MAX_MINUTES = 1440
# 单次导入的提醒条数上限
IMPORT_MAX_ITEMS = 1000
# 允许测试/配置的推送渠道
WEBHOOK_CHANNELS = ("wecom", "dingtalk", "lark", "sms_phone", "sms_api", "voice_api")


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

    def _is_today(value) -> bool:
        """判断 ISO 时间串是否落在今天（按服务时区）"""
        if not value:
            return False
        try:
            parsed = datetime.datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ_ENV)
        return parsed.astimezone(TZ_ENV).date() == datetime.datetime.now(TZ_ENV).date()

    def _log_stats(visible: list) -> dict:
        """通知记录统计（按全部可见记录计算，不受列表截断影响）"""
        return {
            "total": len(visible),
            "today": len([l for l in visible if _is_today(l.get("triggered_at"))]),
            "completed": len([l for l in visible if l.get("completed_at")]),
            "limit": LOG_LIST_LIMIT
        }

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

    @app.route('/api/auth/profile', methods=['POST'])
    @require_api_key
    @require_login
    def auth_update_profile():
        """更新账号资料（当前支持昵称；昵称留空表示恢复显示用户名）"""
        with db_lock:
            try:
                username = _username()
                if not username:
                    return jsonify({"error": "当前为开放模式，请先注册账号"}), 403

                payload = request.json or {}
                if "nickname" not in payload:
                    return jsonify({"error": "没有需要更新的资料"}), 400

                nickname, error = users.set_nickname(db, username, payload.get("nickname"))
                if error:
                    return jsonify({"error": error}), 400

                save_json(CONFIG_FILE, db)
                return jsonify({"status": "ok", "user": username, "nickname": nickname})
            except Exception as e:
                logger.error(f"更新账号资料失败: {e}")
                return jsonify({"error": "更新账号资料失败"}), 500

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
                status["nickname"] = users.get_nickname(db, username)
                if username:
                    status["profile"] = users.public_user_info(db, username)

                visible_logs = _visible_logs()
                return jsonify({
                    "db": {
                        "reminders": scope["reminders"],
                        "settings": scope["settings"],
                        "users": {}
                    },
                    "logs": visible_logs[-LOG_LIST_LIMIT:],
                    "log_stats": _log_stats(visible_logs),
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

    @app.route('/api/settings/test-webhook', methods=['POST'])
    @require_api_key
    @require_login
    def test_webhook():
        """向指定渠道发送测试推送（优先使用请求中未保存的地址）"""
        with db_lock:
            try:
                payload = request.json or {}
                channel = (payload.get("channel") or "").strip()
                if channel not in WEBHOOK_CHANNELS:
                    return jsonify({"error": "不支持的推送渠道"}), 400

                webhooks = _scope_settings().get("webhooks") or {}
                url = (payload.get("url") or webhooks.get(channel) or "").strip()
                if not url:
                    return jsonify({"error": "请先填写该渠道的 Webhook 地址"}), 400
                if not validate_webhook_url(url):
                    return jsonify({"error": "Webhook URL 格式无效"}), 400

                ok, message = send_test_notification(channel, url)
                logger.info(f"测试推送 ({channel}): {message}")
                if not ok:
                    return jsonify({"error": message}), 502
                return jsonify({"status": "ok", "message": message})
            except Exception as e:
                logger.error(f"测试推送失败: {e}")
                return jsonify({"error": "测试推送失败"}), 500

    @app.route('/api/reminders/snooze', methods=['POST'])
    @require_api_key
    @require_login
    def snooze_reminder():
        """基于通知记录创建「稍后提醒」（默认 10 分钟后触发的一次性任务）"""
        with db_lock:
            try:
                payload = request.json or {}
                log_id = (payload.get("log_id") or "").strip()
                if not log_id:
                    return jsonify({"error": "缺少通知记录 id"}), 400

                entry = next(
                    (l for l in app.config['GLOBAL_LOGS'] if l.get("id") == log_id and _log_visible(l)),
                    None
                )
                if entry is None:
                    return jsonify({"error": "通知记录不存在"}), 404

                try:
                    minutes = int(payload.get("minutes", SNOOZE_DEFAULT_MINUTES))
                except (TypeError, ValueError, OverflowError):
                    minutes = SNOOZE_DEFAULT_MINUTES
                minutes = max(1, min(minutes, SNOOZE_MAX_MINUTES))

                scope = _scope_reminders()
                source = next(
                    (r for r in scope if r.get("id") == entry.get("reminder_id")),
                    None
                )
                priority = (source or {}).get("priority")
                if priority not in VALID_PRIORITIES:
                    priority = "mid"

                username = _username()
                now = datetime.datetime.now(TZ_ENV)
                reminder = {
                    "id": str(uuid.uuid4()),
                    "title": f"{entry.get('title') or '提醒'}（稍后提醒）",
                    "time": (now + datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M"),
                    "repeat": "once",
                    "priority": priority,
                    "status": "pending",
                    "created_at": now.isoformat(),
                    "snoozed_from": entry.get("reminder_id")
                }
                if username:
                    reminder["user"] = username
                scope.append(reminder)
                _persist()
                update_scheduler(scheduler, db, _make_notify_fn(app))
                logger.info(f"稍后提醒已创建: {reminder['title']} - {reminder['time']} ({minutes} 分钟后)")
                return jsonify(reminder)
            except Exception as e:
                logger.error(f"创建稍后提醒失败: {e}")
                return jsonify({"error": "创建稍后提醒失败"}), 500

    @app.route('/api/logs/complete/<log_id>', methods=['POST'])
    @require_api_key
    @require_login
    def complete_log(log_id):
        """切换通知记录的「已处理」状态"""
        with db_lock:
            try:
                entry = next(
                    (l for l in app.config['GLOBAL_LOGS'] if l.get("id") == log_id and _log_visible(l)),
                    None
                )
                if entry is None:
                    return jsonify({"error": "通知记录不存在"}), 404

                if entry.get("completed_at"):
                    entry["completed_at"] = None
                    completed = False
                else:
                    entry["completed_at"] = datetime.datetime.now(TZ_ENV).isoformat()
                    completed = True

                save_json(LOGS_FILE, app.config['GLOBAL_LOGS'])
                logger.info(f"通知记录{'标记已处理' if completed else '取消已处理'}: {log_id}")
                return jsonify({"status": "ok", "completed": completed})
            except Exception as e:
                logger.error(f"更新通知记录状态失败: {e}")
                return jsonify({"error": "更新通知记录状态失败"}), 500

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

    @app.route('/api/export')
    @require_api_key
    @require_login
    def export_data():
        """导出当前账号数据（提醒 / 通知记录 / 设置），用于备份与迁移"""
        with db_lock:
            try:
                username = _username()
                payload = {
                    "format": "life-reminder-backup",
                    "exported_at": datetime.datetime.now(TZ_ENV).isoformat(),
                    "version": VERSION,
                    "account": {
                        "username": username,
                        "nickname": users.get_nickname(db, username)
                    },
                    "settings": _scope_settings(),
                    "reminders": _scope_reminders(),
                    "logs": _visible_logs()
                }
                response = jsonify(payload)
                stamp = datetime.datetime.now(TZ_ENV).strftime("%Y%m%d")
                response.headers["Content-Disposition"] = f"attachment; filename=life-reminder-backup-{stamp}.json"
                logger.info(f"导出数据: {username or '开放模式'} (提醒 {len(payload['reminders'])} 条)")
                return response
            except Exception as e:
                logger.error(f"导出数据失败: {e}")
                return jsonify({"error": "导出数据失败"}), 500

    @app.route('/api/import', methods=['POST'])
    @require_api_key
    @require_login
    def import_data():
        """导入备份：按「标题 + 时间 + 重复」去重后新增，不覆盖现有数据"""
        with db_lock:
            try:
                payload = request.json or {}
                incoming = payload.get("reminders")
                if not isinstance(incoming, list):
                    return jsonify({"error": "导入内容缺少 reminders 列表"}), 400
                if len(incoming) > IMPORT_MAX_ITEMS:
                    return jsonify({"error": f"单次最多导入 {IMPORT_MAX_ITEMS} 条提醒"}), 400

                username = _username()
                scope = _scope_reminders()
                existing_keys = {
                    (r.get("title"), r.get("time"), r.get("repeat"))
                    for r in scope if isinstance(r, dict)
                }
                added, skipped, invalid = 0, 0, 0
                now = datetime.datetime.now(TZ_ENV)

                for item in incoming:
                    if not isinstance(item, dict):
                        invalid += 1
                        continue

                    candidate = {
                        "title": str(item.get("title", "")).strip(),
                        "time": str(item.get("time", "")).strip(),
                        "repeat": item.get("repeat", "daily"),
                        "priority": item.get("priority", "low")
                    }
                    if validate_reminder_input(candidate):
                        invalid += 1
                        continue

                    key = (candidate["title"], candidate["time"], candidate["repeat"])
                    if key in existing_keys:
                        skipped += 1
                        continue

                    candidate.update({
                        "id": str(uuid.uuid4()),
                        "status": "completed" if item.get("status") == "completed" else "pending",
                        "created_at": now.isoformat(),
                        "imported_at": now.isoformat()
                    })
                    if username:
                        candidate["user"] = username
                    scope.append(candidate)
                    existing_keys.add(key)
                    added += 1

                if added:
                    _persist()
                    update_scheduler(scheduler, db, _make_notify_fn(app))
                logger.info(f"导入数据: 新增 {added} 条, 跳过重复 {skipped} 条, 忽略无效 {invalid} 条")
                return jsonify({
                    "status": "ok",
                    "added": added,
                    "skipped": skipped,
                    "invalid": invalid
                })
            except Exception as e:
                logger.error(f"导入数据失败: {e}")
                return jsonify({"error": "导入数据失败"}), 500

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
