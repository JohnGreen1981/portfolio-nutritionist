# План очистки

- [x] Перенести `nutri-bot/src/`, `migrations/`, `pyproject.toml` и safe public docs.
- [x] Исключить `.env`, `keys.md`, `.venv`, user data, private profiles, logs, photos и N8N reference files.
- [x] Создать безопасный `.env.example`.
- [x] Добавить публичные `AGENTS.md` / `CLAUDE.md`.
- [x] Добавить synthetic tests без real health/nutrition data.
- [x] Оставить medical disclaimer видимым в README и AGENTS.
- [x] Запустить tests/syntax check.
- [x] Запустить secret scan перед первым GitHub push.
