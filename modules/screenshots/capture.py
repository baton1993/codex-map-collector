"""Захват скриншотов + анализ устаревшего дизайна + концепт через GPT Image."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import time
from pathlib import Path
from typing import Callable


async def capture_and_analyze(
    urls: list[str],
    output_dir: Path,
    generate_concept: bool,
    openai_api_key: str,
    concept_prompt: str,
    agent_bin: str,
    log: Callable,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log("❌ Playwright не установлен")
        return []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        for i, url in enumerate(urls, 1):
            log(f"[{i}/{len(urls)}] Скриншоты: {url}")
            entry = {"url": url, "screenshots": [], "concept": None, "freshness": 0}

            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                )
                page = await context.new_page()
                await page.route("**/*.{woff,woff2,ttf,eot}", lambda r: r.abort())
                resp = await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(2000)

                # 1. Скриншот hero (viewport)
                s1 = output_dir / f"{_slug(url)}_hero.png"
                await page.screenshot(path=str(s1), full_page=False)
                entry["screenshots"].append({"type": "hero", "file": s1.name})
                log(f"  📷 Hero: {s1.name}")

                # 2. Скриншот full page (уменьшаем до 1/3 высоты)
                s2 = output_dir / f"{_slug(url)}_full.png"
                await page.screenshot(path=str(s2), full_page=True, scale="css")
                entry["screenshots"].append({"type": "full", "file": s2.name})
                log(f"  📷 Full: {s2.name}")

                # 3. Mobile скриншот
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.wait_for_timeout(800)
                s3 = output_dir / f"{_slug(url)}_mobile.png"
                await page.screenshot(path=str(s3), full_page=False)
                entry["screenshots"].append({"type": "mobile", "file": s3.name})
                log(f"  📷 Mobile: {s3.name}")

                # Оцениваем устарелость + сохраняем текст для анализа
                html = await page.content()
                entry["freshness"] = _estimate_freshness(html)
                entry["is_outdated"] = entry["freshness"] < 50
                entry["page_text"] = _html_to_text(html)[:5000]
                log(f"  📊 Свежесть дизайна: {entry['freshness']}/100")

                await context.close()

                # 4. Генерация концепта через GPT Image
                if generate_concept and entry["is_outdated"] and openai_api_key:
                    log(f"  🎨 Генерация нового концепта через GPT Image...")
                    concept = await _generate_concept(
                        screenshot_path=s1,
                        url=url,
                        openai_api_key=openai_api_key,
                        custom_prompt=concept_prompt,
                        output_dir=output_dir,
                        log=log,
                    )
                    entry["concept"] = concept
                elif generate_concept and entry["is_outdated"] and not openai_api_key:
                    log(f"  ⚠️ OpenAI API key не задан — пропускаю генерацию концепта")

            except Exception as e:
                entry["error"] = str(e)
                log(f"  ❌ Ошибка: {e}")

            results.append(entry)

        await browser.close()

    return results


def _slug(url: str) -> str:
    url = re.sub(r"https?://", "", url)
    return re.sub(r"[^a-zA-Z0-9а-яА-Я]", "_", url)[:40]


def _estimate_freshness(html: str) -> int:
    """Оценка свежести дизайна 0-100 на основе признаков HTML."""
    score = 0
    h = html.lower()

    # Адаптивность
    if "viewport" in h:
        score += 20
    if "@media" in h or "responsive" in h:
        score += 15

    # CSS-фреймворки и современные технологии
    for framework in ["tailwind", "bootstrap 5", "bootstrap5", "bulma", "material"]:
        if framework in h:
            score += 15
            break

    # React/Vue/Angular/Next.js
    for fw in ["react", "__next", "nuxt", "vue", "angular"]:
        if fw in h:
            score += 10
            break

    # Flexbox/Grid в inline-стилях
    if "display:flex" in h or "display: flex" in h or "display:grid" in h:
        score += 10

    # Год в футере
    import re as re_mod
    years = re_mod.findall(r"©?\s*(20\d{2})", h)
    if years:
        max_year = max(int(y) for y in years)
        if max_year >= 2023:
            score += 20
        elif max_year >= 2021:
            score += 10

    # HTTPS (уже проверяется раньше, добавим балл)
    if "https" in h[:200]:
        score += 5

    # Fontawesome (современный)
    if "fontawesome" in h or "font-awesome" in h:
        score += 5

    # Явно старые признаки — штраф
    for old in ["table border", "<table width", "bgcolor=", "cellpadding", "marquee"]:
        if old in h:
            score -= 20

    return max(0, min(100, score))


async def _generate_concept(
    screenshot_path: Path,
    url: str,
    openai_api_key: str,
    custom_prompt: str,
    output_dir: Path,
    log: Callable,
) -> dict | None:
    """Генерирует новый концепт дизайна через OpenAI gpt-image-1."""
    try:
        import httpx

        img_data = screenshot_path.read_bytes()
        img_b64 = base64.b64encode(img_data).decode()

        prompt = custom_prompt or (
            "Create a modern, professional website redesign concept for this business website. "
            "Make it clean, contemporary with good typography, white space, and mobile-first approach. "
            "Keep the same business but dramatically improve the visual design. "
            "Show the hero section and main navigation."
        )

        # GPT-4o Vision + DALL-E 3 pipeline
        # Сначала просим GPT-4o описать контекст сайта
        async with httpx.AsyncClient(timeout=60) as client:
            analyze_resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_api_key}"},
                json={
                    "model": "gpt-4o",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text",
                             "text": "Analyse this website screenshot. What business is it? What's the color scheme? What's outdated? Give me a one-paragraph description for a DALL-E redesign prompt."},
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "low"}}
                        ]
                    }],
                    "max_tokens": 300,
                }
            )
            if analyze_resp.status_code == 200:
                analysis = analyze_resp.json()["choices"][0]["message"]["content"]
                log(f"  🔍 Анализ сайта: {analysis[:100]}...")
                full_prompt = f"{prompt} Context: {analysis}"
            else:
                full_prompt = prompt

            # Генерируем изображение концепта
            img_resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {openai_api_key}"},
                json={
                    "model": "dall-e-3",
                    "prompt": full_prompt[:4000],
                    "size": "1792x1024",
                    "quality": "standard",
                    "n": 1,
                }
            )
            if img_resp.status_code == 200:
                img_url = img_resp.json()["data"][0]["url"]
                # Скачиваем концепт
                concept_resp = await client.get(img_url)
                concept_path = output_dir / f"{_slug(url)}_concept.png"
                concept_path.write_bytes(concept_resp.content)
                log(f"  ✅ Концепт сохранён: {concept_path.name}")
                return {"file": concept_path.name, "prompt": full_prompt}
            else:
                log(f"  ❌ OpenAI error: {img_resp.status_code} {img_resp.text[:200]}")
    except Exception as e:
        log(f"  ❌ Ошибка генерации концепта: {e}")
    return None


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    lines = [l.strip() for l in html.splitlines() if len(l.strip()) > 20]
    return "\n".join(lines[:200])


async def analyze_site_with_codex(
    url: str,
    company: dict,
    page_text: str,
    freshness: int,
    agent_bin: str,
    agent_model: str,
    openai_api_key: str,
    output_dir: Path,
    log: Callable,
) -> dict:
    name      = company.get("Название", url)
    rubrics   = company.get("Рубрики", "")
    address   = company.get("Адрес", "")
    phones    = company.get("Телефоны", "")
    rating    = company.get("Рейтинг", "")
    rev_count = company.get("Кол-во_отзывов", "")
    descr     = company.get("Описание", "")
    socials   = company.get("Соцсети", "")
    research  = company.get("research_md", "")

    freshness_label = "устарел (нужна переработка)" if freshness < 50 else "приемлемый"

    prompt = f"""Ты — профессиональный веб-аналитик и дизайн-стратег.

ДАННЫЕ О КОМПАНИИ:
- Название: {name}
- Сфера: {rubrics}
- Адрес: {address}
- Телефон: {phones}
- Рейтинг 2GIS: {rating} ({rev_count} отзывов)
- Описание: {descr}
- Соцсети: {socials}

ТЕКУЩИЙ САЙТ:
URL: {url}
Оценка свежести дизайна: {freshness}/100 ({freshness_label})

ТЕКСТ САЙТА:
{page_text[:3000] if page_text else "(не удалось получить)"}

{"ДОПОЛНИТЕЛЬНЫЕ ДАННЫЕ О КОМПАНИИ:" if research else ""}
{research[:2000] if research else ""}

ЗАДАНИЕ — напиши структурированный анализ:

## Проблемы текущего сайта
Перечисли 4-6 конкретных проблем дизайна и UX.

## Рекомендации по переработке
5-7 конкретных улучшений с обоснованием.

## Концепция нового дизайна
Опиши новый сайт: стиль, цветовая схема, структура, ключевые блоки, акценты.

## DALLE_PROMPT:
Напиши промт на английском для DALL-E 3, чтобы сгенерировать концепт главной страницы нового сайта. Начни строго с "DALLE_PROMPT:" и дай детальный промт 3-5 предложений."""

    log(f"  🤖 Отправляю в {agent_bin}...")
    analysis_text = await _call_codex(agent_bin, agent_model, prompt, log)

    dalle_prompt = ""
    if "DALLE_PROMPT:" in analysis_text:
        dalle_prompt = analysis_text.split("DALLE_PROMPT:")[-1].strip()

    result = {
        "url": url,
        "analysis": analysis_text,
        "dalle_prompt": dalle_prompt,
        "concept_image": None,
    }

    if openai_api_key and dalle_prompt:
        log(f"  🎨 Генерирую концепт через DALL-E 3...")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                img_resp = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {openai_api_key}"},
                    json={
                        "model": "dall-e-3",
                        "prompt": dalle_prompt[:4000],
                        "size": "1792x1024",
                        "quality": "standard",
                        "n": 1,
                    }
                )
                if img_resp.status_code == 200:
                    img_url = img_resp.json()["data"][0]["url"]
                    concept_resp = await client.get(img_url)
                    output_dir.mkdir(parents=True, exist_ok=True)
                    concept_path = output_dir / f"{_slug(url)}_analysis_concept.png"
                    concept_path.write_bytes(concept_resp.content)
                    result["concept_image"] = concept_path.name
                    log(f"  ✅ Концепт: {concept_path.name}")
                else:
                    log(f"  ⚠️ DALL-E: {img_resp.status_code}")
        except Exception as e:
            log(f"  ❌ DALL-E ошибка: {e}")

    return result


async def _call_codex(agent_bin: str, agent_model: str, prompt: str, log: Callable) -> str:
    import asyncio

    if agent_bin != "codex":
        log("  ⚠️ Public build supports Codex only")
        return "(Codex only)"
    cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=120,
        )
        text = stdout.decode(errors="replace").strip()
        if not text and stderr:
            log(f"  ⚠️ Codex stderr: {stderr.decode(errors='replace')[:200]}")
        return text or "(нет ответа)"
    except asyncio.TimeoutError:
        log("  ⚠️ Codex таймаут 120с")
        return "(таймаут)"
    except Exception as e:
        log(f"  ❌ Codex ошибка: {e}")
        return f"(ошибка: {e})"
