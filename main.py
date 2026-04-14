# main.py
import sys
from pathlib import Path
import click
from uuid import UUID
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Добавляем путь для импортов
sys.path.append(str(Path(__file__).parent))


def run_single_task(task_id_str, chunk_days=7, batch_size=50000):
    """Запустить одну задачу"""
    try:
        task_uuid = UUID(task_id_str.strip())
        logger.info(f"Запуск задачи: {task_uuid}")

        # Импортируем необходимые модули
        from core.task_loader import load_full_task_config
        from core.dataset_manager import IikoOlapDatasetManager

        # Загружаем конфигурацию задачи
        config = load_full_task_config(task_uuid)

        if not config:
            logger.error(f"Не удалось загрузить конфигурацию для задачи {task_uuid}")
            print("Возможные причины:")
            print("1. Задача не найдена в базе данных")
            print("2. Задача неактивна (is_active = False)")
            print("3. Не найдены связанные подключения (iiko, ClickHouse)")
            print("4. Не найден шаблон отчета")
            return False

        logger.info(f"Конфигурация загружена")
        logger.info(f"Dataset: {config.get('dataset_name')}")
        logger.info(f"Период: {config.get('date_from')} до {config.get('date_to')}")

        # Создаем менеджер датасетов
        dataset_manager = IikoOlapDatasetManager(config_dict=config)

        # Проверяем существование датасета, если нет - создаем
        if not dataset_manager.dataset_exists(config['dataset_name']):
            logger.info(f"Датасет не существует, создаем...")
            if dataset_manager.generate_and_create():
                logger.info(f"Датасет создан успешно")
            else:
                logger.error(f"Не удалось создать датасет")
                return False

        # Запускаем обновление данных
        logger.info(f"Начинаю загрузку данных...")

        success = dataset_manager.update_dataset(
            chunk_days=chunk_days,
            batch_size=batch_size
        )

        if success:
            logger.info(f"Загрузка данных завершена успешно")

            # Получаем информацию о датасете
            dataset_info = dataset_manager.get_dataset_info()
            if dataset_info:
                logger.info(f"Информация о датасете:")
                logger.info(f"  - Имя: {dataset_info['name']}")
                logger.info(f"  - Количество строк: {dataset_info['row_count']}")
                if dataset_info['date_range']['min'] and dataset_info['date_range']['max']:
                    logger.info(
                        f"  - Диапазон дат: {dataset_info['date_range']['min']} - {dataset_info['date_range']['max']}")

            return True
        else:
            logger.error(f"Загрузка данных завершилась с ошибкой")
            return False

    except ValueError as e:
        logger.error(f"Неверный формат UUID: {task_id_str} - {e}")
        return False
    except ImportError as e:
        logger.error(f"Ошибка импорта: {e}")
        print("Убедитесь, что все зависимости установлены")
        return False
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


@click.group()
def cli():
    """AI Assistant for Datasets CLI"""
    pass


@cli.command()
@click.argument('task_ids')
@click.option('--chunk-days', default=7, help='Размер чанка в днях для обработки')
@click.option('--batch-size', default=50000, help='Размер батча для вставки в ClickHouse')
@click.option('--stop-on-error', is_flag=True, default=False, help='Остановить выполнение при ошибке')
def run_task(task_ids, chunk_days, batch_size, stop_on_error):
    """Запустить выполнение задач

    TASK_IDS - один или несколько ID задач через запятую
    Пример: d5b438bf-40f5-404c-9379-171578f4d755,abc123-def456-ghi789-jkl012-mno345
    """
    # Разделяем ID задач
    task_id_list = [tid.strip() for tid in task_ids.split(',')]

    logger.info(f"Получено {len(task_id_list)} задач для выполнения")
    logger.info(f"ID задач: {task_id_list}")

    success_count = 0
    error_count = 0
    failed_tasks = []

    for i, task_id in enumerate(task_id_list, 1):
        logger.info(f"--- Задача {i}/{len(task_id_list)}: {task_id} ---")

        try:
            success = run_single_task(
                task_id,
                chunk_days=chunk_days,
                batch_size=batch_size
            )

            if success:
                success_count += 1
                logger.info(f"Задача {task_id} выполнена успешно")
            else:
                error_count += 1
                failed_tasks.append(task_id)
                logger.error(f"Задача {task_id} завершилась с ошибкой")

                if stop_on_error:
                    logger.info(f"Остановка выполнения из-за ошибки (--stop-on-error)")
                    break

        except Exception as e:
            error_count += 1
            failed_tasks.append(task_id)
            logger.error(f"Критическая ошибка при выполнении задачи {task_id}: {e}")

            if stop_on_error:
                logger.info(f"Остановка выполнения из-за ошибки (--stop-on-error)")
                break

        # Небольшая пауза между задачами (опционально)
        if i < len(task_id_list):
            import time
            time.sleep(1)
            print()  # Пустая строка между задачами

    # Итоговая статистика
    logger.info(f"--- ИТОГО ---")
    logger.info(f"Успешно выполнено: {success_count}/{len(task_id_list)}")
    logger.info(f"С ошибками: {error_count}/{len(task_id_list)}")

    if failed_tasks:
        logger.info(f"Задачи с ошибками: {', '.join(failed_tasks)}")

    if error_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    cli()