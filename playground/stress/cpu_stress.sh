#!/bin/bash
# CPU stress: загружает все ядра на указанное время
# Usage: ./cpu_stress.sh [duration_seconds] [workers]
DURATION=${1:-300}
WORKERS=${2:-$(nproc)}

echo "Starting CPU stress: ${WORKERS} workers for ${DURATION}s"
stress-ng --cpu "$WORKERS" --timeout "${DURATION}s" --metrics-brief
echo "CPU stress finished"
