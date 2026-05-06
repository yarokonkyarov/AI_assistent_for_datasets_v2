# core/dataset_manager.py
import hashlib
import http.client
import json
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from clickhouse_driver import Client

from core.currency_converter import CurrencyConverter

logger = logging.getLogger(__name__)


def parse_dataset_name(dataset_name: str) -> Tuple[str, str]:
    """Парсинг имени датасета на базу данных и таблицу"""
    if '.' not in dataset_name:
        raise ValueError("Dataset name must be in format 'database.table'")
    return tuple(dataset_name.split('.', 1))


class IikoOlapDatasetManager:
    def __init__(self, config_dict: Dict):
        """
        Инициализация без файлов.
        Ожидает:
        - config_dict['iiko'] = {api_url, login, password}
        - config_dict['clickhouse'] = {host, port, user, password, storage_policy}
        - config_dict['report_template'] = {...}  # как в default_report_config
        - config_dict['dataset_name'] = "myata.pl1"
        - config_dict['date_from'] = date(...)
        - config_dict['date_to'] = date(...)
        """
        self.config = config_dict

        # iiko
        self.iiko_api_url = config_dict["iiko"]["api_url"]
        if not self.iiko_api_url.startswith(('http://', 'https://')):
            self.iiko_api_url = f"http://{self.iiko_api_url}"

        parsed_url = urlparse(self.iiko_api_url)
        self.iiko_scheme = parsed_url.scheme
        self.iiko_host = parsed_url.hostname
        self.iiko_port = parsed_url.port or (443 if self.iiko_scheme == 'https' else 80)
        self.iiko_base_path = parsed_url.path or '/'

        logger.info(
            f"Using iiko API endpoint: {self.iiko_scheme}://{self.iiko_host}:{self.iiko_port}{self.iiko_base_path}"
        )

        # ClickHouse
        self.ch_client = self._init_clickhouse()
        self.iiko_key = None

        # Отчёты
        self.report_template = config_dict["report_template"]
        self.dataset_name = config_dict["dataset_name"]
        self.date_from = config_dict["date_from"]
        self.date_to = config_dict["date_to"]

        # Конвертация валют
        cc = config_dict.get('currency_conversion', {})
        self.currency_conversion_enabled: bool = cc.get('enabled', True)
        # Фиксированная валюта подключения (из таблицы iiko_connections).
        # Если задана — используется для всех строк чанка.
        # Если None — читается из поля Currencies_Currency каждой строки.
        self.connection_currency: Optional[str] = cc.get('connection_currency') or None
        # Поле с кодом валюты в строке (fallback, если connection_currency не задана)
        self.currency_field: str = cc.get('currency_field', 'Currencies_Currency')
        # БД и таблица курсов
        self.rates_db: str = cc.get('rates_db', 'currency_db')
        self.rates_table: str = cc.get('rates_table', 'currency_rates')

    def _init_clickhouse(self) -> Client:
        ch = self.config["clickhouse"]
        return Client(
            host=ch["host"],
            port=ch["port"],
            user=ch["user"],
            password=ch["password"]
        )

    def _get_storage_policy(self) -> str:
        return self.config["clickhouse"].get("storage_policy", "default")

    def _get_http_connection(self):
        if self.iiko_scheme == 'https':
            return http.client.HTTPSConnection(self.iiko_host, self.iiko_port, timeout=6000)
        else:
            return http.client.HTTPConnection(self.iiko_host, self.iiko_port, timeout=6000)

    def _authenticate_iiko(self) -> Optional[bytes]:
        conn = None
        try:
            logger.info(f"Authenticating with iiko API at: {self.iiko_scheme}://{self.iiko_host}:{self.iiko_port}")
            conn = self._get_http_connection()
            pass_hash = hashlib.sha1(self.config["iiko"]["password"].encode()).hexdigest()
            auth_url = f"{self.iiko_base_path}resto/api/auth?login={self.config['iiko']['login']}&pass={pass_hash}"
            conn.request("GET", auth_url)
            res = conn.getresponse()
            if res.status == 200:
                key = res.read()
                logger.info("Successfully authenticated with iiko API")
                return key
            logger.error(f"iiko auth failed: {res.status}")
            return None
        except Exception as e:
            logger.error(f"iiko auth error: {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()

    def _logout_iiko(self, key: str) -> bool:
        try:
            logout_url = f'{self.iiko_base_path}resto/api/logout?key={key}'
            conn = self._get_http_connection()
            conn.request("GET", logout_url)
            res = conn.getresponse()
            success = res.status == 200
            if success:
                logger.info("Successfully logged out from iiko API")
            else:
                logger.warning(f"Logout failed: {res.status}")
            return success
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return False
        finally:
            conn.close()

    def _get_date_field_mapping(self, report_type: str) -> Dict[str, str]:
        return {
            'SALES': {'api_field': 'OpenDate.Typed', 'db_field': 'OpenDate_Typed'},
            'TRANSACTIONS': {'api_field': 'DateTime.DateTyped', 'db_field': 'DateTime_DateTyped'}
        }.get(report_type, {})

    def _convert_field_names(self, data: List[Dict], table_columns: List[str]) -> List[Dict]:
        converted_data = []
        for item in data:
            converted_item = {}
            for key, value in item.items():
                new_key = key.replace('.', '_').replace('-', '_')
                if new_key in table_columns:
                    converted_item[new_key] = value
            converted_item['url'] = self.iiko_api_url
            if converted_item:
                converted_data.append(converted_item)
        return converted_data

    def _convert_field_types(self, data: List[Dict], table_columns_info: List[Tuple]) -> List[Dict]:
        column_types = {col[0]: col[1] for col in table_columns_info}
        for item in data:
            for field_name, value in item.items():
                field_type = column_types.get(field_name, '')
                if value is None or value == '':
                    item[field_name] = None
                    continue
                try:
                    if any(t in field_type for t in ['Float', 'Int', 'Decimal']):
                        if isinstance(value, str):
                            value = value.replace(' ', '').replace(',', '.')
                            item[field_name] = float(value) if value else None
                        else:
                            item[field_name] = float(value)
                    elif 'DateTime' in field_type:
                        if isinstance(value, str):
                            fmt = '%Y-%m-%dT%H:%M:%S.%f' if '.' in value else '%Y-%m-%dT%H:%M:%S'
                            item[field_name] = datetime.strptime(value, fmt)
                        elif isinstance(value, datetime):
                            pass
                    elif 'Date' in field_type:
                        if isinstance(value, str):
                            if 'T' in value:
                                item[field_name] = datetime.strptime(value.split('T')[0], '%Y-%m-%d').date()
                            else:
                                item[field_name] = datetime.strptime(value, '%Y-%m-%d').date()
                        elif isinstance(value, datetime):
                            item[field_name] = value.date()
                        elif isinstance(value, date):
                            pass
                except (ValueError, AttributeError) as e:
                    logger.warning(f"Failed to convert field {field_name}: {e}")
                    item[field_name] = None
        return data

    def _fetch_iiko_olap_data(self, date_from: date, date_to: date) -> Optional[List[Dict]]:
        """Запрос OLAP-данных. Используется внутренний self.report_template"""
        conn = None
        try:
            if not self.iiko_key:
                self.iiko_key = self._authenticate_iiko()
                if not self.iiko_key:
                    raise ValueError("Authentication failed")

            report_type = self.report_template.get("reportType", "SALES")
            field_mapping = self._get_date_field_mapping(report_type)
            if not field_mapping:
                raise ValueError(f"Unsupported report type: {report_type}")

            config = self.report_template.copy()
            if 'filters' not in config:
                config['filters'] = {}

            config['filters'][field_mapping['api_field']] = {
                "filterType": "DateRange",
                "periodType": "CUSTOM",
                "from": str(date_from),
                "to": str(date_to + timedelta(days=1))
            }

            headers = {"Content-Type": "application/json"}
            conn = self._get_http_connection()
            request_url = f'{self.iiko_base_path}resto/api/v2/reports/olap?key={self.iiko_key.decode()}'
            conn.request("POST", request_url, json.dumps(config, ensure_ascii=False), headers)
            res = conn.getresponse()
            data = res.read().decode('utf-8')

            if res.status != 200:
                raise ValueError(f"API error {res.status}: {data}")
            logger.info("OLAP data fetched successfully")
            return json.loads(data)['data']

        except Exception as e:
            logger.error(f"Fetch error: {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()
            if self.iiko_key:
                self._logout_iiko(self.iiko_key.decode())
                self.iiko_key = None

    # ──────────────────────────────────────────────
    # Конвертация валют
    # ──────────────────────────────────────────────

    def _ensure_rub_columns(self, db: str, table: str, rub_columns: List[str]) -> None:
        """
        Добавляет недостающие *_RUB колонки в существующую таблицу через ALTER TABLE.
        Безопасно повторять: колонки уже существующие пропускаются.
        """
        try:
            existing = {
                row[0]
                for row in self.ch_client.execute(f"DESCRIBE TABLE {db}.{table}")
            }
        except Exception as e:
            logger.error(f"Не удалось прочитать схему {db}.{table}: {e}")
            return

        for col in rub_columns:
            if col not in existing:
                try:
                    self.ch_client.execute(
                        f"ALTER TABLE {db}.{table} "
                        f"ADD COLUMN IF NOT EXISTS `{col}` Nullable(Float32)"
                    )
                    logger.info(f"Добавлена колонка {col} в {db}.{table}")
                except Exception as e:
                    logger.error(f"Не удалось добавить колонку {col}: {e}")

    def _get_rub_field_pairs(self, table_columns: List[str]) -> List[Tuple[str, str]]:
        """
        Возвращает пары (исходное_поле, поле_RUB) для полей,
        которые есть в таблице и для которых создана RUB-колонка.
        """
        pairs = []
        for field in self.report_template.get("aggregateFields", []):
            name = field.replace('.', '_').replace('-', '_')
            rub_name = f"{name}_RUB"
            if name in table_columns and rub_name in table_columns:
                pairs.append((name, rub_name))
        return pairs

    def _apply_currency_conversion(
        self,
        data: List[Dict],
        converter: CurrencyConverter,
        date_field: str,
        rub_field_pairs: List[Tuple[str, str]],
    ) -> List[Dict]:
        """
        Добавляет RUB-поля в каждую строку.
        Конвертирует по курсу на дату из поля date_field.
        Если курс не найден — пишет None (BI увидит пустое значение).
        """
        if not converter.is_available or not rub_field_pairs:
            # Заполняем RUB-поля None, чтобы INSERT прошёл без ошибок
            for row in data:
                for _, rub_field in rub_field_pairs:
                    row[rub_field] = None
            return data

        no_rate_count = 0
        for row in data:
            # Приоритет: фиксированная валюта подключения → поле в строке → RUB
            currency = (
                self.connection_currency
                or (row.get(self.currency_field) or 'RUB')
            ).strip()
            row_date = row.get(date_field)

            for src_field, rub_field in rub_field_pairs:
                converted = converter.convert(row.get(src_field), currency, row_date)
                row[rub_field] = converted
                if converted is None and row.get(src_field) is not None:
                    no_rate_count += 1

        if no_rate_count:
            logger.warning(
                f"{no_rate_count} значений не сконвертированы (нет курса)"
            )
        return data

    def dataset_exists(self, dataset_name: str) -> bool:
        try:
            db, table = parse_dataset_name(dataset_name)
            return self.ch_client.execute(f"EXISTS TABLE {db}.{table}")[0][0] == 1
        except Exception as e:
            logger.error(f"Check existence error: {e}")
            return False

    def create_dataset(self, fields_config: List[Dict]) -> bool:
        """Создаёт таблицу на основе списка полей (из генератора или маппинга)

        Оптимизации структуры:
        - PARTITION BY toYYYYMM(date_field): BI-запрос за месяц читает 1/N партиций
          вместо полного скана всей таблицы.
        - ORDER BY (date, Department, ...): первичный индекс → чтение тысяч строк
          вместо миллионов при фильтрации по дате + подразделению.
        """
        try:
            db, table = parse_dataset_name(self.dataset_name)
            self.ch_client.execute(f"CREATE DATABASE IF NOT EXISTS {db}")

            # Добавляем url, если нет
            if not any(f["name"] == "url" for f in fields_config):
                fields_config.append({"name": "url", "type": "LowCardinality(String)", "nullable": False})

            fields_sql = []
            for field in fields_config:
                sql_type = field["type"]
                fields_sql.append(f"`{field['name']}` {sql_type}")

            # ── Определяем дату и ключ сортировки ─────────────────────────
            report_type = self.report_template.get("reportType", "SALES")
            field_mapping = self._get_date_field_mapping(report_type) or {}
            date_field = field_mapping.get('db_field', '')
            field_names = {f['name'] for f in fields_config}

            # PARTITION BY — по месяцам, позволяет пропускать старые партиции
            if date_field and date_field in field_names:
                partition_sql = f"PARTITION BY toYYYYMM({date_field})"
            else:
                partition_sql = ""

            # ORDER BY — предпочтительные ключи по типу отчёта
            # Порядок важен: сначала дата (позволяет пропускать гранулы),
            # затем измерения с высокой селективностью
            ORDER_BY_CANDIDATES = {
                'SALES':        ['OpenDate_Typed', 'Department', 'DishGroup', 'DishId'],
                'TRANSACTIONS': ['DateTime_DateTyped', 'Department', 'TransactionType'],
            }
            preferred_keys = ORDER_BY_CANDIDATES.get(report_type, [date_field] if date_field else [])
            order_cols = [col for col in preferred_keys if col in field_names]

            # ClickHouse запрещает Nullable-колонки в ORDER BY.
            # Принудительно снимаем Nullable() с полей, попавших в ключ сортировки.
            if order_cols:
                for field in fields_config:
                    if field['name'] in order_cols and field['type'].startswith('Nullable('):
                        field['type'] = field['type'][len('Nullable('):-1]
                        field['nullable'] = False
                # Пересобираем fields_sql после возможных изменений типов
                fields_sql = [f"`{f['name']}` {f['type']}" for f in fields_config]
                order_sql = f"ORDER BY ({', '.join(order_cols)})"
            else:
                order_sql = "ORDER BY tuple()"
                logger.warning(
                    f"Таблица {db}.{table} создаётся без первичного индекса (ORDER BY tuple()). "
                    "Рекомендуется вручную добавить ключевые колонки в ORDER BY."
                )
            # ──────────────────────────────────────────────────────────────

            storage_policy = self._get_storage_policy()
            parts = [
                f"CREATE TABLE IF NOT EXISTS {db}.{table} (\n"
                f"    {',    '.join(fields_sql)}\n"
                f") ENGINE = MergeTree()",
            ]
            if partition_sql:
                parts.append(partition_sql)
            parts.append(order_sql)
            parts.append(f"SETTINGS storage_policy = '{storage_policy}'")
            create_sql = "\n".join(parts)

            logger.info(f"Creating table:\n{create_sql}")
            self.ch_client.execute(create_sql)
            logger.info(f"Dataset {self.dataset_name} created")
            return True
        except Exception as e:
            logger.error(f"Create error: {e}", exc_info=True)
            return False

    def update_dataset(self, chunk_days: int = 7, batch_size: int = 50000) -> bool:
        """
        Основной метод обновления.
        Все параметры — из self.config.
        Поддерживает chunking, обработку ошибок, удаление по URL.
        """
        try:
            logger.info(f"Starting update for {self.dataset_name} from {self.date_from} to {self.date_to}")

            if not self.dataset_exists(self.dataset_name):
                logger.error("Dataset does not exist")
                return False

            report_type = self.report_template.get("reportType", "SALES")
            field_mapping = self._get_date_field_mapping(report_type)
            if not field_mapping:
                logger.error(f"Unsupported report type: {report_type}")
                return False

            db, table = parse_dataset_name(self.dataset_name)
            desc_sql = f"DESCRIBE TABLE {db}.{table}"
            table_columns_info = self.ch_client.execute(desc_sql)
            table_columns = [col[0] for col in table_columns_info]
            column_types = {col[0]: col[1] for col in table_columns_info}

            if field_mapping['db_field'] not in table_columns:
                logger.error(f"Date field {field_mapping['db_field']} missing")
                return False

            # ── Инициализация конвертера валют ─────────────────────────────
            converter: Optional[CurrencyConverter] = None
            rub_field_pairs: List[Tuple[str, str]] = []

            if self.currency_conversion_enabled:
                # Вычисляем имена RUB-колонок из шаблона
                rub_columns = [
                    f"{f.replace('.', '_').replace('-', '_')}_RUB"
                    for f in self.report_template.get("aggregateFields", [])
                ]
                if rub_columns:
                    # Добавляем недостающие колонки в таблицу
                    self._ensure_rub_columns(db, table, rub_columns)
                    # Обновляем схему после ALTER TABLE
                    table_columns_info = self.ch_client.execute(desc_sql)
                    table_columns = [col[0] for col in table_columns_info]
                    column_types = {col[0]: col[1] for col in table_columns_info}

                    rub_field_pairs = self._get_rub_field_pairs(table_columns)
                    if rub_field_pairs:
                        converter = CurrencyConverter(
                            self.ch_client, self.rates_db, self.rates_table
                        )
                        logger.info(
                            f"Конвертация валют включена для полей: "
                            f"{[p[0] for p in rub_field_pairs]}"
                        )
                    else:
                        logger.warning(
                            "Конвертация валют: не найдены пары полей "
                            "(исходное + _RUB) в таблице"
                        )
            # ──────────────────────────────────────────────────────────────

            current_date = self.date_from
            total_inserted = 0
            problem_records = []

            while current_date <= self.date_to:
                chunk_end = min(current_date + timedelta(days=chunk_days - 1), self.date_to)
                logger.info(f"Processing chunk: {current_date} – {chunk_end}")

                data = self._fetch_iiko_olap_data(current_date, chunk_end)
                if not data:
                    current_date = chunk_end + timedelta(days=1)
                    continue

                converted_data = self._convert_field_names(data, table_columns)
                if not converted_data:
                    current_date = chunk_end + timedelta(days=1)
                    continue

                converted_data = self._convert_field_types(converted_data, table_columns_info)

                # ── Конвертация валют в рубли ──────────────────────────────
                if converter is not None and rub_field_pairs:
                    converter.load_rates(current_date, chunk_end)
                    converted_data = self._apply_currency_conversion(
                        converted_data,
                        converter,
                        field_mapping['db_field'],
                        rub_field_pairs,
                    )
                # ──────────────────────────────────────────────────────────

                # 🔥 Ключевое: удаление с фильтром по URL
                # mutations_sync=1 — ждём ПРИМЕНЕНИЯ мутации перед INSERT.
                # Без этого DELETE асинхронный: старые строки остаются, новые уже вставлены
                # → дубли в таблице и половина строк без обновлённых полей (Department_Id и др.)
                delete_sql = f"""
                ALTER TABLE {db}.{table}
                DELETE WHERE {field_mapping['db_field']} BETWEEN %(from)s AND %(to)s
                AND url = %(url)s
                SETTINGS mutations_sync = 1
                """
                self.ch_client.execute(delete_sql, {
                    'from': current_date.strftime('%Y-%m-%d'),
                    'to': chunk_end.strftime('%Y-%m-%d'),
                    'url': self.iiko_api_url
                })
                logger.info(f"DELETE mutation applied for {current_date} – {chunk_end}")

                if converted_data:
                    columns = list(converted_data[0].keys())
                    insert_sql = f"INSERT INTO {db}.{table} ({', '.join(columns)}) VALUES"
                    string_columns = [col for col, typ in column_types.items() if 'String' in typ]

                    for i in range(0, len(converted_data), batch_size):
                        batch = converted_data[i:i + batch_size]
                        processed_batch = []
                        for rec in batch:
                            rec = rec.copy()
                            for col in string_columns:
                                if rec.get(col) is None:
                                    rec[col] = 'не задана'
                            processed_batch.append(rec)

                        try:
                            self.ch_client.execute(insert_sql, processed_batch, types_check=True)
                            total_inserted += len(processed_batch)
                        except Exception as e:
                            logger.error(f"Batch error: {e}")
                            # fallback to row-by-row
                            for rec in processed_batch:
                                try:
                                    self.ch_client.execute(insert_sql, [rec], types_check=True)
                                    total_inserted += 1
                                except Exception as err:
                                    problem_records.append({
                                        'error': str(err),
                                        'record': rec,
                                        'chunk': f"{current_date} – {chunk_end}"
                                    })

                current_date = chunk_end + timedelta(days=1)

            if problem_records:
                import os
                fname = f"problems_{self.dataset_name.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(problem_records, f, indent=2, ensure_ascii=False, default=str)
                logger.error(f"Saved {len(problem_records)} problem records to {fname}")

            logger.info(f"✅ Total inserted: {total_inserted}")
            return total_inserted > 0

        except Exception as e:
            logger.error(f"Update failed: {e}", exc_info=True)
            return False

    def generate_fields_config(self) -> List[Dict]:
        """
        Генерирует схему полей на основе self.report_template.
        Используется при создании таблицы.

        Оптимизации типов:
        - LowCardinality(String) для полей с малым числом уникальных значений
          (департаменты, группы блюд, типы транзакций и т.д.)
        - Float32 вместо Float64 для агрегатных полей — вдвое меньше RAM/диска
        - Nullable только там, где значение реально может отсутствовать
        """
        report_type = self.report_template.get("reportType", "SALES")
        field_mapping = self._get_date_field_mapping(report_type)
        if not field_mapping:
            raise ValueError(f"Unsupported report type: {report_type}")

        # Поля, которые НИКОГДА не NULL и не нуждаются в Nullable-обёртке
        NON_NULLABLE_FIELDS = {'DateTime_DateTyped', 'UniqOrderId_Id', 'OpenDate_Typed', 'url'}

        # Числовые group-by поля (Float32 достаточно — это счётчики/индексы)
        NUMERIC_FIELDS = {
            'OrderNum': 'Float32', 'HourClose': 'Float32', 'HourOpen': 'Float32',
            'TableNum': 'Float32', 'GuestNum': 'Float32',
        }

        # Строковые поля с малым числом уникальных значений → LowCardinality(String)
        # Ускоряет GROUP BY в 3–10x, экономит RAM.
        # LowCardinality не поддерживает Nullable напрямую: используем непустую строку-замену.
        LOW_CARDINALITY_FIELDS = {
            # Подразделения / юрлица
            'Department', 'Department_Id', 'Department_JurPerson', 'Department_Code',
            'Department_Category1', 'Department_Category2', 'Department_Category3',
            'Department_Category4', 'Department_Category5',
            # Категории и группы блюд
            'DishCategory', 'DishCategory_Id',
            'DishGroup', 'DishGroup_TopParent', 'DishGroup_SecondParent', 'DishGroup_ThirdParent',
            # Типы и статусы
            'DishType', 'DeletedWithWriteoff', 'OrderDeleted', 'CookingPlaceType',
            'OrderDiscount_Type', 'ItemSaleEventDiscountType',
            # Временны́е измерения
            'Mounth', 'YearOpen', 'DayOfWeekOpen',
            # Прочие низкомощностные поля продаж
            'JurName', 'Conception', 'Store_Name', 'Currencies_Currency',
            # Поля транзакций
            'Product_Type', 'TransactionType', 'Contr_Account_Group',
            'Contr_Product_TopParent', 'Contr_Product_SecondParent', 'Contr_Product_ThirdParent',
            'Product_MeasureUnit', 'Product_TopParent', 'Product_SecondParent', 'Product_ThirdParent',
            'Account_CounteragentType', 'Product_Category',
            # URL подключения — несколько десятков значений
            'url',
        }

        fields = []

        # groupByRowFields
        for field in self.report_template.get("groupByRowFields", []):
            name = field.replace('.', '_').replace('-', '_')

            if name in NUMERIC_FIELDS:
                # Числовой group-by: Float32, Nullable (может не прийти)
                fields.append({
                    "name": name,
                    "type": f"Nullable({NUMERIC_FIELDS[name]})",
                    "nullable": True
                })
            elif name == field_mapping['db_field']:
                # Поле даты — всегда NOT NULL
                ftype = 'Date' if report_type in ('SALES', 'TRANSACTIONS') else 'DateTime'
                fields.append({"name": name, "type": ftype, "nullable": False})
            elif name in LOW_CARDINALITY_FIELDS:
                # Строка с малым числом значений — LowCardinality, NOT NULL (пустая строка вместо NULL)
                fields.append({"name": name, "type": "LowCardinality(String)", "nullable": False})
            elif name in NON_NULLABLE_FIELDS:
                fields.append({"name": name, "type": "String", "nullable": False})
            else:
                # Прочие строки: Nullable
                fields.append({"name": name, "type": "Nullable(String)", "nullable": True})

        # aggregateFields → Nullable(Float32)   [было Float64 — вдвое меньше места]
        # + дублирующие *_RUB поля, если конвертация включена
        for field in self.report_template.get("aggregateFields", []):
            name = field.replace('.', '_').replace('-', '_')
            fields.append({
                "name": name,
                "type": "Nullable(Float32)",
                "nullable": True
            })
            if self.currency_conversion_enabled:
                fields.append({
                    "name": f"{name}_RUB",
                    "type": "Nullable(Float32)",
                    "nullable": True
                })

        # url
        fields.append({
            "name": "url",
            "type": "LowCardinality(String)",
            "nullable": False
        })

        return fields

    def generate_and_create(self) -> bool:
        """Генерирует поля и создаёт таблицу"""
        try:
            fields = self.generate_fields_config()
            return self.create_dataset(fields)
        except Exception as e:
            logger.error(f"Generate-and-create failed: {e}", exc_info=True)
            return False

    def get_dataset_info(self) -> Optional[Dict]:
        try:
            if not self.dataset_exists(self.dataset_name):
                return None
            db, table = parse_dataset_name(self.dataset_name)
            report_type = self.report_template.get("reportType", "SALES")
            date_field = self._get_date_field_mapping(report_type).get('db_field', 'OpenDate_Typed')
            row_count = self.ch_client.execute(f"SELECT count() FROM {db}.{table}")[0][0]
            min_d, max_d = self.ch_client.execute(
                f"SELECT min({date_field}), max({date_field}) FROM {db}.{table}"
            )[0]
            fields = self.ch_client.execute(f"DESCRIBE TABLE {db}.{table}")
            return {
                "name": self.dataset_name,
                "row_count": row_count,
                "date_range": {
                    "min": min_d.strftime('%Y-%m-%d') if min_d else None,
                    "max": max_d.strftime('%Y-%m-%d') if max_d else None
                },
                "fields": [{"name": f[0], "type": f[1]} for f in fields]
            }
        except Exception as e:
            logger.error(f"Info error: {e}")
            return None