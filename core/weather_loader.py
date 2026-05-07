# core/weather_loader.py
"""
Загрузка исторических данных о погоде из Open-Meteo API.

Алгоритм:
1. Выбирает все iiko_connections с load_weather=TRUE и iiko_cloud_api_key IS NOT NULL
2. Для каждого подключения получает список организаций (lat/lon) через iiko Cloud API
3. Дедуплицирует организации по городу (кластер ~5км)
4. Запрашивает погоду из Open-Meteo по уникальным координатам
5. Пишет результат в ClickHouse: weather_db.daily_weather
"""

import http.client
import hashlib
import json
import logging
import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

from clickhouse_driver import Client

logger = logging.getLogger(__name__)

# ─── Схема таблицы погоды ────────────────────────────────────────────────────

CREATE_WEATHER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS weather_db.daily_weather (
    date             Date,
    org_id           String,
    org_name         String,
    city_cluster     String,
    lat              Float64,
    lon              Float64,
    temp_avg         Nullable(Float64),
    temp_min         Nullable(Float64),
    temp_max         Nullable(Float64),
    precipitation_mm Nullable(Float64),
    cloud_cover_pct  Nullable(Float64),
    wind_speed_ms    Nullable(Float64),
    loaded_at        DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY (date, org_id)
"""

# ─── Схема справочника организаций ───────────────────────────────────────────

CREATE_ORGS_REF_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS weather_db.organizations_ref (
    org_id           String          COMMENT 'UUID организации из iiko Cloud',
    org_name         String          COMMENT 'Техническое название в iiko (К 1, К 2...)',
    org_code         String          COMMENT 'Короткий код заведения (999, 001...)',
    address          String          COMMENT 'Адрес ресторана',
    country          LowCardinality(String) COMMENT 'Страна',
    lat              Nullable(Float64) COMMENT 'Широта',
    lon              Nullable(Float64) COMMENT 'Долгота',
    inn              String          COMMENT 'ИНН юридического лица',
    currency         LowCardinality(String) COMMENT 'Код валюты (RUB, USD...)',
    delivery_type    LowCardinality(String) COMMENT 'CourierAndSelfService / SelfServiceOnly / NoDelivery',
    iiko_version     String          COMMENT 'Версия ПО iiko на момент синхронизации',
    api_key_hint     String          COMMENT 'Первые 8 символов API-ключа (для идентификации подключения)',
    synced_at        DateTime        DEFAULT now() COMMENT 'Время последней синхронизации'
) ENGINE = ReplacingMergeTree(synced_at)
ORDER BY org_id
COMMENT 'Справочник организаций iiko Cloud. Обновляется при каждой загрузке погоды.'
"""


# ─── iiko Cloud API ──────────────────────────────────────────────────────────

def get_iiko_cloud_token(api_key: str) -> Optional[str]:
    """Получить JWT-токен по API-ключу iiko Cloud"""
    try:
        conn = http.client.HTTPSConnection("api-ru.iiko.services", timeout=30)
        body = json.dumps({"apiLogin": api_key})
        conn.request("POST", "/api/1/access_token",
                     body, {"Content-Type": "application/json"})
        res = conn.getresponse()
        data = json.loads(res.read().decode())
        if res.status == 200 and "token" in data:
            return data["token"]
        logger.error(f"iiko Cloud auth failed: {res.status} {data}")
        return None
    except Exception as e:
        logger.error(f"iiko Cloud auth error: {e}")
        return None
    finally:
        conn.close()


def get_iiko_organizations(api_key: str) -> List[Dict]:
    """
    Возвращает список организаций со всеми полезными полями из iiko Cloud API.

    Каждый элемент содержит:
      id, name, code, address, country, lat, lon,
      inn, currency, delivery_type, iiko_version
    """
    token = get_iiko_cloud_token(api_key)
    if not token:
        return []

    try:
        conn = http.client.HTTPSConnection("api-ru.iiko.services", timeout=30)
        body = json.dumps({"returnAdditionalInfo": True, "includeDisabled": False})
        conn.request("POST", "/api/1/organizations", body,
                     {"Content-Type": "application/json",
                      "Authorization": f"Bearer {token}"})
        res = conn.getresponse()
        data = json.loads(res.read().decode())

        if res.status != 200:
            logger.error(f"organizations API error: {res.status}")
            return []

        result = []
        for org in data.get("organizations", []):
            lat = org.get("latitude")
            lon = org.get("longitude")

            # Координаты нужны для погоды — орги без них тоже попадают в справочник
            lat_val = float(lat) if lat and lat != 0 else None
            lon_val = float(lon) if lon and lon != 0 else None

            result.append({
                "id":            org["id"],
                "name":          org.get("name", "").strip(),
                "code":          str(org.get("code", "") or ""),
                "address":       (org.get("restaurantAddress") or "").strip(),
                "country":       (org.get("country") or "").strip(),
                "lat":           lat_val,
                "lon":           lon_val,
                "inn":           str(org.get("inn") or ""),
                "currency":      str(org.get("currencyIsoName") or "RUB"),
                "delivery_type": str(org.get("deliveryServiceType") or ""),
                "iiko_version":  str(org.get("version") or ""),
            })

        with_coords = sum(1 for o in result if o["lat"] is not None)
        logger.info(f"Got {len(result)} organizations ({with_coords} with coordinates)")
        return result
    except Exception as e:
        logger.error(f"get_organizations error: {e}")
        return []
    finally:
        conn.close()


# ─── Дедупликация по городу ───────────────────────────────────────────────────

def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Приближённое расстояние между двумя точками (км)"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def cluster_organizations(orgs: List[Dict], radius_km: float = 5.0) -> List[Dict]:
    """
    Группирует организации в кластеры по расстоянию.
    Возвращает список записей — по одной на кластер:
      {org_id, org_name, city_cluster, lat, lon, org_ids[]}
    lat/lon кластера = среднее по всем точкам группы.
    """
    clusters: List[List[Dict]] = []

    for org in orgs:
        placed = False
        for cluster in clusters:
            # Сравниваем с центроидом кластера
            c_lat = sum(o["lat"] for o in cluster) / len(cluster)
            c_lon = sum(o["lon"] for o in cluster) / len(cluster)
            if _distance_km(org["lat"], org["lon"], c_lat, c_lon) <= radius_km:
                cluster.append(org)
                placed = True
                break
        if not placed:
            clusters.append([org])

    result = []
    for cluster in clusters:
        c_lat = sum(o["lat"] for o in cluster) / len(cluster)
        c_lon = sum(o["lon"] for o in cluster) / len(cluster)
        # Имя кластера — имя первой (ближайшей к центру) организации
        label = cluster[0]["name"]
        for o in cluster:
            result.append({
                "org_id":        o["id"],
                "org_name":      o["name"],
                "city_cluster":  label,
                "lat":           round(c_lat, 6),
                "lon":           round(c_lon, 6),
            })
    return result


# ─── Open-Meteo API ───────────────────────────────────────────────────────────

_OPENMETEO_FIELDS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "cloud_cover_mean",
    "wind_speed_10m_max",
]


def _fetch_from_endpoint(host: str, path: str, params: dict) -> List[Dict]:
    """Общий HTTP-запрос к Open-Meteo, возвращает распарсенные строки."""
    url = path + "?" + urlencode(params)
    conn = None
    try:
        conn = http.client.HTTPSConnection(host, timeout=60)
        conn.request("GET", url)
        res = conn.getresponse()
        raw = res.read().decode()
        if res.status != 200:
            logger.error(f"Open-Meteo error {res.status} ({host}): {raw[:300]}")
            return []
        data = json.loads(raw)
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                "date":             date.fromisoformat(d),
                "temp_avg":         daily.get("temperature_2m_mean", [None])[i],
                "temp_min":         daily.get("temperature_2m_min",  [None])[i],
                "temp_max":         daily.get("temperature_2m_max",  [None])[i],
                "precipitation_mm": daily.get("precipitation_sum",   [None])[i],
                "cloud_cover_pct":  daily.get("cloud_cover_mean",    [None])[i],
                "wind_speed_ms":    daily.get("wind_speed_10m_max",  [None])[i],
            })
        return rows
    except Exception as e:
        logger.error(f"fetch error {host}: {e}")
        return []
    finally:
        if conn:
            conn.close()


def fetch_weather(lat: float, lon: float,
                  date_from: date, date_to: date) -> List[Dict]:
    """
    Запрашивает дневную погоду из Open-Meteo.

    Автоматически выбирает endpoint:
    - archive-api.open-meteo.com/v1/archive  — для исторических дат (до вчера)
    - api.open-meteo.com/v1/forecast         — для текущего дня и прогноза

    При диапазоне, перекрывающем границу, делает два запроса и склеивает.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    base_params = {
        "latitude":  lat,
        "longitude": lon,
        "daily":     ",".join(_OPENMETEO_FIELDS),
        "timezone":  "UTC",
    }

    rows: List[Dict] = []

    # 1. Исторический кусок: date_from .. min(date_to, yesterday)
    if date_from <= yesterday:
        hist_to = min(date_to, yesterday)
        params = {**base_params, "start_date": str(date_from), "end_date": str(hist_to)}
        logger.debug(f"Archive request: {date_from} – {hist_to}")
        chunk = _fetch_from_endpoint(
            "archive-api.open-meteo.com", "/v1/archive", params
        )
        rows.extend(chunk)
        logger.info(f"Archive: got {len(chunk)} days ({date_from} – {hist_to})")

    # 2. Прогнозный кусок: max(date_from, today) .. date_to
    if date_to >= today:
        fcast_from = max(date_from, today)
        params = {**base_params, "start_date": str(fcast_from), "end_date": str(date_to)}
        logger.debug(f"Forecast request: {fcast_from} – {date_to}")
        chunk = _fetch_from_endpoint(
            "api.open-meteo.com", "/v1/forecast", params
        )
        rows.extend(chunk)
        logger.info(f"Forecast: got {len(chunk)} days ({fcast_from} – {date_to})")

    return rows


# ─── ClickHouse ───────────────────────────────────────────────────────────────

def _init_tables(ch: Client) -> None:
    """Создаёт weather_db и все таблицы если не существуют."""
    ch.execute("CREATE DATABASE IF NOT EXISTS weather_db")
    ch.execute(CREATE_WEATHER_TABLE_SQL)
    ch.execute(CREATE_ORGS_REF_TABLE_SQL)


def sync_org_reference(api_key: str, ch: Client) -> int:
    """
    Синхронизирует справочник организаций weather_db.organizations_ref.

    Вызывается при каждой загрузке погоды — обновляет данные из iiko Cloud.
    Использует ReplacingMergeTree: повторная вставка заменяет старую запись
    по org_id (берётся строка с максимальным synced_at).

    Возвращает количество обработанных организаций.
    """
    orgs = get_iiko_organizations(api_key)
    if not orgs:
        logger.warning("sync_org_reference: no organizations returned")
        return 0

    # Первые 8 символов ключа — для идентификации подключения в справочнике
    api_key_hint = api_key[:8] + "..."

    rows = []
    for org in orgs:
        rows.append({
            "org_id":        org["id"],
            "org_name":      org["name"],
            "org_code":      org["code"],
            "address":       org["address"],
            "country":       org["country"],
            "lat":           org["lat"],
            "lon":           org["lon"],
            "inn":           org["inn"],
            "currency":      org["currency"],
            "delivery_type": org["delivery_type"],
            "iiko_version":  org["iiko_version"],
            "api_key_hint":  api_key_hint,
        })

    ch.execute(
        "INSERT INTO weather_db.organizations_ref "
        "(org_id, org_name, org_code, address, country, lat, lon, "
        " inn, currency, delivery_type, iiko_version, api_key_hint) VALUES",
        rows
    )
    logger.info(f"organizations_ref: upserted {len(rows)} organizations (key: {api_key_hint})")
    return len(rows)


# ─── weather table helpers ────────────────────────────────────────────────────


def _delete_weather(ch: Client, org_ids: List[str],
                    date_from: date, date_to: date) -> None:
    if not org_ids:
        return
    # Передаём org_ids как tuple — clickhouse-driver сам корректно экранирует
    ch.execute(
        "ALTER TABLE weather_db.daily_weather "
        "DELETE WHERE org_id IN %(ids)s "
        "AND date >= %(from)s AND date <= %(to)s",
        {"ids": tuple(org_ids), "from": date_from, "to": date_to}
    )


def _insert_weather(ch: Client, rows: List[Dict]) -> None:
    if not rows:
        return
    ch.execute(
        "INSERT INTO weather_db.daily_weather "
        "(date, org_id, org_name, city_cluster, lat, lon, "
        " temp_avg, temp_min, temp_max, "
        " precipitation_mm, cloud_cover_pct, wind_speed_ms) VALUES",
        rows
    )


# ─── Основная функция ─────────────────────────────────────────────────────────

def load_weather_for_connection(
    iiko_cloud_api_key: str,
    ch_client: Client,
    date_from: date,
    date_to:   date,
) -> bool:
    """
    Загружает погоду для одного iiko-подключения.
    Используется из main.py CLI.
    """
    logger.info(f"Loading weather {date_from} – {date_to}")

    # 1. Получаем все организации (включая без координат)
    all_orgs = get_iiko_organizations(iiko_cloud_api_key)
    if not all_orgs:
        logger.warning("No organizations returned — skipping")
        return False

    # 2. Инициализируем таблицы
    _init_tables(ch_client)

    # 3. Синхронизируем справочник — ВСЕ организации (с координатами и без)
    sync_org_reference(iiko_cloud_api_key, ch_client)

    # 4. Для погоды нужны только орги с координатами
    orgs = [o for o in all_orgs if o["lat"] is not None and o["lon"] is not None]
    if not orgs:
        logger.warning("No organizations with coordinates — weather skipped")
        return False

    # 5. Кластеризуем по городу
    clustered = cluster_organizations(orgs, radius_km=5.0)
    logger.info(f"{len(orgs)} orgs → {len(set(o['city_cluster'] for o in clustered))} city clusters")

    # 6. Уникальные кластеры (lat/lon)
    seen_clusters: Dict[str, List[Dict]] = {}  # city_cluster → [org_rows]
    for o in clustered:
        seen_clusters.setdefault(o["city_cluster"], []).append(o)

    total_rows = 0
    for city, cluster_orgs in seen_clusters.items():
        lat = cluster_orgs[0]["lat"]
        lon = cluster_orgs[0]["lon"]
        org_ids = [o["org_id"] for o in cluster_orgs]

        # Запрашиваем погоду для кластера
        weather_rows = fetch_weather(lat, lon, date_from, date_to)
        if not weather_rows:
            logger.warning(f"No weather data for cluster {city} ({lat},{lon})")
            continue

        # Удаляем старые данные
        _delete_weather(ch_client, org_ids, date_from, date_to)

        # Готовим строки для вставки — одна строка на (дату × орг)
        insert_rows = []
        for org in cluster_orgs:
            for w in weather_rows:
                insert_rows.append({
                    "date":             w["date"],
                    "org_id":           org["org_id"],
                    "org_name":         org["org_name"],
                    "city_cluster":     org["city_cluster"],
                    "lat":              org["lat"],
                    "lon":              org["lon"],
                    "temp_avg":         w["temp_avg"],
                    "temp_min":         w["temp_min"],
                    "temp_max":         w["temp_max"],
                    "precipitation_mm": w["precipitation_mm"],
                    "cloud_cover_pct":  w["cloud_cover_pct"],
                    "wind_speed_ms":    w["wind_speed_ms"],
                })

        _insert_weather(ch_client, insert_rows)
        total_rows += len(insert_rows)
        logger.info(f"  {city}: {len(org_ids)} orgs × {len(weather_rows)} days = {len(insert_rows)} rows")

    logger.info(f"Weather load complete. Total rows inserted: {total_rows}")
    return total_rows > 0
