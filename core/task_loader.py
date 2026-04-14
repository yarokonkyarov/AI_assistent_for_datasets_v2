# core/task_loader.py
from uuid import UUID
from datetime import date, timedelta
from typing import Optional, Dict, Any

from db.repository import get_task_by_id, get_iiko_connection, get_clickhouse_connection, get_report_template


def load_full_task_config(task_id: UUID) -> Optional[Dict[str, Any]]:
    """
    Загружает полную конфигурацию задачи по UUID из PostgreSQL.

    Возвращает словарь, готовый к передаче в IikoOlapDatasetManager(config_dict=...),
    или None, если задача не найдена или неактивна.
    """
    task = get_task_by_id(task_id)
    if not task:
        return None

    iiko_conn = get_iiko_connection(task.iiko_connection_id)
    ch_conn = get_clickhouse_connection(task.clickhouse_connection_id)
    report_template = get_report_template(task.report_template_id)

    if not iiko_conn or not ch_conn or not report_template:
        return None

    # Вычисляем период выгрузки на основе смещений
    today = date.today()
    date_from = today - timedelta(days=task.days_offset_start)
    date_to = today - timedelta(days=task.days_offset_end)

    config_dict = {
        "iiko": {
            "api_url": iiko_conn.api_url,
            "login": iiko_conn.login,
            "password": iiko_conn.password,
        },
        "clickhouse": {
            "host": ch_conn.host,
            "port": ch_conn.port,
            "user": ch_conn.user,
            "password": ch_conn.password,
            "storage_policy": ch_conn.storage_policy,
        },
        "report_template": report_template.default_report_config,
        "dataset_name": task.dataset_name,
        "date_from": date_from,
        "date_to": date_to,
        "currency_conversion": {
            "enabled": True,
            # Фиксированная валюта подключения: все строки из этого iiko
            # конвертируются по одному курсу, без чтения Currencies_Currency
            "connection_currency": iiko_conn.currency,
        },
    }

    return config_dict