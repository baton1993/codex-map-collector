# -*- coding: utf-8 -*-
"""Universal map-provider layer for the parser.

Each provider writes the same CSV schema so the rest of the app can keep using
enrichment, tables, landings, and exports.
"""
from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Iterable, Optional

import httpx

from .parser_core import CSV_HEADERS, ParserConfig, ParserRunner

EXTRA_HEADERS = ["Источник", "Источник_ссылка"]
UNIVERSAL_HEADERS = CSV_HEADERS + [h for h in EXTRA_HEADERS if h not in CSV_HEADERS]


@dataclass
class MapProviderConfig:
    provider: str
    city: str
    query: str
    limit: Optional[int]
    output_file: Path
    raw: bool = False
    sleep_min: float = 2
    sleep_max: float = 6
    fetch_reviews: bool = False
    api_key: str = ""
    locale: str = "ru_RU"


PROVIDER_LABELS = {
    "2gis": "2GIS",
    "yandex": "Yandex Maps",
    "google": "Google Places",
    "osm": "OpenStreetMap",
}


def run_map_provider(config: MapProviderConfig, log: Callable[[str], None], stop_event: Event | None = None) -> dict:
    provider_id = (config.provider or "2gis").strip().lower()
    stop_event = stop_event or Event()
    if provider_id == "2gis":
        return _run_2gis(config, log, stop_event)
    if provider_id == "yandex":
        return _YandexProvider(config, log, stop_event).run()
    if provider_id == "google":
        return _GooglePlacesProvider(config, log, stop_event).run()
    if provider_id == "osm":
        return _OsmProvider(config, log, stop_event).run()
    raise ValueError(f"Неизвестный провайдер карт: {config.provider}")


def _run_2gis(config: MapProviderConfig, log: Callable[[str], None], stop_event: Event) -> dict:
    runner = ParserRunner(
        ParserConfig(
            city=config.city,
            query=config.query,
            limit=config.limit,
            output_file=config.output_file,
            raw=config.raw,
            sleep_min=config.sleep_min,
            sleep_max=config.sleep_max,
            fetch_reviews=config.fetch_reviews,
            api_key=config.api_key,
        ),
        log=log,
        stop_event=stop_event,
    )
    result = runner.run()
    _ensure_extra_columns(config.output_file, "2GIS")
    return result


class _BaseProvider:
    provider_id = ""
    provider_label = ""

    def __init__(self, config: MapProviderConfig, log: Callable[[str], None], stop_event: Event):
        self.config = config
        self.log = log
        self.stop_event = stop_event
        self.rows: list[dict] = []
        self.raw_items: list[dict] = []

    @property
    def limit(self) -> int:
        return max(1, int(self.config.limit or 100))

    def client(self) -> httpx.Client:
        return httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": "CodexMapCollector/1.0 (+https://github.com/)",
                "Accept-Language": "ru,en;q=0.8",
            },
        )

    def require_key(self) -> str:
        key = (self.config.api_key or "").strip()
        if not key:
            raise RuntimeError(f"{self.provider_label} требует API key. Введите его в параметрах парсера.")
        return key

    def add_row(self, row: dict):
        clean = {h: str(row.get(h, "") or "") for h in UNIVERSAL_HEADERS}
        clean["Источник"] = self.provider_label
        if not clean.get("Название"):
            return
        self.rows.append(clean)

    def write(self):
        self.config.output_file.parent.mkdir(parents=True, exist_ok=True)
        with self.config.output_file.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=UNIVERSAL_HEADERS)
            writer.writeheader()
            writer.writerows(self.rows[: self.limit])
        if self.config.raw:
            raw_file = self.config.output_file.with_name(self.config.output_file.stem + "_raw.json")
            raw_file.write_text(json.dumps(self.raw_items, ensure_ascii=False, indent=2), encoding="utf-8")

    def run(self) -> dict:
        self.fetch()
        self.write()
        self.log(f"✅ {self.provider_label}: сохранено {min(len(self.rows), self.limit)} строк")
        return {"count": min(len(self.rows), self.limit), "csv_path": str(self.config.output_file)}

    def fetch(self):
        raise NotImplementedError


class _YandexProvider(_BaseProvider):
    provider_id = "yandex"
    provider_label = "Yandex Maps"

    def fetch(self):
        key = self.require_key()
        self.log(f"Парсер Yandex Maps | {self.config.city} → {self.config.query} | лимит: {self.limit}")
        url = "https://search-maps.yandex.ru/v1/"
        fetched = 0
        skip = 0
        page_size = min(50, self.limit)
        with self.client() as cli:
            while fetched < self.limit and not self.stop_event.is_set():
                params = {
                    "apikey": key,
                    "text": f"{self.config.query} {self.config.city}".strip(),
                    "type": "biz",
                    "lang": self.config.locale or "ru_RU",
                    "results": min(page_size, self.limit - fetched),
                    "skip": skip,
                }
                resp = cli.get(url, params=params)
                if resp.status_code != 200:
                    raise RuntimeError(f"Yandex API вернул {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                features = data.get("features") or []
                self.raw_items.extend(features)
                if not features:
                    break
                for feature in features:
                    self.add_row(self._row(feature))
                fetched = len(self.rows)
                skip += len(features)
                self.log(f"  Yandex: получено {fetched}/{self.limit}")
                if len(features) < page_size:
                    break
                time.sleep(max(0.2, self.config.sleep_min))

    def _row(self, feature: dict) -> dict:
        props = feature.get("properties") or {}
        meta = props.get("CompanyMetaData") or {}
        geometry = feature.get("geometry") or {}
        lon, lat = (geometry.get("coordinates") or ["", ""])[:2]
        phones = "; ".join(p.get("formatted", "") for p in meta.get("Phones", []) if p.get("formatted"))
        links = meta.get("Links") or []
        site = meta.get("url") or _first_link(links, {"website", "site", "url"})
        socials = "; ".join(_format_social_link(x) for x in links if _format_social_link(x))
        categories = ", ".join(c.get("name", "") for c in meta.get("Categories", []) if c.get("name"))
        hours = (meta.get("Hours") or {}).get("text") or ""
        return {
            "Название": meta.get("name") or props.get("name") or "",
            "Рубрики": categories,
            "Адрес": meta.get("address") or props.get("description") or "",
            "Телефоны": phones,
            "Сайт": site or "",
            "Соцсети": socials,
            "Часы_работы": hours,
            "Координаты": f"{lat},{lon}" if lat and lon else "",
            "ID": meta.get("id") or "",
            "Описание": props.get("description") or "",
            "Источник_ссылка": meta.get("url") or props.get("uri") or "",
        }


class _GooglePlacesProvider(_BaseProvider):
    provider_id = "google"
    provider_label = "Google Places"

    def fetch(self):
        key = self.require_key()
        self.log(f"Парсер Google Places | {self.config.city} → {self.config.query} | лимит: {self.limit}")
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,places.location,"
                "places.nationalPhoneNumber,places.internationalPhoneNumber,places.websiteUri,"
                "places.googleMapsUri,places.rating,places.userRatingCount,places.types,"
                "places.businessStatus,places.editorialSummary,nextPageToken"
            ),
        }
        page_token = ""
        with self.client() as cli:
            while len(self.rows) < self.limit and not self.stop_event.is_set():
                payload = {
                    "textQuery": f"{self.config.query} {self.config.city}".strip(),
                    "pageSize": min(20, self.limit - len(self.rows)),
                    "languageCode": _locale_to_language(self.config.locale),
                }
                if page_token:
                    payload["pageToken"] = page_token
                resp = cli.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Google Places API вернул {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                places = data.get("places") or []
                self.raw_items.extend(places)
                for place in places:
                    self.add_row(self._row(place))
                self.log(f"  Google: получено {len(self.rows)}/{self.limit}")
                page_token = data.get("nextPageToken") or ""
                if not page_token or not places:
                    break
                time.sleep(max(2.0, self.config.sleep_min))

    def _row(self, place: dict) -> dict:
        loc = place.get("location") or {}
        name = (place.get("displayName") or {}).get("text") or ""
        phone = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or ""
        return {
            "Название": name,
            "Рубрики": ", ".join(place.get("types") or []),
            "Адрес": place.get("formattedAddress") or "",
            "Телефоны": phone,
            "Сайт": place.get("websiteUri") or "",
            "Рейтинг": place.get("rating") or "",
            "Кол-во_отзывов": place.get("userRatingCount") or "",
            "Координаты": f"{loc.get('latitude')},{loc.get('longitude')}" if loc else "",
            "ID": place.get("id") or "",
            "Описание": (place.get("editorialSummary") or {}).get("text") or place.get("businessStatus") or "",
            "Источник_ссылка": place.get("googleMapsUri") or "",
        }


class _OsmProvider(_BaseProvider):
    provider_id = "osm"
    provider_label = "OpenStreetMap"

    def fetch(self):
        self.log(f"Парсер OpenStreetMap/Nominatim | {self.config.city} → {self.config.query} | лимит: {self.limit}")
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": f"{self.config.query} {self.config.city}".strip(),
            "format": "jsonv2",
            "addressdetails": 1,
            "extratags": 1,
            "namedetails": 1,
            "limit": min(50, self.limit),
            "accept-language": _locale_to_language(self.config.locale),
        }
        with self.client() as cli:
            resp = cli.get(url, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Nominatim вернул {resp.status_code}: {resp.text[:300]}")
        items = resp.json()
        self.raw_items.extend(items)
        for item in items[: self.limit]:
            self.add_row(self._row(item))
        self.log(f"  OSM: получено {len(self.rows)}/{self.limit}")

    def _row(self, item: dict) -> dict:
        extra = item.get("extratags") or {}
        address = item.get("address") or {}
        site = extra.get("website") or extra.get("contact:website") or extra.get("url") or ""
        phone = extra.get("phone") or extra.get("contact:phone") or ""
        email = extra.get("email") or extra.get("contact:email") or ""
        socials = []
        for key in ["contact:instagram", "contact:facebook", "contact:vk", "contact:telegram", "contact:youtube"]:
            if extra.get(key):
                socials.append(f"{key.split(':')[-1]}:{extra[key]}")
        return {
            "Название": item.get("name") or item.get("display_name", "").split(",")[0],
            "Рубрики": item.get("type") or item.get("class") or "",
            "Адрес": address.get("road") or item.get("display_name") or "",
            "Телефоны": phone,
            "Сайт": site,
            "Email": email,
            "Соцсети": "; ".join(socials),
            "Координаты": f"{item.get('lat')},{item.get('lon')}",
            "ID": f"{item.get('osm_type','')}/{item.get('osm_id','')}".strip("/"),
            "Описание": item.get("display_name") or "",
            "Источник_ссылка": f"https://www.openstreetmap.org/{item.get('osm_type')}/{item.get('osm_id')}" if item.get("osm_type") and item.get("osm_id") else "",
        }


def _first_link(links: Iterable[dict], kind_words: set[str]) -> str:
    for link in links:
        href = str(link.get("href") or link.get("url") or "").strip()
        typ = str(link.get("type") or link.get("name") or "").lower()
        if href and any(word in typ for word in kind_words):
            return href
    return ""


def _format_social_link(link: dict) -> str:
    href = str(link.get("href") or link.get("url") or "").strip()
    if not href:
        return ""
    low = href.lower()
    for key in ["instagram", "vk", "facebook", "telegram", "t.me", "youtube", "whatsapp"]:
        if key in low:
            return f"{key.replace('t.me', 'telegram')}:{href}"
    return ""


def _locale_to_language(locale: str) -> str:
    value = (locale or "ru_RU").replace("-", "_").split("_")[0].lower()
    return value or "ru"


def _ensure_extra_columns(path: Path, provider_label: str):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    changed = False
    for header in EXTRA_HEADERS:
        if header not in headers:
            headers.append(header)
            changed = True
    if not changed:
        return
    for row in rows:
        row.setdefault("Источник", provider_label)
        row.setdefault("Источник_ссылка", row.get("2GIS_ссылка", ""))
    with path.open("w", encoding="utf-8-sig", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
