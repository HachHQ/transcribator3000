# Voice → Obsidian (Dropbox)

Telegram-бот на Python: принимает голосовые, транскрибирует через OpenAI Whisper API и сохраняет `.md` в Dropbox.

## Архитектура

```
Telegram → VPS (Python bot) → OpenAI Whisper API → Dropbox
```

Секреты хранятся **вне репозитория** в `/root/.env` на сервере.

## Локальная разработка

```bash
cp .env.example .env   # заполнить токены локально
pip install -r requirements.txt
cd bot && python main.py
```

## Git и деплой

### Первичная настройка на VPS

```bash
ssh root@94.249.203.188
git clone <URL_РЕПОЗИТОРИЯ> /opt/voice-to-obsidian
cp .env.example /root/.env
nano /root/.env
cd /opt/voice-to-obsidian && docker compose up -d --build
```

### Обновление после `git push`

На сервере:

```bash
ssh root@94.249.203.188 "/opt/voice-to-obsidian/deploy/update.sh"
```

Или вручную:

```bash
cd /opt/voice-to-obsidian
git pull
docker compose up -d --build
```

### Смена токенов

Править только `/root/.env`, затем:

```bash
cd /opt/voice-to-obsidian && docker compose restart
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
