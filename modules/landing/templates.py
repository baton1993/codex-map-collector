"""Реестр стилей + загрузка шаблонов."""
from __future__ import annotations

import os
import re
from pathlib import Path

# Папка с кастомными шаблонами
TEMPLATES_DIR = Path(__file__).parent / "custom_templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

# Необязательная внешняя библиотека шаблонов. По умолчанию смотрим внутрь проекта,
# а для личной установки можно указать HTML_ANYTHING_SKILLS_DIR.
HTML_ANYTHING_SKILLS = Path(os.getenv(
    "HTML_ANYTHING_SKILLS_DIR",
    str(Path(__file__).resolve().parents[2] / "templates" / "html-anything" / "skills"),
))

# ─── Стили оформления ────────────────────────────────────────────────────────
STYLES: dict[str, dict] = {
    "realty_modern": {
        "name": "Недвижимость Modern",
        "description": "Тёмно-синий + золото. Профессионально, luxury",
        "preview_color": "#1a3a5c",
        "categories": ["real estate agencies", "real estate"],
    },
    "realty_warm": {
        "name": "Недвижимость Тёплый",
        "description": "Белый + бежевый + золото. Уют и надёжность",
        "preview_color": "#c8a45a",
        "categories": ["real estate agencies"],
    },
    "legal_strict": {
        "name": "Юридические Строгий",
        "description": "Тёмно-серый + белый. Авторитет и доверие",
        "preview_color": "#1a1a2e",
        "categories": ["юридические услуги", "оформление недвижимости"],
    },
    "mortgage_trust": {
        "name": "Ипотека и финансы",
        "description": "Синий + белый. Надёжность, цифры",
        "preview_color": "#0057a8",
        "categories": ["ипотека", "финансы", "страхование"],
    },
    "construction_bold": {
        "name": "Строительство Bold",
        "description": "Оранжевый + чёрный. Мощь и энергия",
        "preview_color": "#e85d04",
        "categories": ["строительство", "ремонт"],
    },
    "medical_clean": {
        "name": "Медицина Clean",
        "description": "Голубой + белый. Чистота и забота",
        "preview_color": "#4a9eca",
        "categories": ["медицина", "здоровье", "клиника"],
    },
    "beauty_elegant": {
        "name": "Красота Elegant",
        "description": "Розово-пудровый + золото. Стиль и уют",
        "preview_color": "#d4a5a5",
        "categories": ["красота", "салон", "косметология"],
    },
    "restaurant_dark": {
        "name": "Ресторан Dark",
        "description": "Тёмный + золото. Ресторанный шик",
        "preview_color": "#1a0a00",
        "categories": ["ресторан", "кафе", "еда"],
    },
    "education_bright": {
        "name": "Образование Bright",
        "description": "Зелёный + жёлтый. Энергия и знания",
        "preview_color": "#2e7d32",
        "categories": ["образование", "курсы", "обучение"],
    },
    "minimal_white": {
        "name": "Минимализм White",
        "description": "Белый + тёмный. Чистый минимализм",
        "preview_color": "#f8f9fa",
        "categories": [],
    },
}


def pick_style(company: dict) -> str:
    cats = str(company.get("Рубрики", "") or "").lower()
    scores = {sid: sum(1 for c in s["categories"] if c in cats)
              for sid, s in STYLES.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "minimal_white"


# ─── Кастомные шаблоны ───────────────────────────────────────────────────────
def list_custom_templates() -> list[dict]:
    """Возвращает список кастомных шаблонов из папки custom_templates/."""
    result = []
    for p in sorted(TEMPLATES_DIR.glob("*.md")):
        meta = _parse_skill_md(p.read_text(encoding="utf-8", errors="replace"))
        result.append({
            "id": p.stem,
            "name": meta.get("name", p.stem),
            "description": meta.get("description", ""),
            "source": "custom",
            "file": str(p),
        })
    return result


def list_ha_templates() -> list[dict]:
    """Возвращает полезные шаблоны из html-anything (адаптированы для лендингов)."""
    # Отбираем только те что подходят для бизнес-лендингов
    useful = {
        "saas-landing": "SaaS / Продуктовый лендинг",
        "dating-web": "Современный веб-лендинг",
        "mobile-app": "Лендинг мобильного приложения",
        "blog-post": "Статья / Описание компании",
        "docs-page": "Информационная страница",
    }
    result = []
    if not HTML_ANYTHING_SKILLS.exists():
        return result
    for skill_id, label in useful.items():
        p = HTML_ANYTHING_SKILLS / skill_id / "SKILL.md"
        if p.exists():
            result.append({
                "id": f"ha_{skill_id}",
                "name": label,
                "description": f"Из html-anything: {skill_id}",
                "source": "html-anything",
                "file": str(p),
            })
    return result


def load_skill(template_id: str) -> dict | None:
    """Загружает шаблон по ID. Поддерживает: ha_<id>, <id> напрямую, кастомный."""
    if not template_id:
        return None

    # 1. Кастомный шаблон пользователя
    custom_path = TEMPLATES_DIR / f"{template_id}.md"
    if custom_path.exists():
        text = custom_path.read_text(encoding="utf-8")
        meta = _parse_skill_md(text)
        meta["body"] = _strip_frontmatter(text)
        meta["source"] = "custom"
        return meta

    # 2. html-anything — прямой ID (например "saas-landing")
    ha_path = HTML_ANYTHING_SKILLS / template_id / "SKILL.md"
    if ha_path.exists():
        text = ha_path.read_text(encoding="utf-8")
        meta = _parse_skill_md(text)
        meta["body"] = _strip_frontmatter(text)
        meta["source"] = "html-anything"
        return meta

    # 3. html-anything — с префиксом "ha_" (например "ha_saas-landing")
    ha_id = template_id.removeprefix("ha_")
    ha_path2 = HTML_ANYTHING_SKILLS / ha_id / "SKILL.md"
    if ha_path2.exists():
        text = ha_path2.read_text(encoding="utf-8")
        meta = _parse_skill_md(text)
        meta["body"] = _strip_frontmatter(text)
        meta["source"] = "html-anything"
        return meta

    return None


def save_custom_template(name: str, body: str) -> str:
    """Сохраняет кастомный шаблон. Возвращает ID."""
    slug = re.sub(r'[^\w]', '_', name.lower())[:30]
    content = f"---\nname: {name}\ndescription: Кастомный шаблон\n---\n\n{body}"
    path = TEMPLATES_DIR / f"{slug}.md"
    path.write_text(content, encoding="utf-8")
    return slug


def _parse_skill_md(text: str) -> dict:
    meta: dict = {}
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ':' in line:
                k, _, v = line.partition(':')
                meta[k.strip()] = v.strip().strip('"')
    return meta


def _strip_frontmatter(text: str) -> str:
    return re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, flags=re.DOTALL).strip()


# ─── Встроенный HTML-рендерер (fallback без AI) ───────────────────────────────
def build_html(content: dict, style_id: str, template_id: str = "") -> str:
    style = STYLES.get(style_id, STYLES["minimal_white"])
    theme = _theme_for_template(style["preview_color"], style_id, template_id)
    css = _css(theme, style_id)
    body = _build_body(content, template_id)
    name = content.get("name", "Компания")
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{_esc(name)}</title>
  <style>{css}</style>
</head>
<body>
{body}
<div id="privacy" style="display:none">
  <h2>Политика конфиденциальности</h2>
  <p>Настоящая Политика определяет порядок обработки персональных данных пользователей сайта в соответствии с ФЗ «О персональных данных» № 152-ФЗ.</p>
</div>
</body>
</html>"""


def _theme_for_template(primary: str, style_id: str, template_id: str) -> dict:
    tid = (template_id or "").removeprefix("ha_").lower()
    presets = {
        "saas-landing": {"primary": "#4f46e5", "accent": "#14b8a6", "bg": "#f8fafc", "card": "#ffffff", "text": "#111827"},
        "pricing-page": {"primary": "#0f766e", "accent": "#f59e0b", "bg": "#f6f7f4", "card": "#ffffff", "text": "#17201d"},
        "mobile-app": {"primary": "#7c3aed", "accent": "#06b6d4", "bg": "#fbfbff", "card": "#ffffff", "text": "#171321"},
        "dating-web": {"primary": "#db2777", "accent": "#f97316", "bg": "#fff7fb", "card": "#ffffff", "text": "#25121d"},
        "blog-post": {"primary": "#334155", "accent": "#c2410c", "bg": "#fafaf9", "card": "#ffffff", "text": "#1c1917"},
        "docs-page": {"primary": "#2563eb", "accent": "#16a34a", "bg": "#f8fafc", "card": "#ffffff", "text": "#111827"},
    }
    theme = presets.get(tid, {"primary": primary, "accent": "#6366f1", "bg": "#fafafa", "card": "#ffffff", "text": "#0a0a0a"})
    if style_id == "restaurant_dark":
        theme = {"primary": primary, "accent": "#ffd700", "bg": "#1a0a00", "card": "#2a1500", "text": "#f0f0f0"}
    return theme


def _css(theme: dict, style_id: str) -> str:
    primary = theme["primary"]
    accent = theme["accent"]
    dk = _darken(primary)
    light = _lighten(primary)
    dark_theme = style_id == "restaurant_dark"
    bg = theme["bg"]
    text_color = theme["text"]
    card_bg = theme["card"]

    return f"""
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--p:{primary};--pd:{dk};--pl:{light};--a:{accent};--bg:{bg};--card:{card_bg};--text:{text_color};--muted:#64748b;--border:#e5e7eb}}
html{{scroll-behavior:smooth}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6}}
::-webkit-scrollbar{{width:5px}}::-webkit-scrollbar-thumb{{background:var(--p);border-radius:3px}}
a{{color:inherit;text-decoration:none}}
.container{{max-width:1200px;margin:0 auto;padding:0 24px}}
.btn{{display:inline-flex;align-items:center;padding:12px 28px;border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;transition:all .2s;border:none}}
.btn-primary{{background:var(--p);color:#fff}}.btn-primary:hover{{background:var(--pd);transform:translateY(-1px)}}
.btn-accent{{background:var(--a);color:#fff;border-color:var(--a)}}
.btn-outline{{background:transparent;color:var(--p);border:2px solid var(--p)}}.btn-outline:hover{{background:var(--pl)}}
section{{padding:80px 0}}
nav{{position:sticky;top:0;z-index:100;background:rgba(255,255,255,.92);backdrop-filter:blur(8px);
     border-bottom:1px solid #e5e7eb;padding:14px 0}}
nav .inner{{display:flex;align-items:center;justify-content:space-between}}
nav .logo{{font-size:1.15rem;font-weight:700;color:var(--p)}}
nav .links{{display:flex;gap:24px;align-items:center}}
nav .links a{{font-size:.875rem;color:var(--text);opacity:.7;transition:opacity .15s}}.links a:hover{{opacity:1}}
.hero{{min-height:82vh;display:flex;align-items:center;
       background:radial-gradient(circle at 70% 15%,rgba(255,255,255,.24),transparent 28%),linear-gradient(135deg,{primary} 0%,{dk} 100%);color:#fff}}
.hero h1{{font-size:clamp(2rem,5vw,3.8rem);font-weight:800;line-height:1.1;margin-bottom:20px}}
.hero p{{font-size:1.15rem;opacity:.9;max-width:540px;margin-bottom:32px}}
.hero .btns{{display:flex;gap:12px;flex-wrap:wrap}}
.hero .btn-primary{{background:#fff;color:var(--p)}}
.hero .btn-outline{{border-color:rgba(255,255,255,.7);color:#fff}}.hero .btn-outline:hover{{background:rgba(255,255,255,.1)}}
.about{{background:{card_bg}}}
.about h2,.services h2,.reviews h2,.contacts h2{{font-size:2rem;font-weight:700;margin-bottom:32px;color:var(--p)}}
.about p{{font-size:1.05rem;max-width:720px;opacity:.85;line-height:1.8}}
.stats{{display:flex;gap:32px;margin-top:32px;flex-wrap:wrap}}
.stat-item .num{{font-size:2.5rem;font-weight:800;color:var(--p)}}
.stat-item .label{{font-size:.85rem;opacity:.6}}
.process{{background:linear-gradient(180deg,var(--bg),var(--card))}}
.steps{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}}
.step{{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px}}
.step .n{{display:inline-flex;width:34px;height:34px;align-items:center;justify-content:center;border-radius:50%;background:var(--p);color:#fff;font-weight:800;margin-bottom:12px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}}
.card{{background:var(--card);border:1px solid #e5e7eb;border-radius:16px;padding:28px;
       border-top:4px solid var(--p);transition:transform .2s,box-shadow .2s}}
.card:hover{{transform:translateY(-4px);box-shadow:0 8px 32px rgba(0,0,0,.12)}}
.card .icon{{font-size:2rem;margin-bottom:12px}}
.card h3{{font-size:1.05rem;font-weight:700;margin-bottom:8px;color:var(--p)}}
.card p{{font-size:.9rem;opacity:.7;line-height:1.7}}
.reviews{{background:{primary};color:#fff}}
.rev-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}
.rev-card{{background:rgba(255,255,255,.12);border-radius:12px;padding:20px}}
.stars{{color:#ffd700;margin-bottom:8px;font-size:1.1rem}}
.rev-card p{{font-size:.9rem;line-height:1.7;opacity:.95}}
.rev-author{{margin-top:10px;font-size:.8rem;opacity:.65}}
.contacts-grid{{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:start}}
@media(max-width:768px){{.contacts-grid{{grid-template-columns:1fr}}nav .links{{display:none}}}}
.contact-items{{display:flex;flex-direction:column;gap:12px}}
.ci{{display:flex;gap:12px;align-items:center;background:var(--card);border:1px solid #e5e7eb;
     border-radius:10px;padding:14px}}
.ci .icon{{font-size:1.3rem;flex-shrink:0}}
.ci a,.ci span{{font-size:.9rem}}
.form{{background:var(--card);border:1px solid #e5e7eb;border-radius:16px;padding:32px;box-shadow:0 4px 24px rgba(0,0,0,.06)}}
.form h3{{font-size:1.3rem;font-weight:700;margin-bottom:20px;color:var(--p)}}
.form input,.form textarea{{width:100%;border:1.5px solid #e5e7eb;border-radius:8px;
   padding:10px 14px;font-size:.9rem;outline:none;transition:border-color .15s;
   background:var(--bg);color:var(--text);margin-bottom:12px}}
.form input:focus,.form textarea:focus{{border-color:var(--p)}}
.form .consent{{display:flex;gap:8px;align-items:flex-start;font-size:.78rem;opacity:.7;margin-bottom:16px}}
.form .consent input{{width:16px;height:16px;margin-top:2px;flex-shrink:0;accent-color:var(--p)}}
.form .btn{{width:100%;justify-content:center}}
footer{{background:#0a0a0a;color:rgba(255,255,255,.4);padding:28px 0;font-size:.82rem;text-align:center}}
footer a{{color:rgba(255,255,255,.4);text-decoration:underline}}
"""


def _build_body(c: dict, template_id: str = "") -> str:
    name = c.get("name", "Компания")
    tagline = c.get("tagline", "")
    about = c.get("about", "")
    services = c.get("services", [])
    reviews = c.get("reviews", [])
    phone = c.get("phone", "")
    email = c.get("email", "")
    address = c.get("address", "")
    gis_link = c.get("gis_link", "")
    socials = c.get("socials", {})
    tid = (template_id or "").removeprefix("ha_").lower()

    # Nav
    html = f"""<nav>
  <div class="container inner">
    <span class="logo">{_esc(name)}</span>
    <div class="links">
      <a href="#about">О нас</a>
      <a href="#services">Услуги</a>
      {'<a href="#reviews">Отзывы</a>' if reviews else ''}
      <a href="#contacts">Контакты</a>
      <a href="#contacts" class="btn btn-primary" style="padding:8px 18px;font-size:.82rem">Связаться</a>
    </div>
  </div>
</nav>"""

    # Hero
    rating = c.get("rating", "")
    reviews_count = c.get("reviews_count", "")
    html += f"""
<section class="hero">
  <div class="container">
    <h1>{_esc(name)}</h1>
    <p>{_esc(tagline or (about[:160] + '...' if len(about) > 160 else about))}</p>
    <div class="btns">
      <a href="#contacts" class="btn btn-primary">Получить консультацию</a>
      <a href="#services" class="btn btn-outline">Наши услуги</a>
    </div>
    {f'<div style="margin-top:28px;opacity:.8;font-size:.9rem">★ {rating} на 2ГИС · {reviews_count} отзывов</div>' if rating else ''}
  </div>
</section>"""

    # About
    if about:
        html += f"""
<section class="about" id="about">
  <div class="container">
    <h2>О компании</h2>
    <p>{_esc(about)}</p>
  </div>
</section>"""

    # Services
    icons = ["🏠", "📋", "💼", "🤝", "⚖️", "🔑"]
    if services:
        cards = "\n".join(
            f'<div class="card"><div class="icon">{icons[i % len(icons)]}</div>'
            f'<h3>{_esc(s["title"])}</h3><p>{_esc(s["text"])}</p></div>'
            for i, s in enumerate(services)
        )
        html += f"""
<section class="services" id="services">
  <div class="container">
    <h2>Наши услуги</h2>
    <div class="cards">{cards}</div>
  </div>
</section>"""

    if tid in {"saas-landing", "mobile-app", "pricing-page", "docs-page"}:
        html += f"""
<section class="process" id="process">
  <div class="container">
    <h2 style="font-size:2rem;font-weight:700;margin-bottom:32px;color:var(--p)">Как мы работаем</h2>
    <div class="steps">
      <div class="step"><span class="n">1</span><h3>Разбираем задачу</h3><p>Уточняем запрос, сроки и критерии результата.</p></div>
      <div class="step"><span class="n">2</span><h3>Подбираем решение</h3><p>Предлагаем понятный план и сопровождаем каждый шаг.</p></div>
      <div class="step"><span class="n">3</span><h3>Доводим до результата</h3><p>Остаёмся на связи и фиксируем договорённости.</p></div>
    </div>
  </div>
</section>"""

    # Reviews
    if reviews:
        rev_cards = "\n".join(
            f"""<div class="rev-card">
  <div class="stars">{"★" * min(5, int(r.get("rating", 5) if isinstance(r, dict) else 5))}</div>
  <p>«{_esc(r.get("text", r) if isinstance(r, dict) else str(r))}»</p>
  <div class="rev-author">— {_esc(r.get("author", "Клиент") if isinstance(r, dict) else "Клиент")}</div>
</div>"""
            for r in reviews[:6]
        )
        html += f"""
<section class="reviews" id="reviews">
  <div class="container">
    <h2>Отзывы клиентов</h2>
    <div class="rev-grid">{rev_cards}</div>
  </div>
</section>"""

    # Contacts
    cis = ""
    if phone:
        cis += f'<div class="ci"><span class="icon">📞</span><span>{_esc(phone)}</span></div>'
    if email:
        cis += f'<div class="ci"><span class="icon">✉️</span><a href="mailto:{_esc(email)}">{_esc(email)}</a></div>'
    if address:
        cis += f'<div class="ci"><span class="icon">📍</span><span>{_esc(address)}</span></div>'
    if gis_link:
        cis += f'<div class="ci"><span class="icon">🗺️</span><a href="{_esc(gis_link)}" target="_blank">Открыть на 2ГИС</a></div>'

    soc_icons = {"telegram": "✈️", "vk": "💙", "whatsapp": "📱",
                 "youtube": "▶️", "instagram": "📸"}
    soc_names = {"telegram": "Telegram", "vk": "ВКонтакте", "whatsapp": "WhatsApp",
                 "youtube": "YouTube", "instagram": "Instagram"}
    for net, link in (socials or {}).items():
        if link:
            cis += (f'<div class="ci"><span class="icon">{soc_icons.get(net, "🔗")}</span>'
                    f'<a href="{_esc(link)}" target="_blank">{soc_names.get(net, net)}</a></div>')

    html += f"""
<section class="contacts" id="contacts">
  <div class="container">
    <h2>Контакты</h2>
    <div class="contacts-grid">
      <div class="contact-items">{cis}</div>
      <div class="form">
        <h3>Оставьте заявку</h3>
        <input type="text" placeholder="Ваше имя *">
        <input type="tel" placeholder="Телефон *">
        <input type="email" placeholder="Email">
        <textarea rows="3" placeholder="Ваш вопрос..."></textarea>
        <label class="consent">
          <input type="checkbox" required>
          <span>Я согласен(а) на обработку персональных данных в соответствии с
          <a href="#privacy" style="text-decoration:underline">Политикой конфиденциальности</a></span>
        </label>
        <button class="btn btn-primary">Отправить заявку</button>
      </div>
    </div>
  </div>
</section>"""

    html += f"""
<footer>
  <div class="container">
    <p>© {name} · {_esc(address)} · <a href="#privacy">Политика конфиденциальности</a></p>
  </div>
</footer>"""

    return html


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _darken(h: str) -> str:
    h = h.lstrip("#")
    r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
    return f"#{max(0,r-40):02x}{max(0,g-40):02x}{max(0,b-40):02x}"


def _lighten(h: str) -> str:
    h = h.lstrip("#")
    r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
    return f"#{min(255,r+80):02x}{min(255,g+80):02x}{min(255,b+80):02x}"
