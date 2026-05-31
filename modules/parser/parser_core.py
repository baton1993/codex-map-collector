# -*- coding: utf-8 -*-
"""Official 2GIS API provider for the local web app."""

from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx

REVIEWS_API_KEY = os.getenv("DGIS_REVIEWS_API_KEY", "")
API_URL = "https://catalog.api.2gis.ru/3.0/items"
REGION_URL = "https://catalog.api.2gis.ru/2.0/region/search"

CITY_SLUGS = {
    "анапа": "anapa", "краснодар": "krasnodar", "сочи": "sochi",
    "москва": "moscow", "санкт-петербург": "saint-petersburg",
    "спб": "saint-petersburg", "питер": "saint-petersburg",
    "ростов-на-дону": "rostov-on-don", "ростов": "rostov-on-don",
    "новороссийск": "novorossiysk", "екатеринбург": "yekaterinburg",
    "новосибирск": "novosibirsk", "казань": "kazan",
    "нижний новгород": "nizhny-novgorod", "самара": "samara",
    "омск": "omsk", "челябинск": "chelyabinsk", "уфа": "ufa",
    "волгоград": "volgograd", "пермь": "perm", "красноярск": "krasnoyarsk",
    "воронеж": "voronezh", "саратов": "saratov", "тюмень": "tyumen",
    "владивосток": "vladivostok", "хабаровск": "khabarovsk",
    "иркутск": "irkutsk", "ставрополь": "stavropol",
    "симферополь": "simferopol", "севастополь": "sevastopol",
    "калининград": "kaliningrad", "тула": "tula", "ярославль": "yaroslavl",
    "астрахань": "astrakhan", "белгород": "belgorod", "пенза": "penza",
    "курск": "kursk", "рязань": "ryazan", "тверь": "tver",
    "киров": "kirov", "барнаул": "barnaul", "томск": "tomsk",
    "кемерово": "kemerovo", "оренбург": "orenburg", "ульяновск": "ulyanovsk",
    "иваново": "ivanovo", "брянск": "bryansk", "владимир": "vladimir",
    "липецк": "lipetsk", "сургут": "surgut", "магнитогорск": "magnitogorsk",
    "нижневартовск": "nizhnevartovsk", "таганрог": "taganrog", "армавир": "armavir",
    "геленджик": "gelendzhik", "туапсе": "tuapse", "темрюк": "temryuk",
}

CITY_BBOX = {
    "anapa":        ("37.15,45.05", "37.55,44.75"),
    "krasnodar":    ("38.78,45.16", "39.15,44.92"),
    "sochi":        ("39.55,43.75", "40.35,43.35"),
    "rostov-on-don":("39.45,47.40", "40.00,47.10"),
    "novorossiysk": ("37.65,44.90", "38.10,44.60"),
    "gelendzhik":   ("38.00,44.65", "38.30,44.45"),
    # Для крупных городов лучше держать ручные bbox, иначе авто-коробка вокруг центра будет тесной.
    "moscow":       ("36.80,56.05", "38.05,55.25"),
    "saint-petersburg": ("29.40,60.25", "30.90,59.55"),
}

PAGE_SIZE = 50
MAX_PAGES = 100
SLEEP_BETWEEN_PAGES = (2, 6)
SLEEP_ON_BLOCK = 60
MAX_ATTEMPTS = 3
MIN_RESULTS_WARN = 5

FIELDS = ",".join([
    "items.point", "items.adm_div", "items.address", "items.contact_groups",
    "items.schedule", "items.reviews", "items.rubrics", "items.org",
    "items.flags", "items.description", "items.attribute_groups", "items.name_ex",
])

DAYS_RU = {"Mon": "Пн", "Tue": "Вт", "Wed": "Ср", "Thu": "Чт", "Fri": "Пт", "Sat": "Сб", "Sun": "Вс"}
DAYS_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CSV_HEADERS = [
    "Название", "Полное_название", "Рубрики", "Адрес", "Доп_адрес",
    "Округ", "Микрорайон", "Телефоны", "Сайт", "Email", "Соцсети",
    "Рейтинг", "Кол-во_отзывов", "Средний_счёт", "Удобства",
    "Часы_работы", "Координаты", "2GIS_ссылка", "ID", "Описание", "Отзывы 2GIS",
]


@dataclass
class ParserConfig:
    city: str
    query: str
    limit: Optional[int]
    output_file: Path
    raw: bool = False
    sleep_min: float = 2
    sleep_max: float = 6
    fetch_reviews: bool = False
    api_key: str = ""


def city_to_slug(city_input: str) -> str:
    return CITY_SLUGS.get(city_input.strip().lower(), city_input.strip())


def safe_filename(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|\s]+', "_", s).strip("_")

SOCIAL_TYPES = {"instagram", "vkontakte", "vk", "facebook", "telegram", "whatsapp", "viber", "youtube", "ok", "twitter", "x", "max"}
SOCIAL_HOST_TO_TYPE = {
    "wa.me": "whatsapp", "whatsapp.com": "whatsapp", "api.whatsapp.com": "whatsapp",
    "t.me": "telegram", "telegram.me": "telegram", "telegram.dog": "telegram",
    "vk.com": "vk", "vkontakte.ru": "vk",
    "instagram.com": "instagram",
    "facebook.com": "facebook", "fb.com": "facebook",
    "youtube.com": "youtube", "youtu.be": "youtube",
    "ok.ru": "ok",
    "twitter.com": "twitter", "x.com": "twitter",
    "viber.com": "viber", "viber.click": "viber",
    "max.ru": "max", "max.com": "max",
    "taplink.cc": "taplink", "taplink.ru": "taplink", "taplink.me": "taplink",
    "linktr.ee": "taplink", "linkinbio.com": "taplink", "beacons.ai": "taplink",
}


def _host(value: str) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", v, re.I) and re.match(r"^[\w.-]+\.[a-zа-я]{2,}(/|$)", v, re.I):
        v = "https://" + v
    try:
        return (urlparse(v).netloc or "").lower().split("@").pop().split(":")[0].lstrip("www.")
    except Exception:
        return ""


def _classify_link(value: str) -> str:
    """Возвращает тип для ссылок, которые 2GIS иногда отдаёт как website.
    Нужно, чтобы Telegram/WhatsApp/2GIS-редиректы не забивали поле Сайт.
    """
    low = str(value or "").strip().lower()
    h = _host(value)
    if low.startswith("viber://"):
        return "viber"
    if h.endswith("2gis.ru") or h.endswith("dgis.ru") or h == "go.2gis.com":
        return "2gis_internal"
    for domain, typ in SOCIAL_HOST_TO_TYPE.items():
        if h == domain or h.endswith("." + domain):
            return typ
    return "website" if h else "other"



class ParserRunner:
    def __init__(self, config: ParserConfig, log: Callable[[str], None], stop_event: Event):
        self.config = config
        self.log = log
        self.stop_event = stop_event
        self.city_slug = city_to_slug(config.city)
        self.search_query = config.query

    def _api_headers(self) -> dict:
        return {
            "User-Agent": "CodexMapCollector/1.0 (+https://github.com/baton1993/codex-map-collector)",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def http_get(self, url: str, params: dict):
        try:
            with httpx.Client(http2=True, timeout=30, headers=self._api_headers(), follow_redirects=True) as cli:
                r = cli.get(url, params=params)
                if r.status_code not in (200, 403, 429):
                    return r.status_code, None
                try:
                    data = r.json()
                except Exception:
                    return r.status_code, None
                meta_code = data.get("meta", {}).get("code", r.status_code)
                if meta_code == 200:
                    return 200, data
                if r.status_code == 429:
                    return 429, None
                return meta_code, None
        except Exception as e:
            self.log(f"[httpx] ошибка: {e}")
        return None, None

    def _validate_key(self, key: str) -> bool:
        if not key:
            return False
        p1, p2 = CITY_BBOX.get(self.city_slug, ("37.15,45.05", "37.55,44.75"))
        code, data = self.http_get(API_URL, {
            "q": self.search_query, "type": "branch", "page_size": 1,
            "point1": p1, "point2": p2, "key": key,
        })
        return code == 200 and data is not None

    def resolve_key(self) -> str:
        if not self.config.api_key:
            raise RuntimeError("2GIS provider requires an official API key. Set DGIS_API_KEY or enter it in the parser panel.")
        self.log("[ключ] проверяю ключ 2GIS из настроек...")
        if self._validate_key(self.config.api_key):
            self.log("[ключ] ключ 2GIS работает")
            return self.config.api_key
        raise RuntimeError("2GIS API key did not pass validation.")

    def resolve_bbox(self, key: str):
        if self.city_slug in CITY_BBOX:
            return CITY_BBOX[self.city_slug]
        code, data = self.http_get(REGION_URL, {"q": self.city_slug, "key": key})
        if code == 200 and data:
            items = (data.get("result") or {}).get("items") or []
            for it in items:
                centroid = it.get("centroid") or ""
                m = re.search(r"POINT\(([\d.]+)\s+([\d.]+)\)", centroid)
                if m:
                    lon, lat = float(m.group(1)), float(m.group(2))
                    d = 0.15
                    p1 = f"{lon - d:.4f},{lat + d:.4f}"
                    p2 = f"{lon + d:.4f},{lat - d:.4f}"
                    self.log(f"[bbox] построил коробку вокруг центра {self.city_slug}: {p1} | {p2}")
                    return p1, p2
        raise RuntimeError(f"Не знаю границ города '{self.city_slug}'. Добавь его в CITY_BBOX вручную.")

    def _extract_contacts(self, item):
        phones, site, email, socials = [], "", "", []
        for group in item.get("contact_groups", []) or []:
            for c in group.get("contacts", []) or []:
                t = (c.get("type") or "").strip().lower()
                val = c.get("value") or c.get("text") or c.get("url") or ""
                val = val.strip()
                if not val:
                    continue
                if t == "phone":
                    val = re.sub(r"[­\s]", "", val)
                    if val not in phones:
                        phones.append(val)
                elif t == "email" and not email:
                    email = val
                elif t in SOCIAL_TYPES:
                    entry = f"{t}:{val}"
                    if entry not in socials:
                        socials.append(entry)
                elif t == "website":
                    kind = _classify_link(val)
                    if kind == "website":
                        # Берём первым именно сайт компании. 2GIS-редиректы и Telegram сюда больше не попадают.
                        if not site:
                            site = val
                    else:
                        entry = f"{kind}:{val}"
                        if entry not in socials:
                            socials.append(entry)
                else:
                    # Не теряем неожиданный тип контакта. Пусть попадёт в поле Соцсети/прочее,
                    # а csv_formatter уже даст вывести его отдельной галочкой как прочее.
                    entry = f"{t or 'other'}:{val}"
                    if entry not in socials:
                        socials.append(entry)
        return "; ".join(phones), site, email, "; ".join(socials)

    def _extract_schedule(self, item):
        sched = item.get("schedule")
        if not sched:
            return ""
        if sched.get("is_24x7") or sched.get("is_24_7"):
            return "Круглосуточно"
        parts = []
        for day in DAYS_ORDER:
            d = sched.get(day)
            if not d:
                continue
            spans = [f"{h.get('from', '')}–{h.get('to', '')}" for h in (d.get("working_hours") or []) if h.get("from")]
            if spans:
                parts.append(f"{DAYS_RU[day]} {', '.join(spans)}")
        return "; ".join(parts)

    def _extract_adm(self, item):
        okrug, mkr = "", ""
        for div in item.get("adm_div", []) or []:
            t = div.get("type")
            if t == "district":
                okrug = div.get("name", "")
            elif t == "living_area":
                mkr = div.get("name", "")
        return okrug, mkr

    @staticmethod
    def _extract_rating(item):
        rev = item.get("reviews") or {}
        rating = rev.get("general_rating") or rev.get("org_rating") or ""
        count = rev.get("general_review_count") or rev.get("review_count") or rev.get("org_review_count") or ""
        return rating, count

    @staticmethod
    def _extract_rubrics(item):
        return ", ".join(r.get("name", "") for r in (item.get("rubrics") or []) if r.get("name"))

    @staticmethod
    def _extract_attributes(item):
        out, avg_bill = [], ""
        for g in item.get("attribute_groups", []) or []:
            for a in g.get("attributes", []) or []:
                aname = a.get("name", "")
                if not aname:
                    continue
                out.append(aname)
                low = aname.lower()
                if "средний счёт" in low or "средний счет" in low or "чек" in low:
                    avg_bill = aname
        return "; ".join(out), avg_bill

    def parse_item(self, item):
        name = item.get("name") or item.get("full_name") or ""
        full_name = item.get("full_name") or ""
        addr_obj = item.get("address") or {}
        address = item.get("address_name") or addr_obj.get("building_name") or ""
        addr_comment = item.get("address_comment") or addr_obj.get("comment") or ""
        phones, site, email, socials = self._extract_contacts(item)
        rating, count = self._extract_rating(item)
        okrug, mkr = self._extract_adm(item)
        attrs, avg_bill = self._extract_attributes(item)
        point = item.get("point") or {}
        coords = f'{point["lat"]},{point["lon"]}' if point.get("lat") and point.get("lon") else ""
        item_id = item.get("id", "")
        short_id = item_id.split("_")[0] if item_id else ""
        link = f"https://2gis.ru/{self.city_slug}/firm/{short_id}" if short_id else ""
        return {
            "Название": name,
            "Полное_название": full_name,
            "Рубрики": self._extract_rubrics(item),
            "Адрес": address,
            "Доп_адрес": addr_comment,
            "Округ": okrug,
            "Микрорайон": mkr,
            "Телефоны": phones,
            "Сайт": site,
            "Email": email,
            "Соцсети": socials,
            "Рейтинг": rating,
            "Кол-во_отзывов": count,
            "Средний_счёт": avg_bill,
            "Удобства": attrs,
            "Часы_работы": self._extract_schedule(item),
            "Координаты": coords,
            "2GIS_ссылка": link,
            "ID": short_id,
            "Описание": (item.get("description") or "")[:500],
            "Отзывы 2GIS": "",
        }

    def _fetch_reviews(self, branch_id: str) -> str:
        if not branch_id or not REVIEWS_API_KEY:
            return ""
        url = f"https://public-api.reviews.2gis.com/2.0/branches/{branch_id}/reviews"
        try:
            with httpx.Client(timeout=10, headers=self._api_headers()) as cli:
                resp = cli.get(url, params={
                    "limit": 5,
                    "sort_by": "date_edited",
                    "key": REVIEWS_API_KEY,
                    "fields": "reviews.user,reviews.text,reviews.rating,reviews.date_edited",
                })
            if resp.status_code != 200:
                return ""
            parts = []
            for rev in resp.json().get("reviews", []):
                text = str(rev.get("text") or "").strip()
                if len(text) < 5:
                    continue
                author = str((rev.get("user") or {}).get("name") or "Клиент").strip()
                rating = rev.get("rating", "")
                date = str(rev.get("date_edited") or "")[:10]
                parts.append(f"★{rating} {author} ({date}): {text[:200]}")
            return " | ".join(parts)
        except Exception:
            return ""

    @staticmethod
    def _dedup_key(row):
        name = re.sub(r"\s+", " ", (row["Название"] or "").strip().lower())
        addr = re.sub(r"\s+", " ", (row["Адрес"] or "").strip().lower())
        return name, addr

    def load_existing_keys(self, filename: Path):
        seen = set()
        if not filename.exists():
            return seen
        try:
            with filename.open("r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("Название") is not None:
                        seen.add(self._dedup_key(row))
        except Exception as e:
            self.log(f"[csv] не смог прочитать файл: {e}")
        return seen

    def save_to_csv(self, rows, filename: Path, seen):
        file_exists = filename.exists() and filename.stat().st_size > 0
        written = 0
        with filename.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if not file_exists:
                writer.writeheader()
            for row in rows:
                if not row["Название"]:
                    continue
                k = self._dedup_key(row)
                if k in seen:
                    continue
                seen.add(k)
                writer.writerow(row)
                written += 1
        return written

    def fetch_page(self, page_num, key, p1, p2):
        params = {
            "q": self.search_query, "type": "branch", "point1": p1, "point2": p2,
            "page": page_num, "page_size": PAGE_SIZE, "fields": FIELDS,
            "key": key, "locale": "ru_RU",
        }
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self.stop_event.is_set():
                return [], 0
            code, data = self.http_get(API_URL, params)
            if code == 200 and data:
                result = data.get("result") or {}
                return result.get("items") or [], result.get("total", 0)
            if code in (429, 451) or code is None:
                wait = SLEEP_ON_BLOCK * attempt
                self.log(f"блок/ошибка (code={code}), пауза {wait}с [попытка {attempt}/{MAX_ATTEMPTS}]")
                # Спим дробно, чтобы стоп работал быстро.
                for _ in range(wait):
                    if self.stop_event.is_set():
                        return [], 0
                    time.sleep(1)
                continue
            self.log(f"код {code}, страница пропущена")
            return [], 0
        return [], 0

    def run(self):
        self.config.output_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file = self.config.output_file.with_name(self.config.output_file.stem + "_raw.json") if self.config.raw else None

        limit_label = "все" if self.config.limit is None else str(self.config.limit)
        self.log(f"Парсер 2GIS | {self.config.city} → {self.search_query} | лимит: {limit_label}")
        key = self.resolve_key()
        p1, p2 = self.resolve_bbox(key)
        seen = self.load_existing_keys(self.config.output_file)
        if seen:
            self.log(f"[csv] в файле уже {len(seen)} записей — продолжаю без дублей")
        self.log(f"Ищу по коробке {p1} | {p2}, листаю страницы...")

        total_new = 0
        grabbed = 0
        raw_items = []
        preview_rows = []
        by_okrug, by_mkr = {}, {}
        page_num = 1

        while page_num <= MAX_PAGES and not self.stop_event.is_set():
            items, total = self.fetch_page(page_num, key, p1, p2)
            if page_num == 1:
                self.log(f"2GIS сообщает всего по запросу: ~{total}")
                if total < MIN_RESULTS_WARN:
                    self.log(f"⚠ меньше {MIN_RESULTS_WARN} — проверь запрос/коробку/ключ")
            if not items:
                break
            if self.config.limit is not None:
                remaining = self.config.limit - grabbed
                if remaining <= 0:
                    break
                items = items[:remaining]

            raw_items.extend(items)
            rows = [self.parse_item(it) for it in items]
            if self.config.fetch_reviews:
                for row in rows:
                    if row.get("ID"):
                        row["Отзывы 2GIS"] = self._fetch_reviews(row["ID"])
            preview_rows.extend(rows[: max(0, 200 - len(preview_rows))])
            grabbed += len(rows)
            for r in rows:
                by_okrug[r["Округ"] or "—"] = by_okrug.get(r["Округ"] or "—", 0) + 1
                by_mkr[r["Микрорайон"] or "—"] = by_mkr.get(r["Микрорайон"] or "—", 0) + 1

            new_cnt = self.save_to_csv(rows, self.config.output_file, seen)
            total_new += new_cnt
            self.log(f"стр.{page_num}: получено {len(rows)}, новых записано {new_cnt}")

            if self.config.limit is not None and grabbed >= self.config.limit:
                break
            if len(items) < PAGE_SIZE:
                break
            page_num += 1
            delay = random.uniform(self.config.sleep_min, self.config.sleep_max)
            end_at = time.time() + delay
            while time.time() < end_at:
                if self.stop_event.is_set():
                    break
                time.sleep(0.2)

        if self.stop_event.is_set():
            self.log("Остановлено пользователем.")

        if raw_file and raw_items:
            with raw_file.open("w", encoding="utf-8") as f:
                json.dump(raw_items, f, ensure_ascii=False, indent=2)
            self.log(f"[raw] сырые карточки: {raw_file}")

        self.log(f"ГОТОВО. Обработано карточек: {grabbed}, новых уникальных: {total_new}")
        self.log(f"CSV: {self.config.output_file}")
        return {
            "processed": grabbed,
            "new_unique": total_new,
            "csv": str(self.config.output_file),
            "raw": str(raw_file) if raw_file and raw_file.exists() else None,
            "preview": preview_rows,
            "districts": by_okrug,
            "microdistricts": by_mkr,
        }
