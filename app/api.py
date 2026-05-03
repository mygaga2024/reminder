import datetime
import uuid
import os
import json
from flask import request, jsonify
from app.config import logger, VERSION, PERSISTENCE_HEALTH, API_KEY
from app.config import CONFIG_FILE, LOGS_FILE, TZ
from app.persistence import save_json, db_lock
from app.auth import require_api_key, validate_reminder_input, validate_webhook_url, sanitize_log_message
from app.scheduler import update_scheduler


def register_routes(app, db: dict, logs: list, scheduler):
    """注册所有 API 路由"""

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

    @app.route('/api/state')
    @require_api_key
    def get_state():
        with db_lock:
            try:
                return jsonify({
                    "db": db,
                    "logs": logs[-100:],
                    "syslogs": app.config['LIST_HANDLER'].logs[::-1],
                    "version": VERSION,
                    "persistence": PERSISTENCE_HEALTH,
                    "auth_required": bool(API_KEY)
                })
            except Exception as e:
                logger.error(f"获取状态失败: {e}")
                return jsonify({"error": "获取状态失败"}), 500

    @app.route('/api/reminders', methods=['POST'])
    @require_api_key
    def add_reminder():
        with db_lock:
            try:
                r = request.json
                if not r:
                    return jsonify({"error": "请求数据为空"}), 400

                errors = validate_reminder_input(r)
                if errors:
                    return jsonify({"error": "; ".join(errors)}), 400

                r.update({
                    "id": str(uuid.uuid4()),
                    "status": "pending",
                    "created_at": datetime.datetime.now().isoformat()
                })
                db["reminders"].append(r)
                save_json(CONFIG_FILE, db)
                update_scheduler(scheduler, db, _make_notify_fn(app))
                logger.info(f"添加提醒: {r.get('title')}")
                return jsonify(r)
            except Exception as e:
                logger.error(f"添加提醒失败: {e}")
                return jsonify({"error": "添加提醒失败"}), 500

    @app.route('/api/reminders/<rid>', methods=['PUT', 'DELETE'])
    @require_api_key
    def mod_reminder(rid):
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

                    errors = validate_reminder_input(update)
                    if errors:
                        return jsonify({"error": "; ".join(errors)}), 400

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
                update_scheduler(scheduler, db, _make_notify_fn(app))
                return jsonify({"status": "ok"})
            except Exception as e:
                logger.error(f"修改提醒失败: {e}")
                return jsonify({"error": "修改提醒失败"}), 500

    @app.route('/api/settings', methods=['POST'])
    @require_api_key
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

                db["settings"].update(update)
                save_json(CONFIG_FILE, db)
                logger.info("更新设置")
                return jsonify({"status": "ok"})
            except Exception as e:
                logger.error(f"修改设置失败: {e}")
                return jsonify({"error": "修改设置失败"}), 500

    @app.route('/api/logs/<log_id>', methods=['DELETE'])
    @require_api_key
    def delete_log(log_id):
        """删除通知日志记录（持久化删除）"""
        with db_lock:
            try:
                g_logs = app.config['GLOBAL_LOGS']
                before = len(g_logs)
                g_logs[:] = [l for l in g_logs if l.get("id") != log_id]
                after = len(g_logs)
                save_json(LOGS_FILE, g_logs)
                logger.info(f"删除日志记录: {log_id} (删除 {before - after} 条)")
                return jsonify({"status": "ok", "deleted": before - after})
            except Exception as e:
                logger.error(f"删除日志失败: {e}")
                return jsonify({"error": "删除日志失败"}), 500

    @app.route('/api/logs/hide/<log_id>', methods=['POST'])
    @require_api_key
    def hide_log(log_id):
        """标记日志为已隐藏"""
        with db_lock:
            try:
                g_logs = app.config['GLOBAL_LOGS']
                for l in g_logs:
                    if l.get("id") == log_id:
                        l["hidden"] = True
                        break
                save_json(LOGS_FILE, g_logs)
                return jsonify({"status": "ok"})
            except Exception as e:
                logger.error(f"隐藏日志失败: {e}")
                return jsonify({"error": "隐藏日志失败"}), 500

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
                            "created_at": datetime.datetime.now().isoformat()
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
