#!/bin/bash

DATA_DIR="./data"

echo "=== Life Reminder 环境检查工具 ==="
echo "正在检查目录: $DATA_DIR"

if [ ! -d "$DATA_DIR" ]; then
    echo "❌ 目录 $DATA_DIR 不存在，正在创建..."
    mkdir -p "$DATA_DIR"
fi

# 获取当前用户 UID 和 GID
USER_UID=$(id -u)
USER_GID=$(id -g)

echo "当前主机的用户 UID: $USER_UID, GID: $USER_GID"

# 检查目录所有权
DIR_UID=$(ls -ld "$DATA_DIR" | awk '{print $3}')
DIR_OWNER_UID=$(id -u $DIR_UID)

echo "数据目录所有者 UID: $DIR_OWNER_UID"

if [ "$USER_UID" != "$DIR_OWNER_UID" ]; then
    echo "⚠️ 警告: 数据目录所有者与当前用户不一致！"
    echo "建议运行以下命令修正权限:"
    echo "sudo chown -R $USER_UID:$USER_GID $DATA_DIR"
else
    echo "✅ 目录权限检查通过"
fi

echo ""
echo "建议在 docker-compose.yaml 中设置以下环境变量:"
echo "PUID: $USER_UID"
echo "PGID: $USER_GID"
echo "================================"
