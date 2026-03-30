#!/bin/bash
# Memory stress: выделяет указанный объём памяти
# Usage: ./memory_stress.sh [percentage] [duration_seconds]
PERCENT=${1:-80}
DURATION=${2:-300}

echo "Starting memory stress: ${PERCENT}% for ${DURATION}s"
stress-ng --vm 1 --vm-bytes "${PERCENT}%" --timeout "${DURATION}s" --metrics-brief
echo "Memory stress finished"
