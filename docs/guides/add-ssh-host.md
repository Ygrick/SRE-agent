# Добавление SSH-хоста для диагностики

SRE Agent подключается к серверам по SSH для выполнения диагностических команд. Хост для подключения берётся из поля `host` в Zabbix-алерте.

## Как это работает

1. Zabbix отправляет алерт с `"host": "production-web"`
2. SRE Agent запускает Codex, который выполняет `ssh production-web <command>`
3. SSH-клиент внутри контейнера ищет хост `production-web` в конфиге `agent/ssh_config`

## Добавление нового хоста

### Шаг 1: Отредактируйте `agent/ssh_config`

```bash
nano agent/ssh_config
```

Добавьте блок для нового хоста:

```
Host production-web
    HostName 10.0.1.10
    Port 22
```

- `Host` — имя, которое **должно совпадать** с `host` в Zabbix-алерте
- `HostName` — IP-адрес или DNS-имя сервера
- `Port` — SSH-порт (по умолчанию 22)

Общие параметры (`User`, `IdentityFile`, `StrictHostKeyChecking`) применяются автоматически из блока `Host *` в конце файла.

### Шаг 2: Убедитесь что SSH-ключ подходит

По умолчанию используется ключ `/run/secrets/ssh/id_ed25519` (общий volume `playground_ssh_keys`).

Если для нового хоста нужен **отдельный ключ**, укажите его в блоке хоста:

```
Host production-web
    HostName 10.0.1.10
    IdentityFile /run/secrets/ssh/id_ed25519_prod
```

И добавьте volume с ключом в `docker-compose.yml`:

```yaml
sre-agent:
  volumes:
    - ./secrets/id_ed25519_prod:/run/secrets/ssh/id_ed25519_prod:ro
```

### Шаг 3: Перезапустите агент

```bash
# Пересборка не нужна — ssh_config монтируется как volume
docker compose restart sre-agent
```

### Шаг 4: Проверьте подключение

```bash
docker compose exec sre-agent ssh production-web uptime
```

## Настройка Zabbix

Чтобы алерты приходили с правильным `host`, убедитесь что:

1. Имя хоста в Zabbix (Configuration → Hosts → Host name) совпадает с `Host` в `agent/ssh_config`
2. Webhook media type передаёт `{HOST.NAME}` в поле `host` JSON-payload

## Пример: несколько хостов

```
# agent/ssh_config

Host playground
    HostName playground-app

Host production-web
    HostName 10.0.1.10

Host staging-db
    HostName staging-db.internal
    Port 2222
    User admin
    IdentityFile /run/secrets/ssh/id_ed25519_staging

Host *
    User sre-agent
    IdentityFile /run/secrets/ssh/id_ed25519
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
    ConnectTimeout 10
```

## Ограничения

- SRE Agent выполняет **только read-only** команды (whitelist в `AGENTS.md`)
- SSH-ключ должен быть **авторизован** на целевом сервере (`~/.ssh/authorized_keys`)
- Сетевая доступность: контейнер `sre-agent` должен иметь доступ к целевому хосту (Docker network или external)
