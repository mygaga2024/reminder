#!/bin/bash

# --- 极空间 NAS Docker 权限持久化诊断脚本 ---
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
    echo "目录详情:"
    ls -ld "$DATA_DIR"
    echo "目录内容:"
    ls -la "$DATA_DIR"
else
    echo "❌ 错误: 目录 $DATA_DIR 不存在！请检查 docker-compose.yaml 中的 volumes 挂载配置。"
fi
echo ""

# 3. 写入能力测试
echo "[3] 物理写入能力测试"
TEST_FILE="$DATA_DIR/.persistence_test_$(date +%s)"
if touch "$TEST_FILE" 2>/dev/null; then
    echo "✅ touch 测试成功"
    if echo "ok" > "$TEST_FILE" 2>/dev/null; then
        echo "✅ 文件写入测试成功"
    else
        echo "❌ 文件写入测试失败（touch 成功但 echo 写入失败——ZSpace ACL 限制典型症状）"
    fi
    rm -f "$TEST_FILE"
else
    echo "❌ touch 测试失败: Permission denied"
fi
echo ""

# 4. ACL 检测
echo "[4] ACL 检测"
if command -v getfacl >/dev/null 2>&1; then
    getfacl "$DATA_DIR" 2>/dev/null || echo "(getfacl 不可用或失败)"
fi
echo ""

# 5. 进程所有权
echo "[5] 进程所有权"
ps aux | grep main.py | grep -v grep
echo ""

# 6. 持久化文件状态
echo "[6] 持久化文件状态"
for f in config.json logs.json; do
    fp="$DATA_DIR/$f"
    if [ -f "$fp" ]; then
        echo "  $f: 存在 ($(wc -c < "$fp") bytes, 权限: $(stat -c '%a' "$fp" 2>/dev/null || ls -l "$fp" | awk '{print $1}'))"
    else
        echo "  $f: 不存在"
    fi
done
echo ""

# 7. 诊断结论
echo "[结论/建议]"
if [ "$(id -u)" -eq 0 ]; then
    echo "• 当前以 ROOT 运行"
    if touch "$DATA_DIR/.final_test" 2>/dev/null && rm -f "$DATA_DIR/.final_test" 2>/dev/null; then
        echo "• ✅ 持久化能力正常"
    else
        echo "• ❌ root 也无法写入！"
        echo "• → 请在极空间「文件管理」中，右键映射目录 →「属性」→「权限设置」→ 勾选「合规目录最大读写权限」"
        echo "• → 或者，在 docker-compose.yaml 中添加: privileged: true"
    fi
else
    echo "• 当前以非 root 用户运行"
    echo "• 如果写入失败，请在 docker-compose.yaml 中设置 PUID=0, PGID=0"
fi

echo "===================================================="
