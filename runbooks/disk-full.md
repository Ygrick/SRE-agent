# Диск заполнен

## Симптомы
- Алерт: Disk usage > 95%
- Ошибки записи в логах приложений
- PostgreSQL: "No space left on device"

## Диагностика
1. `df -h` — использование дисков
2. `du -sh /var/log/* | sort -rh | head -10` — самые большие директории в /var/log
3. `du -sh /tmp/* | sort -rh | head -10` — временные файлы
4. `find / -type f -size +100M -exec ls -lh {} \; 2>/dev/null | head -10` — большие файлы
5. `journalctl --disk-usage` — размер системных журналов

## Возможные причины
- Разросшиеся лог-файлы (нет ротации)
- Временные файлы не очищаются
- Дампы базы данных
- Docker images/volumes занимают место

## Рекомендации
1. Очистить старые логи: `find /var/log -name "*.log.*" -mtime +7 -delete`
2. Очистить журналы: `journalctl --vacuum-size=500M`
3. Настроить logrotate если не настроен
4. Проверить Docker: `docker system df` и `docker system prune`
