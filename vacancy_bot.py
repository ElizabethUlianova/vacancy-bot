#!/usr/bin/env python3
"""
Vacancy bot — присылает новые вакансии в Telegram сразу, как только они появляются.

Мультиисточник. Каждый источник приводится к единому виду и фильтруется по
ключевым словам из config.json. Уже отправленные вакансии запоминаются в seen.json,
поэтому дубли не приходят даже при перезапуске.

Источники:
  • hh            — HeadHunter API (РФ/СНГ), поиск по тексту
  • remoteok      — RemoteOK JSON API
  • remotive      — Remotive JSON API
  • workingnomads — Working Nomads JSON API
  • rss           — любой RSS-фид (We Work Remotely, Design Jobs Board и др.)

Запуск:
    python vacancy_bot.py            # бесконечный цикл (опрос каждые poll_interval_minutes)
    python vacancy_bot.py --once     # один прогон и выход (для cron)
    python vacancy_bot.py --dry-run  # показать найденное в консоли, не отправляя
    python vacancy_bot.py --test     # тест связи с Telegram
"""

import argparse
import html
import json
import os
import sys
import time
from datetime import datetime

import requests

try:
    import feedparser
except ImportError:
    feedparser = None

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
SEEN_PATH = os.path.join(HERE, "seen.json")
UA = "vacancy-bot/2.0 (personal job alerts)"
TIMEOUT = 30


# ------------------------------------------------------------------ config/state

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # Секреты берём из переменных окружения (GitHub Secrets), иначе из config.json.
    tok = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"].get("bot_token", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID") or cfg["telegram"].get("chat_id", "")
    cfg["telegram"]["bot_token"] = tok
    cfg["telegram"]["chat_id"] = chat
    if not tok or not chat or "ВСТАВЬ" in str(tok) or "ВСТАВЬ" in str(chat):
        sys.exit("❌ Не заданы bot_token/chat_id: заполни config.json или переменные "
                 "TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID (см. README/DEPLOY).")
    return cfg


def load_seen():
    if not os.path.exists(SEEN_PATH):
        return set()
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, ValueError):
        return set()


def save_seen(seen):
    trimmed = list(seen)[-8000:]
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False)


# ------------------------------------------------------------------ helpers

def http_get(url, params=None):
    return requests.get(url, params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)


def matches_keywords(text, keywords):
    """True, если любое ключевое слово входит в текст (без учёта регистра)."""
    if not keywords:
        return True
    t = (text or "").lower()
    return any(k.strip().lower() in t for k in keywords if k.strip())


def norm(source, uid, title, url, company="", location="", salary="", extra=""):
    """Единый вид вакансии для всех источников."""
    return {
        "uid": f"{source}:{uid}",
        "source": source,
        "title": (title or "Без названия").strip(),
        "url": url or "",
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "salary": (salary or "").strip(),
        "haystack": " ".join([title or "", company or "", extra or ""]),
    }


# ------------------------------------------------------------------ sources
# Каждая функция возвращает список нормализованных вакансий (norm()).
# Любая сетевая ошибка ловится в collect() — один упавший источник не роняет бот.

def src_hh(conf, keywords):
    quoted = " OR ".join('"{}"'.format(k.strip()) for k in keywords if k.strip())
    params = {
        "text": quoted or "designer",
        "search_field": "name",
        "order_by": "publication_time",
        "per_page": conf.get("per_page", 50),
        "page": 0,
    }
    if conf.get("period_days"):
        params["period"] = int(conf["period_days"])
    if conf.get("area"):
        params["area"] = conf["area"]
    if conf.get("only_with_salary"):
        params["only_with_salary"] = "true"
    r = http_get("https://api.hh.ru/vacancies", params)
    r.raise_for_status()
    out = []
    for v in r.json().get("items", []):
        sal = v.get("salary") or {}
        salary = ""
        if sal:
            lo, hi, cur = sal.get("from"), sal.get("to"), sal.get("currency", "")
            cur = {"RUR": "₽", "USD": "$", "EUR": "€"}.get(cur, cur or "")
            if lo and hi:
                salary = f"{lo}–{hi} {cur}"
            elif lo:
                salary = f"от {lo} {cur}"
            elif hi:
                salary = f"до {hi} {cur}"
        out.append(norm(
            "hh", v.get("id"), v.get("name"), v.get("alternate_url"),
            (v.get("employer") or {}).get("name", ""),
            (v.get("area") or {}).get("name", ""),
            salary,
        ))
    return out


def src_remoteok(conf, keywords):
    # tag=design — просим именно дизайнерские вакансии, а не последние 100 по всем категориям
    params = {}
    if conf.get("tag", "design"):
        params["tag"] = conf.get("tag", "design")
    r = http_get("https://remoteok.com/api", params)
    r.raise_for_status()
    data = r.json()
    out = []
    for v in data:
        if not isinstance(v, dict) or not v.get("id"):
            continue  # первый элемент — юридическая пометка
        tags = " ".join(v.get("tags", []) or [])
        sal = ""
        if v.get("salary_min"):
            sal = f"${v.get('salary_min')}–{v.get('salary_max') or ''}".rstrip("–")
        out.append(norm(
            "remoteok", v.get("id"), v.get("position"),
            v.get("url") or v.get("apply_url"),
            v.get("company", ""), v.get("location", "") or "Remote", sal,
            extra=tags,
        ))
    return out


def src_remotive(conf, keywords):
    params = {"limit": conf.get("limit", 200)}
    if conf.get("category", "design"):
        params["category"] = conf.get("category", "design")  # категория дизайна
    r = http_get("https://remotive.com/api/remote-jobs", params)
    r.raise_for_status()
    out = []
    for v in r.json().get("jobs", []):
        tags = " ".join(v.get("tags", []) or [])
        out.append(norm(
            "remotive", v.get("id"), v.get("title"), v.get("url"),
            v.get("company_name", ""),
            v.get("candidate_required_location", "") or "Remote",
            v.get("salary", "") or "",
            extra=f"{v.get('category','')} {tags}",
        ))
    return out


def src_workingnomads(conf, keywords):
    r = http_get("https://www.workingnomads.com/api/exposed_jobs/")
    r.raise_for_status()
    data = r.json()
    items = data if isinstance(data, list) else data.get("jobs", [])
    out = []
    for v in items:
        uid = v.get("url") or v.get("id") or v.get("slug")
        out.append(norm(
            "workingnomads", uid, v.get("title"), v.get("url"),
            v.get("company_name", "") or v.get("company", ""),
            v.get("location", "") or "Remote", "",
            extra=f"{v.get('category_name','')} {' '.join(v.get('tags',[]) or [])}",
        ))
    return out


def src_rss(conf, keywords):
    if feedparser is None:
        print("⚠️  Для RSS нужен feedparser: pip install feedparser")
        return []
    out = []
    for feed in conf.get("feeds", []):
        url, name = feed.get("url"), feed.get("name", "RSS")
        if not url:
            continue
        try:
            # feedparser сам качает; передаём UA
            d = feedparser.parse(url, request_headers={"User-Agent": UA})
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  RSS «{name}» не прочитан: {e}")
            continue
        for e in d.entries:
            title = e.get("title", "")
            company = ""
            # WeWorkRemotely кодирует как "Компания: Должность"
            if ":" in title and name.lower().startswith("wework"):
                company, title = [p.strip() for p in title.split(":", 1)]
            uid = e.get("id") or e.get("link") or title
            out.append(norm(
                f"rss/{name}", uid, title, e.get("link", ""),
                company, "", "", extra=e.get("summary", "")[:300],
            ))
    return out


SOURCES = {
    "hh": src_hh,
    "remoteok": src_remoteok,
    "remotive": src_remotive,
    "workingnomads": src_workingnomads,
    "rss": src_rss,
}


# ------------------------------------------------------------------ pipeline

def collect(cfg):
    keywords = cfg["search"]["keywords"]
    found = []
    for name, conf in cfg.get("sources", {}).items():
        if not conf.get("enabled", False):
            continue
        fn = SOURCES.get(name)
        if not fn:
            print(f"⚠️  Неизвестный источник: {name}")
            continue
        try:
            items = fn(conf, keywords)
        except requests.RequestException as e:
            print(f"⚠️  Источник «{name}» недоступен: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Ошибка в источнике «{name}»: {e}")
            continue
        kept = [v for v in items if matches_keywords(v["haystack"], keywords)]
        print(f"   {name}: получено {len(items)}, подошло по словам {len(kept)}")
        found.extend(kept)
    return found


def format_message(v):
    title = html.escape(v["title"])
    parts = [f"🆕 <b>{title}</b>"]
    if v["company"]:
        parts.append(f"🏢 {html.escape(v['company'])}")
    if v["location"]:
        parts.append(f"📍 {html.escape(v['location'])}")
    if v["salary"]:
        parts.append(f"💰 {html.escape(v['salary'])}")
    src = v["source"].split("/")[0]
    parts.append(f"🌐 {html.escape(src)}")
    if v["url"]:
        parts.append(f"🔗 <a href=\"{html.escape(v['url'])}\">Открыть вакансию</a>")
    return "\n".join(parts)


def send_telegram(cfg, text):
    token = cfg["telegram"]["bot_token"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": cfg["telegram"]["chat_id"], "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=TIMEOUT,
    )
    if not r.ok:
        print(f"⚠️  Telegram error {r.status_code}: {r.text}")
    return r.ok


def run_once(cfg, dry_run=False, silent_seed=False):
    seen = load_seen()
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] Опрос источников…")
    found = collect(cfg)
    new = [v for v in found if v["uid"] not in seen]

    if silent_seed:
        for v in found:
            seen.add(v["uid"])
        save_seen(seen)
        print(f"[{stamp}] Первичная загрузка: помечено {len(found)} вакансий (без отправки).")
        return

    if not new:
        print(f"[{stamp}] Новых вакансий нет.")
        return
    print(f"[{stamp}] Новых вакансий: {len(new)}")
    for v in new:
        msg = format_message(v)
        if dry_run:
            print("\n" + msg.replace("<b>", "").replace("</b>", ""))
            seen.add(v["uid"])
        else:
            if send_telegram(cfg, msg):
                seen.add(v["uid"])
            time.sleep(1)
    save_seen(seen)


def run_loop(cfg):
    interval = int(cfg.get("poll_interval_minutes", 15)) * 60
    print(f"▶️  Бот запущен. Опрос каждые {interval // 60} мин. Ctrl+C — стоп.")
    if not os.path.exists(SEEN_PATH):
        print("ℹ️  Первый запуск: помечаю текущие вакансии как виденные (без спама).")
        run_once(cfg, silent_seed=True)
    while True:
        try:
            run_once(cfg)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Непредвиденная ошибка прогона: {e}")
        time.sleep(interval)


def main():
    p = argparse.ArgumentParser(description="Telegram vacancy bot (multi-source)")
    p.add_argument("--once", action="store_true", help="один прогон и выход")
    p.add_argument("--dry-run", action="store_true", help="показать без отправки")
    p.add_argument("--test", action="store_true", help="тест связи с Telegram")
    args = p.parse_args()
    cfg = load_config()

    if args.test:
        ok = send_telegram(cfg, "✅ Vacancy bot на связи.")
        print("Отправлено." if ok else "Не удалось — проверь токен и chat_id.")
        return
    if args.dry_run:
        run_once(cfg, dry_run=True)
        return
    if args.once:
        # Первый прогон без истории — только запоминаем текущие вакансии (без спама).
        first = not os.path.exists(SEEN_PATH)
        run_once(cfg, silent_seed=first)
        return
    run_loop(cfg)


if __name__ == "__main__":
    main()
