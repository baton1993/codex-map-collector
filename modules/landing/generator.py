"""Генератор лендингов: сбор инфо → MD → AI (с -p флагом) → HTML."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Callable

from .templates import STYLES, TEMPLATES_DIR, build_html, pick_style, load_skill

# ──────────────────────────────────────────────────────────────────────────────
# Shared design directives (взяты из html-anything/shared.ts)
# ──────────────────────────────────────────────────────────────────────────────
SHARED_DESIGN_DIRECTIVES = """
Ты — элитный веб-дизайнер и продуктовый маркетолог. Создаёшь сайты которые ПРОДАЮТ и РАБОТАЮТ.
Выведи **один самодостаточный HTML-файл** — первый символ `<`, последний `</html>`.
Никаких markdown-блоков, никаких пояснений, никакого текста до или после HTML.

【ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ】
- Tailwind v3 через CDN: https://cdn.tailwindcss.com (ТОЛЬКО этот URL, без изменений)
- Google Fonts через CDN (Inter / Manrope / Noto Sans SC для кириллицы)
- Все скрипты и стили inline — открывается двойным кликом без сервера
- Без внешних изображений — только CSS-градиенты, SVG-иконки, CSS-паттерны
- Полная адаптивность: мобильные sm:, планшеты md:, десктоп lg:

【ДИЗАЙН — МИРОВОЙ УРОВЕНЬ】
- Типографика: hero-заголовок 56-72px, подзаголовки 28-36px, текст 16-18px с line-height 1.7
- Цвета: 1 фирменный + 1 акцентный + нейтральный фон; все с плавными переходами
- Отступы: щедрые (py-20 py-32 на секциях), воздух = роскошь
- Детали: rounded-2xl/3xl, shadow-xl, border с opacity, backdrop-blur
- Анимации: CSS animate-fadeIn, CSS transition-all 300ms, hover:scale-105
- Контраст WCAG AA: основной текст ≥ 4.5:1, большой текст ≥ 3:1
- Hero-секция: ПОЛНЫЙ ЭКРАН (min-h-screen), мощный заголовок, call-to-action кнопки

【КОНТЕНТ — ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ】
- ЗАПРЕЩЕНО писать «данные не представлены», «статистика не раскрыта», «нет информации»
- ЗАПРЕЩЕНО копировать предметную область шаблона (dating, SaaS, dashboard, курс и т.д.)
- Если данных нет — убирай блок или переформулируй нейтрально
- ВСЕ отзывы должны звучать как настоящие голоса клиентов ЭТОЙ компании
- Все цифры, метрики, преимущества — выводить из реальных данных досье
- Форма заявки ОБЯЗАТЕЛЬНО: чекбокс «Согласен на обработку персональных данных»
- Футер: ссылка на Политику конфиденциальности (href="#privacy")
"""

TAPLINK_DIRECTIVES = """
【ТИП СТРАНИЦЫ: TAP-LINK / ВИЗИТКА-ССЫЛКИ】
Это НЕ обычный лендинг. Это красивая мобильная страница-агрегатор ссылок в стиле Linktree/Taplink.

СТРОГАЯ СТРУКТУРА (только это, ничего лишнего):
1. Верхний блок: большой круглый аватар (CSS-заглушка с инициалами в фирменном цвете) + название компании крупно + 1-2 строки описания
2. БЛОК ССЫЛОК (ГЛАВНАЯ ЧАСТЬ): для КАЖДОГО контакта из данных — отдельная широкая красивая кнопка-карточка:
   - SVG-иконка слева (VK, Insta, Telegram, WhatsApp, сайт, телефон, email, YouTube, TikTok)
   - Название сети/типа контакта
   - URL или номер телефона справа
   - Hover: легкое свечение или масштаб
3. Адрес (если есть) — отдельная карточка с иконкой 📍
4. Тонкий футер: копирайт

ДИЗАЙН-ТРЕБОВАНИЯ:
- Страница узкая: max-w-md по центру (как телефон)
- Фон: красивый CSS-градиент или темный с паттерном
- Карточки ссылок: полная ширина, rounded-2xl, py-4 px-6, background с opacity, border
- ЗАПРЕЩЕНО: форма заявки, навбар с пунктами, секция услуг, секция отзывов
- Страница должна быть ГОТОВА К ПУБЛИКАЦИИ и работать КАК ЗАМЕНА САЙТУ в Instagram/TikTok
"""

SELLING_DIRECTIVES = """
【ТИП: ПРОДАЮЩИЙ ЛЕНДИНГ】
Максимальный акцент на конверсию. Психология продаж встроена в каждый блок.

ОБЯЗАТЕЛЬНЫЕ ЭЛЕМЕНТЫ:
- Hero: конкретное ценностное предложение с ЦИФРАМИ (опыт N лет, N клиентов, N% результат)
- Проблема/Решение: блок "Вы сталкивались с..." → "Мы решаем это так..."
- Социальное доказательство: отзывы с именами и деталями, рейтинг
- Ограничение/срочность: "Осталось N мест", "Акция до...", "Первым 5 клиентам скидка"
- Минимум 3 призыва к действию (CTA) по всей странице
- Форма заявки: простая (имя + телефон + чекбокс), максимально заметная
"""

DEMO_DIRECTIVES = """
【ТИП: ДЕМОНСТРАЦИОННЫЙ ЛЕНДИНГ / ПОРТФОЛИО】
Акцент на визуальное впечатление и демонстрацию работ/кейсов.

ОБЯЗАТЕЛЬНЫЕ ЭЛЕМЕНТЫ:
- Портфолио/галерея: CSS-сетка с карточками работ (CSS-заглушки с красивыми цветами)
- Процесс работы: пошаговая инфографика (timeline или numbered steps)
- Кейсы: до/после или результаты с цифрами
- Минималистичная форма внизу
- Акцент на визуальное качество над количеством текста
"""

LANDING_TEMPLATE_BODY = """
【ШАБЛОН: Лендинг для локального бизнеса (Россия)】
【ЗАДАЧА】Создать полный лендинг для компании на основе предоставленных данных.

【ОБЯЗАТЕЛЬНАЯ СТРУКТУРА СЕКЦИЙ】
1. Навбар (лого = название, пункты: О нас, Услуги, Отзывы, Контакты; кнопка CTA)
2. Hero (крупный заголовок, подзаголовок-слоган, 2 кнопки CTA, декоративный элемент)
3. О компании (2-4 абзаца, преимущества в цифрах если есть рейтинг/отзывы)
4. Услуги/Рубрики (карточки с иконками SVG, 3-6 штук из реальных данных)
5. Отзывы (3-6 карточек; если данных нет — сгенерировать реалистичные для данной ниши)
6. Контакты + форма заявки (телефон, email, адрес, соцсети, карта-заглушка)
7. Футер (копирайт, ссылки, политика конфиденциальности)

【ДИЗАЙН-СТИЛЬ】
{style_instructions}

【ВХОДНЫЕ ДАННЫЕ (MD-досье компании)】:
"""

HTML_ANYTHING_TEMPLATE_ADAPTER = """
【КАК ИСПОЛЬЗОВАТЬ ШАБЛОН HTML-ANYTHING】
Ниже дан шаблон из html-anything. Используй его как источник визуального направления, композиции, ритма секций и frontend-приёмов.

Критически важно:
- НЕ копируй предметную область шаблона, если она не совпадает с входными данными компании.
- НЕ используй чужие названия метрик, блоков и терминов из шаблона.
- Если шаблон про dating, SaaS, dashboard, курс, investor pitch, устройство, игру или отчёт, всё равно преврати его в нормальный лендинг компании на русском.
- Секции должны называться по смыслу компании: услуги, преимущества, процесс работы, отзывы, контакты, заявка.
- Не показывай отсутствие данных как контент. Никаких фраз «нет оценки», «статистика не раскрыта», «публичные данные не представлены».

【ИСХОДНЫЙ ШАБЛОН ДЛЯ ВИЗУАЛЬНОЙ АДАПТАЦИИ】
{template_body}

【ВХОДНЫЕ ДАННЫЕ (MD-досье компании)】:
"""

STYLE_INSTRUCTIONS = {
    "realty_modern": "Тёмно-синий (#1a3a5c) + золотой акцент (#c8a45a). Профессионально, доверие, luxury.",
    "realty_warm": "Белый фон, тёплые бежевые тона (#f5f0e8), золото (#c8a45a). Уют и надёжность.",
    "legal_strict": "Тёмно-серый (#1a1a2e) + белый. Строгая типографика, авторитет, минимализм.",
    "mortgage_trust": "Синий (#0057a8) + белый. Финансовая надёжность, цифры, таблицы.",
    "construction_bold": "Оранжевый (#e85d04) + чёрный. Мощь, энергия, индустриальный стиль.",
    "medical_clean": "Светло-голубой (#4a9eca) + белый. Чистота, забота, профессионализм.",
    "beauty_elegant": "Розово-пудровый (#f4d4c8) + золото. Элегантность, женственность.",
    "restaurant_dark": "Тёмный (#1a0a00) + золото (#ffd700). Ресторанный шик, аппетитность.",
    "education_bright": "Зелёный (#2e7d32) + жёлтый. Энергия знаний, оптимизм, молодость.",
    "minimal_white": "Чисто белый (#fafafa) + тёмный текст (#0a0a0a). Максимальный минимализм.",
}


async def generate(
    company: dict,
    style_id: str,
    agent_bin: str,
    agent_model: str,
    log: Callable,
    output_dir: Path,
    job_id: str,
    custom_template_id: str = "",
    md_dossier: str | None = None,
    tmpl_type: str = "standard",
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Выбираем стиль
    if style_id == "auto":
        style_id = pick_style(company)
        log(f"🎨 Авто-стиль: {STYLES.get(style_id, {}).get('name', style_id)}")
    else:
        log(f"🎨 Стиль: {STYLES.get(style_id, {}).get('name', style_id)}")

    # 2. Собираем MD-досье
    if md_dossier and md_dossier.strip():
        log("📋 Использую MD-досье из редактора...")
        md_dossier = md_dossier.strip()
    else:
        log("📋 Формирую досье компании...")
        md_dossier = _build_dossier(company)
    md_path = output_dir / f"dossier_{job_id}.md"
    md_path.write_text(md_dossier, encoding="utf-8")
    log(f"✅ Досье: {len(md_dossier)} символов")

    # 3. Формируем промпт
    style_instr = STYLE_INSTRUCTIONS.get(style_id, STYLE_INSTRUCTIONS["minimal_white"])

    # Загружаем шаблон: приоритет — кастомный/ha шаблон, потом наш встроенный
    template_body = None

    if custom_template_id and custom_template_id != "auto":
        # Пробуем загрузить как ha-шаблон (без префикса и с префиксом ha_)
        skill = load_skill(custom_template_id) or load_skill(f"ha_{custom_template_id}")
        if skill and skill.get("body"):
            log(f"📐 Шаблон из репозитория: {custom_template_id}")
            template_body = HTML_ANYTHING_TEMPLATE_ADAPTER.format(template_body=skill["body"])
        else:
            log(f"⚠️  Шаблон '{custom_template_id}' не найден, использую встроенный")

    if template_body is None:
        template_body = LANDING_TEMPLATE_BODY.format(style_instructions=style_instr)

    # Добавляем директивы типа шаблона
    type_directives = {
        "taplink": TAPLINK_DIRECTIVES,
        "selling": SELLING_DIRECTIVES,
        "demo": DEMO_DIRECTIVES,
    }.get(tmpl_type, "")
    if type_directives:
        log(f"📋 Тип шаблона: {tmpl_type}")

    full_prompt = SHARED_DESIGN_DIRECTIVES + type_directives + "\n" + template_body + "\n\n---\n" + md_dossier

    log(f"📝 Промпт: {len(full_prompt)} символов")

    # 4. Вызываем AI
    log(f"🤖 Запрос к {agent_bin}...")
    raw_output = await _call_agent(
        agent_bin=agent_bin,
        agent_model=agent_model,
        prompt=full_prompt,
        log=log,
    )
    
    html_output = _extract_html(raw_output)

    # 5. Если AI недоступен или вернул мусор — используем встроенный рендерер
    if not html_output:
        log(f"⚠️  AI не вернул HTML (длина ответа: {len(raw_output)}), строю из шаблона...")
        content = _parse_company_to_content(company)
        html_output = build_html(content, style_id, custom_template_id)

    html_path = output_dir / f"landing_{job_id}.html"
    html_path.write_text(html_output, encoding="utf-8")
    log(f"✅ Лендинг готов: {html_path.name} ({len(html_output)} байт)")

    return {
        "html_path": str(html_path),
        "md_path": str(md_path),
        "style_id": style_id,
        "style_name": STYLES.get(style_id, {}).get("name", ""),
        "company_name": company.get("Название", ""),
        "html_size": len(html_output),
    }


async def _call_agent(
    agent_bin: str,
    agent_model: str,
    prompt: str,
    log: Callable,
    timeout: int = 600,  # html-anything шаблоны генерируют 20-50KB = нужно до 10 мин
    expected: str = "html",
) -> str:
    """
    Calls Codex in non-interactive mode through streaming.

    ВАЖНО — почему streaming, а не communicate():
    - communicate() буферизует весь вывод в памяти процесса
    - Если stdout-pipe заполняется (>64KB на macOS), процесс блокируется
    - HTML-лендинги из html-anything = 20-50KB → гарантированный deadlock
    - Streaming читает stdout построчно → буфер не переполняется никогда

    Public build supports only Codex. Other local agents are intentionally not exposed.
    """
    if agent_bin in {"template", "local", "none", "no_ai"}:
        log("  ⚡ Быстрый режим: результат строится локально")
        return ""

    if agent_bin != "codex":
        log("⚠️  Public build supports Codex only")
        return ""

    bin_path = shutil.which("codex")
    if not bin_path:
        log("⚠️  Codex не найден в PATH")
        return ""

    # Map UI aliases to currently available Codex model names.
    MODEL_MAP = {
        "gpt-5-5-ultra": "o1",
        "gpt-5-0-pro": "o3-mini",
        "gpt-4-o-next": "o4-mini",
    }
    real_model = MODEL_MAP.get(agent_model, agent_model)

    cmd = [bin_path, "exec", "--skip-git-repo-check", "--sandbox", "read-only"]
    if real_model:
        cmd += ["--model", real_model]
    cmd += ["-"]

    log(f"  ▶ {' '.join(cmd[:3])} (промпт {len(prompt)} симв., таймаут {timeout}с)")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Отправляем промпт и закрываем stdin сразу
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        # Читаем stdout и stderr одновременно через streaming
        # Это критично: без одновременного чтения stderr процесс может заблокироваться
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        last_progress = 0

        async def read_stdout():
            nonlocal last_progress
            quiet_ticks = 0
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        proc.stdout.read(4096), timeout=30
                    )
                    if not chunk:
                        break
                    stdout_chunks.append(chunk.decode("utf-8", errors="replace"))
                    total = sum(len(c) for c in stdout_chunks)
                    if total - last_progress > 5000:
                        log(f"  ⏳ Получено {total} символов...")
                        last_progress = total
                except asyncio.TimeoutError:
                    quiet_ticks += 1
                    if quiet_ticks == 1 or quiet_ticks % 4 == 0:
                        log("  ⏳ Codex ещё готовит ответ...")
                    continue

        async def read_stderr():
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        proc.stderr.read(1024), timeout=5
                    )
                    if not chunk:
                        break
                    line = chunk.decode("utf-8", errors="replace")
                    stderr_chunks.append(line)
                    # Фильтруем шум (progress-индикаторы, ANSI)
                    clean = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
                    if clean and not any(x in clean.lower() for x in [
                        'esc to interrupt', 'working', '⠋', '⠙', '⠹', '⠸',
                        '⠼', '⠴', '⠦', '⠧', '⠇', '⠏', '\r',
                        'codex_core_skills::loader',
                        'ignoring interface.icon_small',
                        "icon path with '..'",
                    ]):
                        log(f"  [stderr] {clean[:120]}")
                except asyncio.TimeoutError:
                    break

        # Запускаем чтение параллельно с общим таймаутом
        try:
            await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            log(f"⚠️  Общий таймаут {timeout}с")
            proc.kill()

        await proc.wait()

        output = "".join(stdout_chunks).strip()
        total_chars = len(output)
        log(f"  ✅ Агент вернул {total_chars} символов")

        if not output:
            stderr_text = "".join(stderr_chunks)
            if stderr_text:
                log(f"  stderr (последние 300): {stderr_text[-300:]}")
            log("  ⚠️  Пустой ответ от агента")
            return ""

        if any(marker in output.lower() for marker in [
            "you've hit your session limit",
            "session limit",
            "rate limit",
            "not inside a trusted directory",
            "unexpected argument",
        ]):
            log(f"  ⚠️  Агент недоступен: {output[:180]}")
            return ""

        if expected == "markdown":
            md = _extract_markdown(output)
            log(f"  ✅ Markdown получен: {len(md)} символов")
            return md

        html = _extract_html(output)
        if html:
            log(f"  ✅ HTML извлечён: {len(html)} символов")
            return html

        # Если не нашли DOCTYPE — пробуем вернуть весь вывод если похоже на HTML
        if "<html" in output.lower() or "<div" in output.lower():
            log("  ⚠️  HTML без DOCTYPE, оборачиваем...")
            return "<!DOCTYPE html>\n<html lang='ru'><head><meta charset='UTF-8'></head><body>" + output + "</body></html>"

        log(f"  ⚠️  HTML не найден. Начало ответа: {output[:200]}")
        return ""

    except Exception as e:
        import traceback
        log(f"⚠️  Ошибка вызова агента: {e}")
        log(traceback.format_exc()[-300:])
        return ""


def _extract_markdown(text: str) -> str:
    """Извлекает Markdown из ответа агента без HTML-требований."""
    stripped = text.strip()
    m = re.search(r"```(?:md|markdown)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if m:
        stripped = m.group(1).strip()
    stripped = re.sub(r"^\s*(?:вот|here is).{0,80}?:\s*", "", stripped, flags=re.IGNORECASE)
    return stripped


async def build_marketing_md(
    companies: list[dict],
    agent_bin: str,
    agent_model: str,
    custom_template_id: str,
    custom_prompt: str,
    log: Callable,
) -> str:
    """Делает из сырого массива данных маркетинговое MD-досье через Codex."""
    if not companies:
        return ""

    raw_md = "\n\n---\n\n".join(_build_dossier(c) for c in companies)
    template_note = ""
    if custom_template_id:
        skill = load_skill(custom_template_id) or load_skill(f"ha_{custom_template_id}")
        if skill and skill.get("body"):
            template_note = f"""\n\nШаблон html-anything, под который готовится контент:
Используй только визуальную/структурную идею шаблона. Не копируй его предметные термины, метрики и подписи, если они не относятся к компании.
{skill['body'][:2500]}"""
            log(f"📐 Учитываю шаблон для MD: {custom_template_id}")

    custom_instructions = f"\n【ДОПОЛНИТЕЛЬНЫЕ УКАЗАНИЯ ОТ ПОЛЬЗОВАТЕЛЯ】\n{custom_prompt}\n" if custom_prompt else ""

    prompt = f"""Ты — элитный веб-копирайтер и продуктовый маркетолог. Твоя задача: взять сырой массив технических данных о компании (таблица) и написать из него мощный, объемный, захватывающий контент для БУДУЩЕГО ВЕБ-САЙТА (лендинга) в формате Markdown.

Ты пишешь не сухой отчет! Ты пишешь готовые тексты для блоков сайта: крупный заголовок, убедительный оффер, привлекательные списки преимуществ, секцию "О нас", "Услуги" и живые отзывы.

【ТРЕБОВАНИЯ К ТЕКСТУ】
- Стиль: уверенный, экспертный, вызывающий доверие (B2B/B2C сегмент). Максимально "продает" компанию.
- Объем: пиши ПОДРОБНО и ОБЪЕМНО. Это текст для длинного сайта. Разворачивай каждый факт в мощное преимущество. Раскрывай детали.
- Структура: используй заголовки (H1-H3), списки, жирный шрифт, цитаты для отзывов.
- Язык: русский, без канцеляризмов, живой и энергичный.

【СТРУКТУРА КОНТЕНТА ДЛЯ КАЖДОЙ КОМПАНИИ】
1. **Заголовок (H1)** — Название компании + мощный оффер (УТП).
2. **Hero-блок** — Короткий абзац, бьющий в боли клиента, и решение, которое предлагает компания.
3. **О компании** — Развернутый текст о бизнесе, миссии и подходе (раскрой на 3-4 абзаца).
4. **Наши услуги / Что мы предлагаем** — Подробный список с описанием каждой услуги или продукта (минимум 3-5 пунктов с пояснениями).
5. **Преимущества** — Почему стоит выбрать именно их (используй цифры, факты из данных, рейтинг, гео).
6. **Отзывы** — Оформи как красивый блок цитат (используй реальные отзывы из данных, если их нет — адаптируй информацию в "Почему нас любят клиенты").
7. **Контакты и CTA** — Призыв к действию, адрес, телефон, мессенджеры, график работы.

【ВАЖНО】
- Используй ВСЕ найденные данные: соцсети, рейтинги, отзывы, описание из веба.
- Не выдумывай факты (цены, сроки), которых нет в данных, но описывай подходы и качество (например: "Индивидуальный подход", "Своевременное выполнение").
- ЗАПРЕЩЕНО писать «нет данных», «информация отсутствует», «в базе не найдено». Если поля нет — просто не упоминай этот факт, переключись на сильные стороны.
- Не используй термины из шаблона (SaaS, Dating, Investor), если они не относятся к компании.
- Разделяй компании через `---`.
{custom_instructions}
Сырые данные для трансформации:
{raw_md}
"""
    use_agent = agent_bin or "codex"
    if use_agent in {"template", "local", "none", "no_ai"}:
        log("⚡ Локальный fallback MD")
        return _build_marketing_md_fallback(companies)
    log(f"🤖 Формирую MD через {use_agent}...")
    md = await _call_agent(
        agent_bin=use_agent,
        agent_model=agent_model,
        prompt=prompt,
        log=log,
        timeout=420,
        expected="markdown",
    )
    if md and len(md) > 200:
        return md

    log("⚠️  Codex не вернул MD, использую локальную структуру")
    return _build_marketing_md_fallback(companies)


def _build_marketing_md_fallback(companies: list[dict]) -> str:
    blocks = []
    for company in companies:
        name = company.get("Название", "Компания")
        cats = company.get("Рубрики", "") or "профессиональные услуги"
        desc = company.get("web_description") or company.get("research_md") or company.get("web_extra") or ""
        blocks.append(f"""# {name}

## Коротко
**{name}** работает в направлении: **{cats}**. {str(desc)[:700]}

## Почему стоит обратиться
- Реальные контакты и открытые источники собраны в одном месте.
- Есть данные из 2ГИС, сайта и социальных сетей, если они были найдены.
- Можно быстро связаться и уточнить условия.

{_build_dossier(company)}

## Призыв к действию
Оставьте заявку, чтобы получить консультацию и уточнить детали.""")
    return "\n\n---\n\n".join(blocks)


def _extract_html(text: str) -> str:
    """Извлекает HTML из ответа агента."""
    # Ищем полный HTML-документ
    m = re.search(r'(<!DOCTYPE html>.*</html>)', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Ищем из <html> если без DOCTYPE
    m = re.search(r'(<html.*</html>)', text, re.DOTALL | re.IGNORECASE)
    if m:
        return "<!DOCTYPE html>\n" + m.group(1).strip()

    # Если ответ начинается с <!DOCTYPE — весь ответ это HTML
    stripped = text.strip()
    if stripped.lower().startswith("<!doctype"):
        return stripped

    # Ищем в markdown-блоке
    m = re.search(r'```(?:html)?\s*(<!DOCTYPE html>.*?</html>)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return ""


def _build_dossier(company: dict) -> str:
    """Строит подробное MD-досье из всех данных компании."""
    name = company.get("Название", "Компания")
    lines = [f"# {name}\n"]

    # Основные поля
    field_map = [
        ("Рубрики", "Вид деятельности"),
        ("Адрес", "Адрес"),
        ("Номер", "Телефон"),
        ("Почта электронная", "Email"),
        ("Сайт", "Сайт"),
        ("Ссылка 2ГИС", "2GIS карточка"),
        ("Рейтинг", "Рейтинг 2GIS"),
        ("Отзывы", "Количество отзывов"),
        ("Статус сайта", "Статус сайта"),
        ("Свежесть балл", "Свежесть сайта (0-100)"),
        ("Сегмент", "Сегмент"),
    ]
    for key, label in field_map:
        val = str(company.get(key, "") or "").strip()
        if val and val not in ("None", "nan", "0", ""):
            lines.append(f"**{label}:** {val}")

    # Соцсети — отдельные столбцы если есть
    social_keys = ["ВКонтакте", "Instagram", "Telegram", "WhatsApp",
                   "Одноклассники", "YouTube", "Facebook", "Дзен"]
    socials_found = []
    for sk in social_keys:
        for prefix in [f"Соц_{sk}", sk]:
            val = str(company.get(prefix, "") or "").strip()
            if val and val.startswith("http"):
                socials_found.append(f"  - {sk}: {val}")
                break

    if socials_found:
        lines.append("\n## Социальные сети")
        lines.extend(socials_found)

    # Сырая строка соцсетей если нет разбитых
    if not socials_found:
        raw = str(company.get("Соцсети", "") or "").strip()
        if raw:
            lines.append(f"\n## Социальные сети\n{raw}")

    # Комментарий обогатителя
    comment = str(company.get("Комментарий", "") or "").strip()
    if comment and comment not in ("None", "nan"):
        lines.append(f"\n## Примечания (из обогащения)\n{comment}")

    # Веб-описание (из дообогащения)
    web_desc = str(company.get("web_description", "") or "").strip()
    if web_desc:
        lines.append(f"\n## Описание из интернета\n{web_desc}")

    research_md = str(company.get("research_md", "") or "").strip()
    if research_md:
        lines.append("\n" + research_md)

    social_text = str(company.get("research_social_text", "") or "").strip()
    if social_text and social_text not in research_md:
        lines.append(f"\n## Данные из соцсетей\n{social_text}")

    research_sources = company.get("research_sources", [])
    if isinstance(research_sources, str):
        try:
            research_sources = json.loads(research_sources)
        except Exception:
            research_sources = []
    if research_sources and not research_md:
        lines.append("\n## Источники и найденные факты")
        for src in research_sources[:8]:
            if isinstance(src, dict):
                title = str(src.get("title") or src.get("source") or src.get("url") or "").strip()
                desc = str(src.get("description") or src.get("text") or "").strip()
                url = str(src.get("url") or "").strip()
                if title or desc:
                    lines.append(f"- **{title}:** {desc[:420]}")
                if url:
                    lines.append(f"  Источник: {url}")

    # Отзывы
    web_reviews = company.get("web_reviews", [])
    if isinstance(web_reviews, str):
        try:
            web_reviews = json.loads(web_reviews)
        except Exception:
            web_reviews = []

    if not web_reviews:
        raw_reviews_text = str(
            company.get("Отзывы текст", "")
            or company.get("Отзывы_текст", "")
            or company.get("reviews_text", "")
            or ""
        ).strip()
        if raw_reviews_text:
            web_reviews = [
                {"rating": 5, "text": part.strip(" -•\t"), "author": "Клиент"}
                for part in re.split(r"[\n|]+", raw_reviews_text)
                if len(part.strip()) > 20
            ]

    if web_reviews:
        lines.append("\n## Отзывы клиентов")
        for r in web_reviews[:6]:
            if isinstance(r, dict):
                stars = "★" * min(5, int(r.get("rating", 5)))
                lines.append(f"- {stars} «{r.get('text', '')}» — {r.get('author', 'Клиент')}")
            elif isinstance(r, str):
                lines.append(f"- ★★★★★ «{r}»")

    # Доп. веб-данные
    web_extra = str(company.get("web_extra", "") or "").strip()
    if web_extra:
        lines.append(f"\n## Дополнительная информация из поисковиков\n{web_extra[:1200]}")

    research_images = company.get("research_images", [])
    if isinstance(research_images, str):
        try:
            research_images = json.loads(research_images)
        except Exception:
            research_images = []
    if research_images:
        lines.append("\n## Медиа и изображения")
        for img in research_images[:10]:
            lines.append(f"- {img}")

    return "\n".join(lines)


def _parse_company_to_content(company: dict) -> dict:
    """Парсит данные компании в структурированный dict для встроенного рендерера."""
    import re as _re

    name = company.get("Название", "Компания")
    cats_raw = company.get("Рубрики", "") or ""
    cats = [c.strip() for c in cats_raw.split(",") if c.strip()]

    # Собираем соцсети
    socials: dict = {}
    for net in ["telegram", "vk", "whatsapp", "youtube", "instagram", "ok"]:
        for prefix in [f"Соц_{net.capitalize()}", f"Соц_ВКонтакте" if net == "vk" else None]:
            if not prefix:
                continue
            val = company.get(prefix, "") or ""
            if val.startswith("http"):
                socials[net] = val
                break
    # Также парсим из сырой строки
    if not socials:
        raw = company.get("Соцсети", "") or ""
        for url_m in _re.finditer(r'https?://\S+', raw):
            url = url_m.group(0).rstrip(".,;)")
            h = url.split("/")[2].lower().lstrip("www.")
            mapping = {"t.me": "telegram", "vk.com": "vk", "wa.me": "whatsapp",
                       "youtube.com": "youtube", "instagram.com": "instagram"}
            for domain, net in mapping.items():
                if h == domain or h.endswith("." + domain):
                    if net not in socials:
                        socials[net] = url

    # Отзывы
    web_reviews = company.get("web_reviews", [])
    if isinstance(web_reviews, str):
        try:
            web_reviews = json.loads(web_reviews)
        except Exception:
            web_reviews = []

    if not web_reviews:
        raw_reviews_text = str(
            company.get("Отзывы текст", "")
            or company.get("Отзывы_текст", "")
            or company.get("reviews_text", "")
            or ""
        ).strip()
        if raw_reviews_text:
            web_reviews = [
                {"rating": 5, "text": part.strip(" -•\t"), "author": "Клиент"}
                for part in _re.split(r"[\n|]+", raw_reviews_text)
                if len(part.strip()) > 20
            ]

    services = [{"title": c, "text": f"Профессиональные услуги: {c}"}
                for c in cats[:4]] or [
        {"title": "Консультация", "text": "Бесплатная консультация по вашему вопросу"},
        {"title": "Подбор объектов", "text": "Профессиональный подбор под ваши задачи"},
        {"title": "Сопровождение сделки", "text": "Полное юридическое сопровождение"},
        {"title": "Поддержка клиентов", "text": "На связи 7 дней в неделю"},
    ]

    return {
        "name": name,
        "tagline": (
            str(company.get("web_description", "") or "").split(".")[0]
            or f"Профессиональные услуги в сфере {cats[0] if cats else 'бизнеса'}"
        ),
        "about": (
            str(company.get("web_description", "") or "")
            or f"{name} — надёжная компания, специализирующаяся на "
               f"{', '.join(cats[:2]) if cats else 'профессиональных услугах'}. "
               f"Обратитесь к нам — мы поможем решить ваш вопрос."
        ),
        "services": services,
        "reviews": web_reviews or [
            {"rating": 5, "text": "Профессиональный подход, всё чётко и по делу!", "author": "Клиент"},
            {"rating": 5, "text": "Очень довольны результатом, рекомендуем!", "author": "Клиент"},
            {"rating": 4, "text": "Хорошая компания, работают ответственно.", "author": "Клиент"},
        ],
        "phone": company.get("Номер", "") or "",
        "email": company.get("Почта электронная", "") or "",
        "address": company.get("Адрес", "") or "",
        "gis_link": company.get("Ссылка 2ГИС", "") or "",
        "socials": socials,
        "rating": company.get("Рейтинг", "") or "",
        "reviews_count": company.get("Отзывы", "") or "",
    }
