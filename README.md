# transcribator3000

Telegram-бот на Python: принимает голосовые, транскрибирует через OpenAI Whisper API и сохраняет `.md` в Dropbox.

## Архитектура

```
Telegram → VPS (Python bot) → OpenAI Whisper API → Dropbox
```

Секреты хранятся **вне репозитория** в `/root/.env` на сервере.

## Локальная разработка

```bash
cp .env.example .env
poetry install
poetry run python bot/main.py
```

## GitHub Actions (CI/CD)

При каждом **push** и **pull request** в `main`:

1. **Test** — `poetry check`, проверка синтаксиса, сборка Docker-образа
2. **Deploy** — только после успешного теста на `main`: `git pull` + `docker compose up` на VPS

### Одноразовая настройка

**1. SSH-ключ для GitHub Actions** (на вашем ПК):

```bash
bash deploy/setup-github-actions-ssh.sh
```

**2. Публичный ключ** — добавить на VPS в `~/.ssh/authorized_keys`

**3. Secrets** в репозитории GitHub:  
https://github.com/HachHQ/transcribator3000/settings/secrets/actions

| Secret | Значение |
|---|---|
| `VPS_HOST` | `94.249.203.188` |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | приватный ключ из шага 1 |

**4. Проверка** — вкладка **Actions** на GitHub после `git push`

### Ручной деплой (если CI/CD не нужен)

```bash
ssh root@94.249.203.188 "/opt/transcribator3000/deploy/update.sh"
```

## Git и деплой

### Первичная настройка на VPS

```bash
ssh root@94.249.203.188
git clone https://github.com/HachHQ/transcribator3000.git /opt/transcribator3000
cp .env.example /root/.env
nano /root/.env
cd /opt/transcribator3000 && docker compose up -d --build
```

### Обновление после `git push`

На сервере:

```bash
ssh root@94.249.203.188 "/opt/transcribator3000/deploy/update.sh"
```

Или вручную:

```bash
cd /opt/transcribator3000
git pull
docker compose up -d --build
```

### Смена токенов

Править только `/root/.env`, затем:

```bash
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
