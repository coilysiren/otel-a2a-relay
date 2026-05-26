#!/usr/bin/env bash
set -euo pipefail

# Tiny process manager. bg.sh {start|stop|status} <name> -- <cmd...>.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"

pidfile() { echo "$LOGS/$1.pid"; }
logfile() { echo "$LOGS/$1.log"; }

is_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local pf="$1"
  [[ -f "$pf" ]] && cat "$pf" || true
}

cmd_start() {
  local name="$1"; shift
  if [[ "${1:-}" != "--" ]]; then
    echo "usage: bg.sh start <name> -- <cmd...>" >&2
    exit 2
  fi
  shift
  local pf log pid
  pf="$(pidfile "$name")"
  log="$(logfile "$name")"
  pid="$(read_pid "$pf")"
  if is_alive "$pid"; then
    echo "$name already running (pid $pid)"
    return 0
  fi
  rm -f "$pf"
  : > "$log"
  # Run in a fresh session so the whole process tree shares a pgid we can
  # kill on stop. Without this, uvicorn --reload leaks its child uvicorn.
  ( cd "$ROOT" && nohup python3 -c '
import os, sys
os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
' "$@" >>"$log" 2>&1 & echo $! > "$pf" )
  sleep 0.5
  pid="$(read_pid "$pf")"
  if ! is_alive "$pid"; then
    echo "$name failed to start; tail of $log:" >&2
    tail -n 40 "$log" >&2 || true
    exit 1
  fi
  echo "$name started (pid $pid) -> $log"
}

# Recursively collect descendant PIDs of $1.
_descendants() {
  local parent="$1"
  local children
  children="$(pgrep -P "$parent" 2>/dev/null || true)"
  for c in $children; do
    echo "$c"
    _descendants "$c"
  done
}

cmd_stop() {
  local name="$1"
  local pf pid
  pf="$(pidfile "$name")"
  pid="$(read_pid "$pf")"
  if is_alive "$pid"; then
    local kids
    kids="$(_descendants "$pid")"
    # SIGTERM the whole tree, parent last so children see the signal.
    for k in $kids; do kill "$k" 2>/dev/null || true; done
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      is_alive "$pid" || break
      sleep 0.2
    done
    if is_alive "$pid"; then
      for k in $kids; do kill -9 "$k" 2>/dev/null || true; done
      kill -9 "$pid" 2>/dev/null || true
    fi
    # Mop up any survivors among the descendants.
    for k in $kids; do is_alive "$k" && kill -9 "$k" 2>/dev/null || true; done
    echo "$name stopped (pid $pid)"
  else
    echo "$name not running"
  fi
  rm -f "$pf"
}

cmd_status() {
  local name="$1"
  local pf pid
  pf="$(pidfile "$name")"
  pid="$(read_pid "$pf")"
  if is_alive "$pid"; then
    echo "$name: up (pid $pid)"
  else
    echo "$name: down"
  fi
}

verb="${1:-}"; shift || true
case "$verb" in
  start)  cmd_start "$@" ;;
  stop)   cmd_stop "$@" ;;
  status) cmd_status "$@" ;;
  *)
    echo "usage: bg.sh {start|stop|status} <name> [-- <cmd...>]" >&2
    exit 2
    ;;
esac
