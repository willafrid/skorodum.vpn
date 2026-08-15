# Обновление объединённого файла на сервере

`sync_sources.py` загружает оба источника, декодирует Base64, если источник
действительно закодирован, и сохраняет объединённый результат в
`cron-base64/combined.txt`. Уже обычный UTF-8 текст сохраняется без изменений.
Между содержимым источников
добавляется одна пустая строка.

`run_sync.sh` предназначен для cron на сервере. Он обновляет локальную копию
репозитория через `git pull --ff-only`, запускает `sync_sources.py` и, только
если `cron-base64/combined.txt` изменился, создаёт коммит и делает `git push`.
Повторный запуск во время уже идущей синхронизации безопасно пропускается.

## Настройка сервера

1. Установите `git` и Python 3, затем клонируйте репозиторий в постоянный
   каталог, например `/srv/combined-text-sync`.
2. Настройте доступ на запись для этого клона: SSH deploy key с правом записи
   либо credential helper / HTTPS token. Убедитесь, что обычный `git push` из
   этого каталога проходит без интерактивного ввода.
3. При необходимости задайте автора автоматических коммитов:

```sh
export SYNC_GIT_NAME='combined-text-sync'
export SYNC_GIT_EMAIL='combined-text-sync@example.com'
```

4. Проверьте запуск вручную из каталога репозитория:

```sh
bash cron-base64/run_sync.sh
```

5. Откройте crontab (`crontab -e`) и добавьте запуск, например на 7-й и 37-й
   минуте каждого часа. Укажите абсолютные пути, потому что cron не наследует
   обычное окружение shell:

```cron
7,37 * * * * SYNC_REPO_DIR=/srv/combined-text-sync SYNC_GIT_NAME=combined-text-sync SYNC_GIT_EMAIL=combined-text-sync@example.com /bin/bash /srv/combined-text-sync/cron-base64/run_sync.sh >> /var/log/combined-text-sync.log 2>&1
```

Если у пользователя cron нет права писать в `/var/log`, используйте лог внутри
домашнего каталога, например `/home/sync/combined-text-sync.log`.

Прямая ссылка на результат после первого коммита:

`https://raw.githubusercontent.com/<owner>/<repository>/<branch>/cron-base64/combined.txt`

Запуск только скачивания и объединения, без Git-коммита и push:

```sh
python3 cron-base64/sync_sources.py
```
