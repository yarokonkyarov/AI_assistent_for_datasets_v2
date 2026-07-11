# interfaces/web.py
import os
import sys
from typing import List, Optional
from uuid import UUID
import subprocess
from pathlib import Path
import shlex

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Task, IikoConnection, ClickHouseConnection, ReportTemplate, Category
from db.repository import (
    # A=>2=K5 DC=:F88
    get_task_by_id,
    get_iiko_connection,
    get_clickhouse_connection,
    get_report_template,
    list_tasks,
    list_iiko_connections,
    list_clickhouse_connections,
    list_report_templates,
    create_task,
    create_iiko_connection,
    create_clickhouse_connection,
    create_report_template,
    update_report_template,
    bulk_update_tasks_by_filter,
    update_iiko_connection,
    update_clickhouse_connection,
    update_task,

    # $C=:F88 4;O :0B53>@89
    get_category_by_id,
    get_category_by_name,
    list_categories,
    create_category,
    update_category,
    delete_category,
    get_categories_with_stats,
    get_tasks_with_details,

    # Функции для работы с категориями подключений
    update_iiko_connection_category
)
from db.repository import list_connections_for_weather

app = FastAPI(title="iiko Loader Admin")

# >4:;NG05< H01;>=K 8 AB0B8:C
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../web/templates"))
app.mount("/static", StaticFiles(directory="web/static"), name="static")


# interfaces/web.py - добавляем endpoint для массового запуска
@app.post("/tasks/bulk-run")
async def bulk_run_tasks(
        request: Request,
        task_ids: str = Form(...)
):
    """Запустить несколько задач"""
    try:
        # Разделяем ID задач
        task_id_list = [tid.strip() for tid in task_ids.split(',')]
        valid_tasks = []
        invalid_tasks = []

        from uuid import UUID

        # Проверяем валидность UUID
        for task_id in task_id_list:
            try:
                UUID(task_id)
                valid_tasks.append(task_id)
            except ValueError:
                invalid_tasks.append(task_id)

        if invalid_tasks:
            return RedirectResponse(
                url=f"/tasks?error=Неверный+формат+ID+задач: {','.join(invalid_tasks)}",
                status_code=303
            )

        if not valid_tasks:
            return RedirectResponse(
                url=f"/tasks?error=Нет+валидных+ID+задач",
                status_code=303
            )

        # Получаем абсолютный путь к корню проекта
        project_root = Path(__file__).parent.parent

        # Формируем команду
        task_ids_str = ",".join(valid_tasks)
        cmd = [sys.executable, "main.py", "run-task", task_ids_str]

        print(f"Массовый запуск {len(valid_tasks)} задач")
        print(f"Команда: {' '.join(cmd)}")

        # Запускаем процесс в фоновом режиме
        process = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        print(f"Процесс запущен (PID: {process.pid})")

        # Возвращаем успешный ответ
        return RedirectResponse(
            url=f"/tasks?success=Запущено+{len(valid_tasks)}+задач",
            status_code=303
        )

    except Exception as e:
        print(f"Ошибка массового запуска задач: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(
            url=f"/tasks?error=Ошибка+массового+запуска",
            status_code=303
        )

@app.post("/tasks/{task_id}/run")
async def run_task_endpoint(task_id: UUID):
    """Запустить задачу"""
    try:
        # Получаем абсолютный путь к корню проекта
        project_root = Path(__file__).parent.parent

        # Проверяем существование main.py
        main_py_path = project_root / "main.py"
        if not main_py_path.exists():
            return RedirectResponse(
                url=f"/tasks?error=Файл+main.py+не+найден",
                status_code=303
            )

        # Формируем команду как список аргументов
        cmd = [sys.executable, "main.py", "run-task", str(task_id)]

        print(f"Запуск команды: {' '.join(cmd)}")
        print(f"Рабочая директория: {project_root}")

        # Запускаем процесс в фоновом режиме
        process = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Не ждем завершения, чтобы не блокировать ответ
        # Процесс будет работать в фоне

        print(f"Процесс запущен (PID: {process.pid})")

        # Возвращаем успешный ответ
        return RedirectResponse(
            url=f"/tasks?success=Задача+запущена",
            status_code=303
        )

    except Exception as e:
        print(f"Ошибка запуска задачи {task_id}: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(
            url=f"/tasks?error=Ошибка+запуска",
            status_code=303
        )

@app.get("/categories", response_class=HTMLResponse)
async def categories_list(
        request: Request,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
):
    """!?8A>: :0B53>@89"""
    categories_with_stats = get_categories_with_stats()

    # @8<5=O5< D8;LB@K
    filtered_categories = []
    for cat in categories_with_stats:
        if is_active is not None and cat['is_active'] != is_active:
            continue
        if search and search.lower() not in cat['name'].lower() and \
                (not cat['description'] or search.lower() not in cat.get('description', '').lower()):
            continue
        filtered_categories.append(cat)

    return templates.TemplateResponse("categories.html", {
        "request": request,
        "categories": filtered_categories,
        "filters": {
            "is_active": is_active,
            "search": search
        }
    })


@app.get("/categories/new", response_class=HTMLResponse)
async def new_category_form(request: Request):
    """$>@<0 A>740=8O =>2>9 :0B53>@88"""
    return templates.TemplateResponse("category_form.html", {
        "request": request,
        "category": None
    })


@app.post("/categories", response_class=RedirectResponse)
async def create_category_post(
        request: Request,
        name: str = Form(...),
        description: Optional[str] = Form(None),
        color: Optional[str] = Form(None),
        is_active: bool = Form(True)
):
    """!>740BL =>2CN :0B53>@8N"""
    try:
        # @>25@O5<, ACI5AB2C5B ;8 :0B53>@8O A B0:8< 8<5=5<
        existing = get_category_by_name(name)
        if existing:
            return RedirectResponse(
                url="/categories?error=0B53>@8O A B0:8< 8<5=5< C65 ACI5AB2C5B",
                status_code=303
            )

        # !>7405< :0B53>@8N
        create_category(name, description, color, is_active)
        return RedirectResponse(
            url="/categories?success=0B53>@8O A>740=0",
            status_code=303
        )
    except Exception as e:
        print(f"Error creating category: {e}")
        return RedirectResponse(
            url="/categories?error=H81:0 ?@8 A>740=88 :0B53>@88",
            status_code=303
        )


@app.get("/categories/{category_id}/edit", response_class=HTMLResponse)
async def edit_category_form(request: Request, category_id: int):
    """$>@<0 @540:B8@>20=8O :0B53>@88"""
    category = get_category_by_id(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="0B53>@8O =5 =0945=0")

    # >;CG05< AB0B8AB8:C ?> ?>4:;NG5=8O<
    categories_with_stats = get_categories_with_stats()
    connection_count = 0
    for cat in categories_with_stats:
        if cat['id'] == category_id:
            connection_count = cat.get('connection_count', 0)
            break

    # >102;O5< :>;8G5AB2> ?>4:;NG5=89 : >1J5:BC :0B53>@88
    category_dict = category.dict()
    category_dict['connection_count'] = connection_count

    return templates.TemplateResponse("category_form.html", {
        "request": request,
        "category": category_dict
    })


@app.post("/categories/{category_id}/edit", response_class=RedirectResponse)
async def update_category_post(
        request: Request,
        category_id: int,
        name: str = Form(...),
        description: Optional[str] = Form(None),
        color: Optional[str] = Form(None),
        is_active: bool = Form(True)
):
    """1=>28BL :0B53>@8N"""
    try:
        # @>25@O5<, =5 ?KB05<AO ;8 87<5=8BL 8<O =0 C65 ACI5AB2CNI55
        if name:
            existing = get_category_by_name(name)
            if existing and existing.id != category_id:
                return RedirectResponse(
                    url=f"/categories?error=0B53>@8O A 8<5=5< '{name}' C65 ACI5AB2C5B",
                    status_code=303
                )

        success = update_category(category_id, name, description, color, is_active)
        if not success:
            return RedirectResponse(
                url=f"/categories?error=H81:0 >1=>2;5=8O :0B53>@88",
                status_code=303
            )

        return RedirectResponse(
            url="/categories?success=0B53>@8O >1=>2;5=0",
            status_code=303
        )
    except Exception as e:
        print(f"Error updating category: {e}")
        return RedirectResponse(
            url=f"/categories?error=H81:0 ?@8 >1=>2;5=88 :0B53>@88",
            status_code=303
        )


@app.post("/categories/{category_id}/delete", response_class=RedirectResponse)
async def delete_category_post(request: Request, category_id: int):
    """#40;8BL :0B53>@8N"""
    try:
        # @>25@O5<, 5ABL ;8 ?>4:;NG5=8O 2 :0B53>@88
        categories_with_stats = get_categories_with_stats()
        for cat in categories_with_stats:
            if cat['id'] == category_id and cat.get('connection_count', 0) > 0:
                return RedirectResponse(
                    url="/categories?error=52>7<>6=> C40;8BL :0B53>@8N A ?>4:;NG5=8O<8",
                    status_code=303
                )

        success = delete_category(category_id)
        if not success:
            return RedirectResponse(
                url="/categories?error=0B53>@8O =5 =0945=0",
                status_code=303
            )

        return RedirectResponse(
            url="/categories?success=0B53>@8O C40;5=0",
            status_code=303
        )
    except Exception as e:
        print(f"Error deleting category: {e}")
        return RedirectResponse(
            url="/categories?error=H81:0 ?@8 C40;5=88 :0B53>@88",
            status_code=303
        )


# ========== A=>2=K5 endpoint'K ==========

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return RedirectResponse(url="/tasks")


# interfaces/web.py - обновляем функцию tasks_list
@app.get("/tasks", response_class=HTMLResponse)
async def tasks_list(
        request: Request,
        iiko_name: Optional[str] = None,
        report_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        category_id: Optional[int] = None
):
    """Список задач с фильтрацией по категории"""
    try:
        # Используем функцию с деталями, которая загружает связанные объекты
        all_tasks = get_tasks_with_details(category_id=category_id, is_active=is_active)

        # Применяем дополнительные фильтры
        tasks = []
        for task in all_tasks:
            # Фильтр по имени iiko подключения
            if iiko_name and task.iiko_connection and task.iiko_connection.name != iiko_name:
                continue

            # Фильтр по имени шаблона отчета
            if report_name and task.report_template and task.report_template.name != report_name:
                continue

            tasks.append(task)

        # Получаем списки для фильтров
        iiko_list = list_iiko_connections()
        report_list = list_report_templates()
        categories = list_categories(is_active=True)

        return templates.TemplateResponse("tasks.html", {
            "request": request,
            "tasks": tasks,
            "iiko_list": iiko_list,
            "report_list": report_list,
            "categories": categories,
            "filters": {
                "iiko_name": iiko_name,
                "report_name": report_name,
                "is_active": is_active,
                "category_id": category_id
            }
        })
    except Exception as e:
        print(f"Error in tasks_list: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/new", response_class=HTMLResponse)
async def new_task_form(request: Request):
    iiko_list = list_iiko_connections()
    ch_list = list_clickhouse_connections()
    report_list = list_report_templates()
    return templates.TemplateResponse("task_form.html", {
        "request": request,
        "iiko_list": iiko_list,
        "ch_list": ch_list,
        "report_list": report_list,
        "task": None
    })


@app.post("/tasks", response_class=RedirectResponse)
async def create_task_post(
        request: Request,
        name: str = Form(...),
        iiko_connection_id: int = Form(...),
        clickhouse_connection_id: int = Form(...),
        report_template_id: int = Form(...),
        dataset_name: str = Form(...),
        days_offset_start: int = Form(14),
        days_offset_end: int = Form(0),
        is_active: bool = Form(False)
):
    task_id = create_task(
        name=name,
        iiko_connection_id=iiko_connection_id,
        clickhouse_connection_id=clickhouse_connection_id,
        report_template_id=report_template_id,
        dataset_name=dataset_name,
        days_offset_start=days_offset_start,
        days_offset_end=days_offset_end,
        is_active=is_active
    )
    return RedirectResponse(url="/tasks", status_code=303)


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def edit_task_form(request: Request, task_id: UUID):
    task = get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    iiko_list = list_iiko_connections()
    ch_list = list_clickhouse_connections()
    report_list = list_report_templates()
    return templates.TemplateResponse("task_form.html", {
        "request": request,
        "task": task,
        "iiko_list": iiko_list,
        "ch_list": ch_list,
        "report_list": report_list
    })


@app.post("/tasks/{task_id}/edit", response_class=RedirectResponse)
async def update_task_post(
        request: Request,
        task_id: UUID,
        name: str = Form(...),
        iiko_connection_id: int = Form(...),
        clickhouse_connection_id: int = Form(...),
        report_template_id: int = Form(...),
        dataset_name: str = Form(...),
        days_offset_start: int = Form(14),
        days_offset_end: int = Form(0),
        is_active: bool = Form(False)
):
    """1=>28BL 7040GC"""
    try:
        update_task(
            task_id=task_id,
            name=name,
            iiko_connection_id=iiko_connection_id,
            clickhouse_connection_id=clickhouse_connection_id,
            report_template_id=report_template_id,
            dataset_name=dataset_name,
            days_offset_start=days_offset_start,
            days_offset_end=days_offset_end,
            is_active=is_active
        )
        return RedirectResponse(url="/tasks", status_code=303)
    except Exception as e:
        print(f"Error updating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks/bulk-update", response_class=RedirectResponse)
async def bulk_update_tasks(
        request: Request,
        iiko_name_filter: Optional[str] = Form(None),
        report_name_filter: Optional[str] = Form(None),
        is_active_filter: Optional[bool] = Form(None),
        days_offset_start: int = Form(14),
        days_offset_end: int = Form(0)
):
    updated_count = bulk_update_tasks_by_filter(
        iiko_name=iiko_name_filter,
        report_name=report_name_filter,
        is_active=is_active_filter,
        days_offset_start=days_offset_start,
        days_offset_end=days_offset_end
    )
    print(f"Bulk updated {updated_count} tasks")
    return RedirectResponse(url="/tasks", status_code=303)


@app.get("/connections", response_class=HTMLResponse)
async def connections_list(request: Request):
    iiko_list = list_iiko_connections()
    ch_list = list_clickhouse_connections()
    return templates.TemplateResponse("connections.html", {
        "request": request,
        "iiko_list": iiko_list,
        "ch_list": ch_list
    })


@app.get("/connections/iiko/new", response_class=HTMLResponse)
async def new_iiko_form(request: Request):
    """$>@<0 A>740=8O ?>4:;NG5=8O iiko A 2K1>@>< :0B53>@88"""
    categories = list_categories(is_active=True)
    return templates.TemplateResponse("iiko_form.html", {
        "request": request,
        "categories": categories,
        "connection": None
    })


@app.post("/connections/iiko", response_class=RedirectResponse)
async def create_iiko_post(
        request: Request,
        name: str = Form(...),
        api_url: str = Form(...),
        login: str = Form(...),
        password: str = Form(...),
        currency: str = Form('RUB'),
        category_id: Optional[int] = Form(None),
        iiko_cloud_api_key: Optional[str] = Form(None),
        load_weather: bool = Form(False)
):
    """Создать подключение iiko"""
    try:
        create_iiko_connection(name, api_url, login, password, currency, category_id,
                               iiko_cloud_api_key, load_weather)
        return RedirectResponse(url="/connections", status_code=303)
    except Exception as e:
        print(f"Error creating iiko connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connections/iiko/{conn_id}/edit", response_class=HTMLResponse)
async def edit_iiko_form(request: Request, conn_id: int):
    """$>@<0 @540:B8@>20=8O ?>4:;NG5=8O iiko A 2K1>@>< :0B53>@88"""
    conn = get_iiko_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="iiko connection not found")

    categories = list_categories(is_active=True)
    return templates.TemplateResponse("iiko_form.html", {
        "request": request,
        "connection": conn,
        "categories": categories
    })


@app.post("/connections/iiko/{conn_id}/edit", response_class=RedirectResponse)
async def update_iiko_post(
        request: Request,
        conn_id: int,
        name: str = Form(...),
        api_url: str = Form(...),
        login: str = Form(...),
        password: str = Form(...),
        currency: str = Form('RUB'),
        category_id: Optional[int] = Form(None),
        iiko_cloud_api_key: Optional[str] = Form(None),
        load_weather: bool = Form(False)
):
    """Обновить подключение iiko"""
    try:
        update_iiko_connection(conn_id, name, api_url, login, password, currency, category_id,
                               iiko_cloud_api_key, load_weather)
        return RedirectResponse(url="/connections", status_code=303)
    except Exception as e:
        print(f"Error updating iiko connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connections/ch/new", response_class=HTMLResponse)
async def new_ch_form(request: Request):
    return templates.TemplateResponse("ch_form.html", {"request": request})


@app.post("/connections/ch", response_class=RedirectResponse)
async def create_ch_post(
        request: Request,
        name: str = Form(...),
        host: str = Form(...),
        port: int = Form(9000),
        user: str = Form(...),
        password: str = Form(...),
        storage_policy: str = Form("default")
):
    create_clickhouse_connection(
        name=name,
        host=host,
        port=port,
        user=user,
        password=password,
        storage_policy=storage_policy
    )
    return RedirectResponse(url="/connections", status_code=303)


# --- Edit ClickHouse connection ---
@app.get("/connections/ch/{conn_id}/edit", response_class=HTMLResponse)
async def edit_ch_form(request: Request, conn_id: int):
    conn = get_clickhouse_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="ClickHouse connection not found")
    return templates.TemplateResponse("ch_form.html", {"request": request, "connection": conn})


@app.post("/connections/ch/{conn_id}/edit", response_class=RedirectResponse)
async def update_ch_post(
        request: Request,
        conn_id: int,
        name: str = Form(...),
        host: str = Form(...),
        port: int = Form(9000),
        user: str = Form(...),
        password: str = Form(...),
        storage_policy: str = Form("default")
):
    update_clickhouse_connection(conn_id, name, host, port, user, password, storage_policy)
    return RedirectResponse(url="/connections", status_code=303)


@app.get("/templates", response_class=HTMLResponse)
async def templates_list(request: Request):
    templates_list = list_report_templates()
    return templates.TemplateResponse("templates.html", {
        "request": request,
        "templates": templates_list
    })


@app.get("/templates/new", response_class=HTMLResponse)
async def new_template_form(request: Request):
    return templates.TemplateResponse("template_form.html", {"request": request})


@app.post("/templates", response_class=RedirectResponse)
async def create_template_post(
        request: Request,
        name: str = Form(...),
        default_report_config: str = Form(...)
):
    import json
    config_dict = json.loads(default_report_config)
    create_report_template(name=name, default_report_config=config_dict)
    return RedirectResponse(url="/templates", status_code=303)


@app.get("/templates/{template_id}/edit", response_class=HTMLResponse)
async def edit_template_form(request: Request, template_id: int):
    import json
    tpl = get_report_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    return templates.TemplateResponse("template_form.html", {
        "request": request,
        "template": tpl,
        "config_json": json.dumps(tpl.default_report_config, ensure_ascii=False, indent=2)
    })


@app.post("/templates/{template_id}", response_class=RedirectResponse)
async def update_template_post(
        request: Request,
        template_id: int,
        name: str = Form(...),
        default_report_config: str = Form(...)
):
    import json
    if not get_report_template(template_id):
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    config_dict = json.loads(default_report_config)
    update_report_template(template_id, name=name, default_report_config=config_dict)
    return RedirectResponse(url="/templates", status_code=303)