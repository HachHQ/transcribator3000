# transcribator3000

Telegram-бот на Python: принимает голосовые, транскрибирует через OpenAI Whisper API и сохраняет `.md` в Dropbox.

## Архитектура

```
Telegram → VPS (Python bot) → OpenAI Whisper API → Dropbox
```

Секреты хранятся в **GitHub Actions Secrets** и при деплое автоматически записываются в `/root/.env` на сервере.

## Локальная разработка

```bash
cp .env.example .env
poetry install
poetry run python bot/main.py
```

## GitHub Actions (CI/CD)

При каждом **push** и **pull request** в `main`:

1. **Test** — `poetry check`, проверка синтаксиса, сборка Docker-образа
2. **Deploy** — только после успешного теста на `main`: копирование файлов на VPS + запись `/root/.env` из secrets + `docker compose up`

### Одноразовая настройка

**1. SSH-ключ для GitHub Actions** (на вашем ПК):

```bash
bash deploy/setup-github-actions-ssh.sh
```

**2. Публичный ключ** — добавить на VPS в `~/.ssh/authorized_keys`

**3. Secrets** в репозитории GitHub:  
https://github.com/HachHQ/transcribator3000/settings/secrets/actions

> **Где искать:** Settings → **Secrets and variables** → **Actions** → вкладка **Repository secrets** (не Variables, не Environment secrets).

**Быстрая загрузка** — один раз заполнить локальный `.env`, затем:

```bash
cp .env.example .env   # если ещё нет
nano .env
bash deploy/set-github-secrets.sh
```

Скрипт зальёт все переменные из `.env` + спросит IP сервера и пользователя.

| Secret | Значение |
|---|---|
| `VPS_HOST` | IP VPS, например `5.175.161.26` |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | приватный ключ из шага 1 |
| `TELEGRAM_BOT_TOKEN` | токен от @BotFather |
| `OPENAI_API_KEY` | ключ OpenAI |
| `DROPBOX_APP_KEY` | Dropbox app key |
| `DROPBOX_APP_SECRET` | Dropbox app secret |
| `DROPBOX_REFRESH_TOKEN` | Dropbox refresh token |
| `DROPBOX_VAULT_PATH` | `/Obsidian/MyVault` |
| `WHISPER_LANGUAGE` | `ru` (опционально) |
| `TIMEZONE` | `Asia/Bangkok` (опционально) |

Обновить один secret вручную:

```bash
gh secret set VPS_HOST --body "5.175.161.26" -R HachHQ/transcribator3000
```

**4. Проверка** — вкладка **Actions** на GitHub после `git push`

### Ручной деплой (если CI/CD не нужен)

```bash
ssh root@5.175.161.26 "/opt/transcribator3000/deploy/update.sh"
```

## Git и деплой

### Первичная настройка на VPS

На сервере нужен только Docker — файлы и `/root/.env` доставляет GitHub Actions:

```bash
ssh root@5.175.161.26
apt install -y docker-compose-v2   # если ещё нет
mkdir -p /opt/transcribator3000
```

Дальше — `git push` в `main` (после настройки secrets).

### Обновление после `git push`

Автоматически через GitHub Actions. Или вручную на сервере:

```bash
ssh root@5.175.161.26 "/opt/transcribator3000/deploy/update.sh"
```

### Смена токенов

Обновить secret в GitHub (`gh secret set ...`) и сделать `git push` в `main`, либо вручную:

```bash
nano /root/.env
cd /opt/transcribator3000 && docker compose restart
```

## Переменные окружения

См. `.env.example`. Обязательные:

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`
- `DROPBOX_VAULT_PATH`

## Формат заметок (GMT+7)

```
/Obsidian/MyVault/2026-06/14/14-30-45.md
```

```markdown
# 14:30:45

Текст транскрипции...
```

## Ресурсы

~256 MB RAM в Docker.
