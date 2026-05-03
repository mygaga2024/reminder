#!/usr/bin/env python3
"""Legacy persistence test - 验证模块化后的数据持久化功能"""
import os
import json
import tempfile
import sys
sys.path.insert(0, '.')

from app.persistence import load_json, save_json

with tempfile.TemporaryDirectory() as temp_dir:
    os.environ["DATA_DIR"] = temp_dir

    test_reminders = [
        {
            "id": "test-1",
            "title": "测试提醒",
            "time": "10:00",
            "repeat": "daily",
            "status": "pending"
        }
    ]

    test_settings = {
        "language": "zh",
        "dark_mode": True,
        "webhooks": {"wecom": "", "dingtalk": "", "lark": ""}
    }

    test_db = {
        "reminders": test_reminders,
        "settings": test_settings
    }

    config_file = os.path.join(temp_dir, "config.json")
    logs_file = os.path.join(temp_dir, "logs.json")

    print(f"测试数据目录: {temp_dir}")
    print(f"配置文件路径: {config_file}")

    print("\n1. 保存测试数据...")
    save_json(config_file, test_db)

    if os.path.exists(config_file):
        print("\u2713 配置文件创建成功")
        with open(config_file, "r") as f:
            content = f.read()
            print(f"配置文件内容: {content[:100]}...")
    else:
        print("\u2717 配置文件创建失败")

    print("\n2. 重新加载数据...")
    loaded_db = load_json(config_file, {"reminders": [], "settings": {}})
    print(f"加载的提醒数量: {len(loaded_db['reminders'])}")
    print(f"加载的提醒标题: {loaded_db['reminders'][0]['title'] if loaded_db['reminders'] else '无'}")

    if loaded_db['reminders'][0]['title'] == test_reminders[0]['title']:
        print("\u2713 数据持久化正常")
    else:
        print("\u2717 数据持久化失败")

    print("\n测试完成!")
