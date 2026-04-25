-- Миграция: добавляем поля для загрузки погоды в iiko_connections
-- Запустить: psql -d iiko_configs -f scripts/migrate_add_weather.sql

ALTER TABLE iiko_connections
    ADD COLUMN IF NOT EXISTS iiko_cloud_api_key VARCHAR(100) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS load_weather BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN iiko_connections.iiko_cloud_api_key IS
    API ключ iiko Cloud для получения списка организаций с координатами;

COMMENT ON COLUMN iiko_connections.load_weather IS
    Флаг: загружать ли погоду для организаций этого подключения;
