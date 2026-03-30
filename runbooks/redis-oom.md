# Redis Out of Memory

## Симптомы
- Алерт: Memory usage > 85% (на контейнере Redis)
- В логах Redis: "OOM command not allowed when used memory > 'maxmemory'"
- Приложение получает ошибки записи в Redis

## Диагностика
1. `redis-cli INFO memory` — текущее потребление, peak, fragmentation
2. `redis-cli CONFIG GET maxmemory` — установленный лимит
3. `redis-cli CONFIG GET maxmemory-policy` — политика вытеснения
4. `redis-cli DBSIZE` — количество ключей
5. `redis-cli INFO keyspace` — распределение по базам
6. `docker logs --tail 100 playground-redis` — логи Redis

## Возможные причины
- Отсутствует maxmemory-policy (по умолчанию noeviction)
- Ключи без TTL накапливаются
- Большие значения (списки, хэши) разрастаются
- Недостаточный maxmemory для нагрузки

## Рекомендации
1. Установить maxmemory-policy: `redis-cli CONFIG SET maxmemory-policy allkeys-lru`
2. Проверить TTL на ключах: `redis-cli TTL <key>`
3. Найти большие ключи: `redis-cli --bigkeys`
4. Увеличить maxmemory если нужно
