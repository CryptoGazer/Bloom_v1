#!/usr/bin/env bash
# Control the transit logger (scripts/transit/logger.py).
#   ./scripts/transit/logger.sh start [interval_sec]   run in background (default 15 s), Mac kept awake
#   ./scripts/transit/logger.sh stop                   stop; data already written stays
#   ./scripts/transit/logger.sh status                 running or not, row counts, last request
#   ./scripts/transit/logger.sh log                    follow the log (Ctrl+C leaves the logger running)
#   ./scripts/transit/logger.sh summary                build summary tables from what is logged so far
# Data: data/transit/vehicles.csv and polls.csv, append-only. Optional: TRANSIT_LOGGER_UA="Team X (UniHack 2026)".
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/data/transit"
PID_FILE="$DIR/logger.pid"
LOG="$DIR/logger.log"

running_pid() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return 0
    fi
  fi
  return 1
}

cmd="${1:-help}"
case "$cmd" in
  start)
    if pid="$(running_pid)"; then
      echo "Уже работает, pid $pid"
      exit 0
    fi
    mkdir -p "$DIR"
    nohup python3 -I "$ROOT/scripts/transit/logger.py" --dir "$DIR" --interval "${2:-15}" >> "$LOG" 2>&1 &
    for _ in 1 2 3 4 5 6; do
      if pid="$(running_pid)"; then
        echo "Запущен, pid $pid. Данные: $DIR. Лог: $LOG"
        exit 0
      fi
      sleep 0.5
    done
    echo "Не запустился. Последние строки лога:" >&2
    tail -n 5 "$LOG" >&2
    exit 1
    ;;

  stop)
    if ! pid="$(running_pid)"; then
      echo "Не запущен"
      exit 0
    fi
    kill -TERM "$pid"
    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "Остановлен. Данные сохранены в $DIR"
        exit 0
      fi
      sleep 0.5
    done
    echo "Не остановился за 10 с, pid $pid" >&2
    exit 1
    ;;

  status)
    if pid="$(running_pid)"; then echo "Работает, pid $pid"; else echo "Не запущен"; fi
    for f in vehicles.csv polls.csv; do
      if [[ -s "$DIR/$f" ]]; then
        echo "$f: $(($(wc -l < "$DIR/$f") - 1)) строк данных, $(du -h "$DIR/$f" | cut -f1 | tr -d ' ')"
      fi
    done
    if [[ -f "$DIR/polls.csv" ]]; then
      echo "Последний запрос: $(tail -n 1 "$DIR/polls.csv")"
    fi
    ;;

  log)
    tail -n 20 -f "$LOG"
    ;;

  summary)
    python3 -I "$ROOT/scripts/transit/summarize.py" --dir "$DIR" "${@:2}"
    ;;

  *)
    sed -n '2,8p' "$0"
    ;;
esac
