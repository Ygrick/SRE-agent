# Спецификация: Retriever (Qdrant + Runbooks)

## Назначение

Векторная база знаний с Runbooks для SRE-агента. Позволяет находить релевантные инструкции по описанию инцидента.

## Источники данных

Markdown-файлы с Runbooks, расположенные в `runbooks/` директории.

**Пример Runbook:**
```markdown
# Redis OOM (Out of Memory)

## Симптомы
- Алерт: Memory usage > 85%
- `docker stats` показывает высокое потребление RAM контейнером redis
- В логах: "OOM command not allowed when used memory > 'maxmemory'"

## Диагностика
1. `docker logs --tail 100 redis` — проверить ошибки OOM
2. `redis-cli INFO memory` — текущее потребление
3. `redis-cli CONFIG GET maxmemory` — лимит
4. `redis-cli DBSIZE` — количество ключей

## Решение
1. Проверить maxmemory-policy (рекомендуется allkeys-lru)
2. Увеличить maxmemory или добавить RAM
3. Проверить TTL на ключах — возможно, отсутствует expiration
```

## Индексация

### Pipeline

```
runbooks/*.md → Splitter → Chunks → Embedder → Qdrant
```

1. **Парсинг:** Чтение `.md` файлов из директории
2. **Chunking:** Split по заголовкам H1/H2 (сохранение семантической целостности). Если секция > 512 tokens → дополнительный split с overlap 64 tokens
3. **Embedding:** Модель `text-embedding-3-small` (через Gateway) или локальная (sentence-transformers)
4. **Upsert:** В коллекцию Qdrant `runbooks`

### Qdrant Collection

```json
{
  "collection_name": "runbooks",
  "vectors": {
    "size": 1536,
    "distance": "Cosine"
  }
}
```

**Payload (metadata per chunk):**
```json
{
  "source_file": "redis-oom.md",
  "section_title": "Redis OOM (Out of Memory)",
  "chunk_index": 0,
  "total_chunks": 3
}
```

### Обновление

- Скрипт `scripts/index_runbooks.py` — запускается вручную или при деплое
- Idempotent: удаляет старые chunks файла перед upsert новых (по `source_file` filter)

## Поиск

### MCP Tool: qdrant_search

**Input:** текстовый запрос (описание инцидента)

**Process:**
1. Embedding запроса (та же модель, что при индексации)
2. `qdrant_client.search(collection="runbooks", query_vector=embedding, limit=3, score_threshold=0.7)`
3. Конкатенация текстов найденных chunks

**Output:** строка с текстом релевантных секций Runbooks

### Параметры

| Параметр | Значение | Обоснование |
|---|---|---|
| Top-K | 3 | Баланс полноты и context budget |
| Score threshold | 0.7 | Фильтрация нерелевантных результатов |
| Chunk size | ~512 tokens | Оптимум для embedding модели |
| Chunk overlap | 64 tokens | Сохранение контекста на границах |

## Ограничения

- Runbooks обновляются вручную (нет auto-sync)
- Только текстовый поиск (нет фильтрации по severity, host type и т.д. — возможно в будущем)
- При недоступности Qdrant → агент работает без RAG (graceful degradation)

## Зависимости

- **Qdrant** — векторная БД
- **LLM Gateway** — для embedding запросов (или локальная модель)
- **sentence-transformers** (опционально) — для локальных embeddings
