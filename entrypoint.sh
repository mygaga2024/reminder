#!/bin/bash
set -e

USER_ID=${PUID:-0}
GROUP_ID=${PGID:-0}
UMASK_VAL=${UMASK:-000}
DATA_DIR="/app/data"

echo "==== Life Reminder Entrypoint ===="
echo "UID=$USER_ID GID=$GROUP_ID UMASK=$UMASK_VAL"

# ─── Step 1: 设置 umask（NAS Docker 项目通用方案，确保新文件 777 权限） ───
umask "$UMASK_VAL"

# ─── Step 2: 确保数据目录存在并修复权限 ───
mkdir -p "$DATA_DIR" 2>/dev/null || true

# 尝试多重权限修复（NAS 上可能静默失败，不影响启动）
chmod -R 777 "$DATA_DIR" 2>/dev/null || true
chown -R 0:0 "$DATA_DIR" 2>/dev/null || true

# ─── Step 3: 物理写入测试 ───
PROBE="$DATA_DIR/.entrypoint_probe_$$"
if echo "1" > "$PROBE" 2>/dev/null && rm -f "$PROBE" 2>/dev/null; then
    echo "OK: 数据目录可写 → $DATA_DIR"
else
    # 尝试子目录回退
    if mkdir -p "$DATA_DIR/store" 2>/dev/null && echo "1" > "$DATA_DIR/store/.probe" 2>/dev/null; then
        rm -f "$DATA_DIR/store/.probe"
        # 迁移旧数据
        for f in config.json logs.json; do
            [ -f "$DATA_DIR/$f" ] && cp "$DATA_DIR/$f" "$DATA_DIR/store/" 2>/dev/null
        done
        DATA_DIR="$DATA_DIR/store"
        echo "OK: 子目录可写 → $DATA_DIR"
    else
        echo "WARN: 卷不可写，使用容器内部存储"
        DATA_DIR="/app/internal_data"
        mkdir -p "$DATA_DIR"
    fi
fi

export DATA_DIR

# ─── Step 3.5: 节假日库自动升级 ───
CURRENT_YEAR=$(date +%Y)
NEXT_YEAR=$((CURRENT_YEAR + 1))
CAL_CHECK=$(python3 -c "
try:
    from chinese_calendar import is_workday
    from datetime import date
    r = is_workday(date($CURRENT_YEAR, 6, 1))
    print('OK')
except NotImplementedError:
    print('OUTDATED')
except ImportError:
    print('MISSING')
" 2>/dev/null || echo "ERROR")
if [ "$CAL_CHECK" = "OUTDATED" ]; then
    echo "WARN: chinese_calendar 数据未覆盖 $CURRENT_YEAR 年，尝试自动升级..."
    pip install --upgrade chinese-calendar 2>&1 | tail -1
    CAL_CHECK2=$(python3 -c "
try:
    from chinese_calendar import is_workday
    from datetime import date
    r = is_workday(date($CURRENT_YEAR, 6, 1))
    print('OK')
except NotImplementedError:
    print('STILL_OUTDATED')
" 2>/dev/null || echo "ERROR")
    if [ "$CAL_CHECK2" = "OK" ]; then
        echo "OK: 节假日库自动升级成功，已覆盖 $CURRENT_YEAR 年"
    else
        echo "WARN: 自动升级未解决，$CURRENT_YEAR 年节假日判断将回退到简单工作日模式"
    fi
elif [ "$CAL_CHECK" = "MISSING" ]; then
    echo "WARN: chinese_calendar 未安装，尝试安装..."
    pip install chinese-calendar 2>&1 | tail -1
fi

# ─── Step 4: 用户切换 ───
if [ "$USER_ID" -ne 0 ]; then
    getent group appuser >/dev/null 2>&1 || groupadd -g "$GROUP_ID" appuser 2>/dev/null || true
    getent passwd appuser >/dev/null 2>&1 || useradd -u "$USER_ID" -g "$GROUP_ID" -m -s /bin/bash appuser 2>/dev/null || true
    chown -R appuser:appuser "$DATA_DIR" 2>/dev/null || true

    if su appuser -c "echo 1 > $DATA_DIR/.ptest && rm $DATA_DIR/.ptest" 2>/dev/null; then
        echo "→ gosu appuser"
        exec gosu appuser python main.py
    else
        echo "→ root（appuser 不可写）"
        exec python main.py
    fi
else
    echo "→ root"
    exec python main.py
fi
