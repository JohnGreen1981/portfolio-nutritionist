-- nutri-bot: полная схема БД (с нуля)
-- Накатывать через SQL Editor в Supabase или psql.

SET search_path = public;

-- ─── 1. profiles ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS profiles (
    id                     BIGSERIAL PRIMARY KEY,
    telegram_id            BIGINT NOT NULL UNIQUE,
    first_name             TEXT,
    username               TEXT,
    locale                 TEXT,

    sex                    TEXT,             -- 'm' | 'f'
    birth_year             INT,
    height_cm              NUMERIC(5,1),
    weight_kg              NUMERIC(5,1),
    body_type              TEXT,             -- 'slim' | 'medium' | 'solid'
    activity_level         TEXT,             -- 'sedentary' | 'light' | 'moderate' | 'high' | 'very_high'
    goal                   TEXT,             -- 'lose' | 'maintain' | 'gain'
    target_weight_kg       NUMERIC(5,1),
    meal_regime            TEXT,             -- '3x' | '4_5x' | 'intermittent' | 'irregular'
    timezone               TEXT,             -- IANA, e.g. 'Europe/Moscow'
    allergies              TEXT,
    diet_restrictions      TEXT[]  DEFAULT '{}',
    foods_liked            TEXT,
    foods_disliked         TEXT,

    target_kcal            INT,
    target_prot_g          INT,
    target_fat_g           INT,
    target_carb_g          INT,
    weight_change_pct      NUMERIC(4,2),     -- -15.0 | 0 | +10.0

    onboarding_status      TEXT NOT NULL DEFAULT 'pending',
    onboarding_step        TEXT,
    onboarded_at           TIMESTAMPTZ,
    disclaimer_accepted_at TIMESTAMPTZ,
    last_weight_nudge_at   TIMESTAMPTZ,

    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── 2. meals_draft ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS meals_draft (
    id            BIGSERIAL PRIMARY KEY,
    chat_id       BIGINT        NOT NULL,
    message_id    BIGINT        NOT NULL,
    photo_file_id TEXT,
    candidates    JSONB,
    grams_pred    NUMERIC(10,2),
    chosen_name   TEXT,
    status        TEXT          NOT NULL DEFAULT 'await_dish',
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS meals_draft_chat_msg_idx
    ON meals_draft(chat_id, message_id);

CREATE INDEX IF NOT EXISTS meals_draft_updated_idx
    ON meals_draft(updated_at);

-- ─── 3. meals ───────────────────────────────────────────────────────────────
-- eaten_day убран (был GENERATED по МСК).
-- Локальный день считается в запросах через:
--   (eaten_at AT TIME ZONE p.timezone)::date

CREATE TABLE IF NOT EXISTS meals (
    id         BIGSERIAL PRIMARY KEY,
    chat_id    BIGINT        NOT NULL,
    dish       TEXT          NOT NULL,
    grams      NUMERIC(10,2) NOT NULL,
    kcal       NUMERIC(10,2) NOT NULL,
    prot       NUMERIC(10,2) NOT NULL,
    fat        NUMERIC(10,2) NOT NULL,
    carb       NUMERIC(10,2) NOT NULL,
    eaten_at   TIMESTAMPTZ   NOT NULL,
    deleted    BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS meals_chat_eaten_idx
    ON meals(chat_id, eaten_at);

CREATE INDEX IF NOT EXISTS meals_active_idx
    ON meals(chat_id, eaten_at DESC)
    WHERE deleted = FALSE;

CREATE OR REPLACE FUNCTION set_updated_at_meals()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_meals_updated ON meals;
CREATE TRIGGER trg_meals_updated
    BEFORE UPDATE ON meals
    FOR EACH ROW EXECUTE PROCEDURE set_updated_at_meals();

-- ─── 4. digests ─────────────────────────────────────────────────────────────
-- for_date — локальный день пользователя (в его TZ)

CREATE TABLE IF NOT EXISTS digests (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT        NOT NULL,
    for_date    DATE          NOT NULL,
    kcal        NUMERIC(10,2) NOT NULL DEFAULT 0,
    prot        NUMERIC(10,2) NOT NULL DEFAULT 0,
    fat         NUMERIC(10,2) NOT NULL DEFAULT 0,
    carb        NUMERIC(10,2) NOT NULL DEFAULT 0,
    meals_json  JSONB         NOT NULL DEFAULT '[]',
    summary_md  TEXT          NOT NULL DEFAULT '',
    msg_id      BIGINT,
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (chat_id, for_date)
);

-- ─── 5. chat_logs ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS chat_logs (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT        NOT NULL,
    session_id  TEXT          NOT NULL,
    role        TEXT          NOT NULL,
    content     TEXT          NOT NULL,
    username    TEXT,
    first_name  TEXT,
    metadata    JSONB,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS chat_logs_chat_idx
    ON chat_logs(chat_id, created_at);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_logs_role_chk'
          AND conrelid = 'public.chat_logs'::regclass
    ) THEN
        ALTER TABLE public.chat_logs
            ADD CONSTRAINT chat_logs_role_chk
            CHECK (role IN ('user', 'assistant'));
    END IF;
END $$;

-- ─── 6. RPC-функции ─────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION get_current_summary(_chat_id BIGINT)
RETURNS TABLE (
    chat_id    BIGINT,
    for_date   DATE,
    kcal       NUMERIC,
    prot       NUMERIC,
    fat        NUMERIC,
    carb       NUMERIC,
    meals_json JSONB,
    summary_md TEXT
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    _tz TEXT;
    _today DATE;
BEGIN
    SELECT timezone INTO _tz FROM profiles WHERE telegram_id = _chat_id;
    IF _tz IS NULL THEN _tz := 'Europe/Moscow'; END IF;
    _today := (NOW() AT TIME ZONE _tz)::DATE;

    RETURN QUERY
    SELECT d.chat_id, d.for_date, d.kcal, d.prot, d.fat, d.carb,
           d.meals_json, d.summary_md
      FROM digests d
     WHERE d.chat_id  = _chat_id
       AND d.for_date = _today;
END;
$$;

CREATE OR REPLACE FUNCTION upsert_digest(
    _chat_id     BIGINT,
    _for_date    DATE,
    _kcal        NUMERIC,
    _prot        NUMERIC,
    _fat         NUMERIC,
    _carb        NUMERIC,
    _meals_json  JSONB,
    _summary_md  TEXT,
    _msg_id      BIGINT
)
RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO digests
           (chat_id, for_date, kcal, prot, fat, carb,
            meals_json, summary_md, msg_id)
    VALUES (_chat_id, _for_date, _kcal, _prot, _fat, _carb,
            _meals_json, _summary_md, _msg_id)
    ON CONFLICT (chat_id, for_date) DO UPDATE
        SET kcal       = EXCLUDED.kcal,
            prot       = EXCLUDED.prot,
            fat        = EXCLUDED.fat,
            carb       = EXCLUDED.carb,
            meals_json = EXCLUDED.meals_json,
            summary_md = EXCLUDED.summary_md,
            msg_id     = EXCLUDED.msg_id,
            updated_at = NOW();
END;
$$;
