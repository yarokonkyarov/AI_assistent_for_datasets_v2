# scripts/migrate_json_to_db.py
import json
import os
import sys
import hashlib
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor


def connect_db():
    """Подключение к PostgreSQL (читает из config/postgres.json или переменных окружения)"""
    config_path = Path("../config/postgres.json").resolve()
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
    else:
        import os
        cfg = {
            "host": os.getenv("PG_HOST", "localhost"),
            "port": int(os.getenv("PG_PORT", "5432")),
            "database": os.getenv("PG_DB", "iiko_loader"),
            "user": os.getenv("PG_USER", "iiko_loader_user"),
            "password": os.getenv("PG_PASSWORD", "password")
        }
    return psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        database=cfg["database"],
        user=cfg["user"],
        password=cfg["password"],
        cursor_factory=RealDictCursor
    )


def get_or_create_iiko_connection(conn, iiko_config: Dict[str, str]) -> int:
    """Возвращает id iiko-подключения, создавая его при необходимости"""
    api_url = iiko_config["api_url"]
    login = iiko_config["login"]
    password = iiko_config["password"]

    # Генерируем уникальное имя на основе хеша
    name = hashlib.sha256(f"{api_url}|{login}".encode()).hexdigest()[:16]

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, name FROM iiko_connections
            WHERE api_url = %s AND login = %s
        """, (api_url, login))
        row = cur.fetchone()
        if row:
            return row["id"]

        # Создаём новое подключение
        cur.execute("""
            INSERT INTO iiko_connections (name, api_url, login, password)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
            SET api_url = EXCLUDED.api_url, login = EXCLUDED.login, password = EXCLUDED.password
            RETURNING id
        """, (name, api_url, login, password))
        row = cur.fetchone()
        conn.commit()
        return row["id"]


def get_or_create_clickhouse_connection(conn, ch_config: Dict[str, Any]) -> int:
    """Возвращает id ClickHouse-подключения"""
    host = ch_config["host"]
    port = ch_config.get("port", 9000)
    user = ch_config["user"]
    password = ch_config["password"]
    storage_policy = ch_config.get("storage_policy", "default")

    name = hashlib.sha256(f"{host}:{port}|{user}".encode()).hexdigest()[:16]

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM clickhouse_connections
            WHERE host = %s AND port = %s AND user = %s
        """, (host, port, user))
        row = cur.fetchone()
        if row:
            return row["id"]

        cur.execute("""
            INSERT INTO clickhouse_connections (name, host, port, user, password, storage_policy)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
            SET host = EXCLUDED.host, port = EXCLUDED.port, user = EXCLUDED.user,
                password = EXCLUDED.password, storage_policy = EXCLUDED.storage_policy
            RETURNING id
        """, (name, host, port, user, password, storage_policy))
        row = cur.fetchone()
        conn.commit()
        return row["id"]


def get_or_create_report_template(conn, report_config: Dict, template_name: str) -> int:
    """Возвращает id шаблона отчёта по имени (pl1, pl2 и т.д.)"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM report_templates WHERE name = %s
        """, (template_name,))
        row = cur.fetchone()
        if row:
            return row["id"]

        cur.execute("""
            INSERT INTO report_templates (name, default_report_config)
            VALUES (%s, %s)
            RETURNING id
        """, (template_name, json.dumps(report_config)))
        row = cur.fetchone()
        conn.commit()
        return row["id"]


def extract_template_name_from_filename(filename: str) -> str:
    """Извлекает 'pl1', 'pl2' и т.д. из имени файла вида 'myata_pl1.json'"""
    stem = Path(filename).stem  # 'myata_pl1'
    if '_' in stem:
        parts = stem.split('_')
        # Предполагаем, что последняя часть — это шаблон: myata_pl1 → pl1
        return parts[-1]
    else:
        # Например, fobo_pl2.json → pl2
        return stem


def migrate_config_file(conn, file_path: Path):
    """Мигрирует один JSON-файл конфигурации"""
    try:
        with open(file_path, encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"⚠️  Skip invalid JSON: {file_path} — {e}")
        return

    if "iiko" not in config or "clickhouse" not in config or "default_report_config" not in config:
        print(f"⚠️  Skip non-dataset config: {file_path}")
        return

    iiko_id = get_or_create_iiko_connection(conn, config["iiko"])
    ch_id = get_or_create_clickhouse_connection(conn, config["clickhouse"])
    template_name = extract_template_name_from_filename(file_path.name)
    template_id = get_or_create_report_template(conn, config["default_report_config"], template_name)

    # Определяем dataset_name:
    # Если файл в подпапке: configs/m_grand/myata_pl1.json → m_grand.myata_pl1
    # Если в корне configs/: fobo_pl1.json → fobo.pl1
    relative = file_path.relative_to(Path("configs"))
    if len(relative.parts) == 1:
        # В корне
        dataset_name = f"{Path(relative).stem.replace('_', '.')}"
    else:
        # В подпапке
        folder = relative.parts[0]
        stem = Path(relative).stem
        dataset_name = f"{folder}.{stem.replace('_', '.')}"

    # Проверяем, не существует ли уже такая задача
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM tasks WHERE dataset_name = %s
        """, (dataset_name,))
        if cur.fetchone():
            print(f"⏩ Task already exists: {dataset_name}")
            return

    # Создаём задачу
    task_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO tasks (
                id, name, iiko_connection_id, clickhouse_connection_id,
                report_template_id, dataset_name, days_offset_start, days_offset_end, is_active
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            task_id,
            f"Auto-migrated: {dataset_name}",
            iiko_id,
            ch_id,
            template_id,
            dataset_name,
            14,  # days_offset_start
            0,   # days_offset_end
            True
        ))
        conn.commit()
        print(f"✅ Created task {task_id} → {dataset_name}")


def main():
    config_root = Path("../configs").resolve()
    if not config_root.exists():
        print("Configs directory not found. Run from project root.", file=sys.stderr)
        sys.exit(1)

    conn = connect_db()
    try:
        print("Starting migration of JSON configs to PostgreSQL...")
        for json_file in config_root.rglob("*.json"):
            # Пропускаем служебные файлы
            if any(part in str(json_file) for part in ["cronicle_info", "config.json", "fields_", "requirements", "style.css"]):
                continue
            # Пропускаем папки templates, temp и т.д., если они есть в configs/
            if "templates" in json_file.parts or "temp" in json_file.parts:
                continue
            migrate_config_file(conn, json_file)
        print("Migration completed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()