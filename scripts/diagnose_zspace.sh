#!/bin/bash

# --- 极空间 NAS Docker 权限诊断脚本 ---
# 用法: docker exec -it life-reminder bash /app/scripts/diagnose_zspace.sh

echo "===================================================="
echo "   极空间 (ZSpace) Docker 权限持久化诊断工具"
echo "===================================================="

# 1. 基础信息
echo "[1] 系统基础信息"
echo "当前用户: $(id)"
echo "当前工作目录: $(pwd)"
echo ""

# 2. 目录权限检查
DATA_DIR="/app/data"
echo "[2] 目录权限检查: $DATA_DIR"
if [ -d "$DATA_DIR" ]; then
    ls -ld "$DATA_DIR"
    echo "目录内容:"
    ls -la "$DATA_DIR"
else
    echo "❌ 错误: 目录 $DATA_DIR 不存在！请检查挂载配置。"
fi
echo ""

# 3. 写入能力测试
echo "[3] 物理写入能力测试"
TEST_FILE="$DATA_DIR/.persistence_test_$(date +%s)"
if touch "$TEST_FILE" 2>/dev/null; then
    echo "✅ 写入测试成功: 已创建 $TEST_FILE"
    rm "$TEST_FILE"
    echo "✅ 删除测试成功"
else
    echo "❌ 写入测试失败: Permission denied"
    echo "   诊断意见: 极空间共享文件夹 ACL 权限未开启。请前往【文件管理】->【属性】->【权限设置】开启“合规目录最大读写权限”。"
fi
echo ""

# 4. 镜像层检查
echo "[4] 进程所有权核对"
ps aux | grep reminder.py | grep -v grep
echo ""

# 5. 建议操作
echo "[结论/建议]"
if [ "$(id -u)" -eq 0 ]; then
    echo "• 当前以 ROOT 运行，如果依然无法写入，说明 NAS 物理权限被锁定。"
else
    echo "• 当前以非 root 用户运行，如果写入失败，请尝试在 docker-compose 中设置 PUID=0。"
fi

echo "===================================================="
