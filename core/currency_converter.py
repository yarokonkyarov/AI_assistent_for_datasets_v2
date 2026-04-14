# core/currency_converter.py
"""
Конвертация валют к рублю.

Загружает курсы из ClickHouse (currency_db.currency_rates) и конвертирует
суммы по курсу на дату. Для дат без записей использует последний известный курс.
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from clickhouse_driver import Client

logger = logging.getLogger(__name__)


class CurrencyConverter:
    """
    Использование:
        converter = CurrencyConverter(ch_client)
        converter.load_rates(date_from, date_to)  # один раз на чанк
        rub_amount = converter.convert(150.0, 'GEL', date(2024, 3, 1))
    """

    # Соответствие кодов валют → колонкам таблицы курсов
    CURRENCY_COLUMN_MAP: Dict[str, str] = {
        'RUB': 'rub',
        'GEL': 'gel',
        'AMD': 'amd',
    }

    def __init__(
        self,
        ch_client: Client,
        rates_db: str = 'currency_db',
        rates_table: str = 'currency_rates',
    ):
        self.ch_client = ch_client
        self.rates_db = rates_db
        self.rates_table = rates_table

        # {date: {'rub': 1.0, 'gel': 14.5, 'amd': 0.23}}
        self._rates: Dict[date, Dict[str, Optional[float]]] = {}
        self._sorted_dates: List[date] = []
        self._available: bool = False

    # ──────────────────────────────────────────────────────────────────────────
    # Загрузка курсов
    # ──────────────────────────────────────────────────────────────────────────

    def load_rates(self, date_from: date, date_to: date) -> None:
        """
        Загружает курсы для диапазона дат.
        Диапазон расширяется на 10 дней назад для обеспечения fallback.
        """
        extended_from = date_from - timedelta(days=10)
        known_cols = list(self.CURRENCY_COLUMN_MAP.values())
        cols_sql = ', '.join(known_cols)

        try:
            rows = self.ch_client.execute(
                f"""
                SELECT date, {cols_sql}
                FROM {self.rates_db}.{self.rates_table}
                WHERE date >= %(from)s AND date <= %(to)s
                ORDER BY date
                """,
                {'from': extended_from, 'to': date_to},
            )
        except Exception as e:
            logger.warning(
                f"Не удалось загрузить курсы из "
                f"{self.rates_db}.{self.rates_table}: {e}. "
                f"Конвертация будет пропущена."
            )
            self._available = False
            return

        self._rates = {}
        for row in rows:
            row_date = row[0]
            self._rates[row_date] = {
                col: (float(row[i + 1]) if row[i + 1] is not None else None)
                for i, col in enumerate(known_cols)
            }

        self._sorted_dates = sorted(self._rates.keys())
        self._available = bool(self._sorted_dates)

        if self._available:
            logger.info(
                f"Курсы валют загружены: {len(self._rates)} дат "
                f"[{self._sorted_dates[0]} – {self._sorted_dates[-1]}]"
            )
        else:
            logger.warning(
                f"Курсы не найдены за {extended_from} – {date_to}. "
                f"Конвертация будет пропущена."
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Получение курса
    # ──────────────────────────────────────────────────────────────────────────

    def get_rate(self, for_date: date, currency: str) -> Optional[float]:
        """
        Возвращает курс валюты к рублю на дату.
        При отсутствии записи возвращает курс ближайшей предыдущей даты.

        Args:
            for_date: дата продажи
            currency:  код валюты ('RUB', 'GEL', 'AMD', ...)

        Returns:
            float — курс, или None если данных нет
        """
        currency = (currency or '').strip().upper()

        if currency == 'RUB':
            return 1.0

        col = self.CURRENCY_COLUMN_MAP.get(currency)
        if col is None:
            logger.warning(f"Неизвестная валюта: {currency!r}")
            return None

        # Прямое попадание
        if for_date in self._rates:
            return self._rates[for_date].get(col)

        # Fallback: последний известный курс до этой даты
        for d in reversed(self._sorted_dates):
            if d <= for_date:
                rate = self._rates[d].get(col)
                if rate is not None:
                    logger.debug(
                        f"Fallback {currency} для {for_date}: курс от {d} = {rate}"
                    )
                    return rate

        logger.warning(f"Нет курса {currency} для даты {for_date}")
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Конвертация
    # ──────────────────────────────────────────────────────────────────────────

    def convert(
        self,
        amount: Optional[float],
        currency: str,
        for_date: date,
    ) -> Optional[float]:
        """
        Конвертирует сумму в рубли.

        Returns:
            float — сумма в рублях, или None при отсутствии курса/суммы
        """
        if amount is None:
            return None

        rate = self.get_rate(for_date, currency)
        if rate is None:
            return None

        return round(amount * rate, 4)

    # ──────────────────────────────────────────────────────────────────────────
    # Утилиты
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """True если курсы успешно загружены."""
        return self._available

    def register_currency(self, code: str, column: str) -> None:
        """
        Добавляет поддержку новой валюты (если она появилась в таблице курсов).

        Args:
            code:   код валюты, как в поле Currencies_Currency ('KGS', 'USD', ...)
            column: название колонки в таблице currency_rates ('kgs', 'usd', ...)
        """
        self.CURRENCY_COLUMN_MAP[code.upper()] = column.lower()
        logger.info(f"Зарегистрирована валюта {code} → колонка {column}")
