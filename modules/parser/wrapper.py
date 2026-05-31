"""Обёртка над universal map providers для вызова из app.py."""
from pathlib import Path
from threading import Event

from .providers import MapProviderConfig, run_map_provider


def run_parser(
    city: str,
    query: str,
    limit: int,
    sleep_range: tuple,
    save_raw: bool,
    output_path: str,
    log_callback,
    fetch_reviews: bool = False,
    provider: str = "2gis",
    api_key: str = "",
    locale: str = "ru_RU",
) -> dict:
    """Запускает парсер синхронно, возвращает dict с результатом."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    config = MapProviderConfig(
        provider=provider,
        city=city,
        query=query,
        limit=limit if limit else None,
        output_file=out,
        raw=save_raw,
        sleep_min=sleep_range[0],
        sleep_max=sleep_range[1],
        fetch_reviews=fetch_reviews,
        api_key=api_key,
        locale=locale,
    )

    stop_event = Event()
    try:
        result = run_map_provider(config, log=log_callback, stop_event=stop_event)
    except Exception as e:
        log_callback(f"❌ Ошибка парсера: {e}")
        return {"count": 0, "csv_path": str(out)}

    # Считаем строки в CSV
    count = 0
    if out.exists():
        with open(out, encoding="utf-8-sig") as f:
            count = sum(1 for _ in f) - 1  # минус заголовок

    return {"count": max(count, 0), "csv_path": str(out)}
