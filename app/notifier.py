import datetime
import uuid
import random
import requests
from functools import partial
from app.config import logger, TIPS_LIST, TZ_ENV, LOG_RETENTION_DAYS
from app.config import LOGS_FILE, CONFIG_FILE
from app.calendar_utils import is_china_workday
from app.persistence import save_json, db_lock
from app import users
from app import lunar_utils

SUPPORTED_PLATFORMS = ("wecom", "dingtalk", "lark")
GENERIC_PLATFORMS = ("sms_phone", "sms_api", "voice_api")


def _repeat_label(rep: str) -> str:
    """重复模式中文标签（含每周/每月/每年/农历，历史实现对 weekly 会误显示为每天）"""
    lunar_spec = lunar_utils.parse_lunar_repeat(rep)
    if lunar_spec:
        return f"每年（农历{lunar_utils.lunar_label(*lunar_spec)}）"
    if rep.startswith("monthly:"):
        day_expr = rep.split(":", 1)[1]
        return "每月最后一天" if day_expr == "last" else f"每月{day_expr}日"
    if rep == "yearly":
        return "每年"
    if rep.startswith("weekly:"):
        return "每周"
    return {"once": "一次性", "daily": "每天", "workday": "工作日"}.get(rep, "每天")


def _parse_triggered_at(value):
    """解析历史触发时间，兼容历史无时区数据；无法解析返回 None"""
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ_ENV)
    return parsed


def _prune_logs(logs: list, now: datetime.datetime, days: int = LOG_RETENTION_DAYS) -> list:
    """按保留期清理历史记录（无法解析时间的记录保留，避免误删）"""
    cutoff = now - datetime.timedelta(days=days)
    kept = []
    for entry in logs:
        triggered = _parse_triggered_at(entry.get("triggered_at")) if isinstance(entry, dict) else None
        if triggered is None or triggered >= cutoff:
            kept.append(entry)
    return kept


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

            # 农历每年：仅在当天为该农历日期时推送（闰月需月份一致）
            lunar_spec = lunar_utils.parse_lunar_repeat(rep)
            if lunar_spec:
                today = datetime.date.today()
                if not lunar_utils.is_lunar_anniversary(today, lunar_spec[0], lunar_spec[1]):
                    logger.info(
                        f"农历纪念日跳过（今天非农历{lunar_utils.lunar_label(*lunar_spec)}）: "
                        f"{reminder.get('title')} - {today}"
                    )
                    return

            # 多账号：Webhook 配置取自提醒归属账号，开放模式回落顶层设置
            s = users.owned_settings(db, reminder)
            title = reminder.get("title", "未命名提醒")
            now = datetime.datetime.now(TZ_ENV)
            date_str = now.strftime('%Y年%m月%d日')
            time_str = now.strftime('%H:%M')

            tip = random.choice(TIPS_LIST)

            rep_label = _repeat_label(rep)
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
                "user": reminder.get("user"),
                "title": title,
                "triggered_at": now.isoformat(),
                "completed_at": None,
                "status": "triggered"
            }
            logs.append(log_entry)

            # 保留期清理：兼容历史无时区数据，避免字符串比较导致的误删
            logs[:] = _prune_logs(logs, now)

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
                users.remove_reminder(db, rid)
                save_json(CONFIG_FILE, db)
                logger.info(f"一次性任务已自动删除: {title}")
        except Exception as e:
            logger.error(f"通知引擎错误: {e}")


def _send_webhooks(webhooks: dict, msg: str, reminder: dict) -> None:
    """发送所有配置的 webhook 通知"""
    title = reminder.get("title", "")

    for platform, url in webhooks.items():
        if not url:
            continue

        if platform in SUPPORTED_PLATFORMS:
            _send_with_retry(platform, url, partial(_send_platform, platform, url, msg))
        elif platform in ("sms_phone", "sms_api", "voice_api"):
            _send_generic_webhook(platform, url, title, msg)


def _send_platform(platform: str, url: str, msg: str):
    """按平台格式发送消息，返回 requests.Response"""
    if platform in ("wecom", "dingtalk"):
        return requests.post(url, json={"msgtype": "text", "text": {"content": msg}}, timeout=10)
    if platform == "lark":
        return requests.post(url, json={"msg_type": "text", "content": {"text": msg}}, timeout=10)
    raise ValueError(f"不支持的平台: {platform}")


def test_message(platform: str) -> str:
    """测试推送文案"""
    labels = {"wecom": "企业微信", "dingtalk": "钉钉", "lark": "飞书", "sms_phone": "短信/电话", "sms_api": "短信 API", "voice_api": "语音 API"}
    now = datetime.datetime.now(TZ_ENV)
    return (
        "⏰ Life Reminder 测试推送\n\n"
        f"收到这条消息说明「{labels.get(platform, platform)}」渠道配置正确。\n"
        f"发送时间：{now.strftime('%Y-%m-%d %H:%M')}"
    )


def send_test_notification(platform: str, url: str) -> tuple:
    """发送测试消息，返回 (是否成功, 提示信息)"""
    if not url:
        return False, "该渠道还没有配置 Webhook 地址"
    if platform not in SUPPORTED_PLATFORMS and platform not in GENERIC_PLATFORMS:
        return False, f"不支持的渠道: {platform}"

    msg = test_message(platform)
    try:
        if platform in SUPPORTED_PLATFORMS:
            resp = _send_platform(platform, url, msg)
        else:
            resp = requests.post(
                url,
                json={"title": "Life Reminder 测试推送", "message": msg, "channel": platform},
                timeout=10
            )
        if resp.status_code == 200:
            return True, "测试消息已发送，请到对应群聊/网关确认"
        return False, f"推送失败：HTTP {resp.status_code}"
    except requests.RequestException as e:
        return False, f"网络错误：{e}"
    except Exception as e:
        return False, f"推送异常：{e}"


def _send_with_retry(platform: str, url: str, send_fn) -> None:
    """发送 webhook 并处理结果（send_fn 为无参可调用对象，url 仅用于日志上下文）"""
    try:
        resp = send_fn()
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
