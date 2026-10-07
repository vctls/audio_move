#!/bin/sh
set -e

umask "${UMASK:-022}"

# Run as PUID:PGID so moved and tagged files keep the owner of the music library.
if [ "$(id -u)" = "0" ] && [ -n "$PUID" ]; then
  mkdir -p "$CONFIG_DIR"
  chown -R "$PUID:${PGID:-$PUID}" "$CONFIG_DIR"
  exec setpriv --reuid="$PUID" --regid="${PGID:-$PUID}" --clear-groups "$@"
fi

exec "$@"
