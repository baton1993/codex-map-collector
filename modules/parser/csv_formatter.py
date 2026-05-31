# -*- coding: utf-8 -*-
"""
Финальный слой приложения: превращает полный CSV парсера в чистый рабочий CSV.

Принцип:
  - parser_core.py собирает максимум, как и раньше;
  - этот модуль НЕ режет сбор, а только собирает финальную таблицу по галочкам;
  - поле "Сайт" в финальном CSV = только сайт компании, без 2GIS-редиректов,
    Telegram, WhatsApp, VK и прочих соцсетей;
  - мессенджеры/соцсети раскладываются по отдельным колонкам;
  - исходные сырые поля тоже доступны отдельными галочками.

Отдельный запуск:
  python csv_formatter.py exports/full.csv exports/final.csv --standard
  python csv_formatter.py exports/full.csv exports/final.csv --fields Название Сайт Адрес WhatsApp Email 2GIS_ссылка
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable, List, Dict, Any, Tuple, Optional
from urllib.parse import urlparse, unquote

# Полные поля, которые даёт базовый парсер.
BASE_FIELDS = [
    "Название", "Полное_название", "Рубрики", "Адрес", "Доп_адрес",
    "Округ", "Микрорайон", "Телефоны", "Сайт", "Email", "Соцсети",
    "Рейтинг", "Кол-во_отзывов", "Средний_счёт", "Удобства",
    "Часы_работы", "Координаты", "2GIS_ссылка", "ID", "Описание",
]

# Служебные/вычисляемые поля. Они появляются в итоговой таблице по галочкам,
# но не требуют менять сам сбор данных.
DERIVED_FIELDS = [
    "Сайт_компании", "Сайт_из_парсера", "Сайт_исходный",
    "Телефон_1", "Телефон_2", "Телефон_3", "Телефон_4", "Телефон_5",
    "WhatsApp", "WhatsApp_номер", "WhatsApp_ссылка",
    "Max", "Max_ссылка",
    "Telegram", "Telegram_личный", "Telegram_канал", "Telegram_бот", "Telegram_прочее",
    "Viber", "VK", "Instagram", "Facebook", "YouTube", "OK", "Twitter_X",
    "Мессенджеры_все", "Соцсети_все", "Соцсети_прочее",
    "2GIS_служебные_ссылки", "Внешние_ссылки_прочее",
]

# Все поля для галочек. Важно: здесь есть и полные исходные поля, и чистые вычисляемые.
AVAILABLE_FIELDS = [
    "Название", "Полное_название", "Рубрики",
    "Адрес", "Доп_адрес", "Округ", "Микрорайон",
    "Сайт", "Сайт_компании", "Сайт_из_парсера", "Сайт_исходный",
    "Email", "Телефоны", "Телефон_1", "Телефон_2", "Телефон_3", "Телефон_4", "Телефон_5",
    "WhatsApp", "WhatsApp_номер", "WhatsApp_ссылка",
    "Max", "Max_ссылка",
    "Telegram", "Telegram_личный", "Telegram_канал", "Telegram_бот", "Telegram_прочее",
    "Viber", "VK", "Instagram", "Facebook", "YouTube", "OK", "Twitter_X",
    "Мессенджеры_все", "Соцсети_все", "Соцсети", "Соцсети_прочее",
    "2GIS_ссылка", "2GIS_служебные_ссылки", "Внешние_ссылки_прочее",
    "Рейтинг", "Кол-во_отзывов", "Средний_счёт", "Удобства", "Часы_работы",
    "Координаты", "ID", "Описание",
]

# Стандарт: чистая таблица для работы/прозвона.
STANDARD_FIELDS = [
    "Название", "Сайт", "Адрес",
    "WhatsApp", "Max", "Telegram_личный", "Telegram_канал", "Viber",
    "VK", "Instagram", "Facebook", "YouTube", "OK",
    "Email", "Телефон_1", "Телефоны", "2GIS_ссылка",
]

FIELD_GROUPS = [
    {"title": "Основное", "fields": ["Название", "Полное_название", "Рубрики", "Адрес", "Доп_адрес", "Округ", "Микрорайон"]},
    {"title": "Сайты и ссылки", "fields": ["Сайт", "Сайт_компании", "Сайт_из_парсера", "Сайт_исходный", "2GIS_ссылка", "2GIS_служебные_ссылки", "Внешние_ссылки_прочее"]},
    {"title": "Телефоны и почта", "fields": ["Телефоны", "Телефон_1", "Телефон_2", "Телефон_3", "Телефон_4", "Телефон_5", "Email"]},
    {"title": "Мессенджеры", "fields": ["WhatsApp", "WhatsApp_номер", "WhatsApp_ссылка", "Max", "Max_ссылка", "Telegram", "Telegram_личный", "Telegram_канал", "Telegram_бот", "Telegram_прочее", "Viber", "Мессенджеры_все"]},
    {"title": "Соцсети", "fields": ["VK", "Instagram", "Facebook", "YouTube", "OK", "Twitter_X", "Соцсети_все", "Соцсети", "Соцсети_прочее"]},
    {"title": "2GIS и карточка", "fields": ["Рейтинг", "Кол-во_отзывов", "Средний_счёт", "Удобства", "Часы_работы", "Координаты", "ID", "Описание"]},
]

FIELD_LABELS = {
    "Сайт": "Сайт компании (чистый)",
    "Сайт_компании": "Сайт компании",
    "Сайт_из_парсера": "Сайт из 2GIS как пришёл",
    "Сайт_исходный": "Сайт исходный/raw",
    "2GIS_ссылка": "Ссылка на 2GIS",
    "2GIS_служебные_ссылки": "Служебные ссылки 2GIS",
    "Кол-во_отзывов": "Кол-во отзывов",
    "Средний_счёт": "Средний счёт",
    "Полное_название": "Полное название",
    "Доп_адрес": "Доп. адрес",
    "Соцсети_прочее": "Прочие соцсети",
    "Телефон_1": "Телефон 1",
    "Телефон_2": "Телефон 2",
    "Телефон_3": "Телефон 3",
    "Телефон_4": "Телефон 4",
    "Телефон_5": "Телефон 5",
    "WhatsApp_номер": "WhatsApp номер",
    "WhatsApp_ссылка": "WhatsApp ссылка",
    "Max_ссылка": "Max ссылка",
    "Telegram": "Telegram все",
    "Telegram_личный": "Telegram личный/аккаунт",
    "Telegram_канал": "Telegram канал/инвайт",
    "Telegram_бот": "Telegram бот",
    "Telegram_прочее": "Telegram прочее",
    "Twitter_X": "Twitter / X",
    "Мессенджеры_все": "Все мессенджеры",
    "Соцсети_все": "Все соцсети",
}

SOCIAL_ALIASES = {
    "whatsapp": "WhatsApp", "wa": "WhatsApp",
    "max": "Max",
    "telegram": "Telegram", "tg": "Telegram",
    "viber": "Viber",
    "vkontakte": "VK", "vk": "VK",
    "instagram": "Instagram", "inst": "Instagram",
    "facebook": "Facebook", "fb": "Facebook",
    "youtube": "YouTube", "youtu": "YouTube",
    "ok": "OK", "odnoklassniki": "OK",
    "twitter": "Twitter_X", "x": "Twitter_X",
}

COMPANY_SITE_EXCLUDE_DOMAINS = {
    "2gis.ru", "www.2gis.ru", "link.2gis.ru", "go.2gis.com", "dgis.ru", "www.dgis.ru",
    "wa.me", "www.wa.me", "whatsapp.com", "www.whatsapp.com", "api.whatsapp.com",
    "t.me", "telegram.me", "telegram.dog", "www.t.me", "www.telegram.me",
    "vk.com", "www.vk.com", "vkontakte.ru", "www.vkontakte.ru",
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "fb.com", "www.fb.com",
    "youtube.com", "www.youtube.com", "youtu.be", "www.youtu.be",
    "ok.ru", "www.ok.ru",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "viber.com", "www.viber.com", "viber.click", "www.viber.click",
    "max.ru", "www.max.ru", "max.com", "www.max.com",
}


def _uniq(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for v in values:
        v = str(v or "").strip()
        if not v:
            continue
        key = v.lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def join(values: Iterable[str]) -> str:
    return "; ".join(_uniq(values))


def normalize_fields(fields: Iterable[str] | None) -> List[str]:
    src = list(fields or STANDARD_FIELDS)
    out: List[str] = []
    available = set(AVAILABLE_FIELDS)
    for f in src:
        f = str(f).strip()
        if f in available and f not in out:
            out.append(f)
    return out or list(STANDARD_FIELDS)


def split_semicolon(value: str) -> List[str]:
    # В 2GIS такие поля обычно разделены "; ". URL query с %3B не ломается.
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def split_phones(value: str) -> List[str]:
    phones = []
    for p in split_semicolon(value):
        p = re.sub(r"\s+", "", p)
        if p and p not in phones:
            phones.append(p)
    return phones


def _ensure_url(value: str) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*://", v, re.I):
        return v
    if re.match(r"^[\w.-]+\.[a-zа-я]{2,}(/|$)", v, re.I):
        return "https://" + v
    return v


def _host(value: str) -> str:
    v = _ensure_url(value)
    try:
        p = urlparse(v)
        return (p.netloc or "").lower().split("@").pop().split(":")[0].lstrip("www.")
    except Exception:
        return ""


def _path(value: str) -> str:
    try:
        return unquote(urlparse(_ensure_url(value)).path or "").strip("/")
    except Exception:
        return ""


def _is_2gis_url(value: str) -> bool:
    h = _host(value)
    return bool(h and (h.endswith("2gis.ru") or h.endswith("dgis.ru") or h == "go.2gis.com"))


def _is_company_site(value: str) -> bool:
    v = str(value or "").strip()
    if not v:
        return False
    h = _host(v)
    if not h:
        return False
    if any(h == d or h.endswith("." + d) for d in COMPANY_SITE_EXCLUDE_DOMAINS):
        return False
    # link.2gis.ru и похожие редиректы не считаем сайтом компании.
    if "2gis" in h or "dgis" in h:
        return False
    return True


def _classify_by_url(value: str) -> Optional[str]:
    v = str(value or "").strip()
    low = v.lower()
    h = _host(v)

    if not v:
        return None
    if low.startswith("viber://") or h.endswith("viber.com") or h.endswith("viber.click"):
        return "Viber"
    if h in {"wa.me", "whatsapp.com", "api.whatsapp.com"} or h.endswith(".whatsapp.com"):
        return "WhatsApp"
    if h in {"t.me", "telegram.me", "telegram.dog"} or h.endswith(".telegram.org"):
        return "Telegram"
    if h in {"vk.com", "vkontakte.ru"}:
        return "VK"
    if h in {"instagram.com"}:
        return "Instagram"
    if h in {"facebook.com", "fb.com"}:
        return "Facebook"
    if h in {"youtube.com", "youtu.be"}:
        return "YouTube"
    if h in {"ok.ru"}:
        return "OK"
    if h in {"twitter.com", "x.com"}:
        return "Twitter_X"
    if h in {"max.ru", "max.com"} or "maxmessenger" in h:
        return "Max"
    return None


def _telegram_bucket(value: str) -> str:
    """Грубая, но полезная классификация Telegram.
    Канал/личный по одной ссылке определить идеально нельзя: t.me/name может быть и человеком,
    и каналом. Поэтому явные канальные признаки идут в канал, bot — в бот,
    простой username — в личный/аккаунт.
    """
    p = _path(value).lower()
    if not p:
        return "Telegram_прочее"
    first = p.split("/")[0]
    if first.endswith("bot") or "/bot" in p:
        return "Telegram_бот"
    if first in {"joinchat", "c", "s"} or first.startswith("+") or "joinchat" in p:
        return "Telegram_канал"
    return "Telegram_личный"


def _whatsapp_number(value: str) -> str:
    h = _host(value)
    p = _path(value)
    if h == "wa.me" and p:
        m = re.search(r"\d{7,15}", p)
        return "+" + m.group(0) if m else ""
    m = re.search(r"(?:phone=|/send/|/)(\d{7,15})", value)
    return "+" + m.group(1) if m else ""


def _parse_social_entries(value: str) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for raw in split_semicolon(value):
        if ":" in raw:
            typ, val = raw.split(":", 1)
            entries.append((typ.strip().lower(), val.strip()))
        elif raw:
            entries.append(("", raw.strip()))
    return entries


def enrich_row(row: Dict[str, Any]) -> Dict[str, str]:
    new = {k: str(v or "") for k, v in row.items()}

    raw_site = new.get("Сайт", "")
    new["Сайт_из_парсера"] = raw_site
    new["Сайт_исходный"] = raw_site

    phones = split_phones(new.get("Телефоны", ""))
    for idx in range(5):
        new[f"Телефон_{idx + 1}"] = phones[idx] if idx < len(phones) else ""

    buckets: Dict[str, List[str]] = {
        "company_sites": [], "2gis_internal": [], "other_links": [],
        "WhatsApp": [], "WhatsApp_номер": [], "WhatsApp_ссылка": [],
        "Max": [], "Max_ссылка": [],
        "Telegram": [], "Telegram_личный": [], "Telegram_канал": [], "Telegram_бот": [], "Telegram_прочее": [],
        "Viber": [], "VK": [], "Instagram": [], "Facebook": [], "YouTube": [], "OK": [], "Twitter_X": [],
        "Соцсети_прочее": [],
    }

    def add_contact(value: str, explicit_type: str = ""):
        value = str(value or "").strip()
        if not value:
            return
        typ = SOCIAL_ALIASES.get((explicit_type or "").strip().lower())
        typ = typ or _classify_by_url(value)

        if _is_2gis_url(value):
            buckets["2gis_internal"].append(value)
            return

        if typ == "WhatsApp":
            buckets["WhatsApp"].append(value)
            buckets["WhatsApp_ссылка"].append(value)
            num = _whatsapp_number(value)
            if num:
                buckets["WhatsApp_номер"].append(num)
            return

        if typ == "Max":
            buckets["Max"].append(value)
            buckets["Max_ссылка"].append(value)
            return

        if typ == "Telegram":
            buckets["Telegram"].append(value)
            buckets[_telegram_bucket(value)].append(value)
            return

        if typ in {"Viber", "VK", "Instagram", "Facebook", "YouTube", "OK", "Twitter_X"}:
            buckets[typ].append(value)
            return

        if _is_company_site(value):
            buckets["company_sites"].append(value)
        elif re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I) or _host(value):
            buckets["other_links"].append(value)
        else:
            buckets["Соцсети_прочее"].append(value if not explicit_type else f"{explicit_type}:{value}")

    # 1) Классифицируем "Сайт" из полного CSV. Если туда залетел 2GIS/Telegram/WhatsApp —
    # он уйдет в правильную колонку, а не останется в чистом сайте.
    for part in split_semicolon(raw_site):
        add_contact(part, "")

    # 2) Классифицируем поле "Соцсети" формата type:value.
    for typ, val in _parse_social_entries(new.get("Соцсети", "")):
        add_contact(val, typ)

    # 3) Заполняем чистые поля.
    company_site = join(buckets["company_sites"])
    new["Сайт"] = company_site
    new["Сайт_компании"] = company_site
    new["2GIS_служебные_ссылки"] = join(buckets["2gis_internal"])
    new["Внешние_ссылки_прочее"] = join(buckets["other_links"])

    for key in [
        "WhatsApp", "WhatsApp_номер", "WhatsApp_ссылка",
        "Max", "Max_ссылка",
        "Telegram", "Telegram_личный", "Telegram_канал", "Telegram_бот", "Telegram_прочее",
        "Viber", "VK", "Instagram", "Facebook", "YouTube", "OK", "Twitter_X", "Соцсети_прочее",
    ]:
        new[key] = join(buckets[key])

    messenger_values = []
    for key in ["WhatsApp", "Max", "Telegram", "Viber"]:
        messenger_values.extend(buckets[key])
    social_values = []
    for key in ["VK", "Instagram", "Facebook", "YouTube", "OK", "Twitter_X"]:
        social_values.extend(buckets[key])
    new["Мессенджеры_все"] = join(messenger_values)
    new["Соцсети_все"] = join(social_values)

    return new


def read_preview(csv_path: Path, limit: int = 100) -> Dict[str, Any]:
    if not csv_path.exists():
        return {"columns": [], "rows": []}
    rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        for i, row in enumerate(reader):
            if i >= limit:
                break
            rows.append(row)
    return {"columns": cols, "rows": rows}


def format_csv(source_csv: Path, output_csv: Path, fields: Iterable[str] | None = None) -> Dict[str, Any]:
    source_csv = Path(source_csv)
    output_csv = Path(output_csv)
    selected = normalize_fields(fields)

    if not source_csv.exists():
        raise FileNotFoundError(f"Полный CSV не найден: {source_csv}")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with source_csv.open("r", encoding="utf-8-sig", newline="") as src, output_csv.open("w", encoding="utf-8-sig", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=selected, extrasaction="ignore")
        writer.writeheader()
        for row in reader:
            enriched = enrich_row(row)
            writer.writerow({field: enriched.get(field, "") for field in selected})
            count += 1

    preview = read_preview(output_csv, 100)
    return {
        "rows": count,
        "fields": selected,
        "csv": str(output_csv),
        "preview_cols": preview["columns"],
        "preview": preview["rows"],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Форматирует полный CSV 2GIS в чистый финальный CSV")
    p.add_argument("source_csv", help="Полный CSV, который собрал парсер")
    p.add_argument("output_csv", help="Финальный CSV")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--standard", action="store_true", help="Стандартные колонки")
    grp.add_argument("--fields", nargs="+", help="Список колонок")
    args = p.parse_args()

    fields = STANDARD_FIELDS if args.standard or not args.fields else args.fields
    result = format_csv(Path(args.source_csv), Path(args.output_csv), fields)
    print(f"Готово: {result['csv']}")
    print(f"Строк: {result['rows']}")
    print("Колонки: " + ", ".join(result["fields"]))


if __name__ == "__main__":
    main()
