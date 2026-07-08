# Vacancy bot

Личный Telegram-бот, который присылает новые вакансии product/UX-дизайнера сразу, как только они появляются — сразу из нескольких источников.

Ищет по фразам: *product designer, product design, product design lead, product design team lead, product design manager*. Каждые 15 минут (настраивается) опрашивает все включённые источники, фильтрует по ключевым словам, отсеивает уже виденное и шлёт только новое тебе в личку.

## Подключённые источники (проверены, работают)

| Источник | Тип | Что даёт |
|----------|-----|----------|
| **hh.ru** | JSON API | Вакансии по РФ/СНГ, поиск по тексту |
| **RemoteOK** | JSON API | Международные remote-вакансии |
| **Remotive** | JSON API | Remote-вакансии от проверенных компаний |
| **Working Nomads** | JSON API | Remote-вакансии, агрегатор |
| **We Work Remotely** | RSS | Категории Design и Product |
| **Design Jobs Board** | RSS | Дизайнерские вакансии |
| **Remotive Design** | RSS | Дизайн-категория Remotive |

Все они фильтруются одними и теми же ключевыми словами. Если источник временно недоступен — бот пишет предупреждение и продолжает с остальными.

## Что нужно один раз настроить

### 1. Создать бота и получить токен
1. Открой в Telegram [@BotFather](https://t.me/BotFather) → `/newbot` → задай имя и username.
2. Скопируй токен вида `123456789:AAE...`.

### 2. Узнать свой chat_id
1. Напиши что-нибудь **своему новому боту** (нажми Start), иначе он не сможет тебе писать.
2. Открой `https://api.telegram.org/bot<ТОКЕН>/getUpdates` и найди `"chat":{"id":123456789}` — это `chat_id`.

### 3. Вписать значения в `config.json`
```json
"telegram": { "bot_token": "123456789:AAE...", "chat_id": "123456789" }
```

## Запуск

Нужен Python 3.9+. Установи зависимости один раз:
```bash
pip install -r requirements.txt
```

```bash
python vacancy_bot.py --test      # проверить связь с Telegram
python vacancy_bot.py --dry-run   # показать, что находит, ничего не отправляя
python vacancy_bot.py             # запустить постоянно (Ctrl+C — стоп)
python vacancy_bot.py --once      # один прогон (для cron)
```

При первом запуске бот помечает все текущие вакансии как «виденные» и **не** спамит ими — присылать начнёт только то, что появится после старта.

## Как включать/выключать источники и добавлять свои RSS

В `config.json` у каждого источника есть флаг `"enabled"`. Чтобы отключить — поставь `false`.

Добавить любой другой RSS-фид (многие job-борды его отдают) — просто допиши строку в `sources.rss.feeds`:
```json
{ "name": "Моё название", "url": "https://сайт/feed" }
```
Формат бот распознаёт автоматически. Проверить, что у сайта есть фид, можно, открыв `https://сайт/feed` или `https://сайт/rss` в браузере — если увидишь XML, значит работает.

## Настройки поиска

| Поле | Что делает |
|------|-----------|
| `search.keywords` | Список фраз. Совпадение — если фраза входит в название/компанию/теги вакансии. |
| `sources.hh.area` | ID региона hh.ru. `null` = все. Москва `1`, СПб `2`, вся Россия `113`. Список: https://api.hh.ru/areas |
| `sources.hh.period_days` | За сколько дней смотреть выдачу hh. |
| `sources.hh.only_with_salary` | `true` — только вакансии с зарплатой. |
| `poll_interval_minutes` | Как часто проверять. 15 — разумный минимум. |

После правок `config.json` перезапусти бота.

## Статус остальных сайтов из твоего списка

**🟡 Есть RSS / можно добавить строкой в конфиг** (проверь `/feed` или `/rss`):
uiuxjobsboard, designproject.io, weloveproduct, dezeenjobs, lemanoosh, uxwork.nl, craftscareers, designremotejobs, nodesk, 4dayweek.io, aijobs.net, euremotejobs, jobsinforex, unjobs — у части фид есть, у части нет; рабочие добавляются одной строкой в `feeds`.

**🟠 Нужен headless-браузер (парсинг HTML, хрупко, требует поддержки):**
remocate, jobgether, productjobsanywhere, remotivated, remoterocketship, magnet.me, relocate.me, expatjobs, crawljobs, jooble, remotived. Делается отдельными модулями под каждый сайт; ломается при редизайне.

**🔴 Практически закрыты для ботов (защита + запрет в ToS, нужны официальные/платные API):**
LinkedIn, Indeed, Glassdoor, ZipRecruiter, Wellfound, Y Combinator, Otta, Arc.dev, Dice, CareerBuilder, The Muse, FlexJobs, BuiltIn. Надёжно и легально скрейпить их не выйдет.

Скажи, какие из 🟡/🟠 тебе особенно важны — проверю фиды и подключу.

## Файлы
- `vacancy_bot.py` — бот (все источники в одном файле).
- `config.json` — настройки: токен, ключевые слова, источники, RSS-фиды.
- `seen.json` — создаётся автоматически, помнит отправленные вакансии.
- `requirements.txt` — зависимости (`requests`, `feedparser`).

## Чтобы работал 24/7
Скрипт должен где-то постоянно крутиться: включённый компьютер, cron с `--once` каждые 15 минут, или VPS/облако (самое надёжное). Могу помочь развернуть.
