# db/models.py - обновляем модель Category
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field, validator


class Category(BaseModel):
    """Модель категории для группировки подключений"""
    id: int
    name: str = Field(..., min_length=1, max_length=100, description="Название категории")
    description: Optional[str] = Field(None, description="Описание категории")
    color: Optional[str] = Field(
        None,
        pattern='^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$',
        description="HEX цвет, например #FF5733"
    )
    is_active: bool = Field(True, description="Активна ли категория")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


class IikoConnection(BaseModel):
    id: int
    name: str
    api_url: str
    login: str
    password: str
    currency: str = Field('RUB', description="Валюта подключения: RUB, GEL, AMD ...")

    # Добавляем связь с категорией
    category_id: Optional[int] = Field(None, description="ID категории")
    category: Optional[Category] = Field(None, description="Объект категории")

    created_at: datetime

    class Config:
        from_attributes = True


class IikoConnectionCreate(BaseModel):
    """Модель для создания подключения iiko"""
    name: str = Field(..., min_length=1, max_length=100)
    api_url: str
    login: str
    password: str
    currency: str = Field('RUB', description="Валюта подключения")
    category_id: Optional[int] = None


class IikoConnectionUpdate(BaseModel):
    """Модель для обновления подключения iiko"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    api_url: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None
    currency: Optional[str] = None
    category_id: Optional[int] = None


class ClickHouseConnection(BaseModel):
    id: int
    name: str
    host: str
    port: int
    user: str
    password: str
    storage_policy: str
    created_at: datetime

    class Config:
        from_attributes = True


class ReportTemplate(BaseModel):
    id: int
    name: str  # pl1, pl2, pl5...
    default_report_config: dict
    created_at: datetime

    class Config:
        from_attributes = True


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    iiko_connection_id: int
    clickhouse_connection_id: int
    report_template_id: int
    dataset_name: str
    days_offset_start: int
    days_offset_end: int
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Виртуальные поля для удобства (будут заполняться при запросе)
    iiko_connection: Optional[IikoConnection] = Field(None, description="Объект подключения iiko")
    clickhouse_connection: Optional[ClickHouseConnection] = Field(None, description="Объект подключения ClickHouse")
    report_template: Optional[ReportTemplate] = Field(None, description="Объект шаблона отчета")

    class Config:
        from_attributes = True


# Модели для API схем
class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern='^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern='^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$')
    is_active: Optional[bool] = None