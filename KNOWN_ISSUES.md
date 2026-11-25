# Known issues

Bugs decided not to fix now, and rare cases where the app can go wrong (source data, races, network failures, unusual settings) — whoever found them: review, check, tests or the owner.

- Recorded in the same session it was found, never only in chat.
- IDs `KI-<n>` go in order and are never reused.
- Fixed: the entry stays, its status becomes `fixed (test: …)`, and the index row changes too.
- `won't fix (test: …)` — the app cannot fix it; the entry says why and what the owner decided; the test pins the behaviour.
- Each stage description pulls in the open entries that fit its stage.
- Before final polishing, every open entry gets a test.
- Sessions read the index; a full entry is found by its `## KI-<n>` heading (Grep), never by reading the whole file.
- Entries written before 2026-11-01 are in Russian with the labels Где · Что не так · Как воспроизвести · Насколько вероятно / чем грозит · Статус · Найдено; they keep their form (Статус: Открыто = open, Исправлено = fixed).

## Index

| ID | Title | Where | Status | Fix in |
|---|---|---|---|---|
| KI-1 | Аниме: сдвиг частей сезона может упереться в уникальный ключ | `app/tracker/pollers/anime.py` | fixed (test: `tests/test_tracker_anime_part_moves.py`) | 9.1a |
| KI-2 | Аниме: новый приквел у франшизы даёт дубль тайтла при повторном добавлении | `app/tracker/titles.py` | fixed | — |
| KI-3 | Docker: проверка здоровья контейнера всегда проваливается | `docker-compose.yml` | fixed | — |
| KI-4 | Docker: на Linux бот может не получить права на запись в `data/` | `Dockerfile` | fixed | — |
| KI-5 | Остановка, оборвавшая отправку, может повторить сообщение после старта | `app/runtime.py` | fixed (test: `tests/test_delivery_send_unit.py`); the rest is KI-78 | 9.1a |
| KI-6 | Сторож не видит зависание с захваченной блокировкой интерпретатора (GIL) | `app/runtime.py` | fixed (test: `tests/test_healthcheck.py`) | 9.1a |
| KI-7 | Перезапуск сбрасывает счётчик блокировки входа | `app/web/auth.py` | fixed | 7.2.03 |
| KI-8 | Украденную cookie сессии выход не отзывает | `app/web/app.py` | fixed | 7.2.03 |
| KI-9 | Остановка не дожидается начатых нажатий в боте | `app/runtime.py` | fixed (test: `tests/test_bot_stop_watch.py`) | 9.1a |
| KI-10 | «Посмотрел» сдвигает «последнюю проверку источников» в строке веба | `app/tracker/listing.py` | fixed | — |
| KI-11 | Веб: неподдержанный метод и ошибка сервера отвечают не в общем виде | `app/web/app.py` | fixed | — |
| KI-12 | Чужая страница с подменой адреса (DNS rebinding) проходит проверку Origin | `app/web/app.py` | fixed | 7.2.04 |
| KI-13 | Испорченный файл ключа сессий не пересоздаётся | `app/web/auth.py` | fixed | 7.2.03 |
| KI-14 | Пауза повтора подключения бота сбрасывается раньше, чем в спеке | `app/runtime.py` | fixed | — |
| KI-15 | Старт контейнера не от root всё равно проверяет PUID и PGID | `app/container_start.py` | fixed (test: `tests/test_container_start.py::test_start_not_as_root_ignores_puid_and_pgid_and_warns_of_nothing`) | 7.3.02 |
| KI-16 | Сбой запуска с меняющимся текстом сообщается при каждом повторе | `app/startup_report.py` | fixed (test: `tests/test_startup_report.py`) | 9.1a |
| KI-17 | Запись о сбое запуска не сохраняется — сообщение при каждом повторе | `app/startup_report.py` | fixed (test: `tests/test_startup_report.py`) | 9.1a |
| KI-18 | `.\start-bot.ps1` останавливает и чужой `python -m app.main` | `start-bot.ps1` | fixed (test: `tests/test_docker_files.py`) | 9.1a |
| KI-19 | `.\start-bot.ps1` может ждать итога дольше 90 секунд | `start-bot.ps1` | fixed (test: `tests/test_docker_files.py`) | 9.1a |
| KI-20 | Имя `kind` для типа ошибки в `app/startup_report.py` | `app/startup_report.py` | fixed (test: `tests/test_startup_report.py`) | 9.1a |
| KI-21 | Постеры непроверяемых аниме пропадают при смене адреса Shikimori | `app/tracker/pollers/` | fixed (test: `tests/test_poster_site.py`) | 9.1a |
| KI-22 | «Бросил» во время проверки этого же тайтла может пропустить одно сообщение | `Tracker.mark_dropped` | fixed (test: `tests/test_tracker_dropped_restore.py`, `tests/test_tracker_check_rules.py`) | 9.1a |
| KI-23 | Факт, случившийся сразу после «Вернуть в список», становится точкой отсчёта | `Poller.record_all` | fixed (test: `tests/test_tracker_dropped_restore.py`); the rest is KI-77 | 9.1a |
| KI-24 | Номер удалённого последнего тайтла достаётся следующему добавленному | `app/tracker/models.py` | fixed (test: `tests/test_tracker_issued_ids.py`) | 9.1a |
| KI-25 | Очень длинный номер в адресе карточки — «Не получилось» вместо «Этого тайтла нет в списке» | `app/web/card.py` | fixed | — |
| KI-26 | Бот пишет в журнал сбой поиска и добавления без причины | `app/bot/tracker_handlers.py` | fixed | — |
| KI-27 | Устаревшая карточка аниме ставит галочку не тому сезону после перенумерации | `app/web/card.py` | fixed | — |
| KI-28 | Лента: серия аниме ровно в 00:00 UTC показывается без часа | `app/tracker/sources/shikimori_anime.py` | fixed (test: `tests/test_tracker_episode_timing.py`, `tests/test_tracker_feed.py`) | 9.1 |
| KI-29 | «Недавно» не показывает вышедшее до добавления и до первой проверки после возврата | `Poller.record_all` | fixed (test: `tests/test_tracker_feed_released.py`) | 9.1c |
| KI-30 | Фильтр жанров Архива: один жанр под разными именами | `Tracker.genres` | fixed (test: `tests/test_tracker_genres_table.py`) | 9.1c |
| KI-31 | Список: поиск в режиме «Удалить несколько» сбрасывает галочки | `app/web/title_list.py` | fixed | — |
| KI-32 | Лента: серия аниме, найденная без расписания, стоит в «Сегодня» с часом проверки | `app/tracker/anime_events.py` | fixed (test: `tests/test_tracker_episode_timing.py`, `tests/test_tracker_feed.py`) | 9.1 |
| KI-33 | Строка «Бот не подключён к Telegram» не появляется, если связь пропала во время приёма | `app/runtime.py` | fixed (test: `tests/test_bot_stop_watch.py`) | 9.1a |
| KI-34 | Настройки: старые методы ядра и страница проверяют значения по-разному | `app/tracker/settings_store.py` | fixed | — |
| KI-35 | Игры: дата выхода только в Японии считается выходом | `app/tracker/games.py` | fixed (test: `tests/test_tracker_games_dates.py`, `tests/test_tracker_game_outside_date.py`) | 9.1b |
| KI-36 | Игры: выход, о котором IGDB узнал больше чем через 30 дней, приходит без сообщения | `app/tracker/game_events.py` | fixed (test: `tests/test_tracker_game_events.py`, `tests/test_tracker_game_late_release.py`) | 9.1b |
| KI-37 | Игры: ссылка в PlayStation Store может вести на страницу ошибки | `app/tracker/games.py` | fixed (test: `tests/test_tracker_playstation.py`); fixed for the web card, the bot's text link keeps the concept | 9.1b |
| KI-38 | Игры: запись IGDB без точности даты читается как «дата не объявлена» | `app/tracker/games.py` | fixed (test: `tests/test_tracker_games_dates.py`) | 9.1b |
| KI-39 | Игры: примерная дата старшей платформы прячет точную дату своей | `app/tracker/games.py` | fixed | — |
| KI-40 | Игры: галочка «играю здесь» меняется у платформы, которой у игры больше нет | `app/tracker/statuses.py` | fixed | — |
| KI-41 | Настройки, испорченные руками в базе, кроме пояса, платформ и страны, ломают чтение | `app/tracker/settings_store.py` | fixed (test: `tests/test_tracker_rare_input.py`) | 9.1a |
| KI-42 | Ручной запрос «Добавить» с номером не из цифр отвечает «Не удалось связаться» | `app/tracker/titles.py` | fixed (test: `tests/test_tracker_rare_input.py`) | 9.1a |
| KI-43 | Цены Steam: цена бандла — для покупателя без игр набора | `app/tracker/sources/steam_prices.py` | won't fix (test: `tests/test_tracker_price_known_issues.py`) | 9.1b |
| KI-44 | Цены Steam: предзаказ проверен только на собранном ответе | `app/tracker/sources/steam_prices.py` | fixed (test: `tests/test_tracker_price_known_issues.py`) | 9.1b |
| KI-45 | Сбой Steam и сбой IGDB одной игры за сутки — одно сообщение | `app/tracker/queue.py` | fixed (test: `tests/test_tracker_failures.py`) | 9.1a |
| KI-46 | Цены Steam: короткая скидка может пройти без сообщения или с неверным «до» | `app/tracker/pollers/game_prices.py` | won't fix (test: `tests/test_tracker_price_known_issues.py`) | 9.1b |
| KI-47 | Цены Steam: сообщение о скидке может уйти в ту минуту, когда игра ушла из «Хочу» | `app/tracker/pollers/game_prices.py` | fixed (test: `tests/test_tracker_price_press.py`) | 9.1b |
| KI-48 | Anime card: no episode or schedule data for an announced season (Jujutsu Kaisen) | `app/tracker/sources/` | won't fix (test: `tests/test_shikimori_anime_source.py`) | 9.1 |
| KI-49 | `.env` holds variables the code does not read | `.env` | fixed (test: `tests/test_env_example.py`) | 9.1d.05 |
| KI-50 | Steam prices: a spoiled price snapshot stops the price check of every game | `app/tracker/pollers/game_prices.py` | fixed (test: `tests/test_tracker_price_known_issues.py`) | 9.1b |
| KI-51 | Steam prices: the discounts of one check can come as separate messages | `app/tracker/pollers/game_prices.py` | fixed (test: `tests/test_tracker_price_batch.py`) | 9.1b |
| KI-52 | Expansions: a standalone expansion completed before 6.3 never learns it is one | `app/tracker/sources/igdb_games.py` | fixed (test: `tests/test_tracker_follow_up_known_issues.py`) | 9.1b |
| KI-53 | Follow-ups: «Бросил» and «Вернуть в список» within one minute keep the old reference point | `app/tracker/pollers/game_follow_ups.py` | fixed (test: `tests/test_tracker_follow_up_known_issues.py`) | 9.1b |
| KI-54 | Follow-ups: an announcement taken out by «Бросил» never comes from another game of the series | `app/tracker/queue.py` | fixed (test: `tests/test_tracker_follow_up_known_issues.py`) | 9.1b |
| KI-55 | Follow-ups: a game whose own snapshot cannot be read logs a line every minute; never told if it had no check yet | `app/tracker/pollers/game_follow_ups.py` | fixed (test: `tests/test_tracker_follow_up_known_issues.py`) | 9.1b |
| KI-56 | The size test of the core misses the pure modules: `series_events.py` 547 lines, `games.py` 406 | `tests/test_tracker_core_split.py` | fixed (test: `tests/test_tracker_core_split.py`) | 9.1d.01 |
| KI-57 | «Входящие»: a restart within the 2-second pause leaves the item without «Что это?» | `app/bot/inbox_handlers.py` | fixed (test: `tests/test_inbox_after_restart.py`) | 9.1d.04 |
| KI-58 | «Входящие»: a Cyrillic name in the middle of a post without quotes, kind word or bold is not a candidate | `app/tracker/candidates.py` | fixed (test: `tests/test_tracker_candidates_middle.py`) | 9.1d.03 |
| KI-59 | «Входящие»: the stop list of candidates is a fixed list | `app/tracker/candidates.py` | fixed (test: `tests/test_tracker_companies.py`) | 9.1d.03 |
| KI-60 | «Входящие»: a Latin run keeps a leading «from», and a bare number after a colon is cut off the name | `app/tracker/candidates.py` | fixed (test: `tests/test_tracker_candidates_middle.py`) | 9.1d.03 |
| KI-61 | «Входящие»: a typo in a name is not corrected when the source answers in another language | `app/tracker/offers.py` | fixed (test: `tests/test_inbox_offer_dates.py`) | 9.1d.04 |
| KI-62 | «Входящие»: a kind press does not look the links of the item up again | `app/tracker/inbox_answers.py` | fixed (test: `tests/test_inbox_offer_dates.py`) | 9.1d.04 |
| KI-63 | The Shikimori adapter is over the 400 lines of rule 7, and the size test does not see it | `app/tracker/sources/shikimori_anime.py` | fixed (test: `tests/test_tracker_core_split.py`) | 9.1d.01 |
| KI-64 | «Входящие»: an offer of a title announced for a year or a quarter shows a made-up day («выйдет 31 декабря 2028») | `app/tracker/offers.py` | fixed (test: `tests/test_inbox_offer_dates.py`) | 9.1d.04 |
| KI-65 | «Входящие»: «Найти» cannot remove an item whose title is in the list already | `app/web/templates/suggestions.html` | fixed (test: `tests/test_web_inbox.py`) | 9.1c |
| KI-66 | Copies: the time of a copy is the container's clock, not the zone of Settings | `app/utils/backup.py` | fixed (test: `tests/test_copy_names_utc.py`) | 9.1d.05 |
| KI-67 | Google Drive copy: a folder of over 1000 files is listed only in part | `app/providers/google_drive.py` | fixed (test: `tests/test_copy_names_utc.py`) | 9.1d.05 |
| KI-68 | Google Drive copy: an archive of the same name but another size stays as a duplicate until it rotates out | `app/tracker/drive_copies.py` | fixed (test: `tests/test_drive_copies.py`) | 9.1d.05 |
| KI-69 | Restore: the note «ещё одна копия» of an older copy is not always true | `app/utils/restore.py` | fixed (test: `tests/test_restore.py`) | 9.1d.05 |
| KI-70 | Restore: `restore-bot.ps1` needs a recent Docker Compose (`--quiet-build`) | `restore-bot.ps1` | fixed (test: `tests/test_restore.py::test_the_script_builds_the_image_once_before_the_first_run_and_runs_it_without_build_flags`) | 7.3.01 |
| KI-71 | Export: the JSON asks which titles are games and copies the poller's rule of the base game | `app/tracker/export_all.py` | fixed (test: `tests/test_tracker_split_health.py`) | 9.1d.01 |
| KI-72 | Login report: an iPad on iPadOS 13+ reads as «macOS, Safari» | `app/web/devices.py` (stage 7.2) | won't fix (test: `tests/test_web_devices.py`) | 9.1c |
| KI-73 | Login report: a report that failed to send waits for the delivery rules | `app/tracker` (stage 7.2) | fixed (test: `tests/test_tracker_login_report_rules.py`) | 9.1c |
| KI-74 | Phone: the chosen filter can be past the edge of its row | `app/web/static/style.css` (stage 7.2) | fixed (test: `tests/test_web_css.py`) | 9.1c |
| KI-75 | Sign-ins: the block «Вход» counts sign-ins ended by a new `WEB_PASSWORD` or key | `app/web/sessions.py` | fixed (test: `tests/test_web_sign_in_mark.py`) | 9.1c |
| KI-76 | `APP_URL`: a Cyrillic domain is refused with a reason about the dot | `app/config.py` | fixed (test: `tests/test_app_url.py`) | 9.1c |
| KI-77 | Anime: an episode out right after «Вернуть в список» passes silently | `app/tracker/pollers/base.py` (spec 9.1a, 4.2) | fixed (test: `tests/test_tracker_check_rules.py`) | 9.1c |
| KI-78 | A send Telegram has not answered within 5 s of a stop can come again after the start | `app/tracker/delivery_service.py` (spec 9.1a, 2.1) | open | 9.2 |
| KI-79 | Russian: a game added before 9.1b says «Ещё не проверяли» until its own poll (up to a week), with a Steam page up to 6 hours more | `app/tracker/pollers/game_russian.py` (spec 9.1b, 5.5) | open | 9.2 |
| KI-80 | ZoG: while its layout cannot be read, a game whose page is not known yet shows no ZoG hint | `app/tracker/pollers/game_zog.py` (spec 9.1b, 5.6) | open | 9.2 |
| KI-81 | Anime: a premiere Shikimori knows by the month or the year stands on a made-up first day | `app/tracker/sources/shikimori_chain.py` (`part_episodes`) | fixed (test: `tests/test_tracker_anime_approximate.py`, `tests/test_tracker_anime_approximate_polls.py`) | 9.1d |
| KI-82 | Login report: a report that waits past midnight says «сегодня» of the day before | `app/tracker/login_reports.py` | open | 9.2 |
| KI-83 | Anime: an episode first seen with an AniList airing earlier than the previous look comes with no message | `app/tracker/anime_events.py` (`assemble`), `series_events._newly_out` | fixed (test: `tests/test_tracker_anime_late_and_moves.py`) | 9.1d |
| KI-84 | Anime: a premiere moved by hours within its day reads «9 янв 2027 → 9 янв 2027» | `app/tracker/series_messages.py` (`message_moved`), `series_moves` | fixed (test: `tests/test_tracker_anime_late_and_moves.py`) | 9.1d |
| KI-85 | Anime: a franchise film Shikimori knows by the month or the year stands on a made-up first day | `app/tracker/sources/shikimori_anime.py`, `MovieRecord.aired_on` | open | 9.2 |
| KI-86 | «Входящие»: a number after a colon joins a Latin name before a counting word other than an episode, a season or a part («Hades: 2 дня…», «Elden Ring: 10 из 10») | `app/tracker/candidates.py` (`_LATIN_RUN`) | open | 9.2 |
| KI-87 | «Входящие»: an item a newer message moved to «Входящие» while its links were looked up still gets its offer card | `app/tracker/inbox_answers.py` (`pause_over`, `_finish`) | open | 9.2 |
| KI-88 | «Входящие»: the series «From» as a lone Latin word of a post is no candidate | `app/tracker/candidates.py` (`_without_from`) | open | 9.2 |
| KI-89 | «Входящие»: a Russian name with a hyphen in the middle of a sentence is cut at the hyphen («Человек-паук» → «Человек») | `app/tracker/candidates.py` (`_CAPITAL_WORD`) | open | 9.2 |
| KI-90 | Copies on the HDD: the hourly job lists their folder every hour and may wake the disk | `app/utils/backup.py` (`backup_if_due`), `app/tracker/drive_copies.py` (`_due`) | open | 9.2 |
| KI-91 | Copies on the HDD: a folder missing at the container's start is created on the system disk | `docker-compose.override.yml` (NAS only) | open | 9.2 |
| KI-92 | Restore: with no answer from the name service a stopped bot counts as running | `app/utils/restore.py` | open | 9.2 |

## Entries

Format of a new entry:

```text
## KI-<n>. <title>

- Where: file and function.
- What's wrong: one or two sentences.
- How to reproduce: concrete input or state, and what comes out.
- Likelihood / impact:
- Status: open | fixed (test: …)
- Found: date, by what (review, check, owner).
```

## KI-1. Аниме: сдвиг частей сезона может упереться в уникальный ключ

- **Где:** `app/tracker/pollers/anime.py`, `AnimePoller._sync_entries` (выбор переездов частей `moves`).
- **Что не так:** часть получает разрешение на переезд, если её новое место не занято «неподвижной» записью. Но не проверяется, уедет ли оттуда запись, которая стоит там сейчас. Если её собственный переезд заблокирован, две части встают на одно место `(season_id, number)`.
- **Как воспроизвести:** сезон из 4 частей `[P1, C, B, A]`. Shikimori убирает `C` из цепочки (поменял тип записи или связь). Тогда `B` должна уйти на место 2, но там осталась старая запись `C`, поэтому `B` остаётся на месте 3. `A` хочет на место 3 и едет туда. Получается `IntegrityError` (`uq_season_parts_season_number`).
- **Насколько вероятно / чем грозит:** редко: нужен сезон из 4 частей и больше, у которого Shikimori убрал из цепочки среднюю часть. Если это случится, проверка этого аниме будет падать каждые 30 минут, а раз в сутки будет приходить сообщение «Не удалось проверить». Новых событий по этому тайтлу не будет.
- **Статус:** fixed (test: `tests/test_tracker_anime_part_moves.py::test_the_example_of_ki_1_moves_nothing_and_says_so_once`), тикет 04 части 9.1a: часть переезжает, только когда её новое место свободно после переездов (`_free_moves`).
- **Найдено:** 2026-10-27, ревью ветки `audit-fixes` от `wip/before-audit`. На данных владельца не встречается: прогон опроса на копии базы прошёл чисто.

## KI-2. Аниме: новый приквел у франшизы даёт дубль тайтла при повторном добавлении

- **Где:** `app/tracker/titles.py`, `Titles.add_title` / `_store_title`. Ещё `app/tracker/sources/shikimori_anime.py`, `build_snapshot` (`external_id` — это id первого сезона).
- **Что не так:** аниме-тайтл запоминается по id первого сезона франшизы на момент добавления, и этот id потом не обновляется. Если Shikimori позже добавит в цепочку приквел, первым сезоном станет другая запись. Повторное добавление той же франшизы её не узнает и создаст второй тайтл.
- **Как воспроизвести:** франшиза добавлена, когда первым сезоном была запись `H1`. Позже в цепочке появляется приквел `H0`. Владелец ищет это аниме ещё раз; в подсказке показывается самый ранний сезон, то есть `H0`. Снимок возвращает `external_id = H0`, поиск по `H0` ничего не находит, и `_store_title` создаёт второй тайтл.
- **Насколько вероятно / чем грозит:** редко. Обе копии опрашиваются, поэтому о каждой серии приходит по два сообщения. Удалить лишнюю копию можно руками.
- **Статус:** Исправлено (тест: `tests/test_tracker_search.py`, `test_ki_2_…`): аниме узнаётся по первому сезону, любой части и любому фильму франшизы — до запроса к источнику по id подсказки, после снимка в той же сессии записи по всем id цепочки; снимок совпал с двумя тайтлами — открывается меньший номер, в журнал — предупреждение. Подсказка приквела, которого нет в базе, пометки «В списке» не получает, но «Добавить» открывает тот же тайтл. Часть 5.2, тикет 03.
- **Найдено:** 2026-10-27, ревью ветки `audit-fixes` от `wip/before-audit`.

## KI-3. Docker: проверка здоровья контейнера всегда проваливается

- **Где:** `docker-compose.yml`, блок `healthcheck` (`pgrep -f 'python -m app.bot.main'`); `Dockerfile` (образ `python:3.12-slim`).
- **Что не так:** в образе `python:3.12-slim` нет программы `pgrep` (пакет `procps` не ставится), поэтому команда проверки падает при каждом запуске, даже когда бот работает.
- **Как воспроизвести:** `docker compose up -d`, подождать 2–3 минуты, `docker compose ps` — контейнер помечен `unhealthy`, хотя бот отвечает в Telegram.
- **Насколько вероятно / чем грозит:** всегда при запуске через `docker compose`. Сейчас вреда нет (`restart: unless-stopped` не перезапускает «нездоровый» контейнер), но на NAS или сервере такая пометка путает: настоящий сбой от ложного не отличить.
- **Статус:** Исправлено (тесты: `tests/test_healthcheck.py`, `tests/test_docker_files.py::test_dockerfile_starts_as_root_and_checks_health_with_python`; тикет 02 части 5.1). Проверка здоровья — `python -m app.healthcheck` (запрос к `/health`, без `pgrep`); в облаке контейнер стал `healthy`.
- **Найдено:** 2026-10-27, обсуждение размещения (чтение `Dockerfile` и `docker-compose.yml`).

## KI-4. Docker: на Linux бот может не получить права на запись в `data/`

- **Где:** `Dockerfile` (`USER nobody`, `chown` папок внутри образа) и `docker-compose.yml` (`./data:/app/data`, `./logs:/app/app/logs`).
- **Что не так:** папки подключаются с компьютера-хозяина поверх папок образа, и их владелец — хозяин (обычно `root`), а не `nobody`. На Linux (сервер, NAS) процесс от `nobody` не сможет создать `tracker.db`, копии и журнал. На Windows с Docker Desktop права не проверяются, поэтому там запуск проходил.
- **Как воспроизвести:** на Linux-машине: `mkdir data logs`, `docker compose up` — бот падает при открытии базы или файла журнала с ошибкой «Permission denied».
- **Насколько вероятно / чем грозит:** почти наверняка при первом запуске на сервере или NAS; бот не стартует.
- **Статус:** Исправлено (тесты: `tests/test_container_start.py`; тикет 02 части 5.1). Контейнер стартует от `root`, `app/container_start.py` передаёт папке `data` владельца `PUID:PGID` (по умолчанию 1000:1000), сбрасывает права и проверяет запись. Проверено на Linux в облаке 2026-10-27: папка `data`, созданная от `root`, получила `1000:1000`, процесс работал как 1000, `tracker.db` и `data/logs/bot.log` создались. На NAS с другим владельцем папки — задать `PUID` и `PGID` в `.env`; проверка на NAS — при переезде (кусок 7).
- **Найдено:** 2026-10-27, обсуждение размещения (чтение `Dockerfile` и `docker-compose.yml`).

## KI-5. Остановка, оборвавшая отправку, может повторить сообщение после старта

- **Где:** `app/runtime.py`, `Runtime._stop_scheduler` (задачи дольше 15 секунд отменяются); `app/tracker/delivery_service.py` (отметка «доставлено» ставится после ответа Telegram).
- **Что не так:** если остановка (`Ctrl+C`, позже `docker compose down`) отменила отправку очереди в промежутке между «Telegram принял сообщение» и «запись отмечена доставленной», запись остаётся в очереди и после следующего старта уходит ещё раз.
- **Как воспроизвести:** отправка очереди идёт дольше 15 секунд (много событий, медленная сеть) и в этот момент приходит остановка. Владелец получает одно и то же сообщение дважды: до остановки и после старта.
- **Насколько вероятно / чем грозит:** редко: отправка обычно занимает секунды. Вред — повтор одного сообщения, без потери событий.
- **Статус:** fixed (test: `tests/test_delivery_send_unit.py::test_a_cancel_during_a_send_waits_for_its_mark_and_starts_no_next_send`), тикет 03 части 9.1a: отправка и запись её исхода — одна задача (`DeliveryService._send`, `CoreContext.sends`), отмена ждёт её конца; при остановке `TelegramPart.close` ждёт отправки до 5 с (`Tracker.finish_sends`) до закрытия сессии. Остаётся отправка, на которую Telegram не ответил за эти 5 с, — KI-78.
- **Найдено:** 2026-10-27, спека части 5.1 (раздел 7), вводится тикетом 01.

## KI-6. Сторож не видит зависание с захваченной блокировкой интерпретатора (GIL)

- **Где:** `app/runtime.py`, `Watchdog` (поток вне цикла событий).
- **Что не так:** сторож — поток того же процесса. Если цикл событий завис внутри кода на C, который держит блокировку интерпретатора (GIL) и не отпускает её, поток сторожа тоже не получает времени и не может выйти из процесса.
- **Как воспроизвести:** искусственно — долгий вызов C-расширения без отпускания GIL в цикле событий. На нашем коде не встречается: работа с базой идёт в отдельных потоках, сеть — асинхронная.
- **Насколько вероятно / чем грозит:** очень редко. Процесс висит: бот не отвечает, веб не открывается. Позже, в Docker, проверка здоровья пометит контейнер `unhealthy`, но сам Docker его не перезапустит; помогает ручной перезапуск.
- **Статус:** fixed (test: `tests/test_healthcheck.py::test_four_timeouts_in_a_row_kill_the_app_and_say_so`), тикет 03 части 9.1a: проверка здоровья Docker считает таймауты подряд и на четвёртом останавливает приложение (SIGKILL), контейнер перезапускается (`init: true`, ADR 0015).
- **Найдено:** 2026-10-27, спека части 5.1 (раздел 7), вводится тикетом 01.

## KI-7. Перезапуск сбрасывает счётчик блокировки входа

- **Где:** `app/web/auth.py`, `LoginGuard` (счётчик и время блокировки лежат в памяти процесса).
- **Что не так:** после пяти неверных паролей вход закрывается на 15 минут, но перезапуск приложения (`.\stop-bot.ps1` и `.\start-bot.ps1`, перезагрузка ПК) обнуляет и счётчик, и блокировку.
- **Как воспроизвести:** пять раз ввести неверный пароль, перезапустить контейнер — вход снова открыт, попыток снова пять.
- **Насколько вероятно / чем грозит:** принято. Перезапустить контейнер может только тот, кто уже сидит за ПК владельца (порт открыт только на `127.0.0.1`), а такому человеку пароль веба не нужен. Станет важнее, когда веб откроют вне дома (кусок 7): тогда счётчик стоит хранить в `data/`.
- **Статус:** fixed (test: `tests/test_web_sign_ins.py::test_the_lock_survives_a_new_app_on_the_same_file`), тикет 03 этапа 7.2.
- **Найдено:** 2026-10-27, спека части 5.1 (раздел 7), записано в тикете 03.

## KI-8. Украденную cookie сессии выход не отзывает

- **Где:** `app/web/app.py` (сессия — подписанная cookie `tracker_session`, на сервере сессии не хранятся), `POST /logout`.
- **Что не так:** выход очищает cookie только в браузере. Скопированная cookie остаётся действительной до конца 30 дней или до смены `WEB_PASSWORD` (отпечаток пароля в сессии перестаёт совпадать).
- **Как воспроизвести:** скопировать cookie из браузера, нажать «Выйти», вставить cookie в другой клиент — страницы откроются.
- **Насколько вероятно / чем грозит:** принято. Веб открыт только для самого ПК; чтобы взять cookie, нужен доступ к браузеру владельца. Если украли — смена `WEB_PASSWORD` выбрасывает все входы. Станет важнее при доступе вне дома (кусок 7): тогда нужен список отозванных сессий в `data/`.
- **Статус:** fixed (test: `tests/test_web_sign_ins.py::test_the_sign_out_ends_only_its_own_sign_in_and_its_copied_cookie`), тикет 03 этапа 7.2.
- **Найдено:** 2026-10-27, спека части 5.1 (раздел 7), записано в тикете 03.

## KI-9. Остановка не дожидается начатых нажатий в боте

- **Где:** `app/runtime.py`, `Runtime._stop` / `_stop_bot`; `app/main.py`, `TelegramPart.stop` (aiogram `Dispatcher.stop_polling` не ждёт задачи обработчиков).
- **Что не так:** остановка ждёт идущие задачи планировщика (до 15 секунд) и запросы веба (до 5 секунд), но не обработчики бота: aiogram обрабатывает каждое нажатие отдельной задачей и при `stop_polling` её не ждёт. Сессия Telegram закрывается, оставшиеся задачи отменяет `asyncio.run` при выходе.
- **Как воспроизвести:** нажать «➕ Добавить» у сериала с многими сезонами и сразу выполнить `.\stop-bot.ps1` (или `.\start-bot.ps1` после обновления файлов: он пересоздаёт контейнер). Владелец видит «Добавляю…», а карточка и вопрос о сезонах не приходят; в журнале — ошибки отправки. Тайтл добавится, если запись в базу уже началась (поток доделывается), иначе — нет.
- **Насколько вероятно / чем грозит:** редко: нужно нажатие за несколько секунд до остановки. Вред — нет ответа на нажатие; после старта нажать ещё раз.
- **Статус:** fixed (test: `tests/test_bot_stop_watch.py::test_stop_waits_for_a_running_press_that_ends_within_the_grace`), тикет 03 части 9.1a: `RunningUpdates` (внешний слой `dp.update`) держит задачи нажатий, `TelegramPart.stop` ждёт их до 10 с; `stop_grace_period` — 45 с.
- **Найдено:** 2026-10-27, код-ревью части 5.1 (Н8).

## KI-10. «Посмотрел» сдвигает «последнюю проверку источников» в строке веба

- **Где:** `app/tracker/listing.py`, `Listing._overview` (самый поздний `source_snapshots.observed_at`) и `app/tracker/statuses.py`, `Statuses._set_watched` (снимок продолжений создаётся с `observed_at` = момент нажатия и пустым `state`).
- **Что не так:** строка «последняя проверка источников в …» берёт самый поздний момент из снимков источников. «Посмотрел» у фильма заводит пустой снимок продолжений с моментом нажатия, хотя источник никто не спрашивал.
- **Как воспроизвести:** последняя настоящая проверка была, например, вчера; нажать «Посмотрел» у фильма — через минуту строка в вебе пишет «последняя проверка источников в <сейчас>».
- **Насколько вероятно / чем грозит:** при каждом «Посмотрел» у фильма. Вред небольшой: по этой строке владелец судит, что опрос работает, а она может скрыть, что опрос давно не ходил. Чинить вместе с Лентой (часть 5.3) или раньше.
- **Статус:** Исправлено (тест: `tests/test_tracker_feed.py::test_watched_does_not_move_the_last_check_and_the_first_real_sequel_check_does`; тикет 04 части 5.3). `overview` берёт самый поздний `observed_at` только среди снимков с непустым `state`: пустой снимок продолжений, который заводит «Посмотрел», — ещё не ответ источника (`Sequels.checked`).
- **Найдено:** 2026-10-27, код-ревью части 5.1 (Н9).

## KI-11. Веб: неподдержанный метод и ошибка сервера отвечают не в общем виде

- **Где:** `app/web/app.py`, `create_web_app` (свой обработчик есть только у ответа 404; `protect_requests` стоит внутри `ServerErrorMiddleware`, который собирает ответ 500).
- **Что не так:** (1) запрос методом, которого у адреса нет, получает голый текст `{"detail":"Method Not Allowed"}` (405) вместо страницы в общем шаблоне; так же отвечают запросы `HEAD` на любую страницу и на `/health` (маршруты FastAPI на `GET` не принимают `HEAD`). (2) Ответ 500 при ошибке в коде страницы уходит без заголовков безопасности (`Content-Security-Policy`, `nosniff`) — спека 3.5 требует их на каждом ответе.
- **Как воспроизвести:** войти и набрать в адресной строке `http://localhost:8080/logout` — белая страница с `{"detail":"Method Not Allowed"}`; `curl -I http://localhost:8080/health` — 405.
- **Насколько вероятно / чем грозит:** браузер владельца такие запросы сам не шлёт. `HEAD /health` важен для внешних мониторов (кусок 7). Ответ 500 без заголовков — простой текст без скриптов, вред минимальный.
- **Статус:** Исправлено (тесты: `tests/test_web_unusual_requests.py`; тикет 01 части 5.4). Запрос методом, которого у адреса нет, получает общую страницу «Так не открывается» с кодом 405 и `Allow` от фреймворка (за входом сначала вход); `HEAD` отвечает как `GET`, без тела (один слой `HeadAsGet` в `app/web/app.py`); ошибка, которую не поймала сетка страницы, — общая страница «Не получилось» с кодом 500, заголовками безопасности и `Cache-Control: no-store`, трассировку пишет сервер.
- **Найдено:** 2026-10-27, код-ревью части 5.1 (Н10).

## KI-12. Чужая страница с подменой адреса (DNS rebinding) проходит проверку Origin

- **Где:** `app/web/app.py`, `protect_requests` (заголовок `Origin` сравнивается с `Host` того же запроса, спека 3.5).
- **Что не так:** сайт злоумышленника, чьё имя после загрузки страницы начинает указывать на `127.0.0.1`, шлёт запросы, у которых `Origin` и `Host` — его собственное имя; они совпадают, и проверка их пропускает. Cookie входа браузер такому сайту не отдаёт (она выдана для `localhost`), поэтому страницы за входом ему закрыты, но он может отправлять пароли на `/login` и так держать вход владельца заблокированным.
- **Как воспроизвести:** только специально подготовленным сайтом (DNS rebinding), открытым в браузере владельца; новые версии Chrome ограничивают запросы сайтов из интернета к локальным адресам.
- **Насколько вероятно / чем грозит:** очень редко. Вред — блокировка входа на 15 минут; перебор пароля медленный (5 попыток в 15 минут).
- **Статус:** fixed (test: `tests/test_web_hosts.py::test_a_foreign_name_cannot_touch_the_lock_count`), тикет 04 этапа 7.2: веб отвечает только под своими именами (`app/web/hosts.py`), чужое имя — `400` до любой страницы и счётчика.
- **Найдено:** 2026-10-27, код-ревью части 5.1 (Н11).

## KI-13. Испорченный файл ключа сессий не пересоздаётся

- **Где:** `app/web/auth.py`, `load_key`.
- **Что не так:** если `data/web_secret` короче 32 байт (например, пустой после сбоя записи или нехватки места на диске), ключ при каждом запуске создаётся заново только в памяти, а файл так и остаётся испорченным.
- **Как воспроизвести:** заменить `data/web_secret` пустым файлом и перезапустить — в журнале предупреждение «файл ключа сессий повреждён», после каждого перезапуска нужно входить заново.
- **Насколько вероятно / чем грозит:** очень редко; вред — повторный вход после каждого перезапуска. Обход: удалить `data\web_secret`, при следующем запуске он создастся заново.
- **Статус:** fixed (test: `tests/test_web_sign_ins.py::test_a_short_key_file_is_replaced_and_a_sign_in_survives_the_next_start`), тикет 03 этапа 7.2.
- **Найдено:** 2026-10-27, код-ревью части 5.1 (Н12).

## KI-14. Пауза повтора подключения бота сбрасывается раньше, чем в спеке

- **Где:** `app/runtime.py`, `Runtime._run_bot`.
- **Что не так:** спека 1.3 возвращает паузу к 30 секундам «после удачного старта приёма», а код — сразу после удачного подключения (`get_me` и меню команд), ещё до приёма. Если приём падает сразу после подключения, пауза не растёт до 5 минут.
- **Как воспроизвести:** только искусственно: aiogram сам повторяет сбои получения сообщений и наружу их не отдаёт.
- **Насколько вероятно / чем грозит:** практически не встречается; вред — запись об ошибке в журнале раз в 30 секунд вместо раза в 5 минут.
- **Статус:** Исправлено (тесты: `tests/test_runtime.py::test_a_connect_alone_does_not_bring_the_pause_back_to_30_seconds`, `test_once_receiving_has_begun_the_pause_is_30_seconds_again`; `tests/test_app_main.py::test_the_bot_part_says_receiving_has_begun_on_the_dispatchers_startup`). Пауза сбрасывается по сигналу о старте приёма (событие `startup` диспетчера aiogram).
- **Найдено:** 2026-10-27, код-ревью части 5.1 (Н13).

## KI-15. Старт контейнера не от root всё равно проверяет PUID и PGID

- **Где:** `app/container_start.py`, `start`.
- **Что не так:** по спеке 2.2 при запуске не от `root` (строка `user:` в `docker-compose.yml`) `PUID` и `PGID` не нужны, но `start` читает их всегда: мусор в `PUID` — выход 1. Сообщение об отказе в записи называет `PUID:PGID`, а не настоящего пользователя процесса.
- **Как воспроизвести:** добавить в `docker-compose.yml` строку `user: "1000:1000"`, а в `.env` — `PUID=abc`: контейнер не стартует с «PUID и PGID должны быть числами…».
- **Насколько вероятно / чем грозит:** наш `docker-compose.yml` запускает от `root`, так что сейчас не встречается; на NAS с `user:` — понятная, но лишняя ошибка.
- **Статус:** Исправлено (тесты: `tests/test_container_start.py::test_start_not_as_root_ignores_puid_and_pgid_and_warns_of_nothing`, `test_start_not_as_root_refuses_an_unwritable_folder_with_the_new_text`, `test_start_as_root_still_reads_puid_and_pgid_and_warns_of_zero`). Не от `root` `PUID` и `PGID` не читаются, личность — `getuid`/`getgid`; отказ в записи называет настоящего пользователя и строку `user:`.
- **Найдено:** 2026-10-27, код-ревью части 5.1 (Н14).

## KI-16. Сбой запуска с меняющимся текстом сообщается при каждом повторе

- **Где:** `app/startup_report.py`, `fingerprint`.
- **Что не так:** «тот же сбой» узнаётся по отпечатку: тип, места в коде и текст ошибки, в котором числа заменены на `#`. Если в тексте меняется что-то кроме чисел (например, случайное имя временного файла), каждый повтор — новый сбой.
- **Как воспроизвести:** сбой запуска, в тексте которого при каждом запуске новое случайное слово: Docker перезапускает контейнер, и каждый раз уходит сообщение «Бот не запустился».
- **Насколько вероятно / чем грозит:** не встречали; вред — сообщение примерно раз в минуту, пока сбой не исправят (как было до круга исправлений по ревью 5.1).
- **Статус:** fixed (test: `tests/test_startup_report.py::test_failures_with_changing_text_go_by_the_sequence_of_the_spec`), тикет 02 части 9.1a.
- **Найдено:** 2026-10-27, спека круга исправлений по ревью 5.1 (раздел 9), введено тикетом 01.

## KI-17. Запись о сбое запуска не сохраняется — сообщение при каждом повторе

- **Где:** `app/startup_report.py`, `report_failure` / `write_record`.
- **Что не так:** если в папку `data` нельзя писать (нет прав, KI-4 на NAS), запись `data/startup_failure.json` не сохраняется, и каждый повтор запуска считается новым сбоем.
- **Как воспроизвести:** сделать папку `data` недоступной для записи и вызвать сбой запуска: в журнале при каждом повторе «запись о сбое запуска не сохранилась», в Telegram — сообщение «Бот не запустился» примерно раз в минуту.
- **Насколько вероятно / чем грозит:** редко; обычно в этом случае не открывается и база, так что сбой тот же. Вред — поток сообщений до исправления прав (лучше лишнее сообщение, чем молчание).
- **Статус:** fixed (test: `tests/test_startup_report.py::test_when_data_is_unwritable_the_record_goes_to_the_temp_folder_and_the_next_decision_reads_it`), тикет 02 части 9.1a.
- **Найдено:** 2026-10-27, спека круга исправлений по ревью 5.1 (раздел 9), введено тикетом 01.

## KI-18. `.\start-bot.ps1` останавливает и чужой `python -m app.main`

- **Где:** `start-bot.ps1`, шаблон `$oldBotPattern`.
- **Что не так:** скрипт останавливает любой `python.exe`, запущенный целой командой `-m app.main` или `-m app.bot.main`, — по имени модуля нельзя отличить наш старый бот из `.venv` от другого проекта на ПК, у которого модуль называется так же.
- **Как воспроизвести:** запустить в другой папке чужой проект командой `python -m app.main` и выполнить `.\start-bot.ps1`: чужой процесс будет остановлен, в окне — «Остановлен старый бот, запущенный не через Docker».
- **Насколько вероятно / чем грозит:** редко (нужен чужой проект с тем же именем модуля); вред — остановленный чужой процесс.
- **Статус:** fixed (test: `tests/test_docker_files.py::test_the_start_script_stops_only_this_projects_old_bot_and_its_children`), тикет 02 части 9.1a.
- **Найдено:** 2026-10-28, спека круга исправлений по ревью 5.1 (раздел 9), введено тикетом 02.

## KI-19. `.\start-bot.ps1` может ждать итога дольше 90 секунд

- **Где:** `start-bot.ps1`, цикл ожидания `for ($waited = 0; $waited -le 90; $waited += 2)`.
- **Что не так:** цикл считает только паузы по 2 секунды, а время самих проверок (`docker compose ps`, `docker inspect` на каждом из 46 проходов) не учитывает. Окно пишет «до 90 секунд», а сообщение «запускается дольше обычного» может прийти позже.
- **Как воспроизвести:** только при медленном старте приложения, когда контейнер долго остаётся `starting`: на Docker Desktop под Windows ожидание выходит дольше 90 секунд, по оценке до 2–3 минут (вывод из чтения кода, на ПК не измерялось).
- **Насколько вероятно / чем грозит:** редко. Удачный запуск даёт «Готово» через секунды, сбой даёт «Запуск не удался» после первого перезапуска. Вред — лишнее ожидание у окна.
- **Статус:** fixed (test: `tests/test_docker_files.py::test_the_start_script_waits_for_the_outcome_by_the_clock_not_by_the_number_of_checks`), тикет 02 части 9.1a.
- **Найдено:** 2026-10-28, код-ревью круга исправлений по ревью 5.1 (Р1).

## KI-20. Имя `kind` для типа ошибки в `app/startup_report.py`

- **Где:** `app/startup_report.py`: переменная `kind` в `fingerprint`, параметр `failure` в `decide`, поле `Decision.first_seen`.
- **Что не так:** правило 5 `docs/coding-standards.md`: «`kind` значит только тип тайтла», а здесь так назван тип исключения. Рядом ещё два места: параметр `failure` на деле содержит отпечаток, а поле `Decision.first_seen` всегда равно `Decision.record.first_seen`.
- **Как воспроизвести:** прочитать `fingerprint`. Тест `tests/test_code_speaks_glossary.py` слово `kind` вне тайтлов не ищет.
- **Насколько вероятно / чем грозит:** на работу не влияет. Вред только для читающего код: одно слово значит два понятия.
- **Статус:** fixed (test: `tests/test_startup_report.py::test_the_module_has_no_kind_and_the_decision_has_no_first_seen`), тикет 02 части 9.1a.
- **Найдено:** 2026-10-28, код-ревью круга исправлений по ревью 5.1 (Р2).

## KI-21. Постеры непроверяемых аниме пропадают при смене адреса Shikimori

- **Где:** опрос (`app/tracker/pollers/`) обновляет постер только при проверке собственного источника (спека части 5.2, раздел 1.5); `app/web/posters.py` и заголовок `img-src` разрешают картинки только с адреса Shikimori из `SHIKIMORI_BASE_URL`.
- **Что не так:** у аниме в базе хранится полный адрес картинки Shikimori. Если Shikimori сменит адрес сайта (так уже было: `shikimori.one` → `shikimori.io`), опрос перепишет постеры только тех аниме, которые проверяются («Хочу», «В процессе», «Жду»). У «Досмотреть», «Просмотрено» и «Бросил» останется старый адрес: браузер его не загрузит, и вместо постера будет значок типа.
- **Как воспроизвести:** аниме со статусом «Бросил», затем Shikimori меняет адрес, владелец правит `SHIKIMORI_BASE_URL`. В карточке и Списке у этого аниме — значок 🎌 вместо постера.
- **Насколько вероятно / чем грозит:** редко (смена адреса сайта). Вред — только вид: страница работает, данные целы. «Вернуть в список» и первая проверка после него постер возвращают.
- **Статус:** fixed (test: `tests/test_poster_site.py::test_a_shikimori_address_moves_to_the_site_of_the_setting`), тикет 05 части 9.1a: при показе адрес `shikimori.<зона>` заменяется на сайт из `SHIKIMORI_BASE_URL` (`poster_url`), хранимые адреса не меняются.
- **Найдено:** 2026-10-28, спека части 5.2.

## KI-22. «Бросил» во время проверки этого же тайтла может пропустить одно сообщение

- **Где:** `Tracker.mark_dropped` (спека части 5.2, раздел 2.3: очистка очереди) и `app/tracker/polling.py`: `Polling._due_titles` (тайтлы прохода выбираются один раз, в его начале), `Polling._poll_one` и `apply` объектов опроса (статус не перечитывают), `EventQueue.queue_failure_notices` (сообщения «не удалось проверить» ставятся в конце прохода, статус не смотрится); `pollers/sequels.py`, `SequelPoller.apply` (события ставятся до записи снимка).
- **Что не так:** «Бросил» убирает из очереди недоставленные сообщения тайтла. Но проход опроса, начавшийся раньше, всё равно проверяет этот тайтл в свою очередь, и найденное событие встаёт в очередь уже после очистки. Так же в конце прохода встаёт «не удалось проверить» про тайтл, проверка которого сорвалась до «Бросил». И у просмотренного фильма: если «Бросил» или «Вернуть в список» нажато, пока идёт проверка его продолжений, найденное объявление продолжения уже в очереди (снимок проверки исчез, проход считает это «тайтл ушёл», а не сбоем).
- **Как воспроизвести:** опрос проверяет двадцать тайтлов TMDb (пауза 1,5 с между запросами); в начале прохода нажать «Бросил» у сериала, до которого очередь дойдёт через 20 секунд, а в ответе по нему есть новая серия. Приходит «вышла серия …». С недоступным TMDb — приходит «Не удалось проверить» с названием брошенного сериала.
- **Насколько вероятно / чем грозит:** редко: окно — от начала прохода до очереди этого тайтла (обычно секунды, при большом проходе — десятки секунд), для «не удалось проверить» — до конца прохода. Вред — одно лишнее сообщение; статус «Бросил» опрос не меняет. Починка — перечитывать статус и наличие проверки в той же сессии записи, где ставится событие.
- **Статус:** fixed (test: `tests/test_tracker_dropped_restore.py::test_dropped_between_the_start_of_a_pass_and_the_titles_turn_queues_nothing_and_spends_no_key`; ещё `tests/test_tracker_check_rules.py`), тикет 04 части 9.1a: событие и «не удалось проверить» ставятся, только пока тайтл ещё проверяется этой проверкой (`checks.still_checked` в той же сессии записи).
- **Найдено:** 2026-10-28, спека части 5.2. Уточнено 2026-10-28, код-ревью части 5.2: окно — весь проход до тайтла, а не один запрос; ещё два вида сообщения (сбой проверки, продолжение).

## KI-23. Факт, случившийся сразу после «Вернуть в список», становится точкой отсчёта

- **Где:** молчаливая первая проверка после возврата (спека части 5.2, раздел 2.4; `Poller.record_all` и признак из `titles.restored_at`).
- **Что не так:** первая проверка после «Вернуть в список» сохраняет всё, что видит, без сообщений. Факт, случившийся между нажатием и этой проверкой (до минуты), тоже молча станет точкой отсчёта, и сообщения о нём не будет.
- **Как воспроизвести:** вернуть сериал в список в 23:59:30 по UTC; в 00:00 по UTC выходит серия (у TMDb серия выходит с начала дня по UTC); проверка в 00:00:30 записывает её молча — «вышла серия» не приходит.
- **Насколько вероятно / чем грозит:** очень редко: окно — до минуты. Вред — одно пропущенное сообщение; серия в карточке видна.
- **Статус:** fixed (test: `tests/test_tracker_dropped_restore.py::test_an_episode_out_half_a_minute_after_the_return_is_told`), тикет 04 части 9.1a: первая проверка после возврата сообщает то, что вышло после возврата (`happened_at` позже `restored_at`). Остаток — серии аниме, у которых нет надёжного момента выхода: KI-77.
- **Найдено:** 2026-10-28, спека части 5.2.

## KI-24. Номер удалённого последнего тайтла достаётся следующему добавленному

- **Где:** `app/tracker/models.py`, `Title.id` (обычный `INTEGER PRIMARY KEY` SQLite, без `AUTOINCREMENT`); адреса карточки `/titles/<номер>` в вебе и кнопки бота с номером тайтла (`tact:…:<номер>`, `tcard:<номер>`).
- **Что не так:** SQLite выдаёт новому тайтлу номер «самый большой + 1». Если удалить тайтл с самым большим номером, следующий добавленный получит тот же номер. Открытая карточка удалённого тайтла или старая кнопка бота тогда относятся уже к новому тайтлу.
- **Как воспроизвести:** открыть в браузере карточку последнего добавленного фильма (`/titles/7`), удалить его в боте, добавить в Поиске другой фильм, нажать «Бросил» в старой вкладке — брошен новый фильм. В тестах: `tests/test_web_card_status.py`, `test_a_press_on_a_title_deleted_elsewhere_is_the_gone_fragment` («Следить» в карточке удалённого фильма добавляет продолжение под освободившимся номером, поэтому тест берёт продолжение, которого источник не знает).
- **Насколько вероятно / чем грозит:** редко: нужно удалить именно последний тайтл и потом нажать кнопку в старой карточке или под старым сообщением. Вред — действие не над тем тайтлом (его можно отменить другой кнопкой).
- **Статус:** fixed (test: `tests/test_tracker_issued_ids.py::test_the_number_of_a_deleted_last_title_does_not_come_back`), тикет 05 части 9.1a: таблица `issued_ids` (миграция 0015) хранит последний выданный номер, `Titles._next_number` берёт больше из него и из `max(titles.id)`; `titles` не пересоздавалась.
- **Найдено:** 2026-10-28, тесты тикета 04 части 5.2.

## KI-25. Очень длинный номер в адресе карточки — «Не получилось» вместо «Этого тайтла нет в списке»

- **Где:** `app/web/card.py`, адреса `/titles/{title_id:int}…` (число любой длины проходит в обработчик); ядро ищет тайтл по номеру (`listing._title_card`, `statuses`, `titles._delete_title`), и SQLite отказывает числу больше 9 223 372 036 854 775 807 (`OverflowError`).
- **Что не так:** спека части 5.2 (раздел 7) обещает на несуществующий номер страницу `404` «Этого тайтла нет в списке». На номер из 20 и больше цифр приходит общая страница «Не получилось…» с кодом `500` и трассировкой в журнале; нажатие по такому адресу — фрагмент «Не получилось», а не «Этого тайтла больше нет в списке». В Списке такие номера уже отсекаются (`title_list.MAX_ID_DIGITS`), в карточке — нет.
- **Как воспроизвести:** открыть `http://localhost:8080/titles/99999999999999999999` — «Не получилось», код 500, в журнале `OverflowError: Python int too large to convert to SQLite INTEGER`. Проверено скриптом на тестовом клиенте (код-ревью части 5.2).
- **Насколько вероятно / чем грозит:** почти никогда: номер пишет руками только сам владелец, и цифр нужно двадцать. Вред — непонятная страница и красный текст в журнале; данные целы. Починка — одна проверка длины номера (как `MAX_ID_DIGITS`) перед ядром и тест.
- **Статус:** Исправлено (тесты: `tests/test_web_card_scores.py::test_the_card_of_a_number_too_long_is_not_in_the_list_and_the_core_is_not_asked`, `…::test_a_press_at_a_number_too_long_is_the_gone_title_and_the_core_is_not_asked`, `…::test_a_number_of_a_season_too_long_is_a_season_that_is_gone`, `…::test_deleting_a_number_too_long_goes_on_to_the_list_with_the_line_of_a_title_gone`). Номер тайтла или сезона длиннее 12 цифр (`pages.MAX_ID_DIGITS`, `pages.is_id`) отсекается до ядра: открытие карточки — `404` «Этого тайтла нет в списке», нажатие — «Этого тайтла больше нет в списке» (у сезона — «Этого сезона больше нет…»). Часть 5.3, тикет 02.
- **Найдено:** 2026-10-28, код-ревью части 5.2.

## KI-26. Бот пишет в журнал сбой поиска и добавления без причины

- **Где:** `app/bot/tracker_handlers.py`: `search_by_name`, `add_picked`, `follow_sequel` (`logging.warning("…failed: %s", repr(exc))`); с тикета 03 части 5.2 ядро отдаёт при сбое источника `SourceFailed`, а исходная ошибка лежит в `__cause__`.
- **Что не так:** в журнал попадает только `SourceFailed('tmdb_movie')`: нет ли сети, ответил ли TMDb `429` или `500` — не видно. Веб пишет причину (`exc.__cause__`), бот — нет. Код ответа поиска TMDb клиент TMDb пишет сам; остальное (нет связи, ошибка при добавлении, ошибки Shikimori) не видно.
- **Как воспроизвести:** отключить интернет, в Telegram «➕ Добавить» → «Фильм» → «дюна». В журнале — `title search failed: SourceFailed('tmdb_movie')` без `ConnectError`.
- **Насколько вероятно / чем грозит:** при каждом сбое источника в боте. Вред — только разбор сбоя: владельцу бот отвечает правильно. Кнопки «Добавить» и «Мои тайтлы» бота временные (до куска 7). Починка — писать и `exc.__cause__`, как веб.
- **Статус:** Исправлено (тесты: `tests/test_tracker_scores_bot.py::test_a_failed_search_logs_the_cause_and_tells_the_owner_the_source`, `…::test_a_failed_add_logs_the_cause`, `tests/test_tracker_early_answer.py::test_without_a_message_a_failure_goes_to_the_log_only`, `…::test_following_without_a_message_goes_to_the_log_only`). `search_by_name`, `add_picked` и `follow_sequel` пишут в журнал и причину (`exc.__cause__`), как веб; текст для владельца прежний. Часть 5.3, тикет 02.
- **Найдено:** 2026-10-28, код-ревью части 5.2.

## KI-27. Устаревшая карточка аниме ставит галочку не тому сезону после перенумерации

- **Где:** `app/web/card.py` (`POST /titles/<номер>/seasons/<номер сезона>`) и кнопки бота `tsea:<тайтл>:<сезон>` (`app/bot/tracker_handlers.py`); `statuses.set_season_watched` / `toggle_season` ищут сезон по номеру, а номер сезона аниме — только порядок для показа: когда Shikimori вставляет запись в начало цепочки, опрос сдвигает номера (`storage.relayout_records`).
- **Что не так:** карточка, открытая до такой проверки (или старое сообщение бота с кнопками сезонов), шлёт прежний номер. Сезон с этим номером теперь другой, и отметка ставится или снимается у него. Ответ — свежая карточка, на ней видно, какой сезон отмечен.
- **Как воспроизвести:** аниме из двух сезонов, карточка открыта в браузере; Shikimori добавляет приквел, опрос перенумеровывает: прежний «Сезон 1» стал «Сезоном 2». В старой карточке поставить галочку «Сезон 1» — отмечен приквел.
- **Насколько вероятно / чем грозит:** очень редко: Shikimori меняет начало цепочки раз в годы, а карточка должна быть открыта до проверки и нажата после. Вред — неверная отметка (и статус по ней), видна сразу и снимается той же галочкой. Починка — передавать в адресе id сезона (запись `seasons`) вместо номера, а в боте — сверять.
- **Статус:** Исправлено (тесты: `tests/test_tracker_anime_seasons_by_entry.py::test_a_mark_and_a_score_sent_with_the_record_of_a_season_reach_it_after_it_moved_to_another_number`, `…::test_a_season_that_dissolved_after_the_card_was_opened_is_an_unknown_season`, `tests/test_web_card.py::test_a_box_with_a_season_of_another_title_changes_nothing`, `tests/test_tracker_series_bot.py::test_a_season_button_holds_the_record_of_the_season_not_its_number`, `…::test_an_old_season_button_says_it_is_out_of_date_and_changes_nothing`). Сезон отмечается по id записи `seasons`, а не по номеру: `set_season_watched` / `toggle_season` (и новые оценки сезона) берут `SeasonRow.id` / `WatchableSeason.id`, адрес галочки — `/titles/<номер>/seasons/<id сезона>`, кнопки бота — `tsid:<тайтл>:<id сезона>`; старая кнопка `tsea:` отвечает «Эта кнопка устарела — откройте карточку заново» и ничего не меняет; сезон, распавшийся после открытия карточки, — `UnknownSeason`. Часть 5.3, тикет 01.
- **Найдено:** 2026-10-28, код-ревью части 5.2.

## KI-28. Лента: серия аниме ровно в 00:00 UTC показывается без часа

- **Где:** Лента, блок «Скоро» (спека части 5.3, раздел 3.2: «момент без часа у аниме»); `app/tracker/sources/shikimori_anime.py`, `part_episodes` (премьера анонсированной записи без точного момента хранится как 00:00 UTC её дня).
- **Что не так:** в базе нельзя отличить «Shikimori знает только день премьеры» от «серия выходит ровно в 00:00 UTC». Лента считает любой момент аниме ровно в 00:00:00 UTC днём без часа: день — дата UTC, времени в строке нет. Настоящая серия в 00:00 UTC (09:00 по Токио) покажется без «в 03:00»; у владельца к западу от UTC она к тому же встанет на день позже, чем на его часах.
- **Как воспроизвести:** аниме, у которого AniList называет следующую серию в 00:00 UTC; в Ленте строка этой серии — без времени.
- **Насколько вероятно / чем грозит:** редко: аниме обычно выходят вечером и ночью по Токио (14:00–17:00 UTC). Вред — нет часа в одной строке; день у владельца в Израиле верный. Карточка и бот показывают время как раньше («в 03:00» и для премьеры-заглушки). Починка — хранить признак «только день» у серии (колонка) и брать его в Ленте и карточке.
- **Статус:** fixed (test: `tests/test_tracker_episode_timing.py`, `tests/test_tracker_feed.py`). Ticket 9.1c.01: every episode keeps where its moment comes from (`EpisodeTiming`, migration 0017); the hour is shown for an exact moment whatever its time, by the one rule of `cards.episode_when`.
- **Найдено:** 2026-10-28, спека части 5.3.

## KI-29. «Недавно» не показывает вышедшее до добавления и до первой проверки после возврата

- **Где:** Лента, блок «Недавно» (спека части 5.3, раздел 3.4) строится из журнала событий; первая проверка добавленного тайтла и первая после «Вернуть в список» событий не ставят (`Poller.record_all`, признак `baseline`).
- **Что не так:** серия или фильм, вышедшие за последние 7 дней, но до добавления тайтла (или пока он лежал в архиве), в «Недавно» не попадают: для журнала это точка отсчёта, а не новость.
- **Как воспроизвести:** добавить сериал, серия которого вышла вчера; в Ленте в «Недавно» её нет (в карточке видно «вышло N из M»).
- **Насколько вероятно / чем грозит:** при каждом добавлении идущего сериала или аниме. Вред — неполное «Недавно» в первые дни после добавления; данные целы. Решение описания части 5.3 (вопрос 1: журнал показывает ещё объявленные и перенесённые даты и закрытия). Если станет мешать — добавить в «Недавно» серии и фильмы из расписания за 7 дней, которых нет в журнале.
- **Статус:** fixed (test: `tests/test_tracker_feed_released.py`, `tests/test_web_feed.py::test_what_came_out_before_adding_is_a_row_of_recent_with_its_grey_line_no_hour_and_no_buttons`). Ticket 9.1c.03: «Недавно» gets rows from the schedule — the episodes (timing `exact` or `day`) and film dates of its 7 days that came out before adding («вышла до добавления в список») or while the title was in the archive («…, пока тайтл был в архиве») and that no event of the title names; no hour, no buttons, nothing queued (`Poller.feed_released`, the pure `feed_released`).
- **Найдено:** 2026-10-28, описание и спека части 5.3.

## KI-30. Фильтр жанров Архива: один жанр под разными именами

- **Где:** `Tracker.genres` и фильтр `genre` в `list_titles` (спека части 5.3, раздел 5.3): склейка только по регистру и «ё».
- **Что не так:** TMDb и Shikimori называют жанры по-своему, а у сериалов TMDb жанры составные. В фильтре стоят рядом «Боевик» (фильм TMDb), «Экшен» (аниме Shikimori) и «Боевик и Приключения» (сериал TMDb); выбор одного не покажет тайтлы под другими именами.
- **Как воспроизвести:** в архиве фильм-боевик, аниме-экшен и сериал «Боевик и Приключения»; фильтр «Боевик» показывает только фильм.
- **Насколько вероятно / чем грозит:** всегда, когда в архиве есть тайтлы разных источников. Вред — подборку по жанру приходится собирать из двух-трёх фильтров. Починка — таблица синонимов жанров (своя, без источника) или фильтр по нескольким жанрам сразу.
- **Статус:** Исправлено (тесты: `tests/test_tracker_genres_table.py`, `tests/test_web_archive.py`; тикет 04 этапа 9.1c). Своя таблица синонимов `genres.SYNONYMS`: «Экшен» — «Боевик», «Тайна» — «Детектив», составные жанры TMDb считаются по каждой части; `?genre=` читается через таблицу. Карточка и Поиск показывают жанры как их назвал источник.
- **Найдено:** 2026-10-28, спека части 5.3 (описание, «Что может пойти не так»).

## KI-31. Список: поиск в режиме «Удалить несколько» сбрасывает галочки

- **Где:** `app/web/title_list.py`, `results` (`GET /list/results`) и `title_list_results.html`.
- **Что не так:** поиск по названию меняет строки Списка, а в режиме выбора они стоят с галочками; новые строки приходят без галочек. Это то же правило, что у ссылок-фильтров («отмеченное не подошло бы к новым строкам»), но фильтры выходят из режима выбора, а поиск остаётся в нём.
- **Как воспроизвести:** `/list?select=1`, отметить два тайтла, набрать в поле «Название» букву; строки сменились, галочек нет, число в «Удалить выбранные (0)» сброшено.
- **Насколько вероятно / чем грозит:** только если искать после того, как отметили. Вред — отметить заново; удалить не то нельзя: удаляются только отмеченные строки, а вопрос называет их по именам.
- **Статус:** Исправлено (тесты: `tests/test_web_list.py`, раздел «the search in the mode of choosing (KI-31)»; тикет 01 части 5.4). Запрос поиска в режиме выбора несёт номера отмеченных строк (`hx-include` у формы поиска); у строк, оставшихся среди найденных, галочка на месте, полоса считает отмеченные среди показанных, убранная поиском строка галочку теряет — удаляется только видимое и отмеченное.
- **Найдено:** 2026-10-30, тикет 03 части 5.3.

## KI-32. Лента: серия аниме, найденная без расписания, стоит в «Сегодня» с часом проверки

- **Где:** `app/tracker/anime_events.py`, `assemble` (серия, которой не было в базе и у которой источник не назвал точный момент, хранится с моментом проверки: «found out now»); Лента, `app/tracker/feed_rows.py`, `day_of` / `season_pieces` (у аниме время в строке — из этого момента).
- **Что не так:** в блоке «Скоро» у аниме справа стоит время выхода серии. Для такой серии это не время выхода, а время, когда её нашёл опрос («в 14:42»), хотя вышла она, например, ночью. Строка стоит в «Сегодня» (спека 3.3 показывает и уже вышедшее), и время читается как час выхода.
- **Как воспроизвести:** аниме, о котором знает только Shikimori (у AniList нет расписания, у записи нет `next_at`); счётчик вышедших серий вырос с 6 до 7; опрос в 12:42 UTC сохраняет серию 7 с моментом 12:42, и Лента владельца в Израиле показывает «Сегодня · Сезон 1, серия 7 · в 14:42». Проверено на ядре (`assemble` → `season_pieces`) при ревью части 5.3.
- **Насколько вероятно / чем грозит:** редко: у аниме с расписанием AniList следующая серия известна заранее вместе с точным моментом, и он сохраняется. Вред — неверный час в одной строке «Сегодня» (день верный); событие «вышла серия» в «Недавно» и сообщение бота не страдают. Починка — хранить признак «момент найден опросом» у серии (колонка) и в Ленте показывать такую серию без часа (как KI-28).
- **Статус:** fixed (test: `tests/test_tracker_episode_timing.py`, `tests/test_tracker_feed.py`). Ticket 9.1c.01: an episode found by a check is stored as `unknown` and shows its day with no hour.
- **Найдено:** 2026-10-30, код-ревью части 5.3.

## KI-33. Строка «Бот не подключён к Telegram» не появляется, если связь пропала во время приёма

- **Где:** `app/runtime.py`, `Runtime._run_bot` и `Health.telegram_down`; `app/main.py`, `TelegramPart.receive` (`start_polling`).
- **Что не так:** флаг `telegram_down` ставится, когда подключение или приём кончились ошибкой наружу. Пока приём идёт, aiogram 3 сам повторяет запросы к Telegram внутри `start_polling` и ошибку наружу не отдаёт. Поэтому, если связь с Telegram пропала, когда бот уже работал, `_run_bot` ничего не замечает, флаг остаётся `False`, и строки под меню в вебе нет.
- **Как воспроизвести:** запустить бота при работающем интернете (приём начался), отключить интернет на ПК; бот молчит, в журнале повторы aiogram, а веб по-прежнему не показывает «Бот не подключён к Telegram». Строка появляется только при сбое подключения (неверный токен, нет сети при запуске или при повторе).
- **Насколько вероятно / чем грозит:** при обрыве интернета на несколько минут — обычное дело. Вред — владелец не видит в вебе, что сообщения не приходят; события копятся в очереди и уходят, когда связь вернётся (потерь нет). Починка — слушать ошибки внутри приёма (обработчик ошибок диспетчера или проверка `get_me` раз в минуту) и ставить флаг оттуда.
- **Статус:** fixed (test: `tests/test_bot_stop_watch.py::test_a_failing_get_updates_sets_the_flag_and_an_answer_clears_it`), тикет 03 части 9.1a: слой запросов сессии бота `GetUpdatesWatch` ставит флаг при сбое getUpdates и снимает при ответе; отправки флаг не трогают.
- **Найдено:** 2026-10-30, спека части 5.4 (раздел 4), тикет 03.

## KI-34. Настройки: старые методы ядра и страница проверяют значения по-разному

- **Где:** `app/tracker/settings_store.py`: `SettingsStore.set_delivery_rules`, `SettingsStore._checked` (проверка страницы Настроек, `save_settings`) и `SettingsStore.stored_zone` (чтение пояса).
- **Что не так:** спека части 5.4 (раздел 2.2) требует общих проверок для старых методов и для `save_settings`, а сейчас их две.
  - Пояс: чтение (`stored_zone`) и `set_delivery_rules` принимают всё, что открывает `ZoneInfo`. Страница принимает только имена из `available_timezones()`.
  - Время: `set_delivery_rules` принимает «16:5», «+16:05» и «١٦:٠٥» (сохраняет «16:05»). Страница на них отказывает.
  - Рабочие дни: проверка скопирована. Смесь числа и строки (`[1, "x"]`) в обоих путях даёт `TypeError` вместо отказа.
- **Как воспроизвести:** в Docker записать в таблицу `settings` руками пояс `posixrules`. Его открывает `ZoneInfo`, но в `available_timezones()` его нет. Страница Настроек показывает его выбранным, а «Сохранить» отказывает: «Такого часового пояса нет — выберите его из списка». Сохранить получится, только выбрав другой пояс. Разницу во времени и днях видно только при вызове ядра в обход веба (так делают тесты).
- **Насколько вероятно / чем грозит:** очень редко. `set_delivery_rules` вызывают только тесты, а пояс в базу руками не пишут. Вред — «Сохранить» отказывает, пока не выбран другой пояс; данные не портятся. Починка — одна проверка на каждое поле (пояс, время, дни) для `set_delivery_rules`, `_checked` и чтения. Удобно сделать в куске 6, когда в Настройки добавятся «Мои платформы».
- **Статус:** Исправлено (2026-10-31, часть 6.1, тикет 02): у каждого поля одна проверка (`check_zone`, `check_workdays`, `check_clock`, `check_part_gap_weeks` в `app/tracker/settings_store.py`), общая для `save_settings`, `set_delivery_rules`, `set_part_gap_weeks` и чтения пояса; время читает только цифры 0–9 (`delivery.parse_time`). Тесты (`tests/test_tracker_settings_games.py`): `test_ki_34_a_time_the_form_refuses_is_refused_by_set_delivery_rules_too`, `test_ki_34_a_working_day_the_form_refuses_is_a_refusal_not_a_type_error_in_both_ways`, `test_ki_34_no_working_days_given_at_all_is_a_refusal_of_the_form`, `test_ki_34_a_zone_outside_the_list_of_names_is_refused_by_both_ways`, `test_ki_34_a_stored_posixrules_reads_as_no_choice_with_one_warning_and_the_page_can_save`, `test_ki_34_the_weeks_that_are_not_whole_numbers_of_the_range_are_a_value_error_not_a_type_error`, `test_ki_34_the_weeks_of_the_form_that_are_no_number_of_the_range_are_a_refusal`, `test_ki_34_the_older_method_still_takes_the_times_the_form_takes`, `test_ki_34_the_older_method_takes_a_time_and_a_text_as_before`.
- **Найдено:** 2026-10-30, код-ревью части 5.4 (находка Н1).

## KI-35. Игры: дата выхода только в Японии считается выходом

- **Где:** `app/tracker/games.py`: выбор записи даты по региону (спека части 6.1, раздел 5.2).
- **Что не так:** если у платформы нет дат «весь мир», первого и второго региона страны магазинов (у Израиля — Европа и Северная Америка), берётся самая ранняя из остальных регионов. Обычно это Япония. Сообщение «вышла» придёт, когда игра вышла только там, а в магазине вашей страны её ещё нет.
- **Как воспроизвести:** игра, у которой в IGDB на PS5 только японская дата (например, 13 мая 2026), страна магазинов — Израиль. 13 мая приходит «🎮 … вышла на PS5». У Yomawari: Night Alone (Япония 13 мая 2026, Северная Америка 5 ноября 2026) этого нет: для Израиля берётся Северная Америка.
- **Насколько вероятно / чем грозит:** редко: японские игры, у которых IGDB ещё не знает западной даты. Вред — одно преждевременное сообщение «вышла». Починка — не брать регионы вне таблицы страны (тогда у такой игры «дата не объявлена»).
- **Статус:** Исправлено в 9.1b.01: `games.pick` берёт только регионы страны; дата вне них — строка «в Японии — …» на карточке, не выход (тесты `tests/test_tracker_games_dates.py`, `tests/test_tracker_game_outside_date.py`).
- **Найдено:** 2026-10-30, спека части 6.1 (проверка регионов на настоящих ответах IGDB).

## KI-36. Игры: выход, о котором IGDB узнал больше чем через 30 дней, приходит без сообщения

- **Где:** `app/tracker/game_events.py`: правило «вышла — только если день выхода не старше 30 дней» (спека части 6.1, раздел 7.1).
- **Что не так:** правило отсекает поправки старых данных (IGDB уточняет «2015» до «19 мая 2015» у давних игр). Но если игра с примерной датой («4 квартал 2026») вышла, а IGDB записал точный день больше чем через 30 дней, сообщения «вышла» не будет: карточка и Лента обновятся молча.
- **Как воспроизвести:** игра «Хочу» с датой «4 квартал 2026» на ПК. Игра выходит 5 октября 2026, IGDB ставит точный день «5 октября 2026» только 10 ноября. Проверка 10 ноября видит выход 36 дней назад — сообщения нет.
- **Насколько вероятно / чем грозит:** редко: у заметных игр IGDB ставит день заранее или сразу после выхода. Вред — пропущенное «вышла» у малоизвестной игры. Починка — признак «выход уже сообщали» на платформе вместо срока в 30 дней.
- **Статус:** Исправлено в 9.1b.01: 30 дней считаются от дня, когда трекер начал следить за игрой (добавление или «Вернуть в список»); поздний выход называет день (тесты `tests/test_tracker_game_events.py`, `tests/test_tracker_game_late_release.py`).
- **Найдено:** 2026-10-30, спека части 6.1.

## KI-37. Игры: ссылка в PlayStation Store может вести на страницу ошибки

- **Где:** `app/tracker/games.py`: ссылка «Открыть в PlayStation Store» (спека части 6.1, раздел 9.1).
- **Что не так:** IGDB хранит номер концепции американского PS Store. Ссылка ведёт на эту концепцию в магазине вашей страны (`…/en-il/concept/<номер>`). Если концепции в магазине страны нет (игра продаётся только в США или под другим номером), PS Store показывает страницу ошибки.
- **Как воспроизвести:** игра с номером концепции, которой нет в израильском магазине; в карточке нажать «Открыть в PlayStation Store» — PS Store открывает `…/en-il/error?conceptId=…`.
- **Насколько вероятно / чем грозит:** редко: у проверенных игр («Ведьмак 3», GTA VI, Hades II) концепция открывается в `en-il`. Вред — игру приходится искать в магазине вручную. Починка — проверять концепцию ответом PS Store и при ошибке давать ссылку на поиск.
- **Статус:** Исправлено в 9.1b.01 для веб-карточки: ссылка идёт через `/titles/<id>/playstation`, проверка `HEAD`, при ошибке — поиск; текстовая ссылка бота («PS Store: …») по-прежнему ведёт на концепцию (тест `tests/test_tracker_playstation.py`).
- **Найдено:** 2026-10-30, спека части 6.1 (проверка ссылок PS Store).

## KI-38. Игры: запись IGDB без точности даты читается как «дата не объявлена»

- **Где:** `app/tracker/games.py`, `GameDate.from_igdb` (мягкий разбор записи `release_dates`).
- **Что не так:** точность даты берётся из поля `date_format` (0 — день, 1 — месяц, 2 — год, 3–6 — квартал, 7 — «TBD»). Если поля нет или IGDB введёт новое значение, запись читается как «дата не объявлена», даже когда в ней есть `date` или `y`.
- **Как воспроизвести:** запись `{"platform": 6, "release_region": 8, "date": 1795046400, "y": 2026}` без `date_format` — в снимке у ПК `"date": null`, в карточке будет «дата не объявлена» вместо 19 ноября 2026.
- **Насколько вероятно / чем грозит:** редко: во всех сохранённых ответах (девять игр) `date_format` есть у каждой записи. Вред — дата не видна и сообщения о ней нет, пока IGDB не пришлёт запись с точностью. Угадывать точность по `date` нельзя: у года и квартала это последний день периода, а не день выхода.
- **Статус:** Исправлено в 9.1b.01: запись без известного `date_format` читается как год, не как месяц или день (тест `tests/test_tracker_games_dates.py`).
- **Найдено:** 2026-10-31, тикет 03 части 6.1 (разбор дат IGDB).

## KI-39. Игры: примерная дата старшей платформы прячет точную дату своей

- **Где:** `app/tracker/games.py`, `_better` (какая дата у платформы — своя или старшей; спека части 6.1, раздел 5.3).
- **Что не так:** по спеке берётся дата, у которой раньше начало периода. У примерной даты начало — 1-е число её периода, поэтому год или квартал старшей платформы всегда «раньше» точного дня своей, если день попадает в тот же год. Точная дата прячется: в карточке, Ленте и событиях стоит примерная дата старшей.
- **Как воспроизвести:** у игры в IGDB PS4 — «2026», PS5 — 10 ноября 2026; PS5 среди «Моих платформ». В карточке «PS5 — 2026 (версия для PS4)» вместо «PS5 — 10 ноября 2026», игра стоит только в «Позже». Сообщений «объявлена дата» и «вышла на PS5» нет. Так же Switch («2026») → Switch 2 и Xbox One → Xbox Series X|S. Проверено запуском `platform_dates` и `detect_events` на ревью.
- **Насколько вероятно / чем грозит:** нечасто: нужна игра сразу на старой и новой приставке, у которой IGDB знает для старой только год или квартал. На «Моих платформах» по умолчанию (ПК и PS5) это порты на PS4, их в 2026 году немного; на Switch 2 таких игр больше. Вред — пропущенные «объявлена дата» и «вышла» и неточная дата в карточке. Починка — сравнивать по концу периода («точно можно играть к этому дню»), при равенстве — своя: точный день 10 ноября раньше конца «2026» (31 декабря), а точный день PS4 в марте 2027 раньше конца своей «2027». Примеры спеки (Bloodborne, «Ведьмак 3») от этого не меняются.
- **Статус:** Исправлено в тикете 01 части 6.2 (тест: `test_the_date_of_the_older_platform_is_taken_by_the_end_of_the_period` и `test_switch_2_and_xbox_series_take_the_older_date_the_same_way` в `tests/test_tracker_games_dates.py`; события — `test_a_day_of_ps5_inside_the_year_of_ps4_is_announced_and_then_released` в `tests/test_tracker_games.py`).
- **Найдено:** 2026-10-31, код-ревью части 6.1 (находка Н1).

## KI-40. Игры: галочка «играю здесь» меняется у платформы, которой у игры больше нет

- **Где:** `app/tracker/statuses.py`, `Statuses._set_platform_playing`.
- **Что не так:** спека части 6.1 (6.4, 2.2) велит отвечать `UnknownPlatform` («Этой платформы у игры больше нет — карточка обновлена»), если платформы нет у игры. Код проверяет только, есть ли строка в `game_platforms`. Строки не удаляются, когда IGDB убирает платформу у игры, поэтому галочка такой платформы меняется молча.
- **Как воспроизвести:** игра с ПК и PS5 (у PS5 нет дат), опрос, в котором IGDB больше не называет PS5: в карточке остаётся только ПК. Во вкладке, открытой до опроса, снять галочку PS5 — `changed=True`, карточка обновляется без строки об этом.
- **Насколько вероятно / чем грозит:** очень редко: IGDB должен убрать платформу целиком (без записей дат — с ними она остаётся), а владелец нажать галочку в старой вкладке. Вред — галочка невидимой платформы поменялась; если IGDB вернёт платформу, сообщения о ней пойдут по этой галочке.
- **Статус:** Исправлено в тикете 01 части 6.2 (тесты: `test_a_platform_igdb_no_longer_lists_is_unknown_and_its_row_and_mark_stay` в `tests/test_tracker_games.py`, `test_a_platform_igdb_took_away_is_the_fresh_card_with_a_line_and_keeps_its_row` в `tests/test_web_games.py`).
- **Найдено:** 2026-10-31, код-ревью части 6.1 (проверка по спеке).

## KI-41. Настройки, испорченные руками в базе, кроме пояса, платформ и страны, ломают чтение

- **Где:** `app/tracker/settings_store.py`: `SettingsStore.part_gap_weeks_in` и `SettingsStore.rules`.
- **Что не так:** пояс, «Мои платформы» и «Страна магазинов» читаются через свою проверку: испорченное значение — значение по умолчанию и одно предупреждение в журнале. Порог частей сезона, рабочие дни, час сводки и тихие часы читаются без проверки.
- **Как воспроизвести:** записать в таблицу `settings` руками `part_gap_weeks = "x"` — Лента и карточки сериалов отвечают «Не получилось» (`timedelta(weeks="x")`). Испорченные рабочие дни или время ломают очередь доставки.
- **Насколько вероятно / чем грозит:** очень редко: значения пишет только страница Настроек, а она проверяет каждое поле. Так было и до части 6.1. Починка — читать эти поля через те же `check_…`, как пояс.
- **Статус:** fixed (test: `tests/test_tracker_rare_input.py::test_a_spoiled_clock_reads_as_its_default_and_logs_once`), тикет 01 части 9.1a.
- **Найдено:** 2026-10-31, код-ревью части 6.1 (проверка по стандартам).

## KI-42. Ручной запрос «Добавить» с номером не из цифр отвечает «Не удалось связаться»

- **Где:** `app/tracker/titles.py`, `Titles.add_title` (сбой источника оборачивается в `SourceFailed`); источники `tmdb_movies.py`, `igdb_games.py` и другие (`int(external_id)`).
- **Что не так:** номер из формы переводится в число внутри источника. Номер не из цифр даёт `ValueError`, его ядро считает сбоем источника. Владелец видит «Не удалось связаться с IGDB…» (или с TMDb), хотя сеть ни при чём.
- **Как воспроизвести:** отправить форму «Добавить» руками с `external_id=abc`. Кнопки Поиска такой номер не отправляют.
- **Насколько вероятно / чем грозит:** только при запросе, сделанном руками. Вред — неверная строка; ничего не сохраняется. Так у всех типов с части 5.2.
- **Статус:** fixed (test: `tests/test_tracker_rare_input.py::test_a_bad_number_is_refused_before_any_source_is_asked_and_nothing_is_stored`), тикет 01 части 9.1a.
- **Найдено:** 2026-10-31, код-ревью части 6.1 (проверка по стандартам).

## KI-43. Цены Steam: цена бандла — для покупателя без игр набора

- **Где:** `app/tracker/sources/steam_prices.py` (бандлы из ответа `GetItems`; спека части 6.2, раздел 3.3).
- **Что не так:** трекер спрашивает Steam без входа в аккаунт владельца. Steam не знает, какие игры набора у владельца уже есть, и отдаёт полную цену бандла. В магазине владелец увидит меньшую цену «докупить набор» (Steam вычитает купленное).
- **Как воспроизвести:** у владельца в Steam куплена Hades; карточка Hades II показывает бандл «Hades + Hades II» (2 игры) — ₪250, а в магазине для владельца набор стоит меньше.
- **Насколько вероятно / чем грозит:** часто, если владелец покупает игры одной серии. Вред — цена бандла в карточке и в сообщении выше настоящей; сообщения о новом бандле от этого не меняются. Чинить можно только входом в аккаунт Steam — этого в задачах трекера нет.
- **Статус:** won't fix (test: `tests/test_tracker_price_known_issues.py::test_the_bundle_sample_says_the_price_is_of_the_whole_set`, `tests/test_tracker_price_rows.py`, `tests/test_tracker_steam_events.py`), тикет 02 части 9.1b. Без входа в аккаунт Steam цену «докупить набор» не узнать; владелец решил оставить полную цену и сказать об этом: строка бандла в карточке и сообщение о бандле кончаются словами «, цена набора целиком».
- **Найдено:** 2026-10-31, спека части 6.2.

## KI-44. Цены Steam: предзаказ проверен только на собранном ответе

- **Где:** `app/tracker/sources/steam_prices.py` (вид ответа `price` с `is_coming_soon`; спека части 6.2, разделы 3.2, 3.3).
- **Что не так:** в день спеки в Steam не нашлось игры с открытым предзаказом, поэтому разбор предзаказа («скоро выйдет» и строка цены вместе) проверяется на ответе, собранном из настоящего, а не на живом. Steam может отдавать предзаказ иначе (например, без `is_coming_soon` или с особой пометкой строки).
- **Как воспроизвести:** добавить игру с открытым предзаказом в Steam, поставить галочку ПК и сравнить блок «Steam» карточки со страницей магазина.
- **Насколько вероятно / чем грозит:** предзаказы бывают у крупных игр. Вред — в карточке нет пометки «Предзаказ» или игра показана как «Ещё не продаётся — скоро выйдет», хотя её можно заказать. Цены и скидки от этого не теряются, если строка цены в ответе есть. Проверить при первом живом предзаказе и сохранить ответ в фикстуры.
- **Статус:** fixed (test: `tests/test_tracker_price_known_issues.py::test_the_live_preorders_read_on_the_card`), тикет 02 части 9.1b. Живой ответ Steam 2026-11-21 (`tests/fixtures/steam/getitems_preorder_il_live.json`, три игры, Израиль): предзаказ — `is_coming_soon: true` и варианты покупки одной игры, как и предполагалось; разбор не менялся. Карточка: «Предзаказ со скидкой −10 %: ₪238 → ₪214,20, до 3 декабря», «Предзаказ: ₪209».
- **Найдено:** 2026-10-31, спека части 6.2.

## KI-45. Сбой Steam и сбой IGDB одной игры за сутки — одно сообщение

- **Где:** `app/tracker/queue.py`, `EventQueue.queue_failure_notices` (окно «раз в сутки» — `titles.failure_notified_at`, одно на тайтл).
- **Что не так:** окно в 24 часа общее на тайтл, а не на источник. Если в один день не удалась проверка IGDB игры и потом проверка её цен в Steam, придёт только первое сообщение.
- **Как воспроизвести:** утром IGDB не ответил — «⚠️ Не удалось проверить «Hades II»: IGDB не ответил вовремя…»; вечером Steam не ответил — сообщения о Steam нет до следующих суток.
- **Насколько вероятно / чем грозит:** редко: нужны два сбоя разных сервисов у одной игры за сутки. Вред — владелец не знает, что цены тоже не проверялись. Повторные попытки идут как обычно (через 30 минут), так что после восстановления Steam всё догонит само.
- **Статус:** fixed (test: `tests/test_tracker_failures.py::test_two_sources_of_one_title_in_one_pass_give_two_notices_with_the_source_in_the_key`), тикет 04 части 9.1a: окно в 24 часа — на тайтл и источник, читается из событий; столбец `titles.failure_notified_at` убран миграцией 0016.
- **Найдено:** 2026-10-31, спека части 6.2.

## KI-46. Цены Steam: короткая скидка может пройти без сообщения или с неверным «до»

- **Где:** `app/tracker/pollers/game_prices.py` (проверка цен раз в 6 часов) и правило доставки «скидка кончилась — не отправлять» (`expires_at`; спека части 6.2, раздел 5.6).
- **Что не так:** (1) скидка, которая короче промежутка между проверками или кончается до сводки, может не прийти: проверка нашла её поздно, а к отправке она уже кончилась — сообщение убрано. (2) Если Steam отменил скидку раньше объявленного дня, ждущее сообщение уйдёт с прежним «до 3 ноября».
- **Как воспроизвести:** (1) суточная скидка с 20:00 до 20:00 следующего дня, найденная в 22:00 в рабочий день: сообщение ждёт сводки в 15:00 и уходит (успевает); а скидка на 12 часов, найденная в 22:00, к утру кончится — сообщения нет. (2) Steam снял скидку 2 ноября, объявив её до 3-го, а сообщение ждало сводки.
- **Насколько вероятно / чем грозит:** короткие скидки Steam бывают (суточные, «на выходные»), но большинство распродаж длится от нескольких дней. Вред — пропущенная короткая скидка; неверное «до» — очень редко. Скидка всё равно видна в карточке и в Списке, пока идёт.
- **Статус:** won't fix (test: `tests/test_tracker_price_known_issues.py::test_a_discount_found_at_22_on_a_work_day_goes_in_the_summary_only_if_it_is_not_over_by_15`), тикет 02 части 9.1b. Владелец решил (решение 3 описания 9.1): проверка цен остаётся раз в 6 часов, сообщения идут по правилам доставки. Тест закрепляет: `PRICE_INTERVAL` — 6 часов; скидка, найденная в рабочий день в 22:00 и кончающаяся в 08:00, к сводке в 15:00 устарела и не уходит; кончающаяся после 15:00 уходит в сводке.
- **Найдено:** 2026-10-31, спека части 6.2.

## KI-47. Цены Steam: сообщение о скидке может уйти в ту минуту, когда игра ушла из «Хочу»

- **Где:** `app/tracker/pollers/game_prices.py`, сверка снимков цен (недоставленные события Steam убираются в начале проверки цен, раз в проход опроса; спека части 6.2, разделы 4.1 и 5.6).
- **Что не так:** «Начал играть», «Прошёл», снятая галочка ПК или ПК, убранный из «Моих платформ», не убирают ждущие сообщения Steam сразу: это делает следующая проверка цен, в течение минуты. Если доставка сработает в эту минуту раньше опроса, сообщение уйдёт.
- **Как воспроизвести:** в 14:59:50 нажать «Начал играть» у игры, о скидке которой сообщение ждёт сводки в 15:00; доставка идёт в 15:00:00, опрос — в 15:00:05: сообщение о скидке приходит в сводке.
- **Насколько вероятно / чем грозит:** очень редко: нужно нажать в последнюю минуту перед отправкой. Вред — одно лишнее сообщение о скидке. «Бросил» убирает сообщения сразу, как раньше.
- **Статус:** fixed (test: `tests/test_tracker_price_press.py`), тикет 02 части 9.1b. Нажатие («Начал играть», «Прошёл», «Бросил», галочка «играю здесь», сохранение Настроек) само убирает снимок цен игры, которая больше не «игра для цен», и её недоставленные события Steam — в своей сессии записи (`Poller.after_marks`, `GamePrices.drop_unpriced`); проверка, ответившая после нажатия, ничего не ставит в очередь. Новые снимки делает только сверка в начале прохода.
- **Найдено:** 2026-10-31, спека части 6.2.

## KI-48. Anime card: no episode or schedule data for an announced season (Jujutsu Kaisen)

- Where: anime card, data from AniList (`app/tracker/sources/`).
- What's wrong: season 4 of Jujutsu Kaisen is announced, AniList has no data for it, so the card shows no episode or schedule information.
- How to reproduce: open the card of Jujutsu Kaisen and look at the announced season: no episode count, no next-episode time.
- Likelihood / impact: whenever AniList lacks data for an announced season; the card is poorer, no message is lost.
- Status: won't fix (test: `tests/test_shikimori_anime_source.py`). Checked live 2026-11-22: Shikimori 63824 `anons` with no day, AniList 209895 `NOT_YET_RELEASED` with no airing; no source has data. The card says «Сезон 4 анонсирован, дата не объявлена» and fills in by itself once a source has data (spec 9 of stage 9.1c).
- Found: before 2026-10-27, by the owner (old bug table, `docs/history.md`).

## KI-49. `.env` holds variables the code does not read

- Where: `.env`, `.env.example`.
- What's wrong: `PSN_API_KEY` and `SHIKIMORI_CLIENT_ID` / `SHIKIMORI_CLIENT_SECRET` are not read by any code; `psn_api_key` is written in lower case.
- How to reproduce: search `app/` for these names — no reader.
- Likelihood / impact: harmless; confusing for someone who deploys their own instance.
- Status: fixed (test: `tests/test_env_example.py`). Ticket 9.1d.05 (section 11 of 9.1d): `.env.example` lists every name the code reads (`Settings`, `docker-compose.yml`, `container_start.ID_NAMES`) and the test fails on a missing or an alien one; `SHIKIMORI_BASE_URL` and `SHIKIMORI_USER_AGENT` are in it, commented out. The six unread names (`KINOPUB_ACCESS_TOKEN`, `PS_STORE_REGION`, `SHIKIMORI_CLIENT_ID`, `SHIKIMORI_CLIENT_SECRET`, `psn_api_key`, `rawg_api_key`) were removed from the owner's `.env` on 2026-11-24.
- Found: 2026-11-01, while moving the docs (carried over from the old bug table).

## KI-50. Steam prices: a spoiled price snapshot stops the price check of every game

- Where: `app/tracker/pollers/game_prices.py` (the reconciliation reads every price snapshot with the strict `PriceLook.from_state`).
- What's wrong: a price snapshot whose state the code cannot read (edited by hand in the database, or written by a bug) raises `ValueError` in the reconciliation, so the whole price check fails: no game gets its prices until the snapshot is fixed or deleted. The log has the traceback every minute; the owner gets no message.
- How to reproduce: put `{"appid": 1}` into the `state` of a `source_snapshots` row with `source = 'steam'` and wait a minute: «the check at the end of the pass of the game titles failed» with a `ValueError` in the log.
- Likelihood / impact: only after a hand edit or a bug (rule 9: what we wrote is read strictly); prices stop updating, nothing else breaks — dates of games and other kinds are checked as usual. Deleting the row heals it: the reconciliation makes a new one.
- Status: fixed (test: `tests/test_tracker_price_known_issues.py::test_a_spoiled_snapshot_is_a_failure_of_its_game_and_the_others_are_checked`, `…_fails_each_time_it_is_due_but_logs_and_tells_once_a_day`, `…_of_a_game_no_longer_for_prices_is_dropped`), ticket 02 of stage 9.1b. The reconciliation reads each snapshot on its own: one it cannot read is neither reset nor asked; each time it is due it is a failure of its check («неизвестная ошибка», 30 minutes, «could not check» once a day by the usual window), the log line once a day (`failures.DailyLog`); the other games are checked as usual. A game no longer for prices loses such a snapshot as any.
- Found: 2026-11-01, ticket 03 of part 6.2.

## KI-51. Steam prices: the discounts of one check can come as separate messages

- Where: `app/tracker/pollers/game_prices.py` (each event is queued in a write session of its own) and the two jobs of `app/bot/main.py` (polling and delivery run every minute independently).
- What's wrong: two discounts or more found by one price check should go out as one message «🎮 Скидки в Steam:» (spec 5.4 of part 6.2). The check queues them one game after another, and the delivery job does not wait for the check: if its minute comes while the check is between two games, the first discount goes out alone and the others a minute later, folded or alone.
- How to reproduce: hard by hand. A titles pass that takes about a minute (many TMDb titles due, 1.5 s apart) moves the price check onto the next tick of delivery; two discounts found then can come as two messages.
- Likelihood / impact: rare (the queueing of one check takes milliseconds); harm — two or three messages instead of one. A fix: queue the events of one check in one write session, or take `delivery_lock` while queueing them.
- Status: fixed (test: `tests/test_tracker_price_batch.py`), ticket 02 of stage 9.1b. The check works in three phases: all packs asked and the events found; the events of every game queued in one write session (`EventQueue.enqueue_all`); then each look stored. The delivery sees all the events of a check or none, so two discounts fold into «🎮 Скидки в Steam:».
- Found: 2026-11-04, review of part 6.2.

## KI-52. Expansions: a standalone expansion completed before 6.3 never learns it is one

- Where: `app/tracker/sources/igdb_games.py` and `games.GameState` (the fields `expansion` and `parent` of the own snapshot, spec 3.3 of stage 6.3); `polling.py` polls the own source only in «Хочу», «В процессе» and «Жду».
- What's wrong: whether a game is an expansion, and of which game, is stored in its own IGDB snapshot by every own poll. A standalone expansion (IGDB type 4: Miles Morales, The Lost Legacy) added through Search before stage 6.3 and already «Пройдено» is not polled any more, so its card has no line «Дополнение к игре «…»» and its row no mark «дополнение». Its check of expansions and sequels runs as for any game, so nothing is missed.
- How to reproduce: before the update, add «Uncharted: The Lost Legacy» and press «Прошёл»; after the update its card has no line about Uncharted 4.
- Likelihood / impact: rare (a standalone expansion in the archive from before 6.3); only the line and the mark are missing. «Вернуть в список» heals it with the next own poll. A fix: the follow-up check could also store the game's own type and parent.
- Status: fixed (test: `tests/test_tracker_follow_up_known_issues.py::test_a_completed_standalone_expansion_learns_its_kind_and_parent`, `…::test_a_game_in_want_leaves_its_own_snapshot_to_its_own_poll_unless_tracking_is_off`, `…::test_a_spoiled_own_state_is_left_alone`, `…::test_a_game_that_turns_out_to_need_its_game_is_dropped_by_the_next_reconciliation`), ticket 03 of stage 9.1b. The follow-up request also asks `parent_game.name`; the game's own kind of expansion and parent are read as the own poll reads them (`igdb_games.expansion_with_parent`) and, when the game's own check does not run (not polled or tracking off — «Пройдено»), written into its own snapshot in the store session of the weekly check. A spoiled own state is left alone.
- Found: 2026-11-04, spec of stage 6.3.

## KI-53. Follow-ups: «Бросил» and «Вернуть в список» within one minute keep the old reference point

- Where: `app/tracker/pollers/game_follow_ups.py` (the reconciliation at the start of each pass removes the snapshot of a game no longer for the check).
- What's wrong: «Вернуть в список» from «Бросил» should start the follow-up check anew, the first check being a silent reference point (spec 5.1 of stage 6.3). The snapshot of a dropped game goes only at the next pass; if the owner presses «Бросил» and then «Вернуть в список» before it (within about a minute), the snapshot stays, and the check goes on as if the game was never dropped: the next weekly check compares with the state from before «Бросил», so what was announced since that state comes as messages instead of being the silent reference point.
- How to reproduce: a game in «Хочу» with a checked snapshot; press «Бросил» and «Вернуть в список» within a minute; when IGDB lists a new game of its series at the next weekly check, a message comes.
- Likelihood / impact: rare (two buttons within a minute); the messages are true news that would have come without «Бросил» as well. A fix: «Бросил» could remove the snapshot itself, or the reconciliation could compare `Title.restored_at` with the snapshot.
- Status: fixed (test: `tests/test_tracker_follow_up_known_issues.py::test_dropping_and_restoring_within_a_minute_starts_with_a_silent_reference_point`, `…::test_a_check_answering_after_dropping_and_restoring_queues_and_stores_nothing`), ticket 03 of stage 9.1b. The press hook (`GamePoller.after_marks` → `GameFollowUps.drop_unchecked`) drops the follow-up snapshot in the write session of «Бросил», by the same rule as the reconciliation; «Вернуть в список» gets an empty snapshot at the next pass, so its first check is the silent reference point.
- Found: 2026-11-05, ticket 02 of stage 6.3.

## KI-54. Follow-ups: an announcement taken out by «Бросил» never comes from another game of the series

- Where: `app/tracker/queue.py` (`EventQueue.withdraw` keeps the event and its dedup key), with the key of spec 5.5 of stage 6.3 (`game:follow_up:<igdb id>`, one per announced game).
- What's wrong: game A queues «Анонсирована новая игра серии: The Witcher IV», the message waits (quiet hours, the 15:00 summary); the owner presses «Бросил» on A, which takes the message out of the queue but keeps the event, so the key stays taken. When game B of the same series (also in the list) finds The Witcher IV at its weekly check, `enqueue` drops it as a known fact: the owner is never told.
- How to reproduce: two games of one series in «Хочу», both checked; a new game of the series appears in IGDB; the announcement from A waits for the summary; press «Бросил» on A before it goes; B's check queues nothing.
- Likelihood / impact: rare (an undelivered announcement, «Бросил» on exactly that game, and another game of the series in the list); one missed announcement, the card of B still shows the game in «Продолжения». A fix: a withdrawn event frees its key (delete the event, or give it a «withdrawn» mark the key check ignores).
- Status: fixed (test: `tests/test_tracker_follow_up_known_issues.py::test_a_withdrawn_announcement_comes_later_from_another_game_of_the_series`, `…::test_the_same_game_cannot_repeat_a_withdrawn_announcement`, `…::test_withdraw_deletes_the_entries_and_the_events_and_they_leave_recent`, `tests/test_tracker_steam_events.py::test_a_deeper_discount_takes_the_undelivered_one_out_of_the_queue`), ticket 03 of stage 9.1b. `EventQueue.withdraw` deletes the undelivered queue entries and their events, explicitly both: the key is free for another game of the series, never for the same game (its next check is a silent reference point; a deeper discount moved the stored look past the older one). A withdrawn event leaves «Недавно» too; delivered events stay.
- Found: 2026-11-05, review of stage 6.3.

## KI-55. Follow-ups: a game whose own snapshot cannot be read logs a line every minute; never told if it had no check yet

- Where: `app/tracker/pollers/game_follow_ups.py` (`_reconcile`, `_plan`).
- What's wrong: spec 5.2 of stage 6.3 leaves such a game out of the reconciliation «with a line in the log». The reconciliation runs every pass, so the warning comes every minute while the snapshot stays spoiled. And the result depends on history: a game that already had a follow-up snapshot stays due, its check fails in `_decide` and the owner gets «could not check» once a day; a game that never had one gets no snapshot and is silently never checked.
- How to reproduce: spoil the `expansion` key of a game's own snapshot (`source = 'igdb'`) by hand, e.g. `"expansion": "dlc"`; watch `data/logs/bot.log`.
- Likelihood / impact: very rare (a hand edit or a bug; the own snapshot is rewritten by every own poll, which would also fail and report). Noise in the log; for a never-checked game no expansions or sequels. A fix: log once a day, and treat both cases alike (a snapshot made anyway, so the check fails and reports).
- Status: fixed (test: `tests/test_tracker_follow_up_known_issues.py::test_an_unreadable_own_snapshot_fails_before_igdb_and_reports_once_a_day`, `…::test_an_unreadable_own_snapshot_counts_by_status_alone`), ticket 03 of stage 9.1b. The reconciliation judges such a game by its status alone (in «Хочу», «В процессе», «Пройдено» its snapshot is made and never dropped); the check reads the own snapshot before IGDB: unreadable — a failure at once, no request, 30 minutes, «could not check» once a day by the window. The log line comes once a day per game (`failures.DailyLog`, shared by the reconciliation and the check).
- Found: 2026-11-05, review of stage 6.3.

## KI-56. The size test of the core misses the pure modules: `series_events.py` 547 lines, `games.py` 406

- Where: `tests/test_tracker_core_split.py` (`MODULES` and `pollers/` only).
- What's wrong: rule 7 of `docs/coding-standards.md` says no module of the core is longer than ~400 lines, and its check names this test. The test covers only the modules listed in `MODULES` and the pollers; the pure modules (`games`, `cards`, `series_events`, `feed_rows`, `follow_ups`…) are not checked. `series_events.py` has 521 lines (before stage 6.3); `games.py` went from 360 to 406 in stage 6.3 (the expansion of a game). Stage 9.1c: `series_events.py` 534 → 547 lines (the timing of an episode), `cards.py` 393 → 400 (review 9.1c, F3).
- How to reproduce: `wc -l app/tracker/*.py`.
- Likelihood / impact: no effect on the owner; long modules cost more to read in every session. A fix: the test takes every `app/tracker/*.py`; `series_events.py` and `games.py` split (e.g. `GameDate` into a module of its own).
- Status: fixed (test: `tests/test_tracker_core_split.py::test_no_part_of_the_core_is_longer_than_the_limit`, one case for every module found by a glob, and `…::test_the_glob_of_the_size_test_sees_every_module_of_the_core`), ticket 01 of stage 9.1d. The glob takes every `app/tracker/**/*.py` but `core.py`, `migrations/` and `__init__.py`; the pure modules join `PURE`. `series_events` gave `series_messages`, `games` gave `release_dates` (`GameDate` is `ReleaseDate`), `cards` gave its date words to `moment_words`, `offers` gave `offer_cards`, `candidates` gave `candidate_words`.
- Found: 2026-11-05, review of stage 6.3.

## KI-57. «Входящие»: a restart within the 2-second pause leaves the item without «Что это?»

- Where: `app/bot/inbox_handlers.py` (the pause after the last message of an item lives in the bot's memory).
- What's wrong: the item is written at once, but the question comes 2 seconds after its last message. When the bot stops in those 2 seconds, nothing asks after the start: the item waits silently.
- How to reproduce: send a message to the bot and run `.\stop-bot.ps1` within 2 seconds, then `.\start-bot.ps1`.
- Likelihood / impact: rare (a stop exactly then); nothing is lost — the item goes to «Входящие» «без ответа» with the next post or after 12 hours, and the web tab shows it (ticket 05). Spec 13 of stage 6.4 accepts it.
- Status: fixed (test: `tests/test_inbox_after_restart.py`). Ticket 9.1d.04 (spec 9 of 9.1d, migration 0019): the answer to the pause is marked in `inbox_items.answered_at` (the question and the first offer card); once polling starts, the bot gives each waiting item of the last 12 hours without it its pause answer in the owner's chat (`OWNER_CHAT_ID`), without the line «Предыдущий…». Not asked twice: an item asked before the stop has `answered_at`, and a start of polling again in the same process skips the items it took. The rest of the window: a stop between the write of `answered_at` and Telegram's answer to the send (milliseconds), or a send that fails, leaves the item without the question until its 12 hours (it is in «Входящие» then).
- Found: 2026-11-06, spec of stage 6.4.

## KI-58. «Входящие»: a Cyrillic name in the middle of a post without quotes, kind word or bold is not a candidate

- Where: `app/tracker/candidates.py` (`candidates`, the rules of 4.2).
- What's wrong: a Cyrillic name is a candidate only in quotes, in bold, right after a kind word («сериал», «игра»…), at the head of an episode line, or as a whole name message. A Cyrillic title elsewhere in a post («Вчера вышла новая Дюна, и все рады») is not found; the fallback takes the first line only when nothing else was found.
- How to reproduce: `candidates("Вот и вышла новая Дюна вчера, все рады и довольны")` gives the first words of the line (the fallback, weight 1), not «Дюна».
- Likelihood / impact: common for posts about Russian-titled films and series with no kind word, but the owner still answers «Что это?» with a kind and a post with no candidate goes on to «не нашёл» / «Входящие»; nothing is lost. A fix: score capitalised Cyrillic words in the middle of a sentence, against a list of common words.
- Status: fixed (test: `tests/test_tracker_candidates_middle.py`). Ticket 9.1d.03: a run of capitalised Russian words (at most 4) that is not the first word of a sentence, not a quote, a bold piece, a name after a kind word or after a marker, and has no word of `COMMON_WORDS`, is a candidate of weight `MIDDLE` = 2. A post of at most 8 words typed in one line is still a name message (4.2 of 6.4): it is searched as typed.
- Found: 2026-11-06, spec of stage 6.4 (13), ticket 02.

## KI-59. «Входящие»: the stop list of candidates is a fixed list

- Where: `app/tracker/candidates.py` (`STOP_NAMES`).
- What's wrong: stores, platforms, outlets and studios are dropped only by the fixed list of spec 4.5. A studio, outlet or store that is not on it and stands in a post without a Latin title or a marker before it can come first.
- How to reproduce: `candidates("Ubisoft анонсировала новую игру, и все очень этому рады сегодня")` — «Ubisoft» is a candidate (weight 10, first line), as nothing marks it as a studio.
- Likelihood / impact: moderate; the offers of ticket 03–04 show up to three candidates, so a studio wastes one, and a post with no real Latin title offers the studio first. A fix: grow the list by use, or read the names of studios from IGDB.
- Status: fixed (test: `tests/test_tracker_companies.py`). Ticket 9.1d.03: before the searches the first 10 candidates with a Latin letter (not a name message, not a name Steam gave) are asked in one request to IGDB `/companies` (`IgdbGameSource.companies`, `sources/igdb_companies.py`); a name that, alone or with a word of `COMPANY_WORDS`, is a company with at least 20 games is dropped. No keys, a failure or a 429 — a warning, the candidates stay. The stop list grew by the services IGDB does not know.
- Found: 2026-11-06, spec of stage 6.4 (13), ticket 02.

## KI-60. «Входящие»: a Latin run keeps a leading «from», and a bare number after a colon is cut off the name

- Where: `app/tracker/candidates.py` (`_LATIN_RUN`, `_MARKERS`).
- What's wrong: a run of Latin words is one name, so the marker «from» (spec 4.4) cannot lower the name after it: «from Software» is one candidate with «from» in it. And a name written with a number after a colon («Fallout: 76», «Bleach: 3 серия») loses the number: a bare number after `: ` ends the run, because `Name: N серия` is the head of an episode line.
- How to reproduce: `candidates("Игра from Software вышла вчера и все очень этому рады сегодня")` gives «from Software»; `candidates("Вышел Fallout: 76 вчера и все очень этому рады сегодня вечером")` gives «Fallout».
- Likelihood / impact: rare; a name that is searched in the source anyway (the source matches «Fallout» to the series) — a wrong first offer at worst, the owner presses «Нет». A fix: drop a leading «from» of a run; read `: <number>` as part of the name unless an episode word follows.
- Status: fixed (test: `tests/test_tracker_candidates_middle.py`). Ticket 9.1d.03: a Latin run loses a leading «from» (the rest weighs as after a marker, «from» alone is nothing); `: <number>` joins the run unless an episode word follows («Fallout: 76» is one name, «Bleach: 3 серия» stays the episode line).
- Found: 2026-11-06, ticket 02 of stage 6.4.

## KI-61. «Входящие»: a typo in a name is not corrected when the source answers in another language

- Where: `app/tracker/offers.py` (`OfferSearch._corrected`, spec 5.4 and 13 of stage 6.4).
- What's wrong: the correction looks for a close name among the names a search answers; TMDb answers a series in Russian and in its original language, so an English name with a typo of a series whose original is not English finds no close name: «Dead-End Jb» (the English name of the Korean «꿀알바», «Работа с призрачными перспективами») gives nothing to correct by.
- How to reproduce: send the bot «Dead-End Jb», press «Сериал»: «Не нашёл — сохранил во «Входящие»…» (the saved answers of `search-typos-links.json`).
- Likelihood / impact: rare (an English name of a non-English series typed with a typo); the item is in «Входящие», «Найти» on the web finds it with the name fixed by hand. A fix would need the English names of TMDb (`alternative_titles`), one more request a record.
- Status: fixed (test: `tests/test_inbox_offer_dates.py`). Ticket 9.1d.04 (8.2 of 9.1d): when the shortened name finds no close name in the source's language and the source searches in English (TMDb movies and series, `searches_in_english`), the same name is searched once more with `language=en-US`; the corrected name is then searched in Russian and the offer is the record of the same id (its Russian name), else the English record. One search instead of `alternative_titles` (one per record). A correctly typed English name of a series whose Russian name differs now gets «Возможно, вы имели в виду:» with its Russian name too (the typo path ran before as well, and gave only the weak offer).
- Found: 2026-11-06, spec of stage 6.4 (section 13); written by ticket 04.

## KI-62. «Входящие»: a kind press does not look the links of the item up again

- Where: `app/tracker/inbox_answers.py` (`InboxAnswers.answer_kind`).
- What's wrong: the links of sources are looked up once, at the end of the pause. When they gave nothing (the source failed, an unknown number) the bot asks «Что это?», and a kind press then searches only the name candidates of the text: a link whose source failed a moment ago is not tried again.
- How to reproduce: a Steam link while IGDB does not answer; «Что это?» comes; IGDB is back; «Игра» searches the text only (for a bare link: nothing — «Не нашёл…»).
- Likelihood / impact: rare (a failure of a source exactly then); the item is in «Входящие», and sending the link again gives its card. A fix: look the links of the chosen kind up again in `answer_kind` (within the budget of 5.5).
- Status: fixed (test: `tests/test_inbox_offer_dates.py`). Ticket 9.1d.04 (8.3 of 9.1d): `answer_kind` looks the links of the chosen kind up again before the name candidates (an IMDb link for a movie or a series, its records of that kind only); a Steam number IGDB does not know gives Steam's name; a link that fails again goes to the log. A link of another kind is not looked up. The budget is 8.4 of 9.1d (17 requests at a kind press).
- Found: 2026-11-06, ticket 04 of stage 6.4.

## KI-63. The Shikimori adapter is over the 400 lines of rule 7, and the size test does not see it

- Where: `app/tracker/sources/shikimori_anime.py` (464 lines; 457 before ticket 04 of stage 6.4 added the lookup of an entry), `tests/test_tracker_core_split.py` (`MODULES` lists only two adapters).
- What's wrong: rule 7 wants every module of the core within about 400 lines; the adapter holds the parsing, the chain of seasons and the source in one file, and the size test does not list it, so nothing fails.
- How to reproduce: `wc -l app/tracker/sources/shikimori_anime.py`.
- Likelihood / impact: no bug; the file is harder to read and to change in parallel. A fix: move the chain (`collect_entries`, `chain_order`, `group_seasons`, `build_*`) into a module of its own and list every adapter in the size test (like KI-56 for the pure modules).
- Status: fixed (test: `tests/test_tracker_core_split.py::test_no_part_of_the_core_is_longer_than_the_limit[sources/shikimori_anime.py]`), ticket 01 of stage 9.1d. `sources/shikimori_chain.py` holds the entry as Shikimori describes it (`Entry`, `parse_entry`), the walk along `prequel` and `sequel`, the seasons, the parts and the films; `sources/shikimori_anime.py` keeps the suggestions and the source class (the entry types had to move with the chain: the source class calls the chain, and the chain builds from the entries, so one of them could not import the other).
- Found: 2026-11-06, ticket 04 of stage 6.4.

## KI-64. «Входящие»: an offer of a title announced for a year or a quarter shows a made-up day («выйдет 31 декабря 2028»)

- Where: `app/tracker/offers.py` (`released_line`), the dates the adapters give (`Suggestion.released`: `sources/igdb_games.py` from `first_release_date`, `sources/shikimori_anime.py` from `airedOn.date`).
- What's wrong: the card of an offer says «выйдет <day> <month> <year>» for any date in the future (spec 6.1 has this form only «with a day»), but the sources fill a day they do not know: IGDB gives the last day of the year or of the quarter, Shikimori the first of January. Checked live 2026-11-06: The Witcher IV → «выйдет 31 декабря 2028», Intergalactic: The Heretic Prophet and Marvel 1943 → «31 декабря 2027», Fishy Bar → «30 июня 2027» (a quarter), «Выход смерти: Изоляция» → «выйдет 1 января 2027». The web card of the same game, once added, shows the date right (`games.GameDate` by `release_dates`).
- How to reproduce: send the bot «The Witcher IV», press «Игра».
- Likelihood / impact: often — posts are mostly about announcements; the owner may take the day for real. Nothing is stored wrong: adding the title reads its dates anew. A fix: the adapters say whether the day is known (IGDB: `release_dates.date_format` of the record of `first_release_date`, as `sources/igdb_follow_ups` reads it; Shikimori: `airedOn { day }`), the stored offer keeps it, and a future date without a day shows the year alone («2028») — or the precision of `games.GameDate` («IV квартал 2027»), a choice for the fix.
- Status: fixed (test: `tests/test_inbox_offer_dates.py`). Ticket 9.1d.04 (8.1 of 9.1d): `Suggestion.released` and `Offer.released` are a `ReleaseDate`, stored as its text («2027-Q4»; an offer stored before reads as a day). IGDB: the least precise record of `release_dates` whose `date` is `first_release_date`, none — the year alone; Shikimori: `airedOn` with its precision; TMDb: a day. The card: «выйдет в 2028», «выйдет во 2 квартале 2027», «выйдет в январе 2027» while the period has not ended. An answer without `release_dates` (the saved answers of 6.4) gives the year alone: a game out this year then reads «выйдет в 2026».
- Found: 2026-11-06, review of stage 6.4 (F9).

## KI-65. «Входящие»: «Найти» cannot remove an item whose title is in the list already

- Where: `app/web/templates/suggestions.html` (a row in the list is the link «В списке», no add form), `app/web/search.py` (`add`).
- What's wrong: spec 9.3 deletes the item when adding succeeds «new or already in the list», but the Search shows a title of the list without «Добавить», so from «Найти» the item of such a title is never removed; the «already in the list» branch of `add` is reached only by a race.
- How to reproduce: add a game, then send the bot a post about it and let it go to «Входящие» (e.g. «Нет» on its offer); on the web press «Найти» on it — the game shows «В списке», nothing removes the record.
- Likelihood / impact: rare (the bot itself says «Уже в списке» and resolves such an item when it finds the title); the owner presses «Убрать». A fix: with `inbox`, a row in the list gets a button that removes the item («Это оно — убрать запись»), a choice of text for the fix.
- Status: fixed (test: `tests/test_web_inbox.py`, «Это оно — убрать запись»; ticket 04 of stage 9.1c). With `inbox` of an item that is there, a row in the list gets a plain form to `POST /inbox/<id>/remove`.
- Found: 2026-11-06, review of stage 6.4 (F10).

## KI-66. Copies: the time of a copy is the container's clock, not the zone of Settings

- Where: `app/utils/backup.py`, `app/tracker/db.py` (`backup_name` writes `datetime.now()` of the container, whose `TZ` is `BOT_TIMEZONE`); the Settings block and the restore list of stage 7.1 (spec 2.1) show that time as written.
- What's wrong: when the zone chosen in Settings differs from `BOT_TIMEZONE`, the times of copies are off by the difference of the zones, while the time of the Google Drive copy (stored in UTC) is shown in the Settings zone — the two lines of the block can disagree.
- How to reproduce: `BOT_TIMEZONE=UTC`, Settings zone Europe/Moscow; «Сделать копию сейчас» at 16:21 Moscow — the notice and the list say «в 13:21».
- Likelihood / impact: rare (the owner sets one zone in both places); the order and the content of copies are right, only the hour shown. A fix: names in UTC with a marker (old names kept readable), or reading `BOT_TIMEZONE` for the names' clock.
- Status: fixed (test: `tests/test_copy_names_utc.py`). Ticket 9.1d.05 (10.1 of 9.1d): every writer names a copy by the UTC time with a `Z` (`tracker_db_20261123_132100Z.db`, the archive too); a name without `Z` is read in the zone of the process (`db.name_moment`, `old_zone`), the earlier moment at the hour the clocks go back; `Copy.moment` is naive UTC, old and new names mix in one order and one rotation. The Settings block, the notice after «Сделать копию сейчас», the report of a failed copy and the restore list show the zone of Settings (the restore reads it from the base being replaced, else the zone of the process).
- Found: 2026-11-07, spec of stage 7.1.

## KI-67. Google Drive copy: a folder of over 1000 files is listed only in part

- Where: `app/providers/google_drive.py` (`list_folder` asks one page of 1000 and does not follow `nextPageToken`).
- What's wrong: when the owner puts over 1000 files into «Трекер — копии», the archives on the later pages are neither counted nor rotated, and «already there» may miss a file.
- How to reproduce: 1001 files in the folder, the app's archives among the last ones listed.
- Likelihood / impact: very rare (the app keeps 30; the folder is the app's own); at worst a few archives over 30 and a duplicate. A fix: follow `nextPageToken`.
- Status: fixed (test: `tests/test_copy_names_utc.py`). Ticket 9.1d.05 (10.2 of 9.1d): `GoogleDriveApi._files` follows `nextPageToken` (`pageToken`) up to 50 pages, then a warning and what it has; `list_folder` and `find_folder` both go through it.
- Found: 2026-11-08, ticket 7.1.04.

## KI-68. Google Drive copy: an archive of the same name but another size stays as a duplicate until it rotates out

- Where: `app/tracker/drive_copies.py` (`_upload`: only a file of the same name and size counts as sent).
- What's wrong: if a file of the archive's name but another size is in the folder (an archive made before `BACKUP_PASSWORD` changed is the same size, so this needs a copy file changed on the PC, or a file put there by hand), the new archive is sent next to it; both have one name and both count among the 30.
- How to reproduce: upload by hand a file `tracker_db_<time of the newest copy>.7z` of a few bytes, wait for the hourly job.
- Likelihood / impact: very rare; one extra file of the same name in the folder until it rotates out. A fix: delete the same-name file of another size after the upload.
- Status: fixed (test: `tests/test_drive_copies.py`). Ticket 9.1d.05 (10.3 of 9.1d): once the archive is in the folder (sent now or found by name and size) every other file of that name is deleted for good, a failed delete a warning; the kept count does not include what was deleted.
- Found: 2026-11-08, ticket 7.1.04.

## KI-69. Restore: the note «ещё одна копия» of an older copy is not always true

- Where: `app/utils/restore.py` (`OLDER`) and `app/tracker/db.py` (`_backup_before_migration`).
- What's wrong: the confirmation of a copy of an older revision says «перед этим сделается ещё одна копия», but the start makes no copy before the migration when the newest copy before that revision already holds the same content — for instance when the owner restores that very copy «перед обновлением базы».
- How to reproduce: `.\restore-bot.ps1`, choose a copy «перед обновлением базы», «да»: after the start `data\backups` has no new `…_before-<revision>.db` (checked live 2026-11-08 on a copy of the project: 0013 → 0014).
- Likelihood / impact: whenever a before-update copy is restored; nothing is lost (the same content is in the copy already, and the restore made its «перед восстановлением» copy), only the promise of the text is wrong. A fix: «перед этим сохранится копия» or no promise at all.
- Status: fixed (test: `tests/test_restore.py`). Ticket 9.1d.05 (10.4 of 9.1d): `OLDER` says «Копия от более старой версии: при запуске база обновится сама.» with no promise of a copy; the line «Нынешняя база сохранена…» after «да» stays.
- Found: 2026-11-08, ticket 7.1.05.

## KI-70. Restore: `restore-bot.ps1` needs a recent Docker Compose (`--quiet-build`)

- Where: `restore-bot.ps1` (`Invoke-Restore`: `docker compose run … --build --quiet-build --interactive=false -T`).
- What's wrong: `--quiet-build` keeps the build lines out of what the script reads; an older Docker Compose (as a NAS may have) does not know the flag and every command of the restore fails with «unknown flag».
- How to reproduce: run the script with Docker Compose older than the one of Docker Desktop 29 (Compose v5.4 has the flag).
- Likelihood / impact: none on the owner's PC; on the NAS (stage 7.3) the restore would not start until the script builds the image separately (`docker compose build --quiet`) and runs without `--build`.
- Status: fixed (test: `tests/test_restore.py::test_the_script_builds_the_image_once_before_the_first_run_and_runs_it_without_build_flags`, `…::test_the_script_calls_the_one_off_container_and_the_bot_scripts`), ticket 01 of stage 7.3. The script builds the image once (`docker compose build --quiet`, «Готовлю образ бота…»; a failure shows Docker's lines and `Образ бота не собрать — ошибка выше. Ничего не изменено.`) and `Invoke-Restore` runs without `--build` and `--quiet-build`.
- Found: 2026-11-08, ticket 7.1.05.

## KI-71. Export: the JSON asks which titles are games and copies the poller's rule of the base game

- Where: `app/tracker/export_all.py` (`_parents`).
- What's wrong: rule 7 of `docs/coding-standards.md`: the core does not ask a title's kind outside `polling.py`, and a rule lives in one place. `_parents` reads the states of the games by `Title.kind == TitleKind.GAME` and finds the base game of an expansion by its own query, a copy of `GamePoller.parent` and `Poller.known_ids` («the smaller number, as `known_ids`»). `tests/test_tracker_core_split.py` did not see it: `exports` and `export_all` were missing from its list of core modules (review 7.1 added `exports` and the pure `export_rows`; `export_all` stays out until this is fixed, or the test fails).
- How to reproduce: add `"export_all"` to `MODULES` of `tests/test_tracker_core_split.py`: `test_the_core_does_not_ask_which_kind_a_title_is` fails.
- Likelihood / impact: no wrong output today — `expansion_of` in the JSON is the name the card shows. The risk is a change of the card's rule (say, the base game found by another id) that the export does not follow. A fix: the export asks every poller for the extra fields of its titles (a poller action with an empty default; the game poller answers with `parent`), then `export_all` joins the list of the test.
- Status: fixed (test: `tests/test_tracker_split_health.py::test_a_game_poller_names_the_base_game_by_the_list_when_the_list_has_it_else_by_igdb`, `…::test_a_game_whose_state_cannot_be_read_is_left_out_with_a_warning`, `…::test_a_kind_with_nothing_to_add_answers_nothing`, and the JSON byte for byte as before: `tests/test_tracker_split_baselines.py::test_the_export_json_of_the_sample_base_is_the_one_recorded_before_the_split`), ticket 01 of stage 9.1d. `Poller.export_extras(session, title_ids)`, `{}` by default; `GamePoller` answers `{"expansion_of": …}`; `export_all` asks the poller of every kind present and `_parents` is gone.
- Found: 2026-11-15, review 7.1 (F6).

## KI-72. Login report: an iPad on iPadOS 13+ reads as «macOS, Safari»

- Where: `app/web/devices.py` (spec 6.3 of stage 7.2; ticket 7.2.05).
- What's wrong: Safari on an iPad of iPadOS 13 and later sends the `User-Agent` of a Mac (`Macintosh; Intel Mac OS X …`), so the login report and the block «Вход» say «macOS, Safari» for it. Telling them apart needs JavaScript (touch points), which the app does not have (ADR 0004).
- How to reproduce: log in from an iPad in Safari — the 🔐 message says «macOS, Safari».
- Likelihood / impact: the owner has no iPad as far as known; the wrong word only, the report still comes.
- Status: won't fix (test: `tests/test_web_devices.py::test_an_ipad_that_says_it_is_a_mac_reads_as_a_mac_known_issue_72`; ticket 05 of stage 9.1c). Telling an iPad from a Mac needs JavaScript, which the app does not have (ADR 0004); the owner accepted this with the spec of 9.1c («ОК», 2026-11-22). The test pins the behaviour.
- Found: 2026-11-15, spec 7.2.

## KI-73. Login report: a report that failed to send waits for the delivery rules

- Where: the delivery of the events `web_login` and `web_login_locked` (`app/web/login_report.py`, `Tracker.record_login_report`; spec 6.2 of stage 7.2; ticket 7.2.05).
- What's wrong: the report is sent at once whatever the rules; if that send fails (Telegram down, no network), the event stays in the queue and the regular delivery sends it by the rules — a login during the quiet hours is reported only when they end, or in the summary on a work day.
- How to reproduce: stop the network of the container, log in at 22:00, bring the network back — the report comes at 07:30.
- Likelihood / impact: rare (Telegram down at the moment of a login); a strange login is seen later. Behind Cloudflare Access a stranger has passed the mail code too.
- Status: fixed (test: `tests/test_tracker_login_report_rules.py`; ticket 05 of stage 9.1c). The two report types are outside the delivery rules: every pass sends a queued report as a message of its own, «Сводка сейчас» sends it apart before the summary, it never expires. The send at once and a pass run under `delivery_lock` and send it once.
- Found: 2026-11-15, spec 7.2.

## KI-74. Phone: the chosen filter can be past the edge of its row

- Where: `app/web/static/style.css`, the filter rows of «Список» and «Архив» under 40rem (spec 7, P2 of stage 7.2; ticket 7.2.06).
- What's wrong: on a phone each row of filter links is one line that scrolls sideways; a chosen link far to the right (a genre late in the list, «Весь список») can be out of sight until the row is swiped. Bringing it into view needs JavaScript (ADR 0004).
- How to reproduce: at 375 px choose the last genre of «Архив», reload — its row starts from «Все жанры».
- Likelihood / impact: only the look; the shown rows and the line «Показано …» follow the filter.
- Status: fixed (test: `tests/test_web_css.py`; ticket 04 of stage 9.1c). No JavaScript needed after all: `order: -1` puts the chosen link first under 40rem.
- Found: 2026-11-15, spec 7.2.

## KI-75. Sign-ins: the block «Вход» counts sign-ins ended by a new `WEB_PASSWORD` or key

- Where: `app/web/sessions.py` (`SignIns.count`, `end_all`, the cap of 20), the block «Вход» of Settings (spec 4.3–4.5 of stage 7.2).
- What's wrong: a change of `WEB_PASSWORD` or a new `data/web_secret` (deleted, or made anew when spoiled, KI-13) ends every sign-in through the cookie (the fingerprint or the signature no longer matches), but the sign-ins stay in `data/web_login.json` until 30 days without a request. So «Вход открыт на N устройствах» counts them, «Выйти на всех устройствах» logs them in its count, and they keep places among the 20.
- How to reproduce: sign in on the PC and the phone, change `WEB_PASSWORD`, `.\start-bot.ps1`, sign in on the PC — Settings says «Вход открыт на 3 устройствах.», though only one works.
- Likelihood / impact: rare (a password change); the number is too high, nobody gets in. «Выйти на всех устройствах» clears them. A fix keeps the fingerprint of the password and the key in the file and drops the sign-ins when it differs at start — a change of the file's shape (ADR 0014).
- Status: fixed (test: `tests/test_web_sign_in_mark.py`; ticket 05 of stage 9.1c). The file has a `mark` (HMAC of the password with the key of `data/web_secret`), checked at start: another mark drops every sign-in (the last login and the lock count stay), a file of stage 7.2 keeps its sign-ins and gets the mark.
- Found: 2026-11-17, review 7.2 (F2).

## KI-76. `APP_URL`: a Cyrillic domain is refused with a reason about the dot

- Where: `app/config.py`, `parse_app_url` (`_HOST_NAME`: latin letters, digits and hyphens), spec 1.1 of stage 7.2.
- What's wrong: `APP_URL=https://трекер.рф` is malformed with the reason «Telegram не открывает такие ссылки — … или имя сайта с точкой», though the name has a dot; the bot stays in chat mode. Whether Telegram opens such a name in a button was not checked.
- How to reproduce: put `APP_URL=https://трекер.рф` into `.env`, `.\start-bot.ps1` — Settings shows the line «записан с ошибкой» with that reason.
- Likelihood / impact: only if the owner buys a Cyrillic domain. Workaround: write the name in its `xn--…` form (the domain registrar shows it), which is taken.
- Status: fixed (test: `tests/test_app_url.py`; ticket 05 of stage 9.1c). A name with Cyrillic letters is turned into its `xn--…` form by IDNA (UTS 46) for the links and the `Host` check; Settings shows it as written; a name IDNA refuses has its own reason. Telegram took such an address live (2026-11-22).
- Found: 2026-11-17, review 7.2 (F3).


## KI-77. Anime: an episode out right after «Вернуть в список» passes silently

- Where: `Poller.record_all` with the reference point of the first check after a return (spec 9.1a, section 4.2, KI-23); the anime episode events carry no `happened_at`.
- What's wrong: after 9.1a the first check after a return reports the facts that happened after the return, by the moment each one came out. An anime episode found by a check without a schedule gets the moment it was found, so its moment cannot tell «out before the return» from «out after it»; the anime episode events are therefore left without a moment and stay silent, as before 9.1a.
- How to reproduce: return an anime to the list a minute before its episode airs; the first check after the return finds the episode and records it as the reference point — no «вышла серия».
- Likelihood / impact: very rare (a window of up to a minute). One missed message; the episode is in the card.
- Status: fixed (test: `tests/test_tracker_check_rules.py`). Ticket 9.1c.01: an anime episode event carries its moment when it is exact or a day (`series_events._aired_at`), none when unknown; `Flavor.moments` is gone.
- Found: 2026-11-20, spec 9.1a.


## KI-78. A send Telegram has not answered within 5 s of a stop can come again after the start

- Where: `DeliveryService._send` and `Tracker.finish_sends` (spec 9.1a, section 2.1, KI-5); `TelegramPart.close` in `app/main.py`.
- What's wrong: on a stop, a send in progress gets 5 s to finish with its «delivered» mark. If Telegram has not answered by then, the HTTP session closes, the send fails and its entry stays pending; if Telegram had in fact taken the message, it comes again after the start. Only Telegram knows whether it took it.
- How to reproduce: a stop while Telegram hangs on a send (a slow network) for more than 5 s.
- Likelihood / impact: very rare. One repeated message, no loss.
- Status: open. Fix in 9.2 only if met in real use (e.g. a longer grace).
- Found: 2026-11-20, spec 9.1a.


## KI-79. Russian: a game added before 9.1b says «Ещё не проверяли» until its own poll (up to a week), with a Steam page up to 6 hours more

- Where: `GameRussian._store` (spec 9.1b, section 5.5: «while Steam has none and IGDB is «not asked yet», nothing is stored»).
- What's wrong: a game added before stage 9.1b has an own snapshot without the languages of IGDB until its own poll — up to a day for a game with a date ahead, up to a week (`INTERVAL_QUIET`) when every platform is out or the dates are far. Until then the official check stores nothing (the first look with data must be a reference point), and the card says «нет данных» with «Ещё не проверяли — строка появится через минуту-другую». A game without a Steam page stays due, so the log has «Russian check: 1 games, 0 failed» every minute, and it gets its look in the first pass after its own poll. A game with a Steam page whose Steam lists no languages waits 6 hours after each such check, so its hint can stay up to 6 hours after the own poll too. Games added after the update have IGDB's languages from adding and are not affected; the case ends by itself once every old game has had its own poll.
- How to reproduce: the owner's PC, 2026-11-22 — GTA VI (in «Хочу», no Steam page, next own poll 2026-11-27): its card has said «Ещё не проверяли — строка появится через минуту-другую» since 2026-11-21, and the log line comes every minute.
- Likelihood / impact: once per old game, for at most a week after the update; a wrong hint and a log line a minute, no message lost or false.
- Status: open. Fix in 9.2 only if met in real use (e.g. a hint of its own for «IGDB not asked yet», or the own poll made due at once).
- Found: 2026-11-21, ticket 9.1b.04 (self-check on the owner's PC); widened 2026-11-22 by review 9.1b (F2: a game without a Steam page is affected too, up to a week).

## KI-80. ZoG: while its layout cannot be read, a game whose page is not known yet shows no ZoG hint

- Where: `GameZog._look` (spec 9.1b, section 5.6; ADR 0016).
- What's wrong: a stored page with an unreadable layout keeps its last support and the card says «Страницу на ZoG не удалось прочитать». A game whose page is not known yet (never checked, or not found before) meets the same layout while finding a page: the check cannot tell the game's page from another one, so it keeps the state as it was, logs once a day and tries again in a week. Its card shows no ZoG hint at all (or the old «не найдена»), not «не удалось прочитать».
- How to reproduce: a test page whose `<title>` is not «… | Игровой архив на Zone of Games» answered for the first address of a game added just now.
- Likelihood / impact: only while ZoG's layout is broken (the log says so every day); the fan part of new games is unknown for that time anyway. No message lost or false.
- Status: open. Fix in 9.2 only if met (e.g. the state `{"page": null, "by": "unreadable"}` with the hint of an unreadable page).
- Found: 2026-11-21, ticket 9.1b.05.

## KI-81. Anime: a premiere Shikimori knows by the month or the year stands on a made-up first day

- Where: `app/tracker/sources/shikimori_anime.py`, `part_episodes` (the premiere stub of an announced entry from `airedOn.date`); the Feed («Позже») and the card («часть 2 — с 1 апреля»).
- What's wrong: for an announced entry Shikimori fills `airedOn.date` with the first of the month or of January when it knows only the month or the year (`airedOn.day` is null, sometimes `month` too). The stub is stored as that day, so the Feed and the card show a day nobody announced. Checked live 2026-11-22 (`.scratch/9-1c-feed-web/answers/shikimori-premiere-precision-2026-11-22.json`): «Монолог фармацевта» season 3 part 2 → 2027-04-01 (month only), «Ванпанчмен» season 3 part 2 and «Реинкарнация безработного» season 3 part 2 → 2027-01-01 (month only and year only).
- How to reproduce: the card of «Ванпанчмен» — «Сезон 3 …; часть 2 — с 1 января»; the Feed, «Позже» — «1 января 2027».
- Likelihood / impact: every announced part or season without an exact day; the owner may take the day for real. Nothing is lost: the right day comes with the source. A fix: read `airedOn { year month day }`, keep the precision with the stub (the episode timing of spec 9.1c gets one more value, or the stub is not stored) and show it as an approximate date («апрель 2027», «2027»), as games do; together with KI-64 (the same Shikimori day in an offer).
- Status: fixed (test: `tests/test_tracker_anime_approximate.py`, `tests/test_tracker_anime_approximate_polls.py`). Ticket 9.1d.02: Shikimori is asked `airedOn { date year month day }`; a premiere known by the month or the year is the approximate stub (`EpisodeTiming.MONTH`/`YEAR`, no moment, `Episode.rough`), stored at 00:00 of the first day of its period, never out; it reads «часть 2 — в январе 2027» in the card, «январь 2027» in «Позже»; the stored made-up day is replaced at the first look (migration 0018 makes it come at once), with no message.
- Found: 2026-11-22, spec 9.1c.

## KI-82. Login report: a report that waits past midnight says «сегодня» of the day before

- Where: `app/tracker/login_reports.py` (`LoginReports.record`: the moment in words is made when the login is recorded), spec 9.1c, section 6.
- What's wrong: the text of a report keeps the words of the moment as they were at the login («сегодня в 23:50»). A report that could not be sent and goes after midnight says «сегодня» of the day before.
- How to reproduce: stop the network of the container, log in at 23:50, bring the network back at 00:10 — the 🔐 message says «сегодня в 23:50».
- Likelihood / impact: very rare after KI-73 (the report goes at the first delivery pass once Telegram answers); the time is right, only the day word is off.
- Status: open. Fix in 9.2 only if met (e.g. the payload keeps the moment and the words are made at the send).
- Found: 2026-11-22, spec 9.1c.

## KI-83. Anime: an episode first seen with an AniList airing earlier than the previous look comes with no message

- Where: `app/tracker/anime_events.py` (`assemble`: a new episode keeps a fresh `exact` moment, spec 1.1 of 9.1c) and `app/tracker/series_events.py` (`_newly_out`: an episode not stored before whose moment is behind the previous look is «a backfill of history»).
- What's wrong: since ticket 9.1c.02 an episode found out now keeps the moment AniList says it aired. When that episode was not stored at the previous look and its airing is earlier than that look, `_newly_out` counts it as history and no event is queued. Before 9.1c it got the moment of the look and was reported.
- How to reproduce: look at 13:00 stores episode 7 as the next one (14:00); look at 14:30 — AniList still says 6 out (counter lag), episodes 8–9 unknown; look at 20:00 — AniList says 9 out with airings of 8 and 9 at 14:00 (a bulk drop). Episodes 8 and 9 are stored at 14:00 `exact`; `_newly_out` gives `[]` — no message about them (review probe: `came == []`).
- Likelihood / impact: rare — needs an episode AniList did not announce as the next one before it aired, seen first after the following look (a drop of several episodes, a lagging counter, AniList down at the look and Shikimori late). The episode is in the card and the Feed; only its message is missing.
- Status: fixed (test: `tests/test_tracker_anime_late_and_moves.py`). Ticket 9.1d.02: `assemble` returns `Assembled(seasons, late)`; `late` episodes go to `_newly_out` as news, `happened_at` their airing.
- Found: 2026-11-23, review of stage 9.1c (F1).

## KI-84. Anime: a premiere moved by hours within its day reads «9 янв 2027 → 9 янв 2027»

- Where: `app/tracker/series_events.py` (`message_moved`: a premiere shows the days only; `_moved` reports any change of an `exact` moment).
- What's wrong: when AniList moves the premiere of an announced season or part by hours within one day, the bot sends «🎌 … — премьера сезона 4 перенесена» with the same day on both sides. Older than 9.1c for moments not at 00:00 UTC; since 9.1c an `exact` moment at 00:00 UTC is a moment too, so its change is a move as well.
- How to reproduce: the premiere `exact` at 2027-01-09 15:00 UTC, the next look 16:00 the same day → `message_moved(…, premiere=True)` gives «9 янв 2027 → 9 янв 2027» (review probe).
- Likelihood / impact: rare (an hour move of an anime premiere before it airs); the message is confusing, nothing is lost.
- Status: fixed (test: `tests/test_tracker_anime_late_and_moves.py`). Ticket 9.1d.02: equal days read with the hours («9 янв 2027, 18:00 → 9 янв 2027, 19:00»); the same day with and without an hour is no move, both ways (`series_moves`).
- Found: 2026-11-23, review of stage 9.1c (F2).

## KI-85. Anime: a franchise film Shikimori knows by the month or the year stands on a made-up first day

- Where: `app/tracker/sources/shikimori_anime.py` (`FranchiseMovie.aired_on` from `airedOn.date`), `MovieRecord.aired_on`; the Feed («Фильм «…»» in «Скоро» or «Позже») and the message «анонсирован фильм франшизы … премьера: 1 января 2027».
- What's wrong: as KI-81 for a season, Shikimori fills `airedOn.date` with the first of the month or of January when it knows only the month or the year; a film of the franchise is stored with that day. Spec 9.1d (section 4) fixes the premieres of seasons and parts only: a film's date is a column of its own, and a fix needs its precision stored (a migration).
- How to reproduce: a followed franchise whose announced film has `airedOn { day: null }` — the Feed shows the film on the 1st.
- Likelihood / impact: rare (an announced film of a followed franchise without a day); the owner may take the day for real; nothing is lost.
- Status: open. Fix in 9.2 if met.
- Found: 2026-11-23, spec 9.1d.

## KI-86. «Входящие»: a number after a colon joins a Latin name before a counting word other than an episode, a season or a part

- Where: `app/tracker/candidates.py` (`_LATIN_RUN`: `: <number>` joins a run unless a piece word follows — `_PIECE_WORD`).
- What's wrong: KI-60 (9.1d.03) made a number after a colon part of the name («Вышел Fallout: 76 вчера» → «Fallout: 76») unless an episode word follows; the review of 9.1d added the season and part words (F1). Any other counting word after the number still glues it to the name: «Hades: 2 дня до релиза» → «Hades: 2», «Elden Ring: 10 из 10» → «Elden Ring: 10», «Stalker 2: 1 место в чарте» → «Stalker 2: 1». Before 9.1d such a number never joined. The search by the glued name may find no exact or prefix match: then only the first candidate gives the weak offer (the source's first record).
- How to reproduce: a forwarded post «Hades: 2 дня до релиза второй части и все очень этому рады сегодня вечером» → the first candidate «Hades: 2» (review probe).
- Likelihood / impact: medium for game news headlines «Name: N <noun>»; a wrong or missing offer, the owner finds the title with «Найти».
- Status: open. Fix in 9.2 with real posts: a list of counting words, or the number joined only when nothing Cyrillic follows it in its sentence part (keeping «Fallout: 76 вчера»).
- Found: 2026-11-24, review of stage 9.1d (F1).

## KI-87. «Входящие»: an item a newer message moved to «Входящие» while its links were looked up still gets its offer card

- Where: `app/tracker/inbox_answers.py` (`pause_over` → `_finish`: `existing` reads the item in any state).
- What's wrong: the end of the pause of an item with links of sources looks them up (one to three requests, seconds). A message that comes meanwhile is a new item and moves the first one to «Входящие» «без ответа» (its answer says «Предыдущий…»); the lookups of the first one then finish, and `_finish` stores the offers and sends its card anyway. The question path checks the state since the review of 9.1d (F2); this path is older (stage 6.4).
- How to reproduce: forward a post with a TMDb link and, within the seconds of its lookups, another post: the first post's card comes after the second post's «Предыдущий…» line.
- Likelihood / impact: possible when several posts with links are forwarded in a row; a confusing order of messages, the card's buttons still work on the item in «Входящие»; nothing is lost.
- Status: open. Fix in 9.2 if met: the pause path answers nothing for an item that no longer waits (a parameter of `_finish`), as the question does.
- Found: 2026-11-24, review of stage 9.1d (F2).

## KI-88. «Входящие»: the series «From» as a lone Latin word of a post is no candidate

- Where: `app/tracker/candidates.py` (`_without_from`, spec 7.2 of 9.1d: «from» leaves a Latin run, «from» alone is nothing).
- What's wrong: «Вышел трейлер 4 сезона сериала From» gave the candidate «From» (a Latin run of the first line after a kind word, weight 14) before 9.1d; now «From» is dropped as the marker of «from Software» and the post has no candidate but the fallback. A run «From Dusk Till Dawn» becomes «Dusk Till Dawn» with the low weight of a name after a marker.
- How to reproduce: a forwarded post «Вышел трейлер 4 сезона сериала From и все очень этому рады сегодня» + «Сериал» → no offer «Извне» (review probe: only the fallback of the first line).
- Likelihood / impact: rare (one title, «Извне»), but it is a followed kind; the owner types «From» as a name message, which is searched as typed.
- Status: open. Fix in 9.2 if met: keep a lone «From» after a kind word.
- Found: 2026-11-24, review of stage 9.1d (F4).

## KI-89. «Входящие»: a Russian name with a hyphen in the middle of a sentence is cut at the hyphen

- Where: `app/tracker/candidates.py` (`_CAPITAL_WORD` of the middle name, spec 7.1 of 9.1d: a capital, then lower-case letters).
- What's wrong: «Вчера вышел Человек-паук, и все рады» gives the middle name «Человек» (weight 2), not «Человек-паук»; «Санкт-Петербург» gives «Санкт». A name after a kind word («мультфильм Человек-паук») is the older rule and stays whole.
- How to reproduce: a forwarded post «Вчера вышел новый Человек-паук и все очень этому рады сегодня» → the candidate «Человек» (review probe).
- Likelihood / impact: rare, and the weight 2 is the lowest but one, so a quote, bold or Latin name wins; when it is the only name, a search by «Человек» gives a wrong offer, one «Нет».
- Status: open. Fix in 9.2 if met: a word may go on after a hyphen with lower-case letters.
- Found: 2026-11-24, review of stage 9.1d (F5).

## KI-90. Copies on the HDD: the hourly job lists their folder every hour and may wake the disk

- Where: `app/utils/backup.py` (`backup_if_due` → `daily_backups`), `app/tracker/drive_copies.py` (`_due` → `newest`); both read `data/backups` in every run of the hourly job.
- What's wrong: with `data/backups` on the NAS's HDD (spec 3.3 of 7.3, `docker-compose.override.yml`) the listing may spin the disk up every hour when the system no longer holds the folder in memory; the disk then never sleeps for long.
- How to reproduce: only on the NAS — the HDD's sleep set in UGOS, the copies on it; see whether the disk wakes at the tracker's hourly runs.
- Likelihood / impact: unknown until the NAS; more wear and noise, no data at risk.
- Status: open. The NAS project reports it (`docs/nas-move.md`, «Report back»). If met: the copies back on the SSD (delete the override), or 9.2 keeps the newest copy's moment in memory and lists the folder only at start and when a copy is due.
- Found: 2026-11-24, spec of stage 7.3.

## KI-91. Copies on the HDD: a folder missing at the container's start is created on the system disk

- Where: `docker-compose.override.yml` of the NAS (from `docker-compose.override.example.yml`): a bind mount of the copies folder on the HDD.
- What's wrong: when the HDD is not mounted yet (or is gone) as the container starts, Docker creates the missing folder where the path then lies — on the system disk — and the copies go there unnoticed; once the HDD is back, it hides them.
- How to reproduce: on the NAS, start the container with the HDD's volume unmounted; `df <copies folder>` shows the system disk.
- Likelihood / impact: rare (Docker of UGOS starts after the volumes); the copies on the NAS are then in the wrong place, the Google Drive copy still goes; a dead HDD does not stop the bot (a missing folder must not).
- Status: open. The guide checks `df <copies folder>` after a restart of the NAS and says how to move what landed on the system disk; 9.2 decides on a guard in code if it is met.
- Found: 2026-11-24, spec of stage 7.3.

## KI-92. Restore: with no answer from the name service a stopped bot counts as running

- Where: `app/utils/restore.py`, `bot_running` (the guard of the asking restore and of `apply`).
- What's wrong: the guard asks whether the service name `tracker` resolves; any error but «no such name» counts as running (spec 2.4 of 7.3). When the host's DNS does not answer (no internet, the router down), Docker's resolver forwards the unknown name, gets nothing and answers «temporary failure» (`EAI_AGAIN`) after about 8 s, so the asking restore of a stopped bot refuses with «Бот работает, а базу можно заменить только у остановленного…» — a false text, and no restore until the network is back.
- How to reproduce: bot stopped (`docker compose stop`), then `docker run --rm --network telegram-bot_default --dns 192.0.2.1 --entrypoint python telegram-bot-tracker -c "from app.utils import restore; print(restore.bot_running())"` — waits 8 s, prints `True` (with the normal DNS it prints `False`).
- Likelihood / impact: rare (a restore while the NAS has no network; the bot itself needs the internet anyway); the base is never touched by mistake, the restore is only refused with a wrong reason. The guide (`docs/nas-move.md`, section 7) says what the pause and the text mean.
- Status: open. 9.2: a separate text for «no answer» and a way past it once `docker compose ps` shows the bot stopped, if it is met.
- Found: 2026-11-25, review of stage 7.3 (F1), checked live.
