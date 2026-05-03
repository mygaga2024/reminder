import os
import re
import logging
import zoneinfo

VERSION = "3.2.15"

DATETIME_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
TIME_PATTERN = re.compile(r'^\d{1,2}:\d{2}$')

TITLE_MAX_LENGTH = 200
TIME_MAX_LENGTH = 50
WEBHOOK_URL_MAX_LENGTH = 500
VALID_REPEAT_MODES = {"none", "once", "daily", "workday"}
VALID_PRIORITIES = {"low", "mid", "high"}

TIPS_LIST = [
    "\U0001f4a1 每天一苹果，医生远离我！",
    "\U0001f338 保持好心情，万事皆顺利！",
    "\u2600\ufe0f 新的一天，新的开始！",
    "\U0001f308 今日份的小幸运正在派送中~",
    "\U0001f340 愿你今天事事顺心！",
    "\U0001f33b 阳光正好，未来可期！",
    "\u2728 生活明朗，万物可爱！",
    "\U0001f3af 今日目标：开心最重要！",
    "\U0001f98b 偶尔放慢脚步，看看身边的美好~",
    "\U0001f4da 每天进步一点点，成就更好的自己！"
]

try:
    import chinese_calendar
    CHINESE_CALENDAR_AVAILABLE = True
except ImportError:
    CHINESE_CALENDAR_AVAILABLE = False
    chinese_calendar = None


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = []

    def emit(self, record):
        try:
            msg = self.format(record)
            self.logs.append(msg)
            if len(self.logs) > 50:
                self.logs.pop(0)
        except Exception:
            self.handleError(record)


log_handler = ListHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger()
logger.addHandler(log_handler)
logger.addHandler(stream_handler)
logger.setLevel(logging.INFO)

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
APP_PORT = int(os.getenv("APP_PORT", 5000))
TZ = os.getenv("TZ", "Asia/Shanghai")
API_KEY = os.getenv("API_KEY", "").strip()

try:
    TZ_ENV = zoneinfo.ZoneInfo(TZ)
except Exception as e:
    print(f"\u26a0\ufe0f Warning: Could not load timezone {TZ}: {e}. Falling back to UTC.")
    TZ_ENV = zoneinfo.ZoneInfo("UTC")

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")

PERSISTENCE_HEALTH = {"status": "ok", "error": None, "is_writable": False, "is_mount": False}
