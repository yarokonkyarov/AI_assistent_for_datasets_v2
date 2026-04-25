# db/repository.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
import json
from .connection import get_db_connection
from .models import (
    Task, IikoConnection, ClickHouseConnection, ReportTemplate, Category
)


# --- Categories ---

def get_category_by_id(category_id: int) -> Optional[Category]:
    """>;CG8BL :0B53>@8N ?> ID"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, description, color, is_active, 
                       created_at, updated_at
                FROM categories
                WHERE id = %s
            """, (category_id,))
            row = cur.fetchone()
            return Category(**row) if row else None


def get_category_by_name(name: str) -> Optional[Category]:
    """>;CG8BL :0B53>@8N ?> 8<5=8"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, description, color, is_active,
                       created_at, updated_at
                FROM categories
                WHERE LOWER(name) = LOWER(%s)
            """, (name,))
            row = cur.fetchone()
            return Category(**row) if row else None


def list_categories(
        is_active: Optional[bool] = None,
        search: Optional[str] = None
) -> List[Category]:
    """>;CG8BL A?8A>: :0B53>@89"""
    query = """
        SELECT id, name, description, color, is_active,
               created_at, updated_at
        FROM categories
        WHERE 1=1
    """
    params = []

    if is_active is not None:
        query += " AND is_active = %s"
        params.append(is_active)

    if search:
        query += " AND (LOWER(name) LIKE LOWER(%s) OR LOWER(description) LIKE LOWER(%s))"
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    query += " ORDER BY name"

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return [Category(**row) for row in rows]


def create_category(name: str, description: Optional[str] = None,
                    color: Optional[str] = None, is_active: bool = True) -> int:
    """!>740BL =>2CN :0B53>@8N (?@>AB0O 25@A8O)"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO categories (name, description, color, is_active)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (name, description, color, is_active))
            row = cur.fetchone()
            conn.commit()
            return row["id"]


def update_category(category_id: int, name: Optional[str] = None,
                    description: Optional[str] = None, color: Optional[str] = None,
                    is_active: Optional[bool] = None) -> bool:
    """1=>28BL :0B53>@8N (?@>AB0O 25@A8O)"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            fields = []
            params = []

            if name is not None:
                fields.append("name = %s")
                params.append(name)

            if description is not None:
                fields.append("description = %s")
                params.append(description)

            if color is not None:
                fields.append("color = %s")
                params.append(color)

            if is_active is not None:
                fields.append("is_active = %s")
                params.append(is_active)

            if not fields:
                return False

            fields.append("updated_at = NOW()")
            params.append(category_id)

            query = f"UPDATE categories SET {', '.join(fields)} WHERE id = %s"
            cur.execute(query, params)
            conn.commit()
            return cur.rowcount > 0


def delete_category(category_id: int) -> bool:
    """#40;8BL :0B53>@8N (<O3:>5 C40;5=85)"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE categories 
                SET is_active = FALSE, updated_at = NOW()
                WHERE id = %s
            """, (category_id,))
            conn.commit()
            return cur.rowcount > 0


def get_categories_with_stats() -> List[Dict]:
    """>;CG8BL :0B53>@88 A> AB0B8AB8:>9 ?> ?>4:;NG5=8O<"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    c.id,
                    c.name,
                    c.description,
                    c.color,
                    c.is_active,
                    c.created_at,
                    c.updated_at,
                    COUNT(i.id) as connection_count
                FROM categories c
                LEFT JOIN iiko_connections i ON c.id = i.category_id
                GROUP BY c.id, c.name, c.description, c.color, c.is_active, 
                         c.created_at, c.updated_at
                ORDER BY c.name
            """)
            rows = cur.fetchall()
            return rows


# --- Iiko Connections ---

def get_iiko_connection(conn_id: int) -> Optional[IikoConnection]:
    """>;CG8BL ?>4:;NG5=85 iiko ?> ID"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM iiko_connections WHERE id = %s", (conn_id,))
            row = cur.fetchone()
            if row:
                # A;8 5ABL category_id, 703@C605< :0B53>@8N
                category = None
                if row.get('category_id'):
                    category = get_category_by_id(row['category_id'])

                return IikoConnection(
                    id=row['id'],
                    name=row['name'],
                    api_url=row['api_url'],
                    login=row['login'],
                    password=row['password'],
                    currency=row.get('currency', 'RUB'),
                    category_id=row.get('category_id'),
                    category=category,
                    iiko_cloud_api_key=row.get('iiko_cloud_api_key'),
                    load_weather=row.get('load_weather', False),
                    created_at=row['created_at']
                )
            return None


def list_iiko_connections(category_id: Optional[int] = None) -> List[IikoConnection]:
    """>;CG8BL A?8A>: ?>4:;NG5=89 iiko A D8;LB@0F859 ?> :0B53>@88"""
    query = """
        SELECT i.*, 
               c.id as cat_id, c.name as cat_name, c.description as cat_description,
               c.color as cat_color, c.is_active as cat_is_active,
               c.created_at as cat_created_at, c.updated_at as cat_updated_at
        FROM iiko_connections i
        LEFT JOIN categories c ON i.category_id = c.id
        WHERE 1=1
    """
    params = []

    if category_id is not None:
        query += " AND i.category_id = %s"
        params.append(category_id)

    query += " ORDER BY i.name"

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            connections = []
            for row in rows:
                # !>7405< >1J5:B Category 5A;8 5ABL :0B53>@8O
                category = None
                if row['cat_id']:
                    category = Category(
                        id=row['cat_id'],
                        name=row['cat_name'],
                        description=row['cat_description'],
                        color=row['cat_color'],
                        is_active=row['cat_is_active'],
                        created_at=row['cat_created_at'],
                        updated_at=row['cat_updated_at']
                    )

                connection = IikoConnection(
                    id=row['id'],
                    name=row['name'],
                    api_url=row['api_url'],
                    login=row['login'],
                    password=row['password'],
                    currency=row.get('currency', 'RUB'),
                    category_id=row['category_id'],
                    category=category,
                    iiko_cloud_api_key=row.get('iiko_cloud_api_key'),
                    load_weather=row.get('load_weather', False),
                    created_at=row['created_at']
                )
                connections.append(connection)
            return connections


def create_iiko_connection(name: str, api_url: str, login: str, password: str,
                           currency: str = 'RUB',
                           category_id: Optional[int] = None,
                           iiko_cloud_api_key: Optional[str] = None,
                           load_weather: bool = False) -> int:
    """Создать подключение iiko"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO iiko_connections
                    (name, api_url, login, password, currency, category_id,
                     iiko_cloud_api_key, load_weather)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (name, api_url, login, password, currency.upper(), category_id,
                  iiko_cloud_api_key or None, load_weather))
            row = cur.fetchone()
            conn.commit()
            return row["id"]


def update_iiko_connection(conn_id: int, name: str, api_url: str, login: str,
                           password: str, currency: str = 'RUB',
                           category_id: Optional[int] = None,
                           iiko_cloud_api_key: Optional[str] = None,
                           load_weather: bool = False) -> None:
    """Обновить подключение iiko"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE iiko_connections
                SET name = %s, api_url = %s, login = %s, password = %s,
                    currency = %s, category_id = %s,
                    iiko_cloud_api_key = %s, load_weather = %s
                WHERE id = %s
            """, (name, api_url, login, password, currency.upper(), category_id,
                  iiko_cloud_api_key or None, load_weather, conn_id))
            conn.commit()

def update_iiko_connection_category(conn_id: int, category_id: Optional[int] = None) -> bool:
    """1=>28BL B>;L:> :0B53>@8N ?>4:;NG5=8O iiko"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE iiko_connections 
                SET category_id = %s 
                WHERE id = %s
            """, (category_id, conn_id))
            conn.commit()
            return cur.rowcount > 0


# --- Tasks ---

def get_task_by_id(task_id: UUID) -> Optional[Task]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, iiko_connection_id, clickhouse_connection_id,
                       report_template_id, dataset_name, days_offset_start,
                       days_offset_end, is_active, created_at, updated_at
                FROM tasks
                WHERE id = %s
            """, (str(task_id),))
            row = cur.fetchone()
            return Task(**row) if row else None


def update_clickhouse_connection(
        conn_id: int,
        name: str,
        host: str,
        port: int,
        user: str,
        password: str,
        storage_policy: str
) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE clickhouse_connections
                SET name = %s, host = %s, port = %s, "user" = %s, password = %s, storage_policy = %s
                WHERE id = %s
            """, (name, host, port, user, password, storage_policy, conn_id))
            conn.commit()


def list_tasks(
        iiko_name: str = None,
        report_name: str = None,
        is_active: bool = None,
        category_id: Optional[int] = None
) -> List[Task]:
    """>;CG8BL 7040G8 A D8;LB@0F859 ?> :0B53>@88"""
    filters = []
    params = []

    if iiko_name is not None:
        filters.append("i.name = %s")
        params.append(iiko_name)

    if report_name is not None:
        filters.append("rt.name = %s")
        params.append(report_name)

    if is_active is not None:
        filters.append("t.is_active = %s")
        params.append(is_active)

    if category_id is not None:
        filters.append("i.category_id = %s")
        params.append(category_id)

    where_clause = " AND ".join(filters) if filters else "TRUE"

    query = f"""
        SELECT t.id, t.name, t.iiko_connection_id, t.clickhouse_connection_id,
               t.report_template_id, t.dataset_name, t.days_offset_start,
               t.days_offset_end, t.is_active, t.created_at, t.updated_at
        FROM tasks t
        JOIN iiko_connections i ON t.iiko_connection_id = i.id
        JOIN report_templates rt ON t.report_template_id = rt.id
        WHERE {where_clause}
        ORDER BY t.name
    """

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return [Task(**row) for row in rows]


def get_tasks_with_details(
        category_id: Optional[int] = None,
        is_active: Optional[bool] = None
) -> List[Task]:
    """>;CG8BL 7040G8 A ?>;=>9 8=D>@<0F859 > A2O70==KE >1J5:B0E"""
    filters = []
    params = []

    if category_id is not None:
        filters.append("i.category_id = %s")
        params.append(category_id)

    if is_active is not None:
        filters.append("t.is_active = %s")
        params.append(is_active)

    where_clause = " AND ".join(filters) if filters else "TRUE"

    query = f"""
        SELECT 
            t.id, t.name, t.iiko_connection_id, t.clickhouse_connection_id,
            t.report_template_id, t.dataset_name, t.days_offset_start,
            t.days_offset_end, t.is_active, t.created_at, t.updated_at,
            i.name as iiko_name, i.api_url, i.login, i.password, i.currency as iiko_currency, i.category_id,
            i.created_at as iiko_created_at,
            c.name as ch_name, c.host, c.port, c.user, c.password as ch_password,
            c.storage_policy, c.created_at as ch_created_at,
            rt.name as template_name, rt.default_report_config,
            rt.created_at as template_created_at,
            cat.id as cat_id, cat.name as cat_name, cat.description as cat_description,
            cat.color as cat_color, cat.is_active as cat_is_active,
            cat.created_at as cat_created_at, cat.updated_at as cat_updated_at
        FROM tasks t
        JOIN iiko_connections i ON t.iiko_connection_id = i.id
        JOIN clickhouse_connections c ON t.clickhouse_connection_id = c.id
        JOIN report_templates rt ON t.report_template_id = rt.id
        LEFT JOIN categories cat ON i.category_id = cat.id
        WHERE {where_clause}
        ORDER BY t.name
    """

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            tasks = []
            for row in rows:
                # !>7405< A2O70==K5 >1J5:BK
                category = None
                if row['cat_id']:
                    category = Category(
                        id=row['cat_id'],
                        name=row['cat_name'],
                        description=row['cat_description'],
                        color=row['cat_color'],
                        is_active=row['cat_is_active'],
                        created_at=row['cat_created_at'],
                        updated_at=row['cat_updated_at']
                    )

                iiko_connection = IikoConnection(
                    id=row['iiko_connection_id'],
                    name=row['iiko_name'],
                    api_url=row['api_url'],
                    login=row['login'],
                    password=row['password'],
                    currency=row.get('iiko_currency', 'RUB'),
                    category_id=row['category_id'],
                    category=category,
                    created_at=row['iiko_created_at']
                )

                clickhouse_connection = ClickHouseConnection(
                    id=row['clickhouse_connection_id'],
                    name=row['ch_name'],
                    host=row['host'],
                    port=row['port'],
                    user=row['user'],
                    password=row['ch_password'],
                    storage_policy=row['storage_policy'],
                    created_at=row['ch_created_at']
                )

                report_template = ReportTemplate(
                    id=row['report_template_id'],
                    name=row['template_name'],
                    default_report_config=row['default_report_config'],
                    created_at=row['template_created_at']
                )

                task = Task(
                    id=row['id'],
                    name=row['name'],
                    iiko_connection_id=row['iiko_connection_id'],
                    clickhouse_connection_id=row['clickhouse_connection_id'],
                    report_template_id=row['report_template_id'],
                    dataset_name=row['dataset_name'],
                    days_offset_start=row['days_offset_start'],
                    days_offset_end=row['days_offset_end'],
                    is_active=row['is_active'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    iiko_connection=iiko_connection,
                    clickhouse_connection=clickhouse_connection,
                    report_template=report_template
                )
                tasks.append(task)

            return tasks


def create_task(
        name: str,
        iiko_connection_id: int,
        clickhouse_connection_id: int,
        report_template_id: int,
        dataset_name: str,
        days_offset_start: int,
        days_offset_end: int,
        is_active: bool
) -> UUID:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tasks (
                    name, iiko_connection_id, clickhouse_connection_id,
                    report_template_id, dataset_name, days_offset_start,
                    days_offset_end, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                name,
                iiko_connection_id,
                clickhouse_connection_id,
                report_template_id,
                dataset_name,
                days_offset_start,
                days_offset_end,
                is_active
            ))
            row = cur.fetchone()
            conn.commit()
            return UUID(row["id"])


# --- ClickHouse Connections ---

def get_clickhouse_connection(conn_id: int) -> Optional[ClickHouseConnection]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clickhouse_connections WHERE id = %s", (conn_id,))
            row = cur.fetchone()
            return ClickHouseConnection(**row) if row else None


def list_clickhouse_connections() -> List[ClickHouseConnection]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clickhouse_connections ORDER BY name")
            rows = cur.fetchall()
            return [ClickHouseConnection(**row) for row in rows]


def create_clickhouse_connection(
        name: str,
        host: str,
        port: int,
        user: str,
        password: str,
        storage_policy: str
) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clickhouse_connections (
                    name, host, port, "user", password, storage_policy
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (name, host, port, user, password, storage_policy))
            row = cur.fetchone()
            conn.commit()
            return row["id"]


# --- Report Templates ---

def get_report_template(template_id: int) -> Optional[ReportTemplate]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM report_templates WHERE id = %s", (template_id,))
            row = cur.fetchone()
            return ReportTemplate(**row) if row else None


def list_report_templates() -> List[ReportTemplate]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM report_templates ORDER BY name")
            rows = cur.fetchall()
            return [ReportTemplate(**row) for row in rows]


def create_report_template(name: str, default_report_config: dict) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # @5>1@07C5< dict � JSON string
            config_json = json.dumps(default_report_config, ensure_ascii=False)
            cur.execute("""
                INSERT INTO report_templates (name, default_report_config)
                VALUES (%s, %s)
                RETURNING id
            """, (name, config_json))
            row = cur.fetchone()
            conn.commit()
            return row["id"]


def update_task(
        task_id: UUID,
        name: str,
        iiko_connection_id: int,
        clickhouse_connection_id: int,
        report_template_id: int,
        dataset_name: str,
        days_offset_start: int,
        days_offset_end: int,
        is_active: bool
) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tasks
                SET name = %s,
                    iiko_connection_id = %s,
                    clickhouse_connection_id = %s,
                    report_template_id = %s,
                    dataset_name = %s,
                    days_offset_start = %s,
                    days_offset_end = %s,
                    is_active = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (
                name,
                iiko_connection_id,
                clickhouse_connection_id,
                report_template_id,
                dataset_name,
                days_offset_start,
                days_offset_end,
                is_active,
                str(task_id)
            ))
            conn.commit()


# --- Bulk Operations ---

def bulk_update_tasks_by_filter(
        iiko_name: str = None,
        report_name: str = None,
        is_active: bool = None,
        days_offset_start: int = 14,
        days_offset_end: int = 0
) -> int:
    filters = []
    params = [days_offset_start, days_offset_end]

    if iiko_name is not None:
        filters.append("i.name = %s")
        params.append(iiko_name)

    if report_name is not None:
        filters.append("rt.name = %s")
        params.append(report_name)

    if is_active is not None:
        filters.append("t.is_active = %s")
        params.append(is_active)

    where_clause = " AND ".join(filters) if filters else "TRUE"

    query = f"""
        UPDATE tasks t
        SET 
            days_offset_start = %s,
            days_offset_end = %s,
            updated_at = NOW()
        FROM iiko_connections i, report_templates rt
        WHERE t.iiko_connection_id = i.id
          AND t.report_template_id = rt.id
          AND {where_clause}
        RETURNING t.id
    """

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            updated = cur.fetchall()
            conn.commit()
            return len(updated)


# --- Weather ---

def list_connections_for_weather() -> List[IikoConnection]:
    """Вернуть подключения iiko с включённой загрузкой погоды и заполненным API-ключом"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT i.*,
                       c.id as cat_id, c.name as cat_name, c.description as cat_description,
                       c.color as cat_color, c.is_active as cat_is_active,
                       c.created_at as cat_created_at, c.updated_at as cat_updated_at
                FROM iiko_connections i
                LEFT JOIN categories c ON i.category_id = c.id
                WHERE i.load_weather = TRUE
                  AND i.iiko_cloud_api_key IS NOT NULL
                  AND i.iiko_cloud_api_key != ''
                ORDER BY i.name
            """)
            rows = cur.fetchall()
            connections = []
            for row in rows:
                category = None
                if row['cat_id']:
                    category = Category(
                        id=row['cat_id'],
                        name=row['cat_name'],
                        description=row['cat_description'],
                        color=row['cat_color'],
                        is_active=row['cat_is_active'],
                        created_at=row['cat_created_at'],
                        updated_at=row['cat_updated_at']
                    )
                connections.append(IikoConnection(
                    id=row['id'],
                    name=row['name'],
                    api_url=row['api_url'],
                    login=row['login'],
                    password=row['password'],
                    currency=row.get('currency', 'RUB'),
                    category_id=row['category_id'],
                    category=category,
                    iiko_cloud_api_key=row.get('iiko_cloud_api_key'),
                    load_weather=row.get('load_weather', False),
                    created_at=row['created_at']
                ))
            return connections
            return len(updated)