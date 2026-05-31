"""Дообогащение компании из интернета: реальные отзывы и описания."""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
from typing import Callable
from urllib.parse import urlparse, quote_plus

import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

GIS_API_KEY = os.getenv("DGIS_REVIEWS_API_KEY", "")


async def enrich_company_web(
    company: dict,
    log: Callable = print,
) -> dict:
    name = company.get("Название", "")
    city = _extract_city(company.get("Адрес", ""))

    if not name:
        return company

    log(f"  🌐 {name} ({city})")

    result = dict(company)
    result.setdefault("web_description", "")
    result.setdefault("web_reviews", [])
    result.setdefault("web_extra", "")
    result.setdefault("research_sources", [])
    result.setdefault("research_images", [])
    result.setdefault("research_social_text", "")
    result.setdefault("research_md", "")

    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True,
        timeout=httpx.Timeout(18.0, connect=8.0), verify=False
    ) as client:

        # ── 1. Reviews through official API access ───────────────────────────
        gis_link = (company.get("2GIS_ссылка", "") or
                    company.get("Ссылка 2ГИС", "") or
                    company.get("Ссылка_2ГИС", ""))
        gis_reviews = []
        if gis_link and GIS_API_KEY:
            gis_reviews = await _get_2gis_reviews_api(client, gis_link, log)
        elif gis_link:
            log("    2ГИС отзывы: задайте DGIS_REVIEWS_API_KEY для официального API")

        # ── 2. Поисковые сниппеты ─────────────────────────────────────────────
        query = f"{name} {city} отзывы"
        ddg = await _ddg_search(client, query, log)
        ya  = await _yandex_search(client, query, log)
        snippets = ddg + ya

        # ── 3. Обход всех ссылок компании ────────────────────────────────────
        urls = _collect_company_urls(company)
        log(f"    🔗 Обхожу {len(urls)} ссылок: {', '.join(_source_label(u) for u in urls[:6])}")
        page_summaries = await _fetch_many_pages(client, urls, log)

    # ── Сборка результата ─────────────────────────────────────────────────────
    page_text = " ".join(
        " ".join(filter(None, [p.get("title", ""), p.get("description", ""), p.get("text", "")]))
        for p in page_summaries
    )
    all_text = " ".join([*snippets, page_text])

    result["web_description"]    = _extract_best_description(name, all_text)
    result["web_reviews"]        = gis_reviews if gis_reviews else _extract_reviews(all_text)
    result["web_extra"]          = all_text[:3000] if all_text else ""
    result["research_sources"]   = page_summaries
    result["research_images"]    = _unique([
        img for p in page_summaries for img in p.get("images", [])
    ])[:15]
    result["research_social_text"] = "\n\n".join(
        f"[{_source_label(p['url'])}] {p.get('title','')} — {p.get('description') or p.get('text','')[:400]}"
        for p in page_summaries
        if _is_social_url(p.get("url", ""))
    )[:3000]
    result["research_md"] = _build_research_md(result, page_summaries)

    log(f"  ✅ Итого: описание {len(result['web_description'])} симв, "
        f"{len(result['web_reviews'])} отзывов, {len(page_summaries)} источников")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2GIS reviews API
# ─────────────────────────────────────────────────────────────────────────────

async def _get_2gis_reviews_api(
    client: httpx.AsyncClient, gis_url: str, log: Callable
) -> list[dict]:
    """Получает реальные отзывы через публичный 2GIS Reviews API."""
    branch_id = _extract_gis_branch_id(gis_url)
    if not branch_id:
        return []

    url = f"https://public-api.reviews.2gis.com/2.0/branches/{branch_id}/reviews"
    try:
        resp = await client.get(url, params={
            "limit": 50,
            "sort_by": "date_edited",
            "key": GIS_API_KEY,
            "fields": "reviews.user,reviews.text,reviews.rating,reviews.date_edited,reviews.photos",
        }, timeout=12)
        if resp.status_code != 200:
            log(f"    2ГИС API: статус {resp.status_code}")
            return []
        data = resp.json()
        reviews = []
        for rev in data.get("reviews", []):
            text = str(rev.get("text") or "").strip()
            if len(text) < 5:
                continue
            user  = rev.get("user") or {}
            author = str(user.get("name") or "Клиент").strip() or "Клиент"
            rating = rev.get("rating", 5)
            date_raw = str(rev.get("date_edited") or "")[:10]
            photos = [p.get("url", "") for p in (rev.get("photos") or []) if p.get("url")]
            reviews.append({
                "rating": int(rating) if str(rating).isdigit() else 5,
                "text": text,
                "author": author,
                "date": date_raw,
                "source": "2ГИС",
                "photos": photos[:3],
            })
        log(f"    2ГИС API: {len(reviews)} отзывов (branch {branch_id})")
        return reviews
    except Exception as e:
        log(f"    2ГИС API ошибка: {e}")
        return []


def _extract_gis_branch_id(url: str) -> str:
    """Извлекает branch_id из ссылки 2GIS."""
    # Форматы: /firm/70000001038726897, /branches/70000001038726897
    m = re.search(r'/(?:firm|branches)/(\d{10,})', url)
    if m:
        return m.group(1)
    # В некоторых URL id в конце: 2gis.ru/anapa/70000001038726897
    m = re.search(r'2gis\.ru/[^/]+/(\d{10,})', url)
    if m:
        return m.group(1)
    # Любое длинное число в URL
    nums = re.findall(r'\d{14,}', url)
    return nums[0] if nums else ""


# ─────────────────────────────────────────────────────────────────────────────
# Сбор URL компании
# ─────────────────────────────────────────────────────────────────────────────

_SKIP_URL_HOSTS = (
    "wa.me", "api.whatsapp.com", "viber.com", "viber.click",
    "2gis.ru", "www.2gis.ru", "link.2gis.ru", "go.2gis.com", "dgis.ru",
)


def _collect_company_urls(company: dict) -> list[str]:
    """Собирает все URL из строки таблицы."""
    keys = [
        "Сайт", "2GIS_ссылка", "Ссылка 2ГИС", "Ссылка_2ГИС", "Соцсети",
        "Соц_Telegram", "Соц_ВКонтакте", "Соц_VK", "Соц_WhatsApp",
        "Соц_Instagram", "Соц_Одноклассники", "Соц_YouTube",
        "Соц_Facebook", "Соц_Дзен", "Соц_TikTok",
    ]
    raw = []
    for k in keys:
        v = str(company.get(k, "") or "")
        if v:
            raw.append(v)
    for k, v in company.items():
        if k.startswith("Соц_") and v:
            raw.append(str(v))

    urls: list[str] = []
    for text in raw:
        urls += re.findall(r"https?://[^\s;,\]\)\"'<>]+", text)
        urls += ["https://" + u for u in re.findall(r"(?<!@)\bwww\.[^\s;,\]\)\"'<>]+", text)]

    expanded = []
    for u in urls:
        u = u.strip().rstrip(".,;)")
        host = urlparse(u).netloc.lower()
        if any(skip in host for skip in _SKIP_URL_HOSTS):
            continue
        # Telegram: используем публичный просмотр t.me/s/{name} вместо t.me/{name}
        tg = _telegram_public_url(u)
        if tg:
            expanded.append(tg)
        else:
            expanded.append(u)
    return _unique(expanded)[:15]


# ─────────────────────────────────────────────────────────────────────────────
# Загрузка страниц
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_many_pages(
    client: httpx.AsyncClient, urls: list[str], log: Callable
) -> list[dict]:
    sem = asyncio.Semaphore(4)

    async def one(url: str):
        async with sem:
            return await _fetch_page_summary(client, url, log)

    results = await asyncio.gather(*(one(u) for u in urls), return_exceptions=True)
    return [x for x in results if isinstance(x, dict) and (x.get("title") or x.get("text"))]


async def _fetch_page_summary(
    client: httpx.AsyncClient, url: str, log: Callable
) -> dict | None:
    try:
        # Для ВКонтакте используем мобильную версию (меньше JS)
        fetch_url = _mobile_url(url)
        resp = await client.get(fetch_url, timeout=14)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code >= 400 or "text/html" not in ctype:
            return None
        raw = resp.text[:500_000]

        title = _first_match(raw, [
            r"<title[^>]*>(.*?)</title>",
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']title["\'][^>]+content=["\'](.*?)["\']',
        ])
        desc = _first_match(raw, [
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        ])
        images = re.findall(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
            raw, re.IGNORECASE,
        )
        body = _html_to_text(raw)
        src = _source_label(url)
        if body:
            log(f"    {src}: {len(body)} симв")
        return {
            "url": url,
            "source": src,
            "title": title[:200] if title else "",
            "description": desc[:600] if desc else "",
            "text": body[:3000],
            "images": _unique(images)[:5],
        }
    except Exception as e:
        log(f"    {_source_label(url)}: ошибка — {str(e)[:80]}")
        return None


def _mobile_url(url: str) -> str:
    """Для ВКонтакте и Одноклассников возвращает мобильную версию."""
    if "vk.com" in url:
        return url.replace("vk.com", "m.vk.com", 1)
    if "ok.ru" in url:
        return url.replace("ok.ru", "m.ok.ru", 1)
    return url


# ─────────────────────────────────────────────────────────────────────────────
# Поисковые движки
# ─────────────────────────────────────────────────────────────────────────────

async def _ddg_search(client: httpx.AsyncClient, query: str, log: Callable) -> list[str]:
    try:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": "ru-ru"},
        )
        if resp.status_code != 200:
            return []
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
        clean = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:6]]
        result = [c for c in clean if len(c) > 25]
        if result:
            log(f"    DDG: {len(result)} сниппетов")
        return result
    except Exception as e:
        log(f"    DDG: {e}")
        return []


async def _yandex_search(client: httpx.AsyncClient, query: str, log: Callable) -> list[str]:
    try:
        resp = await client.get(
            "https://yandex.ru/search/",
            params={"text": query, "lr": "35"},
        )
        if resp.status_code != 200:
            return []
        snippets = re.findall(
            r'class="[^"]*OrganicTextContentSpan[^"]*"[^>]*>(.*?)</span>',
            resp.text, re.DOTALL,
        )
        if not snippets:
            snippets = re.findall(r'<span[^>]*itemprop="description"[^>]*>(.*?)</span>', resp.text)
        clean = [re.sub(r'<[^>]+>', ' ', s).strip() for s in snippets[:6]]
        result = [c for c in clean if len(c) > 25]
        if result:
            log(f"    Яндекс: {len(result)} сниппетов")
        return result
    except Exception as e:
        log(f"    Яндекс: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>", "\n", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    text = _clean_text(raw)
    chunks = []
    total = 0
    for part in re.split(r"\n+|(?<=[.!?])\s+", text):
        part = part.strip()
        if 20 <= len(part) <= 500 and not _is_nav_noise(part):
            chunks.append(part)
            total += len(part)
        if total > 4000:
            break
    return " ".join(chunks)


def _clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_nav_noise(text: str) -> bool:
    tl = text.lower()
    noise = ["cookie", "javascript", "войти", "регистрация", "подписаться",
             "скачать приложение", "обновите браузер", "enable javascript",
             "поделиться", "пожаловаться", "версия для"]
    return any(n in tl for n in noise)


def _first_match(text: str, patterns: list[str]) -> str:
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.DOTALL)
        if m:
            return _clean_text(m.group(1))
    return ""


def _extract_best_description(name: str, text: str) -> str:
    if not text:
        return ""
    sentences = re.split(r'[.!?]\s+', text)
    name_words = name.lower().split()[:3]
    relevant = []
    for s in sentences:
        s = s.strip()
        if len(s) < 30:
            continue
        sl = s.lower()
        if (any(w in sl for w in name_words) or
                any(w in sl for w in ["агентство", "компания", "фирма", "предлагает",
                                       "специализируется", "занимается", "работает", "услуги"])):
            relevant.append(s)
    if relevant:
        return ". ".join(relevant[:4]) + "."
    return ". ".join(sentences[:3]) + "." if sentences else ""


def _extract_reviews(text: str) -> list[dict]:
    """Извлекает отзывоподобный текст из поисковых сниппетов."""
    reviews = []
    # Статистика рейтингов
    for m in re.finditer(
        r'(?i)(рейтинг\s*[0-9,.]+[^.!?]{5,80}(?:оценок|отзыв)[^.!?]{0,60})',
        text
    ):
        reviews.append({"rating": 5, "text": m.group(1).strip(), "author": "Поиск (статистика)", "source": "Поиск"})

    # Текстовые отзывы из сниппетов
    for s in re.split(r'[.!]\s+', text):
        s = s.strip()
        if 35 <= len(s) <= 400 and _looks_like_review(s):
            if not re.match(r'(?i)^отзывы\s+о\s+(компании|агентстве)', s):
                if not any(r["text"] == s for r in reviews):
                    reviews.append({"rating": 5, "text": s, "author": "Клиент из сети", "source": "Поиск"})
        if len(reviews) >= 8:
            break
    return reviews


def _looks_like_review(text: str) -> bool:
    kw = ["рекомендую", "отлично", "хорошо", "замечательно", "спасибо", "благодарю",
          "довольны", "помогли", "профессионально", "качественно", "быстро",
          "обратились", "результат", "сделка", "покупка", "огромное спасибо",
          "лучшие", "молодцы", "ужасно", "плохо", "не советую", "всё понравилось",
          "остались довольны", "очень понравилось", "приятно удивили"]
    return any(k in text.lower() for k in kw)


def _telegram_public_url(url: str) -> str:
    m = re.match(r"https?://t\.me/([A-Za-z0-9_]{4,})(?:[/?].*)?$", url)
    if not m:
        return ""
    name = m.group(1)
    if name in {"share", "joinchat", "addstickers"}:
        return ""
    return f"https://t.me/s/{name}"


def _source_label(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    labels = {
        "2gis": "2ГИС", "t.me": "Telegram", "vk.com": "ВКонтакте",
        "m.vk.com": "ВКонтакте", "ok.ru": "Одноклассники",
        "youtube.com": "YouTube", "youtu.be": "YouTube",
        "instagram.com": "Instagram", "wa.me": "WhatsApp",
        "facebook.com": "Facebook", "dzen.ru": "Дзен", "tiktok.com": "TikTok",
    }
    for k, v in labels.items():
        if k in host:
            return v
    return host or url[:40]


def _is_social_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(x in host for x in [
        "t.me", "vk.com", "ok.ru", "youtube", "youtu.be",
        "instagram", "whatsapp", "facebook", "dzen", "tiktok",
    ])


def _unique(items: list) -> list:
    seen, out = set(), []
    for item in items:
        key = str(item or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _extract_city(address: str) -> str:
    if not address:
        return ""
    return address.split(",")[0].strip()


def _build_research_md(company: dict, sources: list[dict]) -> str:
    lines = []

    reviews = company.get("web_reviews", [])
    if reviews:
        lines.append("## Отзывы клиентов")
        for r in reviews[:10]:
            author = r.get("author", "Клиент")
            date   = r.get("date", "")
            rating = "⭐" * min(5, int(r.get("rating", 5) or 5))
            text   = r.get("text", "")
            src    = r.get("source", "")
            header = f"**{author}**"
            if date:
                header += f" · {date}"
            if rating:
                header += f" · {rating}"
            if src:
                header += f" · {src}"
            lines.append(f"- {header}")
            lines.append(f"  > {text}")
        lines.append("")

    desc = company.get("web_description", "")
    if desc:
        lines.append("## Описание из открытых источников")
        lines.append(desc)
        lines.append("")

    social = company.get("research_social_text", "")
    if social:
        lines.append("## Соцсети и публичные страницы")
        lines.append(social)
        lines.append("")

    if sources:
        lines.append("## Источники")
        for src in sources[:8]:
            title = src.get("title") or src.get("source") or src.get("url")
            body  = src.get("description") or src.get("text", "")
            if title:
                lines.append(f"- **{_clean_text(title)}** ({src.get('source', '?')}): "
                              f"{_clean_text(body)[:350]}")

    imgs = company.get("research_images", [])
    if imgs:
        lines.append("\n## Медиа")
        for img in imgs[:8]:
            lines.append(f"- {img}")

    return "\n".join(lines)


async def batch_web_enrich(
    companies: list[dict],
    log: Callable = print,
    concurrency: int = 3,
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(company):
        async with sem:
            return await enrich_company_web(company, log)

    return await asyncio.gather(*[_one(c) for c in companies])
