#!/usr/bin/env python3
import os
import json
import tempfile

# 模拟容器内的环境
DATA_DIR = "/app/data"

# 创建临时目录模拟容器的数据卷
with tempfile.TemporaryDirectory() as temp_dir:
    # 设置环境变量
    os.environ["DATA_DIR"] = temp_dir
    
    # 导入reminder.py中的函数
    import sys
    sys.path.insert(0, '.')
    from reminder import load_json, save_json
    
    # 测试数据
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
    
    # 构建文件路径
    config_file = os.path.join(temp_dir, "config.json")
    logs_file = os.path.join(temp_dir, "logs.json")
    
    print(f"测试数据目录: {temp_dir}")
    print(f"配置文件路径: {config_file}")
    
    # 保存数据
    print("\n1. 保存测试数据...")
    save_json(config_file, test_db)
    
    # 验证文件是否创建
    if os.path.exists(config_file):
        print("✓ 配置文件创建成功")
        with open(config_file, "r") as f:
            content = f.read()
            print(f"配置文件内容: {content[:100]}...")
    else:
        print("✗ 配置文件创建失败")
    
    # 重新加载数据
    print("\n2. 重新加载数据...")
    loaded_db = load_json(config_file, {"reminders": [], "settings": {}})
    print(f"加载的提醒数量: {len(loaded_db['reminders'])}")
    print(f"加载的提醒标题: {loaded_db['reminders'][0]['title'] if loaded_db['reminders'] else '无'}")
    
    # 验证数据是否一致
    if loaded_db['reminders'][0]['title'] == test_reminders[0]['title']:
        print("✓ 数据持久化正常")
    else:
        print("✗ 数据持久化失败")
    
    print("\n测试完成!")