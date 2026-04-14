# interfaces/cli.py
import click
import logging
from uuid import UUID
from core.dataset_manager import IikoOlapDatasetManager
from core.task_loader import load_full_task_config

logger = logging.getLogger(__name__)


def validate_task_id(ctx, param, value):
    """Валидатор UUID"""
    try:
        return UUID(value)
    except ValueError:
        raise click.BadParameter("Invalid UUID format")


@click.group()
def cli():
    """CLI tool for managing iiko OLAP datasets using PostgreSQL configuration."""
    pass


@cli.command()
@click.argument('task_id', callback=validate_task_id)
def run_task(task_id: UUID):
    """
    Run a data loading task by its UUID.

    Example:
    python main.py run-task 123e4567-e89b-12d3-a456-426614174000
    """
    logger.info(f"Starting task execution: {task_id}")

    # Загружаем полную конфигурацию из БД
    config_dict = load_full_task_config(task_id)
    if not config_dict:
        raise click.ClickException(f"Task {task_id} not found, inactive, or has invalid references")

    # Создаём менеджер
    manager = IikoOlapDatasetManager(config_dict=config_dict)

    # Выполняем обновление
    success = manager.update_dataset()
    if success:
        click.echo(f"✅ Task {task_id} completed successfully")
    else:
        raise click.ClickException(f"Task {task_id} failed")


@cli.command()
@click.argument('task_id', callback=validate_task_id)
def create_dataset(task_id: UUID):
    """
    Create ClickHouse table based on task configuration (without loading data).
    """
    config_dict = load_full_task_config(task_id)
    if not config_dict:
        raise click.ClickException(f"Task {task_id} not found or invalid")

    manager = IikoOlapDatasetManager(config_dict=config_dict)
    fields = manager.generate_fields_config()
    success = manager.create_dataset(fields)
    if success:
        click.echo(f"✅ Dataset for task {task_id} created")
    else:
        raise click.ClickException(f"Failed to create dataset for task {task_id}")


@cli.command()
@click.argument('task_id', callback=validate_task_id)
def info(task_id: UUID):
    """
    Show dataset information for a given task.
    """
    config_dict = load_full_task_config(task_id)
    if not config_dict:
        raise click.ClickException(f"Task {task_id} not found or invalid")

    manager = IikoOlapDatasetManager(config_dict=config_dict)
    dataset_info = manager.get_dataset_info()
    if dataset_info:
        click.echo("Dataset info:")
        click.echo(f"  Name: {dataset_info['name']}")
        click.echo(f"  Rows: {dataset_info['row_count']}")
        dr = dataset_info['date_range']
        click.echo(f"  Date range: {dr['min']} – {dr['max']}")
        click.echo("  Fields:")
        for f in dataset_info['fields']:
            click.echo(f"    {f['name']}: {f['type']}")
    else:
        click.echo("Dataset not found or empty", err=True)


def main():
    try:
        cli()
    except Exception as e:
        logger.error(f"CLI error: {e}", exc_info=True)
        raise click.ClickException(str(e))