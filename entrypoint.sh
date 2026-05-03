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
