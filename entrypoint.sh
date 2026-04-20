#!/bin/bash

# Default values
USER_ID=${PUID:-1000}
GROUP_ID=${PGID:-1000}

echo "Starting with UID: $USER_ID, GID: $GROUP_ID"

# If group doesn't exist, create it
if ! getent group appuser > /dev/null 2>&1; then
    groupadd -g $GROUP_ID appuser
fi

# If user doesn't exist, create it
if ! getent passwd appuser > /dev/null 2>&1; then
    useradd -u $USER_ID -g $GROUP_ID -m -s /bin/bash appuser
fi

# Ensure data directory owner matches
chown -R appuser:appuser /app/data

# Run the application
exec gosu appuser python reminder.py
