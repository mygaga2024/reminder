# Life Reminder - Test Suite
import os
import json
import tempfile
import pytest

# 导入期即指向可写数据目录：app.config 在导入时读取 DATA_DIR，
# 若等到 fixture 阶段才设置，单独运行某个测试文件会落到只读的 /app/data
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="reminder_test_"))
os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("API_KEY", "")


@pytest.fixture(autouse=True)
def setup_test_env():
    """为每个测试设置临时环境"""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATA_DIR"] = tmpdir
        os.environ["TZ"] = "Asia/Shanghai"
        os.environ["API_KEY"] = ""
        yield tmpdir
