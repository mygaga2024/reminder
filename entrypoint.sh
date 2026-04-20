#!/bin/bash
set -e

# --- ZSpace Compatibility & Permission Logic ---
USER_ID=${PUID:-0}
GROUP_ID=${PGID:-0}
DATA_DIR="/app/data"

echo "==== [Diagnostic] Container Entrypoint Starting ===="
echo "Target User: UID=$USER_ID, GID=$GROUP_ID"
echo "Current OS User: $(id)"

# Only perform user-switching logic if PUID/PGID are not 0 (root)
if [ "$USER_ID" -ne 0 ]; then
    echo "Configuring non-root user: appuser ($USER_ID:$GROUP_ID)"
    
    # Create group if it doesn't exist
    if ! getent group appuser > /dev/null 2>&1; then
        groupadd -g $GROUP_ID appuser || echo "Warning: groupadd failed, group might already exist."
    fi

    # Create user if it doesn't exist
    if ! getent passwd appuser > /dev/null 2>&1; then
        useradd -u $USER_ID -g $GROUP_ID -m -s /bin/bash appuser || echo "Warning: useradd failed, user might already exist."
    fi

    # Attempt to fix permissions on data directory
    echo "Applying 'chown' to $DATA_DIR (this may fail on some NAS mounts)..."
    if ! chown -R appuser:appuser $DATA_DIR 2>/dev/null; then
        echo "⚠️ Warning: Failed to change ownership of $DATA_DIR."
        echo "Checking if directory is still writable by UID $USER_ID..."
    fi

    # Final sanity check: Can the appuser actually touch the volume?
    if ! su appuser -c "touch $DATA_DIR/.perm_test && rm $DATA_DIR/.perm_test" 2>/dev/null; then
        echo "❌ CRITICAL ERROR: UID $USER_ID has NO write access to $DATA_DIR."
        echo "Please check ZSpace NAS folder permissions (合规目录最大读写权限)."
        echo "Falling back to ROOT to prevent data loss..."
        exec python reminder.py
    else
        echo "✅ Persistence Check: UID $USER_ID has write access."
        exec gosu appuser python reminder.py
    fi
else
    echo "Running as ROOT (PUID=0). Bypassing user-switch logic."
    # Even as root, ensure directory exists
    mkdir -p $DATA_DIR
    exec python reminder.py
fi
