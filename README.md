# asyncio-tools

**asyncio-tools** — это маленькая, самодостаточная однофайловая библиотека (`asyncio_tools.py`)  
для удобной работы с асинхронными задачами в Python.

Фокус: **параллельный запуск**, **ограничение concurrency**, **таймауты**,  
**retry**, **batching**, **гонки задач**, **периодические задачи**,  
и безопасное завершение корутин.

Библиотека не имеет зависимостей, полностью на стандартной библиотеке (`asyncio`).

---

## 🚀 Возможности

### ✔ Универсальный запуск задач
```python
from asyncio_tools import run_tasks

summary = await run_tasks(tasks, parallel=True, stop_on_error=False, limit=50)
````

* `parallel=True/False` — параллельный или последовательный запуск
* `stop_on_error=True` — останавливает все при первой ошибке
* `limit=50` — ограничитель concurrency

Возвращает структуру:

```python
RunSummary(
    results = [...],         # результаты (failed → None)
    errors = [(index, exc)], # все ошибки
    cancelled = bool         # были ли отмены
)
```

---

### ✔ Повторная попытка (retry)

```python
from asyncio_tools import retry

result = await retry(fetch(), retries=3, delay=0.5, backoff=2.0)
```

---

### ✔ Таймаут

```python
from asyncio_tools import with_timeout

result = await with_timeout(fetch(), timeout=3.0)
```

---

### ✔ Гонка задач (race)

Возвращает первый результат — остальные отменяет.

```python
from asyncio_tools import race

result, index = await race([task1(), task2(), task3()])
```

---

### ✔ Первый успешный результат

Если все упали — FirstSuccessError.

```python
from asyncio_tools import wait_first

answer = await wait_first([probe_1(), probe_2(), probe_3()])
```

---

### ✔ Ограничение concurrency (sugar)

```python
from asyncio_tools import limit_concurrency

summary = await limit_concurrency(tasks, limit=20)
```

---

### ✔ Асинхронный worker-pool (consume)

```python
from asyncio_tools import consume

await consume(urls, worker=fetch_url, limit=50)
```

---

### ✔ Периодическая задача

```python
from asyncio_tools import run_periodic

task = run_periodic(refresh_cache, interval=10.0)
# task.cancel() чтобы остановить
```

---

### ✔ Глобальный таймаут для всех задач

```python
from asyncio_tools import timeout_or_cancel
```

---

### ✔ Замер времени

```python
from asyncio_tools import measure
result, seconds = await measure(job())
```

---

### ✔ Чанки

```python
from asyncio_tools import chunked

for batch in chunked(urls, 100):
    ...
```

---

## 📦 Установка

### Через GitHub

```
pip install git+https://github.com/megamen32/asyncio-tools
```

### Локально

```
pip install .
```

---

## 📁 Структура проекта

```
asyncio-tools/
  asyncio_tools.py     # <-- основной файл-библиотека
  README.md
  pyproject.toml
```

---

## 📝 Лицензия

MIT
