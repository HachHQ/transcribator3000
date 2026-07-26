# transcribator3000 (LLM Vault)

Multi-user Telegram + API продукт: голос → транскрипция → транзитный Redis-кэш → Dropbox, затем LLM-постобработка, классификация в Google Tasks/Calendar и ежедневная сводка менеджера.

## Архитектура

```
Telegram / API
    → Postgres (users, oauth, note meta, jobs)
    → Redis (note body/audio cache + arq queue)
    → Workers: Whisper → Dropbox → LLM postprocess → classify
    → Google Calendar / Tasks
```

Тело заметки **не хранится** в Postgres — только в Redis на время пайплайна (TTL), durable копия в Dropbox.

## Сервисы (docker compose)

| Service | Роль |
|---|---|
| `api` | FastAPI: `/health`, OAuth Google/Dropbox |
| `worker` | arq jobs + daily_manager cron |
| `bot` | Telegram polling |
| `postgres` | метаданные |
| `redis` | кэш + очередь |
| `migrate` | Alembic upgrade |

## Локальный запуск

```bash
cp .env.example .env
# заполните TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, TOKEN_ENCRYPTION_KEY,
# DROPBOX_*, GOOGLE_*, PUBLIC_BASE_URL

poetry install
docker compose up -d postgres redis
poetry run alembic upgrade head
poetry run vault-api      # :8000
poetry run vault-worker
poetry run vault-bot
```

Или всё сразу:

```bash
docker compose up -d --build
```

## OAuth (на пользователя)

`/start` и `/connections` показывают статус Dropbox/Google и кнопки (или текстовые ссылки).

Redirect URI = `{PUBLIC_BASE_URL}/oauth/dropbox/callback` и `.../oauth/google/callback` — должны совпадать с консолями приложений.

Токены шифруются (`TOKEN_ENCRYPTION_KEY`) в `oauth_credentials`.

## Пайплайн заметки

`received → transcribing → cached → uploaded → postprocessing → classified → awaiting_confirmation? → done`

Jobs: `transcribe` → `upload_note` → `postprocess_note` → `classify_task` → (кнопки) `apply_classification`.

Если LLM видит задачу/событие и Google подключён — бот пришлёт **Подтвердить / Пропустить**.  
Без Google — заметка `done` + подсказка `/connections`.

## Daily brief

- `/brief` — сводка на сегодня (Calendar conflicts + free windows + Tasks + LLM)
- cron каждый час на `:05`; отправка в **локальный `brief_hour`** пользователя (по умолчанию 7), dedupe в Redis
- `/settings`, `/setbriefhour 8`, `/settimezone Asia/Bangkok`

## Smoke (Google-слой)

1. `/connections` → подключить Google  
2. Голосовое с задачей («завтра в 15:00 созвон…»)  
3. Дождаться кнопок → Подтвердить → проверить Google Tasks/Calendar  
4. `/brief` — получить сводку  

## Промпты агента

Пользователь настраивает system prompt из бота:

- `/prompts` — текущие промпты (`notes`, `brief`, `classify`)
- `/setprompt brief` → следующим сообщением новый текст
- `/resetprompt notes` — сброс к дефолту

`notes` — постобработка транскрипта; `brief` — ежедневная сводка; `classify` — извлечение задач/событий.

## LLM

Единый интерфейс `LLMProvider` (`complete` / `structured`).  
По умолчанию OpenAI; для локального сервера задайте `OPENAI_BASE_URL` (Ollama/vLLM OpenAI-compatible).

## Переменные окружения

См. [`.env.example`](.env.example). Обязательные для полного цикла:

- `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `TOKEN_ENCRYPTION_KEY`
- `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `PUBLIC_BASE_URL`, `DATABASE_URL`, `REDIS_URL`

## Структура

```
app/
  api/                 FastAPI
  db/                  SQLAlchemy + models
  domain/              enums, DTO
  integrations/        llm, dropbox, google, telegram
  pipelines/           статусы
  services/            use-cases
  workers/             arq jobs
alembic/               миграции
```

## CI/CD

Push в `main`: test (`compileall` + unittest + docker build) → deploy на VPS (`docker compose up`).
