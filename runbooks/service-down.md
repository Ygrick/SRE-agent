# Сервис не отвечает

## Симптомы
- Алерт: HTTP endpoint response time > 5s or status != 200
- Алерт: Container down
- Пользователи жалуются на недоступность

## Диагностика
1. `docker ps -a` — статус всех контейнеров
2. `docker logs --tail 100 <container>` — последние логи
3. `docker inspect <container> --format='{{.State.Status}} {{.State.ExitCode}}'` — статус и код выхода
4. `netstat -tlnp | grep <port>` — порт слушается?
5. `curl -v http://localhost:<port>/health` — ответ health endpoint

## Возможные причины
- Контейнер упал (OOM, exception, segfault)
- Порт занят другим процессом
- Зависимость недоступна (БД, Redis)
- Ошибка конфигурации после деплоя

## Рекомендации
1. Проверить логи контейнера на причину падения
2. Если OOM — увеличить memory limit или найти утечку
3. Если зависимость — проверить health зависимостей
4. Рестарт: `docker compose restart <service>`
