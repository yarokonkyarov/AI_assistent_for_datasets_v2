"""
tests/test_currency_converter.py

Тесты конвертации валют.
Запуск из корня проекта:
    python -m pytest tests/test_currency_converter.py -v
    # или без pytest:
    python tests/test_currency_converter.py
"""
import sys
import os
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.currency_converter import CurrencyConverter


# ─────────────────────────────────────────────────────────────────────────────
# Хелпер: создать конвертер с замоканным CH-клиентом
# ─────────────────────────────────────────────────────────────────────────────

def make_converter(ch_rows=None, ch_error=None):
    """
    Возвращает CurrencyConverter с замоканным ClickHouse.

    ch_rows  — список строк, которые вернёт execute()
    ch_error — если задан, execute() бросит это исключение
    """
    mock_client = MagicMock()
    if ch_error:
        mock_client.execute.side_effect = ch_error
    else:
        mock_client.execute.return_value = ch_rows or []
    return CurrencyConverter(mock_client)


# Тестовые курсы: (date, rub, gel, amd)
RATES_FIXTURE = [
    (date(2024, 2, 19), 1.0, 14.20, 0.220),   # понедельник (за 10 дней до Feb 29)
    (date(2024, 2, 21), 1.0, 14.35, 0.221),
    (date(2024, 2, 23), 1.0, 14.50, 0.222),
    # 24 Feb — суббота (нет записи)
    # 25 Feb — воскресенье (нет записи)
    (date(2024, 2, 26), 1.0, 14.60, 0.223),
    (date(2024, 2, 27), 1.0, 14.70, 0.224),
    (date(2024, 2, 28), 1.0, 14.80, 0.225),
    (date(2024, 2, 29), 1.0, 14.90, 0.226),   # 29 Feb — последний день чанка
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Загрузка курсов
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadRates(unittest.TestCase):

    def test_loaded_dates_count(self):
        """Все строки из CH попадают во внутренний кэш."""
        conv = make_converter(ch_rows=RATES_FIXTURE)
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))
        self.assertEqual(len(conv._rates), len(RATES_FIXTURE))

    def test_is_available_after_load(self):
        conv = make_converter(ch_rows=RATES_FIXTURE)
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))
        self.assertTrue(conv.is_available)

    def test_not_available_on_empty_result(self):
        """Пустой ответ от CH → конвертация недоступна."""
        conv = make_converter(ch_rows=[])
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))
        self.assertFalse(conv.is_available)

    def test_not_available_on_ch_exception(self):
        """Ошибка соединения с CH → конвертация недоступна, исключение не прокидывается."""
        conv = make_converter(ch_error=Exception("connection refused"))
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))
        self.assertFalse(conv.is_available)

    def test_extended_range_passed_to_ch(self):
        """CH-запрос должен начинаться за 10 дней до date_from (для fallback)."""
        mock_client = MagicMock()
        mock_client.execute.return_value = RATES_FIXTURE
        conv = CurrencyConverter(mock_client)

        date_from = date(2024, 2, 29)
        conv.load_rates(date_from, date(2024, 2, 29))

        called_params = mock_client.execute.call_args[0][1]
        self.assertEqual(called_params['from'], date_from - timedelta(days=10))
        self.assertEqual(called_params['to'], date(2024, 2, 29))

    def test_rates_parsed_correctly(self):
        """Значения курсов корректно сохраняются в кэш."""
        conv = make_converter(ch_rows=RATES_FIXTURE)
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))

        d = date(2024, 2, 29)
        self.assertAlmostEqual(conv._rates[d]['rub'], 1.0)
        self.assertAlmostEqual(conv._rates[d]['gel'], 14.90)
        self.assertAlmostEqual(conv._rates[d]['amd'], 0.226)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Получение курса
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRate(unittest.TestCase):

    def setUp(self):
        self.conv = make_converter(ch_rows=RATES_FIXTURE)
        self.conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))

    # --- RUB всегда 1.0 ---

    def test_rub_is_always_one(self):
        self.assertEqual(self.conv.get_rate(date(2024, 2, 29), 'RUB'), 1.0)

    def test_rub_before_any_data(self):
        """RUB возвращает 1.0 даже до загрузки курсов."""
        conv = make_converter()
        self.assertEqual(conv.get_rate(date(2020, 1, 1), 'RUB'), 1.0)

    # --- Прямое попадание ---

    def test_gel_exact_date(self):
        rate = self.conv.get_rate(date(2024, 2, 29), 'GEL')
        self.assertAlmostEqual(rate, 14.90)

    def test_amd_exact_date(self):
        rate = self.conv.get_rate(date(2024, 2, 28), 'AMD')
        self.assertAlmostEqual(rate, 0.225)

    # --- Регистр не важен ---

    def test_case_insensitive_currency(self):
        self.assertAlmostEqual(
            self.conv.get_rate(date(2024, 2, 29), 'gel'),
            self.conv.get_rate(date(2024, 2, 29), 'GEL'),
        )

    # --- Fallback ---

    def test_fallback_for_saturday(self):
        """Суббота 24.02 — нет записи → должен вернуть курс пятницы 23.02."""
        rate = self.conv.get_rate(date(2024, 2, 24), 'GEL')
        self.assertAlmostEqual(rate, 14.50)  # курс 2024-02-23

    def test_fallback_for_sunday(self):
        """Воскресенье 25.02 — нет записи → пятница 23.02."""
        rate = self.conv.get_rate(date(2024, 2, 25), 'GEL')
        self.assertAlmostEqual(rate, 14.50)

    def test_fallback_chain(self):
        """Несколько дней подряд без данных → последний известный."""
        # Между 21 Feb (14.35) и 23 Feb (14.50) нет записи за 22 Feb
        rate = self.conv.get_rate(date(2024, 2, 22), 'GEL')
        self.assertAlmostEqual(rate, 14.35)  # курс от 21 Feb

    # --- Нет данных до запрошенной даты ---

    def test_no_fallback_before_all_data(self):
        """Дата раньше всех загруженных → None."""
        rate = self.conv.get_rate(date(2024, 2, 10), 'GEL')
        self.assertIsNone(rate)

    # --- Неизвестная валюта ---

    def test_unknown_currency_returns_none(self):
        rate = self.conv.get_rate(date(2024, 2, 29), 'USD')
        self.assertIsNone(rate)

    def test_empty_currency_returns_none(self):
        rate = self.conv.get_rate(date(2024, 2, 29), '')
        self.assertIsNone(rate)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Конвертация сумм
# ─────────────────────────────────────────────────────────────────────────────

class TestConvert(unittest.TestCase):

    def setUp(self):
        self.conv = make_converter(ch_rows=RATES_FIXTURE)
        self.conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))

    def test_gel_conversion(self):
        """100 GEL × 14.90 = 1490 RUB."""
        result = self.conv.convert(100.0, 'GEL', date(2024, 2, 29))
        self.assertAlmostEqual(result, 1490.0, places=2)

    def test_amd_conversion(self):
        """1000 AMD × 0.225 = 225 RUB."""
        result = self.conv.convert(1000.0, 'AMD', date(2024, 2, 28))
        self.assertAlmostEqual(result, 225.0, places=2)

    def test_rub_unchanged(self):
        """RUB остаётся без изменений."""
        result = self.conv.convert(500.0, 'RUB', date(2024, 2, 29))
        self.assertAlmostEqual(result, 500.0)

    def test_none_amount_returns_none(self):
        result = self.conv.convert(None, 'GEL', date(2024, 2, 29))
        self.assertIsNone(result)

    def test_unknown_currency_returns_none(self):
        result = self.conv.convert(100.0, 'USD', date(2024, 2, 29))
        self.assertIsNone(result)

    def test_missing_rate_returns_none(self):
        """Дата до загруженного диапазона → None."""
        result = self.conv.convert(100.0, 'GEL', date(2024, 2, 10))
        self.assertIsNone(result)

    def test_result_rounded_to_4_places(self):
        """Результат округлён до 4 знаков."""
        result = self.conv.convert(1.0, 'GEL', date(2024, 2, 29))
        # 1.0 × 14.90 = 14.9 → rounded to 4 decimal places
        self.assertEqual(result, round(1.0 * 14.90, 4))

    def test_conversion_unavailable_returns_none(self):
        """Курсы не загружены → None для любой суммы."""
        conv = make_converter(ch_rows=[])
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))
        result = conv.convert(100.0, 'GEL', date(2024, 2, 29))
        self.assertIsNone(result)

    def test_fallback_used_in_conversion(self):
        """Конвертация в выходной день использует пятничный курс."""
        # Суббота 24 Feb → должен использоваться курс 23 Feb (14.50)
        result = self.conv.convert(100.0, 'GEL', date(2024, 2, 24))
        self.assertAlmostEqual(result, 100.0 * 14.50, places=4)


# ─────────────────────────────────────────────────────────────────────────────
# 4. register_currency
# ─────────────────────────────────────────────────────────────────────────────

class TestRegisterCurrency(unittest.TestCase):

    def test_register_and_use_new_currency(self):
        """После register_currency новая валюта конвертируется корректно."""
        # Курсы: добавляем колонку kgs
        rows = [
            (date(2024, 2, 29), 1.0, 14.90, 0.226, 0.85),
        ]
        mock_client = MagicMock()
        mock_client.execute.return_value = rows
        conv = CurrencyConverter(mock_client)
        # Регистрируем KGS → колонка kgs (индекс 4 в строке)
        # Но load_rates строит SELECT только из CURRENCY_COLUMN_MAP,
        # поэтому нам нужно зарегистрировать ДО load_rates
        conv.register_currency('KGS', 'kgs')
        # Колонки: rub, gel, amd, kgs
        rows_kgs = [
            (date(2024, 2, 29), 1.0, 14.90, 0.226, 0.85),
        ]
        mock_client.execute.return_value = rows_kgs
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))
        self.assertIn('KGS', conv.CURRENCY_COLUMN_MAP)

    def test_register_uppercase_normalized(self):
        conv = make_converter()
        conv.register_currency('usd', 'usd')
        self.assertIn('USD', conv.CURRENCY_COLUMN_MAP)
        self.assertEqual(conv.CURRENCY_COLUMN_MAP['USD'], 'usd')


# ─────────────────────────────────────────────────────────────────────────────
# 5. Интеграционный тест: _apply_currency_conversion в dataset_manager
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyCurrencyConversion(unittest.TestCase):
    """
    Тестирует метод IikoOlapDatasetManager._apply_currency_conversion
    без реального ClickHouse и iiko.
    """

    def _make_manager(self, ch_rows=None):
        """Создаёт минимальный менеджер с мок-клиентом."""
        from core.dataset_manager import IikoOlapDatasetManager

        mock_client = MagicMock()
        mock_client.execute.return_value = ch_rows or RATES_FIXTURE

        config = {
            'iiko': {'api_url': 'http://test', 'login': 'u', 'password': 'p'},
            'clickhouse': {
                'host': 'localhost', 'port': 9000,
                'user': 'default', 'password': '', 'storage_policy': 'default',
            },
            'report_template': {
                'reportType': 'SALES',
                'groupByRowFields': ['OpenDate.Typed', 'Currencies.Currency'],
                'aggregateFields': [
                    'DishSumInt',
                    'DishDiscountSumInt',
                    'ProductCostBase.ProductCost',
                ],
            },
            'dataset_name': 'fobo.pl1',
            'date_from': date(2024, 2, 21),
            'date_to': date(2024, 2, 29),
            'currency_conversion': {'enabled': True},
        }

        with patch('core.dataset_manager.Client', return_value=mock_client):
            manager = IikoOlapDatasetManager(config)
        manager.ch_client = mock_client
        return manager

    def _make_converter(self, ch_rows=None):
        conv = make_converter(ch_rows=ch_rows or RATES_FIXTURE)
        conv.load_rates(date(2024, 2, 21), date(2024, 2, 29))
        return conv

    # --- Основной сценарий ---

    def test_rub_fields_added_to_rows(self):
        manager = self._make_manager()
        conv = self._make_converter()

        data = [
            {
                'OpenDate_Typed': date(2024, 2, 29),
                'Currencies_Currency': 'GEL',
                'DishSumInt': 100.0,
                'DishDiscountSumInt': 90.0,
                'ProductCostBase_ProductCost': 30.0,
            }
        ]
        pairs = [
            ('DishSumInt', 'DishSumInt_RUB'),
            ('DishDiscountSumInt', 'DishDiscountSumInt_RUB'),
            ('ProductCostBase_ProductCost', 'ProductCostBase_ProductCost_RUB'),
        ]

        result = manager._apply_currency_conversion(data, conv, 'OpenDate_Typed', pairs)

        row = result[0]
        self.assertIn('DishSumInt_RUB', row)
        self.assertIn('DishDiscountSumInt_RUB', row)
        self.assertIn('ProductCostBase_ProductCost_RUB', row)

        # 100 GEL × 14.90 = 1490.0
        self.assertAlmostEqual(row['DishSumInt_RUB'], 1490.0, places=2)
        # 90 GEL × 14.90 = 1341.0
        self.assertAlmostEqual(row['DishDiscountSumInt_RUB'], 1341.0, places=2)
        # 30 GEL × 14.90 = 447.0
        self.assertAlmostEqual(row['ProductCostBase_ProductCost_RUB'], 447.0, places=2)

    def test_rub_rows_unchanged(self):
        """Строки с валютой RUB должны иметь _RUB = исходное значение."""
        manager = self._make_manager()
        conv = self._make_converter()

        data = [
            {
                'OpenDate_Typed': date(2024, 2, 29),
                'Currencies_Currency': 'RUB',
                'DishSumInt': 5000.0,
            }
        ]
        pairs = [('DishSumInt', 'DishSumInt_RUB')]
        result = manager._apply_currency_conversion(data, conv, 'OpenDate_Typed', pairs)

        self.assertAlmostEqual(result[0]['DishSumInt_RUB'], 5000.0)

    def test_amd_conversion_in_pipeline(self):
        """1000 AMD × 0.226 = 226.0 RUB."""
        manager = self._make_manager()
        conv = self._make_converter()

        data = [
            {
                'OpenDate_Typed': date(2024, 2, 29),
                'Currencies_Currency': 'AMD',
                'DishSumInt': 1000.0,
            }
        ]
        pairs = [('DishSumInt', 'DishSumInt_RUB')]
        result = manager._apply_currency_conversion(data, conv, 'OpenDate_Typed', pairs)

        self.assertAlmostEqual(result[0]['DishSumInt_RUB'], 226.0, places=2)

    def test_mixed_currencies_in_batch(self):
        """Чанк с разными валютами конвертируется корректно."""
        manager = self._make_manager()
        conv = self._make_converter()

        data = [
            {'OpenDate_Typed': date(2024, 2, 29), 'Currencies_Currency': 'RUB', 'DishSumInt': 1000.0},
            {'OpenDate_Typed': date(2024, 2, 29), 'Currencies_Currency': 'GEL', 'DishSumInt': 100.0},
            {'OpenDate_Typed': date(2024, 2, 28), 'Currencies_Currency': 'AMD', 'DishSumInt': 500.0},
        ]
        pairs = [('DishSumInt', 'DishSumInt_RUB')]
        result = manager._apply_currency_conversion(data, conv, 'OpenDate_Typed', pairs)

        self.assertAlmostEqual(result[0]['DishSumInt_RUB'], 1000.0)        # RUB × 1
        self.assertAlmostEqual(result[1]['DishSumInt_RUB'], 1490.0, places=2)  # GEL × 14.90
        self.assertAlmostEqual(result[2]['DishSumInt_RUB'], 500 * 0.225, places=4)  # AMD × 0.225

    def test_none_amount_stays_none(self):
        """NULL-сумма не конвертируется (остаётся NULL)."""
        manager = self._make_manager()
        conv = self._make_converter()

        data = [
            {
                'OpenDate_Typed': date(2024, 2, 29),
                'Currencies_Currency': 'GEL',
                'DishSumInt': None,
            }
        ]
        pairs = [('DishSumInt', 'DishSumInt_RUB')]
        result = manager._apply_currency_conversion(data, conv, 'OpenDate_Typed', pairs)

        self.assertIsNone(result[0]['DishSumInt_RUB'])

    def test_converter_unavailable_fills_none(self):
        """Если курсы не загружены — все _RUB поля = None (не падает)."""
        manager = self._make_manager()
        conv = make_converter(ch_rows=[])   # пустой ответ → is_available = False
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))

        data = [
            {
                'OpenDate_Typed': date(2024, 2, 29),
                'Currencies_Currency': 'GEL',
                'DishSumInt': 100.0,
            }
        ]
        pairs = [('DishSumInt', 'DishSumInt_RUB')]
        result = manager._apply_currency_conversion(data, conv, 'OpenDate_Typed', pairs)

        self.assertIsNone(result[0]['DishSumInt_RUB'])

    def test_weekend_uses_friday_rate(self):
        """Продажи в субботу конвертируются по курсу пятницы."""
        manager = self._make_manager()
        conv = self._make_converter()

        # Суббота 24 Feb → fallback на пятницу 23 Feb (gel = 14.50)
        data = [
            {
                'OpenDate_Typed': date(2024, 2, 24),
                'Currencies_Currency': 'GEL',
                'DishSumInt': 100.0,
            }
        ]
        pairs = [('DishSumInt', 'DishSumInt_RUB')]
        result = manager._apply_currency_conversion(data, conv, 'OpenDate_Typed', pairs)

        self.assertAlmostEqual(result[0]['DishSumInt_RUB'], 100.0 * 14.50, places=4)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Граничные случаи
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_single_rate_record_fallback(self):
        """Один курс на всё → используется для всех дат после него."""
        rows = [(date(2024, 1, 1), 1.0, 15.0, 0.25)]
        conv = make_converter(ch_rows=rows)
        conv.load_rates(date(2024, 1, 1), date(2024, 3, 1))

        self.assertAlmostEqual(conv.get_rate(date(2024, 3, 1), 'GEL'), 15.0)
        self.assertAlmostEqual(conv.get_rate(date(2024, 6, 15), 'GEL'), 15.0)

    def test_zero_amount(self):
        """Нулевая сумма конвертируется в 0."""
        rows = [(date(2024, 2, 29), 1.0, 14.90, 0.226)]
        conv = make_converter(ch_rows=rows)
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))

        self.assertEqual(conv.convert(0.0, 'GEL', date(2024, 2, 29)), 0.0)

    def test_large_amount(self):
        """Большие суммы (миллионы) не теряют точность."""
        rows = [(date(2024, 2, 29), 1.0, 14.90, 0.226)]
        conv = make_converter(ch_rows=rows)
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))

        result = conv.convert(10_000_000.0, 'GEL', date(2024, 2, 29))
        self.assertAlmostEqual(result, 10_000_000.0 * 14.90, places=0)

    def test_none_rate_in_db_for_currency(self):
        """Если в таблице курс = NULL для валюты → возвращает None."""
        rows = [(date(2024, 2, 29), 1.0, None, 0.226)]  # gel = NULL
        conv = make_converter(ch_rows=rows)
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))

        result = conv.get_rate(date(2024, 2, 29), 'GEL')
        self.assertIsNone(result)

    def test_whitespace_in_currency_code(self):
        """Пробелы в коде валюты не ломают конвертацию."""
        rows = [(date(2024, 2, 29), 1.0, 14.90, 0.226)]
        conv = make_converter(ch_rows=rows)
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))

        result = conv.convert(100.0, '  GEL  ', date(2024, 2, 29))
        self.assertAlmostEqual(result, 1490.0, places=2)

    def test_multiple_load_rates_resets_cache(self):
        """Повторный вызов load_rates перезаписывает кэш."""
        rows_v1 = [(date(2024, 2, 29), 1.0, 10.0, 0.2)]
        rows_v2 = [(date(2024, 2, 29), 1.0, 20.0, 0.3)]

        mock_client = MagicMock()
        conv = CurrencyConverter(mock_client)

        mock_client.execute.return_value = rows_v1
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))
        self.assertAlmostEqual(conv.get_rate(date(2024, 2, 29), 'GEL'), 10.0)

        mock_client.execute.return_value = rows_v2
        conv.load_rates(date(2024, 2, 29), date(2024, 2, 29))
        self.assertAlmostEqual(conv.get_rate(date(2024, 2, 29), 'GEL'), 20.0)


# ─────────────────────────────────────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Цветной вывод при запуске напрямую
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for cls in [
        TestLoadRates,
        TestGetRate,
        TestConvert,
        TestRegisterCurrency,
        TestApplyCurrencyConversion,
        TestEdgeCases,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
