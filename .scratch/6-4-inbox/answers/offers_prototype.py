"""Prototype of the offers of spec 6.4: live searches of the top candidates, the match, the order, the typo flow."""
import asyncio, json, sys, pathlib, difflib
from datetime import date, datetime, timezone
sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path("E:/LocalAI/Bionic/Telegram-bot")
SP = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(SP))
import os; os.chdir(ROOT)
from candidates import extract, norm
from app.config import get_settings
from app.providers.tmdb import TMDbProvider
from app.providers.shikimori import ShikimoriClient
from app.providers.igdb import IGDBProvider
from app.tracker.sources.igdb_games import SEARCH_QUERY, clean_query, is_game
from app.tracker.sources.shikimori_anime import parse_search as shiki_parse

TODAY = date(2026, 11, 5)
NEW_FROM = date(2024, 11, 5)
KIND = {"Игра": "game", "Сериал": "series", "Аниме": "anime", "Фильм": "movie"}
LOG = {}


def d(s):
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


async def search(kind, q, P):
    if kind == "game":
        raw = await P["igdb"].games(SEARCH_QUERY.format(query=clean_query(q)), at_once=True)
        await asyncio.sleep(0.3)
        out = []
        for r in raw:
            if not is_game(r):
                continue
            names = [r["name"]] + [a["name"] for a in r.get("alternative_names") or [] if a.get("name")]
            ts = r.get("first_release_date")
            out.append((str(r["id"]), r["name"], names, datetime.fromtimestamp(ts, timezone.utc).date() if ts else None))
    elif kind == "anime":
        raw = await P["shiki"].search_anime(q, strict=True)
        by_id = {str(x["id"]): x for x in raw}
        out = []
        for s in shiki_parse(raw):
            x = by_id[s.external_id]
            out.append((s.external_id, s.name, [x.get("name"), x.get("russian"), x.get("english")], d((x.get("airedOn") or {}).get("date"))))
    elif kind == "series":
        raw = await P["tmdb"].search_tv(q, strict=True)
        out = [(str(x["id"]), x.get("name"), [x.get("name"), x.get("original_name")], d(x.get("first_air_date"))) for x in raw]
    else:
        raw = await P["tmdb"].search_movie(q, strict=True)
        out = [(str(x["id"]), x.get("title"), [x.get("title"), x.get("original_title")], d(x.get("release_date"))) for x in raw]
    LOG[f"{kind}:{q}"] = raw
    return out


def match(cand, names):
    c = norm(cand)
    best = 0
    for n in filter(None, names):
        n = norm(n)
        if n == c:
            return 2
        if n.startswith(c + " "):
            best = 1
    return best


def order_key(rec, years, idx):
    _id, _name, _names, day = rec
    in_post = day is not None and day.year in years
    new = day is None or day >= NEW_FROM
    return (not in_post, not (new and day is not None), not new, idx)


def close(cand, names):
    c = norm(cand)
    k = len(c.split())
    best = 0.0
    best_name = None
    for n in filter(None, names):
        cut = " ".join(norm(n).split()[:k])
        r = difflib.SequenceMatcher(None, c, cut).ratio()
        if r > best:
            best, best_name = r, n
    return best, best_name


async def offers_for(kind, cands, years, P, short=False, budget=4):
    offers, used = [], 0
    for i, cand in enumerate(cands):
        if len(offers) >= 3 or used >= budget:
            break
        recs = await search(kind, cand, P); used += 1
        good = [(match(cand, r[2]), r) for r in recs]
        good = [(m, r) for m, r in good if m]
        good.sort(key=lambda mr: (-mr[0], order_key(mr[1], years, recs.index(mr[1]))))
        mine = [r for _, r in good][:2]
        heading = "Это оно?"
        if short and i == 0 and not mine and len(cand.split()) >= 2:
            words = cand.split()
            for j in reversed(range(len(words))):
                if used >= 1 + 3:
                    break
                q = " ".join(words[:j] + words[j + 1:])
                rel = await search(kind, q, P); used += 1
                scored = sorted(((close(cand, r[2]), r) for r in rel), key=lambda x: -x[0][0])
                if scored and scored[0][0][0] >= 0.8:
                    corrected = " ".join(scored[0][0][1].split()[: len(words)]).rstrip(":")
                    rec2 = await search(kind, corrected, P); used += 1
                    g2 = [r for r in rec2 if match(corrected, r[2])] or [scored[0][1]]
                    mine = g2[:2]
                    heading = f"Возможно, вы имели в виду (по «{corrected}»):"
                    break
        if not mine and recs:
            mine = [recs[0]]
            heading = heading if heading != "Это оно?" else "Это оно? (слабое)"
        for r in mine:
            if len(offers) < 3 and r[0] not in [o[1][0] for o in offers]:
                offers.append((heading, r))
    return offers, used


async def main():
    s = get_settings()
    P = {"tmdb": TMDbProvider(), "shiki": ShikimoriClient(), "igdb": IGDBProvider(s.igdb_client_id, s.igdb_client_secret)}
    samples = json.load(open(SP / "samples.json", encoding="utf-8"))
    for smp in samples:
        cands, years = extract(smp["text"])
        offers, used = await offers_for(KIND[smp["kind"]], [c.text for c in cands], years, P)
        print(f'{smp["n"]:>2} {smp["kind"]} expected {smp["expected"]!r}; requests {used}')
        for h, r in offers:
            print(f"      {h} {r[0]} {r[1]} {r[3]}")
    print("--- names with typos")
    for kind, name in [("anime", "Реинкарнация безработнго"), ("game", "Phantom Blad Zero"), ("game", "Ведьмак 3 Дикая охта"),
                       ("game", "Cyberpnk 2077"), ("series", "Dead-End Job"), ("series", "Игра в кальмра"), ("movie", "Eldn Ring"),
                       ("anime", "Магическая битва"), ("game", "Hades 2"), ("movie", "Дюна")]:
        cands, years = extract(name)
        offers, used = await offers_for(kind, [c.text for c in cands], years, P, short=True)
        print(f"   {kind} {name!r}; requests {used}")
        for h, r in offers:
            print(f"      {h} {r[0]} {r[1]} {r[3]}")
    (ROOT / ".scratch/6-4-inbox/answers/offers-prototype.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in P.values():
        await p.aclose()

asyncio.run(main())
