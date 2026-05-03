# Life Reminder - Test Suite
import os
import json
import tempfile
import pytest


@pytest.fixture(autouse=True)
def setup_test_env():
    """为每个测试设置临时环境"""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATA_DIR"] = tmpdir
        os.environ["TZ"] = "Asia/Shanghai"
        os.environ["API_KEY"] = ""
        yield tmpdir
