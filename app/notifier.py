import datetime
import uuid
import random
import requests
from app.config import logger, TIPS_LIST
from app.config import LOGS_FILE, CONFIG_FILE
from app.calendar_utils import is_china_workday
from app.persistence import save_json, db_lock


def notify_engine(reminder: dict, db: dict, logs: list, scheduler=None) -> None:
    """通知引擎：发送 webhook 通知并记录日志"""
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
            msg = f"""\u23f0 您有一个提醒！

\U0001f4dd 提醒内容：{title}
\U0001f4c5 提醒时间：{date_str} {time_str}
\U0001f504 重复类型：{rep_label}

{tip}"""

            webhooks = s.get("webhooks", {})
            _send_webhooks(webhooks, msg, reminder)

            log_entry = {
                "id": str(uuid.uuid4()),
                "reminder_id": reminder.get("id", "unknown"),
                "title": title,
                "triggered_at": datetime.datetime.now().isoformat(),
                "completed_at": None,
                "status": "triggered"
            }
            logs.append(log_entry)

            cutoff = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
            logs[:] = [l for l in logs if l.get("triggered_at", "") > cutoff]

            save_json(LOGS_FILE, logs)
            logger.info(f"提醒已触发: {title}")

            if rep == "once":
                rid = reminder.get("id")
                if scheduler:
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


def _send_webhooks(webhooks: dict, msg: str, reminder: dict) -> None:
    """发送所有配置的 webhook 通知"""
    title = reminder.get("title", "")

    platform_handlers = {
        "wecom": lambda url: requests.post(url, json={"msgtype": "text", "text": {"content": msg}}, timeout=10),
        "dingtalk": lambda url: requests.post(url, json={"msgtype": "text", "text": {"content": msg}}, timeout=10),
        "lark": lambda url: requests.post(url, json={"msg_type": "text", "content": {"text": msg}}, timeout=10),
    }

    for platform, url in webhooks.items():
        if not url:
            continue

        if platform in platform_handlers:
            _send_with_retry(platform, url, platform_handlers[platform])
        elif platform in ("sms_phone", "sms_api", "voice_api"):
            _send_generic_webhook(platform, url, title, msg)


def _send_with_retry(platform: str, url: str, send_fn) -> None:
    """发送 webhook 并处理结果"""
    try:
        resp = send_fn(url)
        if resp.status_code == 200:
            logger.info(f"推送成功 ({platform})")
        else:
            logger.error(f"推送失败 ({platform}): HTTP {resp.status_code}")
    except requests.RequestException as e:
        logger.error(f"网络错误 ({platform}): {e}")
    except Exception as e:
        logger.error(f"推送异常 ({platform}): {e}")


def _send_generic_webhook(key: str, url: str, title: str, msg: str) -> None:
    """发送通用 webhook (短信/电话等第三方网关)"""
    labels = {"sms_phone": "短信电话", "sms_api": "短信API", "voice_api": "语音API"}
    label = labels.get(key, key)
    try:
        payload = {"title": title, "message": msg, "channel": key}
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info(f"推送成功 ({label})")
        else:
            logger.error(f"推送失败 ({label}): HTTP {resp.status_code}")
    except requests.RequestException as e:
        logger.error(f"网络错误 ({label}): {e}")
    except Exception as e:
        logger.error(f"推送异常 ({label}): {e}")
