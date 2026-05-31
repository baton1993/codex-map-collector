"""Разбивает строку соцсетей на отдельные столбцы + извлекает телефоны."""
import re
from typing import Optional

SOCIAL_KEYS = [
    "ВКонтакте", "Instagram", "Telegram", "WhatsApp",
    "Одноклассники", "YouTube", "Facebook", "Дзен",
    "Rutube", "TenChat", "Viber", "Twitter",
]

HOST_MAP = {
    "vk.com": "ВКонтакте", "vkontakte.ru": "ВКонтакте",
    "instagram.com": "Instagram",
    "t.me": "Telegram", "telegram.me": "Telegram",
    "wa.me": "WhatsApp", "whatsapp.com": "WhatsApp", "api.whatsapp.com": "WhatsApp",
    "ok.ru": "Одноклассники",
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "facebook.com": "Facebook", "fb.com": "Facebook",
    "dzen.ru": "Дзен",
    "rutube.ru": "Rutube",
    "tenchat.ru": "TenChat",
    "viber.com": "Viber",
    "twitter.com": "Twitter", "x.com": "Twitter",
    "mssg.me": "WhatsApp",
    "me-qr.com": "WhatsApp",
    "taplink.cc": "Taplink",
    "hipolink.ru": "Hipolink",
    "linktr.ee": "Linktree",
}

URL_RE = re.compile(r'https?://[^\s,;|>]+')


def parse_socials(raw: str) -> dict[str, str]:
    """Принимает сырую строку соцсетей, возвращает {Название: url}."""
    result: dict[str, str] = {k: "" for k in SOCIAL_KEYS}
    if not raw:
        return result

    # Ищем все URL в строке
    for url in URL_RE.findall(raw):
        url = url.rstrip(".,;)")
        try:
            from urllib.parse import urlparse
            host = urlparse(url).netloc.lower().lstrip("www.")
        except Exception:
            continue
        for domain, name in HOST_MAP.items():
            if host == domain or host.endswith("." + domain):
                if not result.get(name):
                    result[name] = url
                break

    # Ищем явные указания без URL (например "WhatsApp: +79001234567")
    phone_re = re.compile(r'(?:WhatsApp|Viber)[^\d+]*([+\d][\d\s\-]{8,})')
    for m in phone_re.finditer(raw):
        net = "WhatsApp" if "whatsapp" in m.group(0).lower() else "Viber"
        if not result.get(net):
            phone = re.sub(r'[\s\-]', '', m.group(1))
            result[net] = f"https://wa.me/{phone.lstrip('+')}"

    return result


def extract_phones(raw: str) -> list[str]:
    """Извлекает телефоны из сырой строки."""
    phone_re = re.compile(r'[+7|8][\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}')
    phones = []
    seen = set()
    for m in phone_re.finditer(raw):
        normalized = re.sub(r'[\s\-\(\)]', '', m.group(0))
        if normalized not in seen:
            seen.add(normalized)
            phones.append(m.group(0).strip())
    return phones


def expand_row(row: dict) -> dict:
    """Расширяет строку: разбивает Соцсети на отдельные столбцы."""
    socials_raw = str(row.get("Соцсети", "") or "")
    parsed = parse_socials(socials_raw)
    result = dict(row)
    for k, v in parsed.items():
        result[f"Соц_{k}"] = v
    return result
