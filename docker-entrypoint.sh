#!/bin/sh
# Runs the server as the unprivileged `app` user.
#
# The container has to START as root: Railway mounts the volume at /data owned by
# root, and only root can hand it to `app`. So we chown the data directory, then drop
# privileges with setpriv before exec'ing the real command.
#
# If any step isn't possible (volume refuses chown, setpriv missing) we keep running as
# root, with a warning, rather than failing the deploy.
set -e

if [ "$(id -u)" = "0" ]; then
    DATA_DIR="$(dirname "${DB_PATH:-/data/app.db}")"
    mkdir -p "$DATA_DIR" 2>/dev/null || true
    if command -v setpriv >/dev/null 2>&1 && chown -R app:app "$DATA_DIR" 2>/dev/null; then
        exec setpriv --reuid=app --regid=app --init-groups "$@"
    fi
    echo "WARNING: could not drop privileges (chown of $DATA_DIR or setpriv failed); running as root" >&2
fi

exec "$@"
