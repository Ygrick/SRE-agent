#!/bin/bash
# Disk stress: генерирует большие лог-файлы
# Usage: ./disk_stress.sh [duration_seconds] [log_dir]
DURATION=${1:-300}
LOG_DIR=${2:-/tmp/stress-logs}

mkdir -p "$LOG_DIR"
echo "Starting disk stress: writing to ${LOG_DIR} for ${DURATION}s"

END=$((SECONDS + DURATION))
COUNT=0
while [ $SECONDS -lt $END ]; do
    for i in $(seq 1 100); do
        echo "[$(date -Iseconds)] ERROR: Simulated error #$COUNT in service playground-app. Stack trace: java.lang.OutOfMemoryError at com.example.Service.process(Service.java:42)" >> "$LOG_DIR/app.log"
        COUNT=$((COUNT + 1))
    done
    sleep 0.1
done

SIZE=$(du -sh "$LOG_DIR" | cut -f1)
echo "Disk stress finished: wrote $COUNT lines, total size: $SIZE"
