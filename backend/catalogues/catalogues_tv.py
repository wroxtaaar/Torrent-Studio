"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from core.cache_diagnostics import _record_cache_event
from search.search_providers import _normalize_title
from core.settings import (
    BACKFILL_MISSING_METADATA,
    CACHE_ONLY_MODE,
    DATA_DIR,
    DC_TV_CATALOGUE_CACHE_FILE,
    MARVEL_TV_CATALOGUE_CACHE_FILE,
    REGIONAL_TV_PREBUILT_CACHE_FILE,
    TMDB_API_KEYS,
    TMDB_IMAGE_BASE,
    TMDB_READ_ACCESS_TOKENS,
    _CACHE_SEED_DIR,
    logger,
    stored_ttl,
)
from metadata.imdb import _get_imdb_rating_record
from metadata.tmdb import _tmdb_get_json
from catalogues.pakistani_drama_order import PAKISTANI_DRAMA_POPULARITY_ORDER

router = APIRouter()

# IMDb's supplied 100 most popular anime TV shows, in the order from the saved chart.
ANIME_POPULARITY_ORDER: tuple[tuple[str, str], ...] = (
    ("Cyberpunk: Edgerunners", "tt12590266"),
    ("Black Clover", "tt7441658"),
    ("Bleach: Thousand-Year Blood War", "tt14986406"),
    ("Attack on Titan", "tt2560140"),
    ("Steel Ball Run: JoJo's Bizarre Adventure", "tt38268282"),
    ("One Piece", "tt0388629"),
    ("Dragon Ball Super: Beerus", "tt39395275"),
    ("Re: Zero - Starting Life in Another World", "tt5607616"),
    ("Jujutsu Kaisen", "tt12343534"),
    ("JoJo's Bizarre Adventure", "tt2359704"),
    ("Vinland Saga", "tt10233448"),
    ("My Hero Academia", "tt5626028"),
    ("Bleach", "tt0434665"),
    ("Death Note", "tt0877057"),
    ("Demon Slayer: Kimetsu no Yaiba", "tt9335498"),
    ("Fullmetal Alchemist: Brotherhood", "tt1355642"),
    ("Naruto: Shippuden", "tt0988824"),
    ("Hunter X Hunter", "tt2098220"),
    ("Tokyo Revengers", "tt13196080"),
    ("Mushoku Tensei: Jobless Reincarnation", "tt13293588"),
    ("The Apothecary Diaries", "tt26743760"),
    ("Monster", "tt0434706"),
    ("Frieren: Beyond Journey's End", "tt22248376"),
    ("Solo Leveling", "tt21209876"),
    ("Naruto", "tt0409591"),
    ("Firefly Wedding", "tt39394153"),
    ("Chainsaw Man", "tt13616990"),
    ("Code Geass: Lelouch of the Rebellion", "tt0994314"),
    ("Berserk", "tt0318871"),
    ("One Punch Man", "tt4508902"),
    ("Steins; Gate", "tt1910272"),
    ("Cowboy Bebop", "tt0213338"),
    ("Neon Genesis Evangelion", "tt0112159"),
    ("Gintama", "tt0988818"),
    ("Dragon Ball Z", "tt0214341"),
    ("Mob Psycho 100", "tt5897304"),
    ("The Ramparts of Ice", "tt39123061"),
    ("Dragon Ball Super", "tt4644488"),
    ("That Time I Got Reincarnated as a Slime", "tt9054364"),
    ("Link Click", "tt14976292"),
    ("Dandadan", "tt30217403"),
    ("Pokémon", "tt0168366"),
    ("Kaiju No. 8", "tt21975436"),
    ("Tokyo Ghoul", "tt3741634"),
    ("Takopi's Original Sin", "tt36988358"),
    ("Gurren Lagann", "tt0948103"),
    ("Dr. Stone", "tt9679542"),
    ("Blue Box", "tt32639706"),
    ("Witch Hat Atelier", "tt32550889"),
    ("Haikyuu!!", "tt3398540"),
    ("Overgeared", "tt43691353"),
    ("Daemons of the Shadow Realm", "tt37532356"),
    ("86", "tt13718450"),
    ("Spy x Family", "tt13706018"),
    ("The Boondocks", "tt0373732"),
    ("Hell's Paradise", "tt13911284"),
    ("Gachiakuta", "tt32612521"),
    ("Erased", "tt5249462"),
    ("Devil May Cry", "tt15716776"),
    ("Pluto", "tt26737616"),
    ("The Fragrant Flower Blooms with Dignity", "tt36592690"),
    ("My Dress-Up Darling", "tt15765670"),
    ("Made in Abyss", "tt7222086"),
    ("Your Lie in April", "tt3895150"),
    ("Rascal Does Not Dream of Bunny Girl Senpai", "tt8993398"),
    ("Violet Evergarden", "tt7078180"),
    ("Boruto: Naruto Next Generations", "tt6342474"),
    ("Blue Lock", "tt15222080"),
    ("The Ghost in the Shell", "tt36517689"),
    ("Love Unseen Beneath the Clear Night Sky", "tt39304754"),
    ("Teen Titans", "tt0343314"),
    ("Classroom of the Elite", "tt7263328"),
    ("The Seven Deadly Sins", "tt3909224"),
    ("Kaguya-sama: Love Is War", "tt9522300"),
    ("Sword Art Online", "tt2250192"),
    ("Orb: On the Movements of the Earth", "tt33044444"),
    ("Serial Experiments Lain", "tt0500092"),
    ("Smoking Behind the Supermarket with You", "tt37614297"),
    ("Ranma ½", "tt32766897"),
    ("Dragon Ball", "tt0280249"),
    ("Fire Force", "tt9307686"),
    ("Fullmetal Alchemist", "tt0421357"),
    ("Samurai Champloo", "tt0423731"),
    ("Fighting Spirit", "tt0481256"),
    ("Tougen Anki: Dark Demon of Paradise", "tt32344704"),
    ("Kingdom", "tt2404499"),
    ("Even the Student Council Has Its Holes!", "tt43650242"),
    ("Chainsmoker Cat", "tt39551330"),
    ("Parasyte: The Maxim", "tt3358020"),
    ("Legend of the Galactic Heroes", "tt0096633"),
    ("The Promised Neverland", "tt8788458"),
    ("Delicious in Dungeon", "tt21621494"),
    ("Dororo", "tt9458304"),
    ("Akame ga Kill!", "tt3742982"),
    ("Horimiya", "tt13103134"),
    ("Dragon Ball", "tt0088509"),
    ("Sakamoto Days", "tt17069148"),
    ("The Eminence in Shadow", "tt14115938"),
    ("Assassination Classroom", "tt3837246"),
    ("Aoashi", "tt15792808"),
)


KOREAN_DRAMA_POPULARITY_ORDER: tuple[tuple[str, str], ...] = (
    ("Doctor X: Age of the White Mafia", "tt39328047"),
    ("Squid Game", "tt10919420"),
    ("All of Us Are Dead", "tt14169960"),
    ("When Life Gives You Tangerines", "tt26471411"),
    ("Teach You a Lesson", "tt34809853"),
    ("Bloodhounds", "tt26315487"),
    ("A Love Other Than Yours", "tt43736405"),
    ("Agent Kim Reactivated", "tt42127457"),
    ("Mouse", "tt13634792"),
    ("Crash Landing on You", "tt10850932"),
    ("Weak Hero Class 1", "tt20234568"),
    ("Kingdom", "tt6611916"),
    ("Dead-End Job", "tt36458668"),
    ("Mousetrap", "tt36996011"),
    ("Extraordinary Attorney Woo", "tt20869502"),
    ("Our Sticky Love", "tt36955608"),
    ("Alchemy of Souls", "tt20859920"),
    ("A Shop for Killers", "tt26450613"),
    ("The Glory", "tt21344706"),
    ("Reply 1988", "tt5182866"),
    ("The East Palace", "tt35051401"),
    ("The Wonderfools", "tt34440854"),
    ("Doctor of Love", "tt39087958"),
    ("Sweet Home", "tt11612120"),
    ("Spooky in Love", "tt40247521"),
    ("My Name", "tt12940504"),
    ("Vincenzo", "tt13433812"),
    ("My Mister", "tt7923710"),
    ("The Scandal", "tt36347588"),
    ("My Demon", "tt29569035"),
    ("Perfect Crown", "tt39333617"),
    ("Business Proposal", "tt14819828"),
    ("Death's Game", "tt26225038"),
    ("Queen of Tears", "tt27668559"),
    ("If Wishes Could Kill", "tt36104233"),
    ("Trigger", "tt27898511"),
    ("It's Okay to Not Be Okay", "tt12451520"),
    ("Guardian: The Lonely and Great God", "tt5994364"),
    ("We Are All Trying Here", "tt36732944"),
    ("True Beauty", "tt13274038"),
    ("Twinkling Watermelon", "tt27446493"),
    ("Can This Love Be Translated?", "tt30293074"),
    ("Twenty Five Twenty One", "tt17513352"),
    ("Moving", "tt24640580"),
    ("The Penthouse: War in Life", "tt13067118"),
    ("Descendants of the Sun", "tt4925000"),
    ("Study Group", "tt35304338"),
    ("The Uncanny Counter", "tt13273826"),
    ("Lovely Runner", "tt31324295"),
    ("The Blue Road", "tt38336631"),
    ("Love Next Door", "tt30446769"),
    ("Good Boy", "tt32361930"),
    ("My Dearest", "tt26228190"),
    ("Boyfriend on Demand", "tt35848827"),
    ("Taxi Driver", "tt13759970"),
    ("Marry My Husband", "tt26628595"),
    ("Hometown Cha-Cha-Cha", "tt14518756"),
    ("Mercy for None", "tt29650530"),
    ("Mr. Sunshine", "tt7094780"),
    ("Bon Appetit, Your Majesty", "tt37600136"),
    ("The Art of Sarah", "tt35149250"),
    ("Karma", "tt29921070"),
    ("Strong Girl Bong-soon", "tt6263222"),
    ("My Royal Nemesis", "tt38828946"),
    ("A Bona Fide Killer", "tt43616775"),
    ("Happiness", "tt14979052"),
    ("Made in Korea", "tt33298903"),
    ("Signal", "tt5332206"),
    ("The Scarecrow", "tt39245629"),
    ("Mr. Plankton", "tt27539317"),
    ("The Manipulated", "tt36188448"),
    ("Gyeongseong Creature", "tt22352854"),
    ("Dear X", "tt37890201"),
    ("D.P.", "tt13024974"),
    ("Spring Fever", "tt39137681"),
    ("Light Shop", "tt31014115"),
    ("Vagabond", "tt8523042"),
    ("Stranger", "tt6461346"),
    ("Hospital Playlist", "tt11769304"),
    ("Our Blues", "tt19115260"),
    ("The Worst of Evil", "tt20600022"),
    ("Big Mouth", "tt21195490"),
    ("The 8 Show", "tt30423279"),
    ("My Dearest Nemesis", "tt33320428"),
    ("Moon Lovers: Scarlet Heart Ryeo", "tt5320412"),
    ("Genie, Make a Wish", "tt32409807"),
    ("Mr. Queen", "tt13400006"),
    ("Itaewon Class", "tt11239552"),
    ("Sold Out on You", "tt39387440"),
    ("Welcome to Samdalri", "tt26653824"),
    ("Beyond Evil", "tt13634872"),
    ("King the Land", "tt26693803"),
    ("Little Women", "tt21828868"),
    ("Parasyte: The Grey", "tt21874396"),
    ("Night Has Come", "tt29899652"),
    ("Hotel Del Luna", "tt10220588"),
    ("The Fiery Priest", "tt9674954"),
    ("In Your Radiant Season", "tt39369595"),
    ("Oh! My Guard", "tt49931644"),
    ("Hellbound", "tt12235718"),
)


MARVEL_WEB_SERIES: tuple[tuple[str, int], ...] = (
    ("WandaVision", 2021), ("The Falcon and the Winter Soldier", 2021), ("Loki", 2021),
    ("What If...?", 2021), ("Hawkeye", 2021), ("Moon Knight", 2022), ("Ms. Marvel", 2022),
    ("She-Hulk: Attorney at Law", 2022), ("Secret Invasion", 2023), ("Echo", 2024),
    ("Agatha All Along", 2024), ("Daredevil: Born Again", 2025), ("Ironheart", 2025),
    ("Eyes of Wakanda", 2025), ("Wonder Man", 2026), ("VisionQuest", 2026),
    ("Marvel Zombies", 2025), ("Your Friendly Neighborhood Spider-Man", 2025), ("X-Men '97", 2024),
    ("I Am Groot", 2022), ("Marvel Studios: Legends", 2021),
    ("Marvel's Avengers", 2018), ("Marvel Rising", 2018),
    ("Legion", 2017), ("The Gifted", 2017), ("Agents of S.H.I.E.L.D.", 2013),
    ("Agent Carter", 2015), ("Inhumans", 2017), ("Runaways", 2017), ("Cloak & Dagger", 2018),
    ("Daredevil", 2015), ("Jessica Jones", 2015), ("Luke Cage", 2016), ("Iron Fist", 2017),
    ("The Defenders", 2017), ("The Punisher", 2017), ("Helstrom", 2020), ("Blade: The Series", 2006),
    ("Mutant X", 2001), ("Avengers Assemble", 2013), ("Guardians of the Galaxy", 2015),
    ("Ultimate Spider-Man", 2012), ("Hulk and the Agents of S.M.A.S.H.", 2013),
    ("The Spectacular Spider-Man", 2008), ("Wolverine and the X-Men", 2009),
    ("X-Men: The Animated Series", 1992), ("Spider-Man: The Animated Series", 1994),
    ("Fantastic Four", 1994), ("Iron Man", 1994), ("The Incredible Hulk", 1996),
    ("Silver Surfer", 1998), ("Spider-Man Unlimited", 1999),
    ("The Avengers: Earth's Mightiest Heroes", 2010), ("Wolverine", 2011),
)
DC_WEB_SERIES: tuple[tuple[str, int], ...] = (
    ("Adventures of Superman", 1952), ("Batman", 1966), ("Shazam!", 1974), ("Wonder Woman", 1975),
    ("Superboy", 1988), ("Swamp Thing", 1990), ("The Flash", 1990), ("Lois & Clark: The New Adventures of Superman", 1993),
    ("Smallville", 2001), ("Birds of Prey", 2002), ("Human Target", 2010), ("Arrow", 2012),
    ("The Flash", 2014), ("Constantine", 2014), ("Gotham", 2014), ("Supergirl", 2015), ("iZombie", 2015),
    ("Legends of Tomorrow", 2016), ("Lucifer", 2016), ("Preacher", 2016), ("Powerless", 2017),
    ("Krypton", 2018), ("Titans", 2018), ("Black Lightning", 2018), ("Doom Patrol", 2019), ("Pennyworth", 2019),
    ("Swamp Thing", 2019), ("Watchmen", 2019), ("Batwoman", 2019), ("Stargirl", 2020),
    ("Superman & Lois", 2021), ("Sweet Tooth", 2021), ("Y: The Last Man", 2021), ("Naomi", 2022),
    ("The Sandman", 2022), ("Peacemaker", 2022), ("Gotham Knights", 2023), ("Dead Boy Detectives", 2024), ("The Penguin", 2024), ("Lanterns", 2026),
)

_MARVEL_TV_CATALOGUE_CACHE: dict[str, Any] = {"expiresAt": 0.0, "payload": None}
_DC_TV_CATALOGUE_CACHE: dict[str, Any] = {"expiresAt": 0.0, "payload": None}
def _load_persistent_tv_catalogue(cache: dict[str, Any], path: Path) -> dict[str, Any] | None:
    """Load a completed TV catalogue from persistent storage; it has no time-based expiry."""
    store = "tv_catalogue:" + path.stem
    if cache.get("payload"):
        _record_cache_event(store, "memory_hit")
        return cache["payload"]
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("results"), list)
            and payload["results"]
            # Provider enrichment was added after the original permanent cache.
            # Rebuild older cache files once so cards gain streaming-service data.
            and all(isinstance(item, dict) and isinstance(item.get("streamingProviders"), list) for item in payload["results"])
        ):
            cache.update({"expiresAt": float("inf"), "payload": payload})
            _record_cache_event(store, "persistent_hit")
            _record_cache_event(store, "persistent_rows_served", len(payload["results"]))
            logger.info("Loaded persistent TV catalogue cache %s (%d titles)", path.name, len(payload["results"]))
            return payload
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Persistent TV catalogue cache unavailable at %s: %s", path, exc)
    _record_cache_event(store, "miss")
    return None


def _save_persistent_tv_catalogue(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist TV metadata so container restarts never trigger a full TMDB scan."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        logger.info("Saved persistent TV catalogue cache %s (%d titles)", path.name, len(payload.get("results") or []))
    except OSError as exc:
        logger.warning("Could not persist TV catalogue cache %s: %s", path, exc)


async def _tv_streaming_providers(tmdb_id: int) -> list[dict[str, Any]]:
    """Resolve India streaming/rent/buy providers for one TMDB TV series."""
    if CACHE_ONLY_MODE:
        _record_cache_event("tv_streaming_availability", "cache_only_miss_blocked")
        return []
    _record_cache_event("tv_streaming_availability", "live_provider_lookup")
    try:
        payload = await _tmdb_get_json(f"tv/{tmdb_id}/watch/providers", {})
    except Exception as exc:
        logger.info("TMDB TV provider lookup failed for %s: %s", tmdb_id, exc)
        return []
    region = (payload.get("results") or {}).get("IN") or {}
    providers: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for category, kind in (
        ("flatrate", "subscription"),
        ("free", "free"),
        ("ads", "ads"),
        ("rent", "rent"),
        ("buy", "buy"),
    ):
        for item in region.get(category) or []:
            name = str(item.get("provider_name") or "").strip()
            if not name:
                continue
            try:
                provider_id = int(item.get("provider_id")) if item.get("provider_id") is not None else None
            except (TypeError, ValueError):
                provider_id = None
            identity = (provider_id, name.casefold())
            if identity in seen:
                continue
            seen.add(identity)
            logo_path = str(item.get("logo_path") or "").strip()
            providers.append({
                "providerId": provider_id,
                "name": name,
                "type": kind,
                "region": "IN",
                "logoUrl": "https://image.tmdb.org/t/p/w92" + logo_path if logo_path else "",
                "webUrl": str(region.get("link") or ""),
            })
    return providers


@router.get("/api/tv/catalogue/marvel")
async def api_tmdb_marvel_tv_catalogue(page: int = Query(1, ge=1, le=500)):
    """Return cards for the curated Marvel TV/web-series list, enriched from TMDB."""
    cached_payload = _load_persistent_tv_catalogue(_MARVEL_TV_CATALOGUE_CACHE, MARVEL_TV_CATALOGUE_CACHE_FILE)
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS) and not cached_payload:
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured.")

    semaphore = asyncio.Semaphore(3)

    async def resolve_series(title: str, year: int) -> dict[str, Any]:
        fallback = {
            "id": f"marvel-tv:{re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')}:{year}",
            "title": title,
            "year": year,
            "releaseDate": str(year),
            "overview": "",
            "posterUrl": "",
            "backdropUrl": "",
            "rating": 0.0,
            "tmdbUrl": "",
            "streamingProviders": [],
            "providerLink": "",
            "source": "Curated Marvel series list",
        }
        async with semaphore:
            try:
                payload = await _tmdb_get_json("search/tv", {
                    "query": title,
                    "first_air_date_year": year,
                    "include_adult": "false",
                    "language": "en-US",
                    "page": 1,
                })
            except HTTPException as exc:
                logger.info("TMDB Marvel TV lookup failed for %s (%s): %s", title, year, exc.detail)
                return fallback
            target = _normalize_title(title)
            candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
            candidates.sort(key=lambda row: (
                _normalize_title(str(row.get("name") or "")) == target,
                str(row.get("first_air_date") or "").startswith(str(year)),
                float(row.get("popularity") or 0),
            ), reverse=True)
            if not candidates:
                return fallback
            item = candidates[0]
            air_date = str(item.get("first_air_date") or "").strip()
            year_match = re.match(r"^(\d{4})", air_date)
            poster_path = str(item.get("poster_path") or "").strip()
            backdrop_path = str(item.get("backdrop_path") or "").strip()
            tmdb_id = int(item["id"])
            return {
                "id": tmdb_id,
                "title": title,
                "year": int(year_match.group(1)) if year_match else year,
                "releaseDate": air_date,
                "overview": str(item.get("overview") or "").strip(),
                "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
                "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
                "rating": float(item.get("vote_average") or 0),
                "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}",
                "streamingProviders": await _tv_streaming_providers(tmdb_id),
                "providerLink": "",
                "source": "TMDB",
            }

    if cached_payload:
        # Extend existing persistent catalogues additively. Never discard existing
        # entries: official Marvel titles missing from an older cache are appended.
        results = list(cached_payload.get("results") or [])
        known_titles = {_normalize_title(str(row.get("title") or "")) for row in results if isinstance(row, dict)}
        missing = [
            (title, year) for title, year in MARVEL_WEB_SERIES
            if _normalize_title(title) not in known_titles
        ]
        if missing and (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
            additions = await asyncio.gather(*(resolve_series(title, year) for title, year in missing))
            results.extend(additions)
            cached_payload = {**cached_payload, "results": results, "totalResults": len(results),
                              "provider": "TMDB + curated Marvel series list"}
            _save_persistent_tv_catalogue(MARVEL_TV_CATALOGUE_CACHE_FILE, cached_payload)
        _MARVEL_TV_CATALOGUE_CACHE.update({"expiresAt": float("inf"), "payload": cached_payload})
        return cached_payload

    results = await asyncio.gather(*(resolve_series(title, year) for title, year in MARVEL_WEB_SERIES))
    result = {
        "catalogue": "marvel-web-series",
        "page": 1,
        "totalPages": 1,
        "totalResults": len(results),
        "provider": "TMDB + curated Marvel series list",
        "results": results,
    }
    _MARVEL_TV_CATALOGUE_CACHE.update({"expiresAt": float("inf"), "payload": result})
    _save_persistent_tv_catalogue(MARVEL_TV_CATALOGUE_CACHE_FILE, result)
    return result


@router.get("/api/tv/catalogue/dc-live-action")
async def api_tmdb_dc_live_action_tv_catalogue(page: int = Query(1, ge=1, le=500)):
    """Return curated live-action DC TV series cards enriched from TMDB."""
    cached_payload = _load_persistent_tv_catalogue(_DC_TV_CATALOGUE_CACHE, DC_TV_CATALOGUE_CACHE_FILE)
    if cached_payload:
        return cached_payload
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured.")
    semaphore = asyncio.Semaphore(3)
    async def resolve_series(title: str, year: int) -> dict[str, Any]:
        fallback = {"id": f"dc-tv:{re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')}:{year}", "title": title, "year": year, "releaseDate": str(year), "overview": "", "posterUrl": "", "backdropUrl": "", "rating": 0.0, "tmdbUrl": "", "streamingProviders": [], "providerLink": "", "source": "Curated DC live-action series list"}
        async with semaphore:
            try:
                payload = await _tmdb_get_json("search/tv", {"query": title, "first_air_date_year": year, "include_adult": "false", "language": "en-US", "page": 1})
            except HTTPException as exc:
                logger.info("TMDB DC TV lookup failed for %s (%s): %s", title, year, exc.detail)
                return fallback
            target = _normalize_title(title)
            candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
            candidates.sort(key=lambda row: (_normalize_title(str(row.get("name") or "")) == target, str(row.get("first_air_date") or "").startswith(str(year)), float(row.get("popularity") or 0)), reverse=True)
            if not candidates: return fallback
            item = candidates[0]
            air_date = str(item.get("first_air_date") or "").strip()
            year_match = re.match(r"^(\d{4})", air_date)
            poster_path = str(item.get("poster_path") or "").strip()
            backdrop_path = str(item.get("backdrop_path") or "").strip()
            tmdb_id = int(item["id"])
            return {"id": tmdb_id, "title": title, "year": int(year_match.group(1)) if year_match else year, "releaseDate": air_date, "overview": str(item.get("overview") or "").strip(), "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "", "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "", "rating": float(item.get("vote_average") or 0), "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}", "streamingProviders": await _tv_streaming_providers(tmdb_id), "providerLink": "", "source": "TMDB"}
    results = await asyncio.gather(*(resolve_series(title, year) for title, year in DC_WEB_SERIES))
    result = {"catalogue": "dc-live-action-web-series", "page": 1, "totalPages": 1, "totalResults": len(results), "provider": "TMDB + curated DC live-action series list", "results": results}
    _DC_TV_CATALOGUE_CACHE.update({"expiresAt": float("inf"), "payload": result})
    _save_persistent_tv_catalogue(DC_TV_CATALOGUE_CACHE_FILE, result)
    return result


# Curated Classics TV and anime catalogues. These use NexStream/TMDB cards,
# not torrent searches.
_CLASSICS_TV_CATALOGUES: dict[str, list[tuple[str, int]]] = {
    "classics-web-series": [
        ("Breaking Bad", 2008), ("Better Call Saul", 2015), ("Arrow", 2012),
        ("The Flash", 2014), ("Marvel's Daredevil", 2015),
        ("The Queen's Gambit", 2020), ("Sherlock", 2010),
        ("How I Met Your Mother", 2005), ("The Last of Us", 2023),
        ("Peaky Blinders", 2013), ("The Big Bang Theory", 2007),
        ("Chernobyl", 2019), ("Dark", 2017), ("Succession", 2018),
        ("The Wire", 2002), ("The Office", 2005), ("Wednesday", 2022),
        ("Squid Game", 2021), ("Stranger Things", 2016),
        ("Game of Thrones", 2011), ("Severance", 2022),
        ("True Detective", 2014), ("Billions", 2016),
        ("The Studio", 2025), ("Secret Level", 2024),
        ("Love, Death & Robots", 2019), ("Two and a Half Men", 2003),
        ("Person of Interest", 2011), ("Prison Break", 2005), ("Suits", 2011),
        ("Money Heist", 2017), ("Silicon Valley", 2014),
    ],
    "classics-anime": [
        ("Death Note", 2006), ("Attack on Titan", 2013), ("Code Geass", 2006),
        ("Monster", 2004), ("Dragon Ball", 1986), ("Dragon Ball Z", 1989),
        ("Dragon Ball GT", 1996), ("Dragon Ball Z Kai", 2009), ("Super Dragon Ball Heroes", 2018), ("Dragon Ball Super", 2015),
        ("Dragon Ball Daima", 2024), ("Naruto", 2002),
        ("Naruto: Shippuden", 2007), ("Bleach", 2004), ("One Piece", 1999),
        ("One-Punch Man", 2015), ("Terror in Resonance", 2014),
        ("My Hero Academia", 2016), ("Fullmetal Alchemist: Brotherhood", 2009),
        ("Demon Slayer: Kimetsu no Yaiba", 2019), ("Vinland Saga", 2019),
        ("Cowboy Bebop", 1998), ("Jujutsu Kaisen", 2020), ("Hunter x Hunter", 2011),
        ("Hajime no Ippo", 2000), ("Chainsaw Man", 2022), ("Berserk", 1997),
        ("Parasyte: The Maxim", 2014), ("Avatar: The Last Airbender", 2005),
    ],
}
_CLASSICS_TV_CATALOGUE_CACHE: dict[str, dict[str, Any]] = {}
_CLASSICS_TV_CACHE_FILES = {
    "classics-web-series": "classics_web_series_tv_catalogue.json",
    "classics-anime": "classics_anime_tv_catalogue.json",
}


def _load_bundled_classics_tv_cache(catalogue_key: str) -> dict[str, Any] | None:
    filename = _CLASSICS_TV_CACHE_FILES.get(catalogue_key)
    if not filename:
        return None
    candidates = (
        _CACHE_SEED_DIR / filename,
        Path(str(DATA_DIR)) / filename,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("catalogue") == catalogue_key and isinstance(payload.get("results"), list):
                return payload
        except (OSError, ValueError, AttributeError):
            continue
    return None


async def _get_classics_tv_catalogue(catalogue_key: str) -> dict[str, Any]:
    titles = _CLASSICS_TV_CATALOGUES.get(catalogue_key)
    if titles is None:
        raise HTTPException(status_code=404, detail="Unknown Classics TV catalogue.")
    cached = _CLASSICS_TV_CATALOGUE_CACHE.get(catalogue_key)
    if cached is not None:
        _record_cache_event("classics_tv:" + catalogue_key, "memory_hit")
        return cached
    bundled = _load_bundled_classics_tv_cache(catalogue_key)
    if bundled is not None:
        _record_cache_event("classics_tv:" + catalogue_key, "bundled_hit")
        _CLASSICS_TV_CATALOGUE_CACHE[catalogue_key] = bundled
        return bundled
    _record_cache_event("classics_tv:" + catalogue_key, "miss")
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured.")
    semaphore = asyncio.Semaphore(3)

    async def resolve_series(title: str, year: int) -> dict[str, Any]:
        fallback = {
            "id": f"classics-tv:{re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')}:{year}",
            "title": title, "year": year, "releaseDate": str(year), "overview": "",
            "posterUrl": "", "backdropUrl": "", "rating": 0.0, "tmdbUrl": "",
            "streamingProviders": [], "providerLink": "", "source": "Curated Classics list",
        }
        async with semaphore:
            try:
                is_anime_film = title == "Akira"
                payload = await _tmdb_get_json("search/movie" if is_anime_film else "search/tv", {
                    "query": title,
                    ("year" if is_anime_film else "first_air_date_year"): year,
                    "include_adult": "false", "language": "en-US", "page": 1,
                })
            except HTTPException as exc:
                logger.info("TMDB Classics TV lookup failed for %s (%s): %s", title, year, exc.detail)
                return fallback
            target = _normalize_title(title)
            candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
            candidates.sort(key=lambda row: (
                _normalize_title(str(row.get("name") or "")) == target,
                str(row.get("first_air_date") or "").startswith(str(year)),
                float(row.get("popularity") or 0),
            ), reverse=True)
            if not candidates:
                return fallback
            item = candidates[0]
            air_date = str(item.get("first_air_date") or "").strip()
            year_match = re.match(r"^(\d{4})", air_date)
            poster_path = str(item.get("poster_path") or "").strip()
            backdrop_path = str(item.get("backdrop_path") or "").strip()
            tmdb_id = int(item["id"])
            return {
                "id": tmdb_id, "title": title,
                "year": int(year_match.group(1)) if year_match else year,
                "releaseDate": air_date, "overview": str(item.get("overview") or "").strip(),
                "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
                "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
                "rating": float(item.get("vote_average") or 0),
                "tmdbUrl": f"https://www.themoviedb.org/{'movie' if is_anime_film else 'tv'}/{tmdb_id}",
                "streamingProviders": [] if is_anime_film else await _tv_streaming_providers(tmdb_id),
                "providerLink": "", "source": "TMDB",
            }

    results = await asyncio.gather(*(resolve_series(title, year) for title, year in titles))
    results.sort(key=lambda row: (str(row.get("releaseDate") or row.get("year") or ""), str(row.get("title") or "")), reverse=True)
    result = {
        "catalogue": catalogue_key, "page": 1, "totalPages": 1,
        "totalResults": len(results), "provider": "TMDB + curated Classics list", "results": results,
    }
    _CLASSICS_TV_CATALOGUE_CACHE[catalogue_key] = result

    # Persist the resolved catalogue so the manual GitHub snapshot workflow can
    # copy it from APP_DATA_DIR and seed ephemeral deployments with a warm cache.
    filename = _CLASSICS_TV_CACHE_FILES[catalogue_key]
    cache_path = Path(str(DATA_DIR)) / filename
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary_path.replace(cache_path)
        logger.info("Persisted Classics TV catalogue cache %s (%s titles)", filename, len(results))
    except OSError as exc:
        logger.warning("Could not persist Classics TV catalogue cache %s: %s", filename, exc)

    return result


@router.get("/api/tv/catalogue/classics-web-series")
async def api_tmdb_classics_web_series_catalogue():
    return await _get_classics_tv_catalogue("classics-web-series")


@router.get("/api/tv/catalogue/classics-anime")
async def api_tmdb_classics_anime_catalogue():
    return await _get_classics_tv_catalogue("classics-anime")


def _read_regional_tv_prebuilt_page(catalogue_key: str, page: int) -> dict[str, Any] | None:
    """Read one page from the persistent TV catalogue built by scripts/build_regional_movie_cache.py."""
    try:
        if not REGIONAL_TV_PREBUILT_CACHE_FILE.exists():
            return None
        payload = json.loads(REGIONAL_TV_PREBUILT_CACHE_FILE.read_text(encoding="utf-8"))
        # The cache builder writes "version", not "schemaVersion". Accept both
        # formats so valid snapshots created by the VPS builder are actually used.
        cache_version = int(payload.get("schemaVersion") or payload.get("version") or 0)
        if cache_version < 3:
            return None
        catalogue = (payload.get("catalogues") or {}).get(catalogue_key) or {}
        # The builder marks snapshots with status/seriesCount; the API's own
        # writer uses verifiedWebSeries. Accept either valid persisted format.
        pages = catalogue.get("pages") or []
        is_verified = bool(catalogue.get("verifiedWebSeries")) or (
            catalogue.get("status") in {"ready", "partial"} and bool(pages)
        )
        if not is_verified:
            return None
        if catalogue_key.startswith("pakistani-"):
            all_rows = [
                row
                for entry in pages
                if isinstance(entry, dict)
                for row in (entry.get("results") or [])
                if isinstance(row, dict) and _is_pakistani_tv_row(row)
            ]
            start = (page - 1) * 18
            return {
                "catalogue": catalogue_key,
                "page": page,
                "totalPages": max(1, (len(all_rows) + 17) // 18),
                "totalResults": len(all_rows),
                "provider": "Persistent TMDB + verified India OTT availability",
                "results": _dedupe_regional_tv_rows(all_rows)[start:start + 18],
                "pageSize": 18,
                "prebuilt": True,
            }
        for entry in pages:
            if int(entry.get("page") or 0) == page:
                rows = [row for row in (entry.get("results") or []) if isinstance(row, dict)]
                if catalogue_key.startswith("indian-"):
                    excluded_titles = {"gangaa", "dearishq", "mastram"}
                    rows = [
                        row for row in rows
                        if re.sub(r"[^a-z0-9]+", "", str(row.get("title") or row.get("name") or "").casefold()) not in excluded_titles
                    ]
                return {
                    "catalogue": catalogue_key,
                    "page": page,
                    "totalPages": max(1, len(pages)),
                    "totalResults": int(catalogue.get("totalResults") or catalogue.get("seriesCount") or 0),
                    "provider": "Persistent TMDB + verified India OTT availability",
                    "results": _dedupe_regional_tv_rows(rows),
                    "prebuilt": True,
                }
    except Exception as exc:
        logger.warning("Could not read regional TV prebuilt cache for %s page %s: %s", catalogue_key, page, exc)
    return None


def _dedupe_regional_tv_rows(rows: Any) -> list[dict[str, Any]]:
    """Keep the first occurrence of each series across cached and live TV results."""
    if not isinstance(rows, list):
        return []
    unique: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("id") or row.get("tmdbId")
        identity = str(raw_id).strip() if raw_id is not None else ""
        title = re.sub(r"[^a-z0-9]+", " ", str(row.get("title") or row.get("name") or "").casefold()).strip()
        year = str(row.get("year") or str(row.get("releaseDate") or row.get("first_air_date") or "")[:4]).strip()
        title_identity = (title, year)
        if (identity and identity in seen_ids) or (title and title_identity in seen_titles):
            continue
        if identity:
            seen_ids.add(identity)
        if title:
            seen_titles.add(title_identity)
        unique.append(row)
    return unique


def _is_pakistani_tv_row(row: dict[str, Any]) -> bool:
    countries = row.get("originCountry") or row.get("origin_country") or []
    if not isinstance(countries, list):
        countries = [str(countries)]
    normalized_countries = {str(country).strip().upper() for country in countries}
    if normalized_countries:
        return "PK" in normalized_countries and "IN" not in normalized_countries
    return str(row.get("originalLanguage") or row.get("original_language") or "").casefold() in {"ur", "pa"}


async def _enrich_regional_tv_imdb_ratings(payload: dict[str, Any]) -> dict[str, Any]:
    # Explicitly disabled metadata backfill means cached catalogue responses must not
    # trigger fresh OMDb/MDBList lookups for missing IMDb fields.
    if not BACKFILL_MISSING_METADATA:
        return payload
    rows = payload.get("results")
    if not isinstance(rows, list):
        return payload
    semaphore = asyncio.Semaphore(4)

    async def enrich(row: Any) -> None:
        if not isinstance(row, dict):
            return
        title = str(row.get("title") or "").strip()
        try:
            year = int(row.get("year") or 0)
            tmdb_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            year = tmdb_id = 0
        if not title or tmdb_id <= 0:
            return
        async with semaphore:
            try:
                rating = await _get_imdb_rating_record(title, year, "tv", tmdb_id)
            except Exception:
                logger.warning("IMDb enrichment failed for regional TV %s (%s)", title, tmdb_id, exc_info=True)
                row["imdbRatingStatus"] = "unavailable"
                return
        row["imdbRatingStatus"] = str(rating.get("status") or "unavailable")
        for field in ("imdbRating", "imdbVotes", "imdbId", "imdbUrl"):
            if rating.get(field) is not None:
                row[field] = rating[field]

    await asyncio.gather(*(enrich(row) for row in rows))
    return payload


def _save_regional_tv_prebuilt_pages(catalogue_key: str, rows: list[dict[str, Any]]) -> None:
    """Store three 18-item pages in the persistent VPS TV catalogue."""
    try:
        REGIONAL_TV_PREBUILT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schemaVersion": 3, "catalogues": {}}
        if REGIONAL_TV_PREBUILT_CACHE_FILE.exists():
            try:
                existing = json.loads(REGIONAL_TV_PREBUILT_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    payload = existing
            except Exception:
                logger.warning("Regional TV cache unreadable; rebuilding its document")
        payload["schemaVersion"] = 3
        catalogues = payload.setdefault("catalogues", {})
        if not isinstance(catalogues, dict):
            catalogues = {}
            payload["catalogues"] = catalogues
        # Persist every discovered page, not only the first three. Page 4+
        # requires more discovery/enrichment on its first request; saving all
        # verified rows prevents repeating that expensive work on every visit.
        page_count = max(3, (len(rows) + 17) // 18)
        pages = [{"page": n + 1, "results": rows[n * 18:(n + 1) * 18]} for n in range(page_count)]
        catalogues[catalogue_key] = {
            "verifiedWebSeries": True,
            "totalResults": len(rows),
            "seriesCount": len(rows),
            "pages": pages,
        }
        temporary = REGIONAL_TV_PREBUILT_CACHE_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(REGIONAL_TV_PREBUILT_CACHE_FILE)
    except Exception as exc:
        logger.warning("Could not save regional TV catalogue %s: %s", catalogue_key, exc)


_REGIONAL_TV_PAGE_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_REGIONAL_TV_PAGE_CACHE_TTL = stored_ttl(6 * 60 * 60)
_REGIONAL_TV_DISCOVERY_CACHE = _REGIONAL_TV_PAGE_CACHE
_INDIAN_LINEAR_TV_NETWORKS = {
    "starplus", "colors", "zee tv", "zeetv", "sony entertainment television",
    "sony sab", "sab tv", "dd national", "andtv", "&tv", "star bharat",
    "sony pal", "dangal tv", "sun tv", "star utsav",
}


_PAKISTANI_DRAMA_ROWS: dict[str, dict[str, Any]] = {}


def _pakistani_drama_title_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())




async def _anime_popular_curated_page(page: int) -> dict[str, Any]:
    """Resolve one page of the supplied IMDb top-100 anime TV list against TMDB."""
    page_size = 18
    start = (page - 1) * page_size
    selected = ANIME_POPULARITY_ORDER[start:start + page_size]
    semaphore = asyncio.Semaphore(4)

    async def resolve(item: tuple[str, str]) -> dict[str, Any]:
        title, imdb_id = item
        fallback: dict[str, Any] = {
            "id": f"anime-imdb:{imdb_id}",
            "title": title,
            "year": None,
            "releaseDate": "",
            "overview": "",
            "posterUrl": "",
            "backdropUrl": "",
            "rating": 0.0,
            "tmdbUrl": "",
            "streamingProviders": [],
            "providerLink": "",
            "source": "IMDb 100 most popular anime TV shows",
            "imdbId": imdb_id,
        }
        async with semaphore:
            try:
                payload = await _tmdb_get_json("search/tv", {
                    "query": title,
                    "include_adult": "false",
                    "language": "en-US",
                    "page": 1,
                })
                candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
                normalized = _normalize_title(title)
                candidates.sort(key=lambda row: (
                    0 if _normalize_title(row.get("name") or row.get("original_name")) == normalized else 1,
                    -float(row.get("popularity") or 0),
                ))
                if not candidates:
                    return fallback
                row = candidates[0]
                release_date = str(row.get("first_air_date") or "")
                try:
                    year = int(release_date[:4]) if len(release_date) >= 4 else None
                except ValueError:
                    year = None
                tmdb_id = int(row["id"])
                poster_path = str(row.get("poster_path") or "")
                backdrop_path = str(row.get("backdrop_path") or "")
                return {
                    **fallback,
                    "id": tmdb_id,
                    "tmdbId": tmdb_id,
                    "title": str(row.get("name") or title),
                    "year": year,
                    "releaseDate": release_date,
                    "overview": str(row.get("overview") or ""),
                    "posterUrl": f"{TMDB_IMAGE_BASE}/w500{poster_path}" if poster_path else "",
                    "backdropUrl": f"{TMDB_IMAGE_BASE}/w780{backdrop_path}" if backdrop_path else "",
                    "rating": float(row.get("vote_average") or 0),
                    "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}",
                }
            except Exception as exc:
                logger.info("TMDB anime lookup failed for %s (%s): %s", title, imdb_id, exc)
                return fallback

    results = await asyncio.gather(*(resolve(item) for item in selected))
    return {
        "catalogue": "anime-popular",
        "page": page,
        "totalPages": max(1, (len(ANIME_POPULARITY_ORDER) + page_size - 1) // page_size),
        "totalResults": len(ANIME_POPULARITY_ORDER),
        "pageSize": page_size,
        "provider": "IMDb supplied top-100 anime TV chart + TMDB metadata",
        "curatedOrder": True,
        "results": results,
    }


async def _pakistani_drama_catalogue_page(catalogue_key: str, page: int) -> dict[str, Any]:
    """Resolve one page of the fixed 144-title Pakistani drama order from TMDB."""
    page_size = 18
    titles = PAKISTANI_DRAMA_POPULARITY_ORDER[(page - 1) * page_size:page * page_size]
    semaphore = asyncio.Semaphore(4)

    async def resolve(title: str) -> dict[str, Any]:
        cached = _PAKISTANI_DRAMA_ROWS.get(_pakistani_drama_title_key(title))
        if cached is not None:
            return cached
        fallback = {
            "id": "pakistani-drama:" + _pakistani_drama_title_key(title),
            "title": title, "year": 0, "releaseDate": "", "overview": "",
            "posterUrl": "", "backdropUrl": "", "rating": 0.0,
            "tmdbUrl": "", "streamingProviders": [], "providerLink": "",
            "originalLanguage": "ur", "originCountry": ["PK"],
            "source": "Curated Pakistani drama order",
        }
        async with semaphore:
            try:
                payload = await _tmdb_get_json("search/tv", {
                    "query": title, "include_adult": "false", "language": "en-US", "page": 1,
                })
                target = _pakistani_drama_title_key(title)
                candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
                candidates.sort(key=lambda row: (
                    _pakistani_drama_title_key(row.get("name") or row.get("original_name")) == target,
                    "PK" in (row.get("origin_country") or []) and "IN" not in (row.get("origin_country") or []),
                    float(row.get("popularity") or 0),
                ), reverse=True)
                item = next((row for row in candidates if _pakistani_drama_title_key(row.get("name") or row.get("original_name")) == target and "PK" in (row.get("origin_country") or []) and "IN" not in (row.get("origin_country") or [])), None)
                if item is None:
                    # Verify candidates whose search result omits origin_country, while still
                    # refusing an Indian or cross-border title when canonical details disagree.
                    for candidate in candidates:
                        if _pakistani_drama_title_key(candidate.get("name") or candidate.get("original_name")) != target:
                            continue
                        details = await _tmdb_get_json(f"tv/{int(candidate['id'])}", {})
                        countries = details.get("origin_country") or []
                        if "PK" in countries and "IN" not in countries:
                            item = {**candidate, **details}
                            break
                if item is not None:
                    air_date = str(item.get("first_air_date") or "").strip()
                    year_match = re.match(r"^(\\d{4})", air_date)
                    tmdb_id = int(item["id"])
                    poster_path = str(item.get("poster_path") or "").strip()
                    backdrop_path = str(item.get("backdrop_path") or "").strip()
                    fallback.update({
                        "id": tmdb_id, "title": title,
                        "year": int(year_match.group(1)) if year_match else 0,
                        "releaseDate": air_date,
                        "overview": str(item.get("overview") or "").strip(),
                        "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
                        "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
                        "rating": float(item.get("vote_average") or 0),
                        "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}",
                        "streamingProviders": await _tv_streaming_providers(tmdb_id),
                        "originalLanguage": str(item.get("original_language") or "ur"),
                        "originCountry": item.get("origin_country") or ["PK"],
                        "source": "TMDB + curated Pakistani drama order",
                    })
            except Exception as exc:
                logger.info("Pakistani drama lookup failed for %s: %s", title, type(exc).__name__)
        _PAKISTANI_DRAMA_ROWS[_pakistani_drama_title_key(title)] = fallback
        return fallback

    rows = await asyncio.gather(*(resolve(title) for title in titles))
    # Never expose synthetic fallback IDs: the player requires a real TMDB TV ID.
    # Also omit entries without a poster so this curated catalogue contains usable cards.
    playable_rows = [
        row for row in rows
        if isinstance(row.get("id"), int)
        and int(row["id"]) > 0
        and bool(str(row.get("posterUrl") or "").strip())
    ]
    return {
        "catalogue": catalogue_key, "page": page,
        "totalPages": max(1, (len(PAKISTANI_DRAMA_POPULARITY_ORDER) + page_size - 1) // page_size),
        "totalResults": len(PAKISTANI_DRAMA_POPULARITY_ORDER),
        "provider": "TMDB + fixed Pakistani drama popularity order (playable entries only)",
        "results": playable_rows, "pageSize": page_size, "curatedOrder": True,
    }


async def _korean_popular_curated_page(page: int) -> dict[str, Any]:
    """Resolve one page of the supplied IMDb top-100 Korean drama TV list against TMDB."""
    page_size = 18
    start = (page - 1) * page_size
    selected = KOREAN_DRAMA_POPULARITY_ORDER[start:start + page_size]
    semaphore = asyncio.Semaphore(4)

    async def resolve(item: tuple[str, str]) -> dict[str, Any]:
        title, imdb_id = item
        fallback: dict[str, Any] = {
            "id": f"korean-imdb:{imdb_id}",
            "title": title,
            "year": None,
            "releaseDate": "",
            "overview": "",
            "posterUrl": "",
            "backdropUrl": "",
            "rating": 0.0,
            "tmdbUrl": "",
            "streamingProviders": [],
            "providerLink": "",
            "source": "IMDb 100 most popular Korean drama TV shows",
            "imdbId": imdb_id,
        }
        async with semaphore:
            try:
                payload = await _tmdb_get_json("search/tv", {
                    "query": title,
                    "include_adult": "false",
                    "language": "en-US",
                    "page": 1,
                })
                candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
                normalized = _normalize_title(title)
                candidates.sort(key=lambda row: (
                    0 if _normalize_title(row.get("name") or row.get("original_name")) == normalized else 1,
                    -float(row.get("popularity") or 0),
                ))
                if not candidates:
                    return fallback
                row = candidates[0]
                release_date = str(row.get("first_air_date") or "")
                try:
                    year = int(release_date[:4]) if len(release_date) >= 4 else None
                except ValueError:
                    year = None
                tmdb_id = int(row["id"])
                poster_path = str(row.get("poster_path") or "")
                backdrop_path = str(row.get("backdrop_path") or "")
                return {
                    **fallback,
                    "id": tmdb_id,
                    "tmdbId": tmdb_id,
                    "title": str(row.get("name") or title),
                    "year": year,
                    "releaseDate": release_date,
                    "overview": str(row.get("overview") or ""),
                    "posterUrl": f"{TMDB_IMAGE_BASE}/w500{poster_path}" if poster_path else "",
                    "backdropUrl": f"{TMDB_IMAGE_BASE}/w780{backdrop_path}" if backdrop_path else "",
                    "rating": float(row.get("vote_average") or 0),
                    "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}",
                }
            except Exception as exc:
                logger.info("TMDB anime lookup failed for %s (%s): %s", title, imdb_id, exc)
                return fallback

    results = await asyncio.gather(*(resolve(item) for item in selected))
    return {
        "catalogue": "korean-popular",
        "page": page,
        "totalPages": max(1, (len(KOREAN_DRAMA_POPULARITY_ORDER) + page_size - 1) // page_size),
        "totalResults": len(KOREAN_DRAMA_POPULARITY_ORDER),
        "pageSize": page_size,
        "provider": "IMDb supplied top-100 Korean drama TV chart + TMDB metadata",
        "curatedOrder": True,
        "results": results,
    }


async def _pakistani_drama_catalogue_page(catalogue_key: str, page: int) -> dict[str, Any]:
    """Resolve one page of the fixed 144-title Pakistani drama order from TMDB."""
    page_size = 18
    titles = PAKISTANI_DRAMA_POPULARITY_ORDER[(page - 1) * page_size:page * page_size]
    semaphore = asyncio.Semaphore(4)

    async def resolve(title: str) -> dict[str, Any]:
        cached = _PAKISTANI_DRAMA_ROWS.get(_pakistani_drama_title_key(title))
        if cached is not None:
            return cached
        fallback = {
            "id": "pakistani-drama:" + _pakistani_drama_title_key(title),
            "title": title, "year": 0, "releaseDate": "", "overview": "",
            "posterUrl": "", "backdropUrl": "", "rating": 0.0,
            "tmdbUrl": "", "streamingProviders": [], "providerLink": "",
            "originalLanguage": "ur", "originCountry": ["PK"],
            "source": "Curated Pakistani drama order",
        }
        async with semaphore:
            try:
                payload = await _tmdb_get_json("search/tv", {
                    "query": title, "include_adult": "false", "language": "en-US", "page": 1,
                })
                target = _pakistani_drama_title_key(title)
                candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
                candidates.sort(key=lambda row: (
                    _pakistani_drama_title_key(row.get("name") or row.get("original_name")) == target,
                    "PK" in (row.get("origin_country") or []) and "IN" not in (row.get("origin_country") or []),
                    float(row.get("popularity") or 0),
                ), reverse=True)
                item = next((row for row in candidates if _pakistani_drama_title_key(row.get("name") or row.get("original_name")) == target and "PK" in (row.get("origin_country") or []) and "IN" not in (row.get("origin_country") or [])), None)
                if item is None:
                    # Verify candidates whose search result omits origin_country, while still
                    # refusing an Indian or cross-border title when canonical details disagree.
                    for candidate in candidates:
                        if _pakistani_drama_title_key(candidate.get("name") or candidate.get("original_name")) != target:
                            continue
                        details = await _tmdb_get_json(f"tv/{int(candidate['id'])}", {})
                        countries = details.get("origin_country") or []
                        if "PK" in countries and "IN" not in countries:
                            item = {**candidate, **details}
                            break
                if item is not None:
                    air_date = str(item.get("first_air_date") or "").strip()
                    year_match = re.match(r"^(\\d{4})", air_date)
                    tmdb_id = int(item["id"])
                    poster_path = str(item.get("poster_path") or "").strip()
                    backdrop_path = str(item.get("backdrop_path") or "").strip()
                    fallback.update({
                        "id": tmdb_id, "title": title,
                        "year": int(year_match.group(1)) if year_match else 0,
                        "releaseDate": air_date,
                        "overview": str(item.get("overview") or "").strip(),
                        "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
                        "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
                        "rating": float(item.get("vote_average") or 0),
                        "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}",
                        "streamingProviders": await _tv_streaming_providers(tmdb_id),
                        "originalLanguage": str(item.get("original_language") or "ur"),
                        "originCountry": item.get("origin_country") or ["PK"],
                        "source": "TMDB + curated Pakistani drama order",
                    })
            except Exception as exc:
                logger.info("Pakistani drama lookup failed for %s: %s", title, type(exc).__name__)
        _PAKISTANI_DRAMA_ROWS[_pakistani_drama_title_key(title)] = fallback
        return fallback

    rows = await asyncio.gather(*(resolve(title) for title in titles))
    return {
        "catalogue": catalogue_key, "page": page, "totalPages": max(1, (len(PAKISTANI_DRAMA_POPULARITY_ORDER) + page_size - 1) // page_size),
        "totalResults": len(PAKISTANI_DRAMA_POPULARITY_ORDER),
        "provider": "TMDB + fixed Pakistani drama popularity order",
        "results": rows, "pageSize": page_size, "curatedOrder": True,
    }


@router.get("/api/tv/catalogue/{catalogue_key}")
async def api_tmdb_regional_tv_catalogue(
    catalogue_key: str,
    page: int = Query(1, ge=1, le=500),
    refresh: bool = False,
):
    """Return Hindi Indian OTT web-series, excluding non-Hindi and non-scripted TV formats."""
    configs = {
        "indian-popular": ("IN", "hi", "popularity.desc"),
        "indian-trending": ("IN", "hi", "popularity.desc"),
        "indian-latest": ("IN", "hi", "first_air_date.desc"),
        "hollywood-popular": ("US", "en", "popularity.desc"),
        "hollywood-trending": ("US", "en", "popularity.desc"),
        "hollywood-latest": ("US", "en", "first_air_date.desc"),
        "korean-popular": ("KR", "ko", "popularity.desc"),
        "korean-trending": ("KR", "ko", "popularity.desc"),
        "korean-latest": ("KR", "ko", "first_air_date.desc"),
        "pakistani-popular": ("PK", "ur", "popularity.desc"),
        "pakistani-trending": ("PK", "ur", "popularity.desc"),
        "pakistani-latest": ("PK", "ur", "first_air_date.desc"),
        "anime-popular": ("JP", "ja", "popularity.desc"),
        "anime-trending": ("JP", "ja", "popularity.desc"),
        "anime-latest": ("JP", "ja", "first_air_date.desc"),
    }
    if catalogue_key not in configs:
        raise HTTPException(status_code=404, detail="Unknown TV catalogue.")
    if catalogue_key.startswith("pakistani-"):
        payload = await _pakistani_drama_catalogue_page(catalogue_key, page)
        return await _enrich_regional_tv_imdb_ratings(payload)
    if catalogue_key == "anime-popular":
        return await _anime_popular_curated_page(page)
    if catalogue_key == "korean-popular":
        return await _korean_popular_curated_page(page)
    # Indian Popular and Trending exclude scripted series whose TMDB network
    # metadata identifies Zee TV, Star Plus, Colors, or Sony TV as a broadcaster.
    exclude_indian_broadcast_networks = catalogue_key in {"indian-popular", "indian-trending"}
    excluded_network_names = {
        "zee tv", "zeetv", "star plus", "starplus", "colors", "colorstv",
        "sony tv", "sony entertainment television", "sony entertainment tv",
        "set india", "sony sab",
    }
    # TMDB's genre 10766 is Soap. TMDB genre tagging is not complete for every
    # Indian serial, so retain a small, exact-title safety list for known soaps.
    # Keep names normalized and exact-match only to avoid excluding unrelated titles.
    known_indian_soap_titles = {
        "agniphera", "bhabiji ghar par hain", "devon ke dev mahadev",
        "jiji maa", "radha krishn", "sirf tum", "pushpa impossible",
        "yeh rishta kya kehlata hai", "kundali bhagya", "kumkum bhagya",
        "anupamaa", "ghum hai kisikey pyaar mein", "imli", "udne ki aasha",
        "taarak mehta ka ooltah chashmah", "sasural simar ka", "saath nibhaana saathiya",
        "diya aur baati hum", "yeh hai mohabbatein", "kasautii zindagii kay",
        "naagin", "ishqbaaaz", "shakti astitva ke ehsaas ki", "choti sarrdaarni",
        "molkki", "pinjara khubsurti ka", "mere angne mein", "swaragini",
        "balika vadhu", "uttaran", "pavitra rishta", "kumkum",
    }

    def _normalized_tv_title(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()

    def has_soap_genre(genres: Any) -> bool:
        return isinstance(genres, list) and any(
            isinstance(genre, dict) and str(genre.get("id") or "").strip() == "10766"
            for genre in genres
        )

    def is_known_indian_soap(*titles: Any) -> bool:
        return any(_normalized_tv_title(title) in known_indian_soap_titles for title in titles if title)

    def has_excluded_broadcast_network(networks: Any) -> bool:
        if not isinstance(networks, list):
            return False
        for network in networks:
            if not isinstance(network, dict):
                continue
            name = re.sub(r"[^a-z0-9]+", " ", str(network.get("name") or "").casefold()).strip()
            compact = name.replace(" ", "")
            if name in excluded_network_names or compact in {n.replace(" ", "") for n in excluded_network_names}:
                return True
        return False

    async def filter_cached_networks(result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return result
        if catalogue_key.startswith("korean-"):
            # Older persistent caches can predate the current eligibility rules.
            # Re-check Korean rows against canonical TMDB metadata and confirmed
            # India subscription/free/ad availability before showing them.
            rows = result.get("results")
            if not isinstance(rows, list):
                return result
            today_date = datetime.now(timezone.utc).date()
            verified: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    tmdb_id = int(row.get("id") or row.get("tmdbId") or 0)
                    if tmdb_id <= 0:
                        continue
                    details = await _tmdb_get_json(f"tv/{tmdb_id}", {})
                    air_date = str(details.get("first_air_date") or row.get("releaseDate") or "").strip()
                    parsed_date = datetime.strptime(air_date[:10], "%Y-%m-%d").date()
                    if parsed_date < datetime(2015, 1, 1).date() or parsed_date > today_date:
                        continue
                    if "KR" not in (details.get("origin_country") or row.get("originCountry") or []):
                        continue
                    if str(details.get("original_language") or row.get("originalLanguage") or "").casefold() != "ko":
                        continue
                    if str(details.get("type") or row.get("seriesType") or "").casefold() not in {"scripted", "miniseries"}:
                        continue
                    genres = details.get("genres") if isinstance(details.get("genres"), list) else row.get("genres") or []
                    if has_soap_genre(genres):
                        continue
                    providers = await _tv_streaming_providers(tmdb_id)
                    providers = [
                        provider for provider in providers
                        if str(provider.get("type") or "").casefold() in {"subscription", "free", "ads"}
                    ]
                    if not providers:
                        continue
                    verified.append({
                        **row,
                        "id": tmdb_id,
                        "title": str(details.get("name") or row.get("title") or row.get("name") or "").strip(),
                        "year": parsed_date.year,
                        "releaseDate": air_date,
                        "streamingProviders": providers,
                        "originalLanguage": "ko",
                        "originCountry": ["KR"],
                        "seriesType": str(details.get("type") or row.get("seriesType") or "").casefold(),
                        "genres": genres,
                    })
                except Exception as exc:
                    logger.info("Skipping cached Korean TV item %s because eligibility could not be verified: %s", row.get("id"), type(exc).__name__)
            updated = dict(result)
            updated["results"] = _dedupe_regional_tv_rows(verified)[:18]
            updated["totalResults"] = len(updated["results"])
            updated["pageSize"] = 18
            return updated
        if not exclude_indian_broadcast_networks:
            rows = result.get("results")
            if isinstance(rows, list):
                filtered_by_year = []
                for row in rows:
                    try:
                        air_date = str(row.get("releaseDate") or row.get("first_air_date") or "").strip()
                        if air_date and datetime.strptime(air_date[:10], "%Y-%m-%d").date() >= datetime(2015, 1, 1).date():
                            filtered_by_year.append(row)
                    except (TypeError, ValueError):
                        continue
                updated = dict(result)
                updated["results"] = _dedupe_regional_tv_rows([
                    row for row in filtered_by_year
                    if not catalogue_key.startswith("pakistani-") or (
                        isinstance(row, dict) and _is_pakistani_tv_row(row)
                    )
                ])[:18]
                updated["totalResults"] = len(updated["results"])
                updated["pageSize"] = 18
                return updated
            return result
        rows = result.get("results")
        if not isinstance(rows, list):
            return result
        filtered = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                tmdb_id = int(row.get("id") or 0)
                if not tmdb_id:
                    continue
                # Always resolve canonical metadata for cached entries. Old cache
                # rows predate the soap filter and cannot be trusted on their own.
                details = await _tmdb_get_json(f"tv/{tmdb_id}", {})
                networks = details.get("networks") if isinstance(details.get("networks"), list) else []
                genres = details.get("genres") if isinstance(details.get("genres"), list) else []
                titles = (details.get("name"), details.get("original_name"), row.get("title"), row.get("name"))
                series_type = str(details.get("type") or row.get("seriesType") or "").casefold()
                if series_type not in {"scripted", "miniseries"}:
                    continue
                air_date = str(details.get("first_air_date") or row.get("releaseDate") or row.get("first_air_date") or "").strip()
                try:
                    if not air_date or datetime.strptime(air_date[:10], "%Y-%m-%d").date() < datetime(2015, 1, 1).date():
                        continue
                except ValueError:
                    continue
                if has_soap_genre(genres) or is_known_indian_soap(*titles):
                    continue
                # Fail closed when network metadata is missing: this catalogue
                # must not leak linear-TV entries merely because metadata is absent.
                if not networks or has_excluded_broadcast_network(networks):
                    continue
                row = dict(row)
                row["networks"] = networks
                row["genres"] = genres
                row["seriesType"] = series_type
            except Exception as exc:
                logger.info("Skipping cached TV item %s because its metadata could not be verified: %s", row.get("id"), type(exc).__name__)
                continue
            filtered.append(row)
        result = dict(result)
        result["results"] = [
            row for row in filtered
            if not catalogue_key.startswith("pakistani-") or _is_pakistani_tv_row(row)
        ]
        result["totalResults"] = len(filtered)
        return result

    # Use only pages explicitly marked as verified by this endpoint.
    prebuilt = None if refresh else _read_regional_tv_prebuilt_page(catalogue_key, page)
    if prebuilt is not None:
        _record_cache_event("regional_tv_catalogue", "prebuilt_hit")
        if catalogue_key.startswith("korean-"):
            prebuilt = await filter_cached_networks(prebuilt)
        return await _enrich_regional_tv_imdb_ratings(prebuilt)
    _record_cache_event("regional_tv_catalogue", "prebuilt_miss")

    country, language, sort_by = configs[catalogue_key]
    cache_key = (catalogue_key, page)
    cached = _REGIONAL_TV_DISCOVERY_CACHE.get(cache_key)
    cache_ttl = stored_ttl(900 if catalogue_key.endswith("-trending") else 21600)
    if not refresh and cached and time.monotonic() - cached[0] < cache_ttl and not exclude_indian_broadcast_networks:
        _record_cache_event("regional_tv_catalogue", "memory_hit")
        return await _enrich_regional_tv_imdb_ratings(await filter_cached_networks(cached[1]))
    _record_cache_event("regional_tv_catalogue", "discovery_miss")
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured.")

    today = datetime.now(timezone.utc).date().isoformat()
    try:
        # Build UI pages from the filtered result set, not raw TMDB pages.
        # Continue fetching source pages until this page has 18 eligible series
        # (or TMDB runs out), so strict Indian web-series filters don't leave gaps.
        source_page = 1
        source_total_pages = 1
        eligible_rows: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        # Build enough verified rows to fill the requested page, then persist
        # every verified row so later visits to deeper pages can use disk cache.
        required_count = max(54, page * 18)

        while source_page <= source_total_pages and len(eligible_rows) < required_count:
            if catalogue_key.endswith("-trending"):
                # Popular is popularity-ranked Discover; Trending must use TMDB's
                # independent weekly trend ranking or it duplicates Popular.
                payload = await _tmdb_get_json("trending/tv/week", {
                    "language": "en-US",
                    "include_adult": "false",
                    "page": source_page,
                })
            else:
                payload = await _tmdb_get_json("discover/tv", {
                    "include_adult": "false",
                    "language": "en-US",
                    "sort_by": sort_by,
                    "with_origin_country": country,
                    **({} if catalogue_key.startswith("pakistani-") else {"with_original_language": language}),
                    "with_type": "2|4",
                    **({"with_genres": "16"} if catalogue_key.startswith("anime-") else {}),
                    "watch_region": "IN",
                    "with_watch_monetization_types": "flatrate|free|ads",
                    "first_air_date.gte": "2015-01-01",
                    "first_air_date.lte": today,
                    "page": source_page,
                })
            source_total_pages = max(1, min(int(payload.get("total_pages") or 1), 500))

            # Resolve independent series concurrently. The old sequential loop
            # made page 4+ wait for two remote requests per candidate in series.
            tv_lookup_semaphore = asyncio.Semaphore(8)

            async def verify_tv_item(item: Any) -> dict[str, Any] | None:
                if not isinstance(item, dict) or not item.get("id"):
                    return None
                try:
                    tmdb_id = int(item["id"])
                except (TypeError, ValueError):
                    return None
                origins = item.get("origin_country") or []
                original_language = str(item.get("original_language") or "").casefold()
                matches_language = (
                    original_language in {"ur", "pa", "en"}
                    if catalogue_key.startswith("pakistani-")
                    else original_language == language
                )
                if country not in origins or not matches_language:
                    return None
                air_date = str(item.get("first_air_date") or "").strip()
                try:
                    parsed_air_date = datetime.strptime(air_date[:10], "%Y-%m-%d").date()
                    if parsed_air_date < datetime(2015, 1, 1).date() or parsed_air_date > datetime.now(timezone.utc).date():
                        return None
                except ValueError:
                    return None

                async with tv_lookup_semaphore:
                    try:
                        details = await _tmdb_get_json(f"tv/{tmdb_id}", {})
                    except Exception as exc:
                        logger.info("Skipping TV item %s because series type could not be verified: %s", tmdb_id, type(exc).__name__)
                        return None
                    series_type = str(details.get("type") or item.get("type") or "").casefold()
                    if series_type not in {"scripted", "miniseries"}:
                        return None

                    networks = details.get("networks") if isinstance(details.get("networks"), list) else []
                    genres = details.get("genres") if isinstance(details.get("genres"), list) else []
                    if catalogue_key.startswith("anime-") and not any(
                        isinstance(genre, dict) and int(genre.get("id") or 0) == 16 for genre in genres
                    ):
                        return None
                    title_candidates = (details.get("name"), details.get("original_name"), item.get("name"), item.get("original_name"))
                    title_keys = {
                        re.sub(r"[^a-z0-9]+", "", str(title or "").casefold())
                        for title in title_candidates
                    }
                    if catalogue_key.startswith("indian-") and title_keys.intersection({"gangaa", "dearishq", "mastram"}):
                        return None
                    if exclude_indian_broadcast_networks:
                        if has_soap_genre(genres) or is_known_indian_soap(*title_candidates):
                            return None
                        if not networks or has_excluded_broadcast_network(networks):
                            return None

                    try:
                        providers = await _tv_streaming_providers(tmdb_id)
                    except Exception as exc:
                        logger.info("Skipping TV item %s because OTT availability could not be verified: %s", tmdb_id, type(exc).__name__)
                        return None
                    providers = [
                        provider for provider in providers
                        if str(provider.get("type") or "").casefold() in {"subscription", "free", "ads"}
                    ]
                    if not providers:
                        return None

                poster = str(item.get("poster_path") or details.get("poster_path") or "").strip()
                backdrop = str(item.get("backdrop_path") or details.get("backdrop_path") or "").strip()
                year_match = re.match(r"^(\d{4})", air_date)
                return {
                    "id": tmdb_id,
                    "title": str(item.get("name") or details.get("name") or "").strip(),
                    "year": int(year_match.group(1)) if year_match else None,
                    "releaseDate": air_date,
                    "overview": str(item.get("overview") or details.get("overview") or "").strip(),
                    "posterUrl": TMDB_IMAGE_BASE + poster if poster else "",
                    "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop if backdrop else "",
                    "rating": float(item.get("vote_average") or details.get("vote_average") or 0),
                    "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}",
                    "streamingProviders": providers,
                    "providerLink": "",
                    "source": "TMDB",
                    "originalLanguage": original_language,
                    "originCountry": origins,
                    "seriesType": series_type,
                    "networks": networks,
                    "genres": genres,
                }

            verified_rows = await asyncio.gather(
                *(verify_tv_item(item) for item in payload.get("results", [])),
                return_exceptions=True,
            )
            for row in verified_rows:
                if isinstance(row, dict):
                    eligible_rows.append(row)
            eligible_rows = _dedupe_regional_tv_rows(eligible_rows)
            seen_ids = {int(row["id"]) for row in eligible_rows if str(row.get("id") or "").isdigit()}
            source_page += 1
    except HTTPException:
        raise

    _save_regional_tv_prebuilt_pages(catalogue_key, eligible_rows)
    start_index = (page - 1) * 18
    eligible_rows = _dedupe_regional_tv_rows(eligible_rows)
    results = eligible_rows[start_index:start_index + 18]
    # UI pages are 18 filtered titles each. Estimate the number of pages from
    # TMDB's candidate count; the last page may be shorter after verification.
    total_eligible_pages = max(1, (int(payload.get("total_results") or len(eligible_rows)) + 17) // 18)
    result = {
        "catalogue": catalogue_key, "page": page,
        "totalPages": total_eligible_pages,
        "totalResults": len(eligible_rows),
        "pageSize": 18,
        "provider": "TMDB + verified India OTT availability",
        "results": results,
    }
    _REGIONAL_TV_DISCOVERY_CACHE[cache_key] = (time.monotonic(), result)
    return await _enrich_regional_tv_imdb_ratings(result)
