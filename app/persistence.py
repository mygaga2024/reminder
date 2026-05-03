import os
import json
import datetime
import shutil
import stat
import tempfile
import threading
from app.config import logger, PERSISTENCE_HEALTH, DATA_DIR, CONFIG_FILE, LOGS_FILE

db_lock = threading.RLock()

# NAS 兼容：设置 umask 000，确保所有新文件权限为 777
os.umask(0o000)


def _ensure_dir_writable(dir_path: str) -> bool:
    """尝试确保目录可写"""
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path, exist_ok=True)
        except Exception:
            return False

    if os.access(dir_path, os.W_OK):
        return True

    try:
        os.chmod(dir_path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    except Exception:
        pass

    if os.access(dir_path, os.W_OK):
        return True

    try:
        probe = os.path.join(dir_path, ".zspace_probe")
        with open(probe, "w") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


def _atomic_write(filepath: str, data, max_retries: int = 3) -> bool:
    """多重策略原子写入，NAS 环境下自动降级"""
    dir_path = os.path.dirname(filepath)

    # 策略优先级：标准原子 → 备选原子 → 直接覆盖（NAS 兜底）
    strategies = [
        lambda: _write_via_tempfile(filepath, dir_path, data),
        lambda: _write_via_tmp_sibling(filepath, data),
        lambda: _write_via_direct(filepath, dir_path, data),
    ]

    last_error = None
    for attempt in range(max_retries):
        for strategy in strategies:
            try:
                strategy()
                PERSISTENCE_HEALTH["last_save"] = datetime.datetime.now().isoformat()
                PERSISTENCE_HEALTH["status"] = "ok"
                logger.info(f"保存成功: {filepath}")
                return True
            except Exception as e:
                last_error = str(e)
        _ensure_dir_writable(dir_path)

    PERSISTENCE_HEALTH["status"] = "error"
    PERSISTENCE_HEALTH["error"] = last_error

    logger.error(f"持久化失败 {filepath}: {last_error}")
    logger.error(
        f"  dir={dir_path} exists={os.path.exists(dir_path)} "
        f"access={os.access(dir_path, os.W_OK) if os.path.exists(dir_path) else 'N/A'} "
        f"uid={os.getuid()} gid={os.getgid()}"
    )
    return False


def _write_via_tempfile(filepath: str, dir_path: str, data) -> None:
    """tempfile.mkstemp + os.replace — 标准原子写入"""
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)

    fd, tmp = tempfile.mkstemp(
        suffix=".json",
        prefix="reminder_",
        dir=dir_path if os.access(dir_path, os.W_OK) else None
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, filepath)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _write_via_tmp_sibling(filepath: str, data) -> None:
    """同名 .tmp + os.replace — 备选原子写入"""
    dir_path = os.path.dirname(filepath)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)

    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, filepath)


def _write_via_direct(filepath: str, dir_path: str, data) -> None:
    """直接覆盖 + .bak — NAS 兜底策略（牺牲原子性保证写入成功）"""
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)

    bak = filepath + ".bak"
    if os.path.exists(filepath):
        try:
            shutil.copy2(filepath, bak)
        except Exception:
            pass

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    try:
        if os.path.exists(bak):
            os.remove(bak)
    except Exception:
        pass


def run_health_check() -> None:
    """启动时诊断持久化能力"""
    logger.info("=== 环境诊断 ===")
    logger.info(f"uid={os.getuid()} gid={os.getgid()} data_dir={DATA_DIR}")

    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)

        PERSISTENCE_HEALTH["is_writable"] = os.access(DATA_DIR, os.W_OK)
        PERSISTENCE_HEALTH["is_mount"] = os.path.ismount(DATA_DIR)

        test_file = os.path.join(DATA_DIR, ".write_test")
        write_ok = False
        try:
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            write_ok = True
        except Exception:
            try:
                fd, tmp = tempfile.mkstemp(prefix="wt_", dir=DATA_DIR)
                os.close(fd)
                os.remove(tmp)
                write_ok = True
            except Exception:
                pass

        PERSISTENCE_HEALTH["real_write_test"] = write_ok
        if write_ok:
            PERSISTENCE_HEALTH["status"] = "ok"
            PERSISTENCE_HEALTH["error"] = None
        else:
            PERSISTENCE_HEALTH["status"] = "error"
            PERSISTENCE_HEALTH["error"] = "写入测试失败"

        logger.info(f"writable={PERSISTENCE_HEALTH['is_writable']}")
        logger.info(f"mount={PERSISTENCE_HEALTH['is_mount']}")
        logger.info(f"write_test={write_ok}")

    except Exception as e:
        logger.error(f"诊断异常: {e}")
        PERSISTENCE_HEALTH["status"] = "critical"
        PERSISTENCE_HEALTH["error"] = str(e)
    logger.info("=====================")


def load_json(filepath: str, default):
    """加载 JSON 文件"""
    if os.path.exists(filepath):
        try:
            if os.path.getsize(filepath) == 0:
                logger.warning(f"空文件，初始化: {filepath}")
                return default
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"加载成功: {filepath} ({os.path.getsize(filepath)}b)")
                return data
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败 ({filepath}): {e}")
            backup_path = filepath + ".corrupt_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            try:
                shutil.copy2(filepath, backup_path)
                logger.info(f"已备份损坏文件: {backup_path}")
            except Exception as be:
                logger.error(f"备份失败: {be}")
            raise RuntimeError(f"配置文件损坏: {filepath}")
        except PermissionError as e:
            logger.error(f"无读取权限 ({filepath}): {e}")
            raise RuntimeError(f"无法读取数据: {filepath}")
        except Exception as e:
            logger.error(f"读取失败 ({filepath}): {e}")
            raise
    else:
        logger.info(f"文件不存在，初始化: {filepath}")
    return default


def save_json(filepath: str, data) -> None:
    """保存 JSON — 多重降级策略，NAS 环境自动适配"""
    if not data or (isinstance(data, dict) and "reminders" in data and len(data["reminders"]) == 0):
        if os.path.exists(filepath) and os.path.getsize(filepath) > 100:
            logger.error(f"拦截空数据写入: {filepath}")
            return

    with db_lock:
        if not _atomic_write(filepath, data):
            raise IOError(f"持久化失败: {filepath}")


def init_db(db: dict, logs: list) -> tuple:
    """初始化数据库结构"""
    if not isinstance(db.get("reminders"), list):
        db["reminders"] = []
    if "settings" not in db:
        db["settings"] = {"sound": True, "vibrate": True, "notify": True, "dark": True}
    if "users" not in db:
        db["users"] = {}
    if not isinstance(logs, list):
        logs = []
    return db, logs
