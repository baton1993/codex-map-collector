"""Проверка сайтов на соответствие 152-ФЗ."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from pathlib import Path
from typing import Callable

# Триггеры трансграничной передачи данных
CROSS_BORDER_TRIGGERS = [
    ("Google Analytics", r"google-analytics\.com|gtag|ga\("),
    ("Google Tag Manager", r"googletagmanager\.com"),
    ("Google Ads", r"googleadservices\.com|googlesyndication\.com"),
    ("Meta Pixel", r"connect\.facebook\.net|fbq\("),
    ("reCAPTCHA", r"recaptcha"),
    ("Hotjar", r"hotjar\.com"),
    ("Mixpanel", r"mixpanel\.com"),
    ("Amplitude", r"amplitude\.com"),
    ("HubSpot", r"hubspot\.com|hs-scripts"),
    ("Intercom", r"intercom\.io|intercomcdn"),
    ("Zendesk", r"zendesk\.com|zdassets"),
    ("Salesforce", r"salesforce\.com|exacttarget"),
    ("YouTube embed", r"youtube\.com/embed|youtube-nocookie"),
]

# Паттерны политики конфиденциальности
PRIVACY_POLICY_PATTERNS = [
    r"политик[аеуи].{0,30}(конфиденциальн|персональн)",
    r"(конфиденциальн|персональн).{0,30}данн",
    r"privacy\s*policy",
    r"обработк[аеу].{0,30}персональн",
    r"защит[аеу].{0,30}персональн",
    r"пользовательск.{0,10}соглашени",
]

# Паттерны согласия на обработку ПД
CONSENT_PATTERNS = [
    r"соглас[иеьую].{0,50}(обработк|персональн)",
    r"(обработк[аеу]|использовани[еюя]).{0,50}персональн",
    r"даю?\s*соглас",
    r"согласи[еья]\s*на\s*(обработку|использование)",
    r"consent",
]

# Паттерны cookie-баннера
COOKIE_PATTERNS = [
    r"cookie",
    r"куки",
    r"файл[ыов]\s*cookie",
]

# Паттерны форм обратной связи с чекбоксом
FORM_WITH_CONSENT = [
    r'<input[^>]+type=["\']checkbox["\'][^>]*>',
    r'checkbox',
]

# Согласие через текст под кнопкой ("нажимая кнопку — вы соглашаетесь")
BUTTON_CONSENT_PATTERNS = [
    r"нажима[яь].{0,30}(кнопк|«|отправить|подтвердить|далее|заказать).{0,150}(соглас|обработк|персональн)",
    r"отправля[яь].{0,30}(форму|заявку|данные|запрос).{0,150}(соглас|обработк|персональн)",
    r"продолжая.{0,80}(соглас|обработк|персональн)",
    r"(соглас|обработк|персональн).{0,150}нажима[яь].{0,30}(кнопк|«|отправить)",
    r"нажатие.{0,30}(кнопки|на кнопку).{0,150}(соглас|обработк|персональн)",
    r"подтвержда[яь].{0,80}(соглас|обработк|персональн)",
    r"регистрируясь.{0,80}(соглас|обработк|персональн)",
]

# Проверка HTTPS
def check_https(url: str) -> bool:
    return url.lower().startswith("https://")


async def check_sites(
    urls: list[str],
    log: Callable,
    use_ai: bool = False,
    agent_bin: str = "codex",
) -> list[dict]:
    results = []
    try:
        from playwright.async_api import async_playwright
        playwright_available = True
    except ImportError:
        playwright_available = False
        log("⚠️ Playwright не установлен. Упрощённая проверка через httpx.")

    if playwright_available:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (compatible; CodexMapCollector/1.0)",
                ignore_https_errors=True,
            )
            for i, url in enumerate(urls, 1):
                log(f"[{i}/{len(urls)}] Проверяю: {url}")
                result = await _check_one(url, context, log)
                results.append(result)
            await browser.close()
    else:
        for i, url in enumerate(urls, 1):
            log(f"[{i}/{len(urls)}] Проверяю (httpx): {url}")
            result = await _check_one_httpx(url, log)
            results.append(result)

    log(f"✅ Проверено {len(results)} сайтов")
    return results


async def _check_one(url: str, context, log: Callable) -> dict:
    result = _empty_result(url)
    result["https"] = check_https(url)

    try:
        page = await context.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}", lambda r: r.abort())

        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1500)

        if resp:
            result["http_code"] = resp.status
            result["accessible"] = (200 <= resp.status < 400)

        html = await page.content()
        result.update(_analyze_html(html, url))

        # Проверяем страницы политики
        await _check_policy_pages(page, result, log)

        await page.close()
    except Exception as e:
        result["error"] = str(e)
        result["accessible"] = False

    result["violations"] = _compute_violations(result)
    result["risk_score"] = _compute_risk(result)
    return result


async def _check_one_httpx(url: str, log: Callable) -> dict:
    import httpx
    result = _empty_result(url)
    result["https"] = check_https(url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15,
                                     verify=False) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            result["http_code"] = resp.status_code
            result["accessible"] = (200 <= resp.status_code < 400)
            html = resp.text
            result.update(_analyze_html(html, url))
    except Exception as e:
        result["error"] = str(e)
    result["violations"] = _compute_violations(result)
    result["risk_score"] = _compute_risk(result)
    return result


def _empty_result(url: str) -> dict:
    return {
        "url": url,
        "accessible": False,
        "https": False,
        "http_code": None,
        "has_privacy_policy": False,
        "privacy_policy_url": "",
        "has_consent_form": False,
        "has_form_checkbox": False,
        "has_button_consent": False,
        "has_cookie_consent": False,
        "cross_border": [],
        "violations": [],
        "risk_score": 0,
        "error": "",
    }


def _analyze_html(html: str, url: str) -> dict:
    html_lower = html.lower()
    result: dict = {}

    # Политика конфиденциальности в тексте
    has_pp = any(re.search(p, html_lower) for p in PRIVACY_POLICY_PATTERNS)
    result["has_privacy_policy"] = has_pp

    # Согласие на обработку
    result["has_consent_form"] = any(re.search(p, html_lower) for p in CONSENT_PATTERNS)

    # Чекбокс в формах
    forms = re.findall(r"<form[^>]*>.*?</form>", html_lower, re.DOTALL)
    result["has_form_checkbox"] = any(
        re.search(r'type=["\']checkbox["\']', f) for f in forms
    ) if forms else bool(re.search(r'type=["\']checkbox["\']', html_lower))

    # Согласие через текст под кнопкой (без чекбокса — тоже законно)
    result["has_button_consent"] = any(re.search(p, html_lower) for p in BUTTON_CONSENT_PATTERNS)

    # Cookie-баннер
    result["has_cookie_consent"] = any(re.search(p, html_lower) for p in COOKIE_PATTERNS)

    # Трансграничная передача
    found_trackers = []
    for name, pattern in CROSS_BORDER_TRIGGERS:
        if re.search(pattern, html_lower):
            found_trackers.append(name)
    result["cross_border"] = found_trackers

    # Ссылка на политику конфиденциальности
    pp_link = re.search(
        r'href=["\']([^"\']*(?:privacy|confidential|policy|politik|personal)[^"\']*)["\']',
        html_lower
    )
    if pp_link:
        result["privacy_policy_url"] = pp_link.group(1)

    return result


async def _check_policy_pages(page, result: dict, log: Callable):
    """Ищет и проверяет страницы политики конфиденциальности."""
    if result.get("privacy_policy_url"):
        return
    # Ищем ссылки в footer
    try:
        links = await page.eval_on_selector_all(
            "a",
            """els => els.map(e => ({href: e.href, text: e.textContent.trim().toLowerCase()}))"""
        )
        for link in links:
            text = link.get("text", "")
            href = link.get("href", "")
            if any(kw in text for kw in ["политик", "конфиденц", "персональн", "privacy"]):
                result["has_privacy_policy"] = True
                result["privacy_policy_url"] = href
                break
    except Exception:
        pass


def _compute_violations(r: dict) -> list[dict]:
    violations = []

    if not r.get("accessible"):
        return [{"code": "not_accessible", "title": "Сайт недоступен",
                 "law": "—", "fine": "—", "severity": "info"}]

    if not r.get("https"):
        violations.append({
            "code": "no_https",
            "title": "Сайт работает без HTTPS",
            "law": "ч.6 ст.13.11 КоАП РФ",
            "fine": "50 000 — 100 000 ₽",
            "severity": "high",
        })

    if not r.get("has_privacy_policy"):
        violations.append({
            "code": "no_privacy_policy",
            "title": "Отсутствует Политика обработки персональных данных",
            "law": "ч.3 ст.13.11 КоАП РФ",
            "fine": "60 000 — 100 000 ₽",
            "severity": "high",
        })

    has_any_consent = (r.get("has_consent_form") or
                       r.get("has_form_checkbox") or
                       r.get("has_button_consent"))
    if not has_any_consent:
        violations.append({
            "code": "no_consent",
            "title": "Отсутствует согласие на обработку ПДн в формах",
            "law": "ч.2 ст.13.11 КоАП РФ",
            "fine": "300 000 — 700 000 ₽",
            "severity": "critical",
        })

    if not r.get("has_cookie_consent"):
        violations.append({
            "code": "no_cookie_consent",
            "title": "Cookie используются без баннера/согласия",
            "law": "ч.1 ст.13.11 КоАП РФ",
            "fine": "150 000 — 300 000 ₽",
            "severity": "medium",
        })

    for tracker in r.get("cross_border", []):
        violations.append({
            "code": f"cross_border_{tracker.lower().replace(' ', '_')}",
            "title": f"Трансграничная передача данных: {tracker}",
            "law": "ч.10 ст.13.11 КоАП РФ",
            "fine": "100 000 — 300 000 ₽",
            "severity": "medium",
        })

    return violations


def _compute_risk(r: dict) -> int:
    """0-100: суммарный уровень риска."""
    severity_weights = {"critical": 40, "high": 20, "medium": 10, "info": 0}
    score = sum(severity_weights.get(v.get("severity", ""), 0)
                for v in r.get("violations", []))
    return min(100, score)
