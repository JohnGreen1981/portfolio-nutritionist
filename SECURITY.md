# Безопасность

Не коммитить API keys, Telegram tokens, Supabase keys, user health data, meal logs, profile data, photos, chat logs, medical/nutrition history и deployment credentials.

Перед публикацией проверить:

- `.env.example` содержит только placeholder-значения;
- `keys.md`, `.env`, `.venv`, N8N exports, photos и user data не попали в git;
- в миграциях нет реальных профилей, meal logs или chat logs;
- README содержит health/privacy limitations;
- secret scan не находит токены и ключи.
