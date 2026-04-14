-- Добавляет поле currency в таблицу iiko_connections.
-- Запустить один раз: psql -d iiko_configs -f scripts/migrate_add_currency.sql

ALTER TABLE iiko_connections
    ADD COLUMN IF NOT EXISTS currency VARCHAR(10) NOT NULL DEFAULT 'RUB';

-- Обновить комментарий к колонке
COMMENT ON COLUMN iiko_connections.currency IS
    'Валюта данного подключения: RUB, GEL, AMD и т.д.';
