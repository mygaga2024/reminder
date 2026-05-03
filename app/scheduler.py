import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from app.config import (
    logger, TZ, TZ_ENV, CHINESE_CALENDAR_AVAILABLE,
    DATETIME_PATTERN, TIME_PATTERN
)
from app.persistence import db_lock


def update_scheduler(scheduler: BackgroundScheduler, db: dict, notify_fn) -> None:
    """更新调度器：清除旧任务并根据数据库重建所有调度"""
    with db_lock:
        try:
            job_count = len(scheduler.get_jobs())
            if job_count > 0:
                scheduler.remove_all_jobs()
                logger.info(f"已清理旧调度任务 (共 {job_count} 个)")

            if CHINESE_CALENDAR_AVAILABLE:
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

                    trigger = _build_trigger(t_str, rep)
                    if trigger:
                        scheduler.add_job(notify_fn, trigger, args=[r], id=r.get('id'))
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


def _build_trigger(t_str: str, rep: str):
    """根据时间字符串和重复模式构建触发器"""
    if DATETIME_PATTERN.match(t_str):
        target_dt = datetime.datetime.strptime(t_str, '%Y-%m-%d %H:%M')
        target_dt = target_dt.replace(tzinfo=TZ_ENV)
        if target_dt <= datetime.datetime.now(TZ_ENV):
            target_dt += datetime.timedelta(days=1)
        return DateTrigger(run_date=target_dt)

    elif TIME_PATTERN.match(t_str):
        h, m = t_str.split(':')[:2]
        if rep == "daily":
            return CronTrigger(hour=h, minute=m)
        elif rep.startswith("weekly:"):
            days = rep.split(":")[1]
            return CronTrigger(day_of_week=days, hour=h, minute=m)
        elif rep == "workday":
            return CronTrigger(hour=h, minute=m, day_of_week='mon-fri')
        else:
            target_datetime = datetime.datetime.combine(
                datetime.date.today(), datetime.time(int(h), int(m))
            )
            target_datetime = target_datetime.replace(tzinfo=TZ_ENV)
            if target_datetime <= datetime.datetime.now(TZ_ENV):
                target_datetime += datetime.timedelta(days=1)
            return DateTrigger(run_date=target_datetime)

    return None
