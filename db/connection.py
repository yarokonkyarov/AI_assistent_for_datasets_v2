# db/connection.py
import json
import os
import sys  # ← добавьте эту строку
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictConnection

import psycopg2
from psycopg2.extras import RealDictConnection

def get_postgres_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "postgres.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                # Проверяем наличие обязательных ключей
                required = ["host", "port", "database", "user", "password"]
                for key in required:
                    if key not in cfg:
                        raise ValueError(f"Missing required key '{key}' in {config_path}")
                return cfg
        except (json.JSONDecodeError, ValueError) as e:
            print(f"ERROR: Invalid config file {config_path}: {e}", file=sys.stderr)
            raise
    else:
        import os
        import sys
        cfg = {
            "host": os.getenv("PG_HOST"),
            "port": os.getenv("PG_PORT"),
            "database": os.getenv("PG_DB"),
            "user": os.getenv("PG_USER"),
            "password": os.getenv("PG_PASSWORD")
        }
        # Проверяем переменные окружения
        missing = [k for k, v in cfg.items() if not v]
        if missing:
            print(f"ERROR: Missing environment variables: {', '.join(missing)}", file=sys.stderr)
            raise RuntimeError("Database configuration incomplete")
        cfg["port"] = int(cfg["port"])
        return cfg

def get_db_connection():
    cfg = get_postgres_config()
    return psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        database=cfg["database"],
        user=cfg["user"],
        password=cfg["password"],
        connection_factory=RealDictConnection
    )