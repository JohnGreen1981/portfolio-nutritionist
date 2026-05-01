# Nutritionist Bot

## Назначение

Репозиторий Telegram-бота нутри-помощника.

Проект показывает продуктовый AI workflow: onboarding с дисклеймером, профиль пользователя, распознавание еды по фото, текстовый/голосовой лог питания, расчёт КБЖУ, дневной контекст, chat-agent, вечерний digest и настройки целей.

## Стек

- Python 3.12+
- aiogram 3
- Supabase/Postgres
- OpenAI API: vision, parsing, macros, chat-agent, digest
- APScheduler
- pydantic / pydantic-settings
- timezonefinder / geopy

## Структура

```text
src/nutri_bot/
  main.py             application setup, routers, middleware, scheduler
  config.py           env/config
  llm.py              OpenAI calls and prompts
  nutrition.py        target calories and macro calculation
  scheduler.py        digest and weight nudge jobs
  handlers/           onboarding, photo, chat, manual, settings, today
  middleware/         onboarding gate, throttling
  repo/               Supabase repositories
  schemas.py          Pydantic models
migrations/001_init.sql
pyproject.toml
.env.example
```

## Роль проекта

Проект показывает AI-assisted product automation prototype: product workflow, stateful onboarding, контекст для LLM, tool-calling, privacy-aware data model, Telegram UX и scheduled digest.

Не описывать проект как медицинский продукт или замену врача/диетолога.

## Privacy / Health Safety

В репозитории не хранить реальные `.env`, `keys.md`, Supabase credentials, пользовательские профили, история питания, фотографии еды, health data, chat logs и production deployment details.

Дисклеймер перед onboarding обязателен: бот не является медицинской консультацией, не предназначен для несовершеннолетних, беременных/кормящих и пользователей с медицинскими состояниями без консультации врача.

## Правила

- Не коммитить `.env`, `keys.md`, tokens, Supabase keys, user profiles, meal logs, photos, chat logs и medical/nutrition history.
- `.env.example` должен содержать только placeholder-значения.
- При изменении Python-кода запускать `python3 -m py_compile $(find src -name '*.py')`.
- Запускать tests и проверку на секреты перед публикацией изменений.
- `AGENTS.md` и `CLAUDE.md` должны оставаться синхронизированными по смыслу.
