"""The world calendar and the ONE value type for game time.

Concept (plan-game-calendar.md §1/§2): the game clock does not deal in real
dates. A world runs on a calendar of **seasons and days** — no months, no
timezones, no leap years, no real-world dates at all. The value is a plain
count of whole GAME seconds since the world epoch (Year 1, Day 1, 00:00:00);
everything else (year, season, day, hour, weekday, sunrise) is *derived* from
that count plus the world's :class:`Calendar`.

Three types live here:

* :class:`Calendar` — the per-world definition (seasons, their lengths,
  sunrise/sunset and atmosphere, optional weekday names, the year label, the
  day buckets). Loaded from config via :func:`get_calendar` and cached. The
  world's temperature and weather are a property of the SEASON, not of the
  world — see :meth:`GameTime.atmosphere`.
* :class:`GameTime` — a point in world time. Immutable, ordered, and
  serialised as the canonical string ``Y0003-D047T14:23:45`` (4-digit year,
  3-digit day-of-year, 24 h time). Lexicographic order of that string equals
  chronological order, so persisted stamps stay comparable in SQL.
* :class:`GameDuration` — a span of world time. Replaces ``timedelta`` for
  everything the game world measures.

SYSTEM time stays ``datetime`` (``app.core.timeutils.utc_now``) — that border
is the whole point: ``datetime`` = technical stamps, ``GameTime`` = the world.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, NamedTuple, Optional, Tuple

# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

DAY_HOURS = 24
DAY_SECONDS = 24 * 60 * 60

_DEFAULT_SUNRISE_MIN = 6 * 60    # 06:00
_DEFAULT_SUNSET_MIN = 18 * 60    # 18:00
_DEFAULT_YEAR_LABEL = "Year {n}"
_DEFAULT_NOON_HOUR = 12
_DEFAULT_EVENING_HOUR = 17

_HHMM_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_CANONICAL_RE = re.compile(r"^Y(\d{4,})-D(\d{3,})T(\d{2}):(\d{2}):(\d{2})$")

# The world's atmosphere is a property of the SEASON, not of the world: a
# season carries the temperature level and the weather the world sees while it
# lasts, plus a free-text note the LLM gets verbatim. These are soft hints for
# the prompt (variable ``game_weather``), never compliance logic.
TEMPERATURE_LEVELS = ("freezing", "cold", "mild", "hot")
WEATHER_KINDS = ("dry", "rain", "snow")

_DEFAULT_TEMPERATURE = "mild"
_DEFAULT_WEATHER = "dry"

# key, display name, temperature, weather
_DEFAULT_SEASONS = (
    ("spring", "Spring", "mild", "rain"),
    ("summer", "Summer", "hot", "dry"),
    ("autumn", "Autumn", "cold", "rain"),
    ("winter", "Winter", "freezing", "snow"),
)


def _to_int(value: Any, fallback: int) -> int:
    """Best-effort int conversion — anything unusable falls back."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return fallback
    return fallback


def _parse_hhmm(value: Any, fallback_min: int) -> int:
    """Parse ``"HH:MM"`` into minutes of day; anything invalid → fallback."""
    if isinstance(value, str):
        m = _HHMM_RE.match(value)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
            if 0 <= hour < DAY_HOURS and 0 <= minute < 60:
                return hour * 60 + minute
    return fallback_min


def _format_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _pick_level(value: Any, allowed: Tuple[str, ...], fallback: str) -> str:
    """Normalize a configured atmosphere level; anything unknown → fallback."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in allowed:
            return v
    return fallback


@dataclass(frozen=True)
class Season:
    """One season of the world calendar.

    ``names`` holds localized display names collected from ``name_<lang>``
    config fields (the ``localized()`` convention); ``key`` is the stable id
    that rules, schedules and cron expressions reference.

    ``temperature``/``weather``/``weather_note`` are the season's ATMOSPHERE —
    what the world feels like while this season lasts. They are soft LLM hints
    with no code effect; the note is free text and reaches the prompt verbatim.
    """

    key: str
    name: str
    days: int
    sunrise_min: int = _DEFAULT_SUNRISE_MIN
    sunset_min: int = _DEFAULT_SUNSET_MIN
    names: Dict[str, str] = field(default_factory=dict)
    temperature: str = _DEFAULT_TEMPERATURE
    weather: str = _DEFAULT_WEATHER
    weather_note: str = ""

    def name_for(self, lang: str = "en") -> str:
        """Localized season name, falling back to the base ``name``."""
        if lang and lang != "en":
            localized = (self.names or {}).get(lang)
            if localized:
                return localized
        return self.name

    @property
    def sunrise(self) -> str:
        return _format_hhmm(self.sunrise_min)

    @property
    def sunset(self) -> str:
        return _format_hhmm(self.sunset_min)

    def atmosphere_label(self, lang: str = "en") -> str:
        """``"freezing, snow — often fog in the morning"``.

        The two levels are translatable UI/prompt words; the note is user text
        and stays raw.
        """
        from app.core.i18n import t
        head = f"{t(self.temperature, lang)}, {t(self.weather, lang)}"
        note = (self.weather_note or "").strip()
        return f"{head} — {note}" if note else head

    def atmosphere(self, lang: str = "en") -> dict:
        """The season's atmosphere as the payload dict every surface uses."""
        return {
            "season": self.key,
            "temperature": self.temperature,
            "weather": self.weather,
            "note": (self.weather_note or "").strip(),
            "label": self.atmosphere_label(lang),
        }

    def to_config(self) -> dict:
        """The season as one ``game_seasons`` config item (schema field names)."""
        return {
            "key": self.key,
            "name": self.name,
            "days": self.days,
            "sunrise": self.sunrise,
            "sunset": self.sunset,
            "temperature": self.temperature,
            "weather": self.weather,
            "weather_note": self.weather_note,
        }


@dataclass(frozen=True)
class Calendar:
    """A world's calendar definition — seasons, weeks, labels, day buckets."""

    seasons: Tuple[Season, ...]
    week_days: Tuple[str, ...] = ()
    year_label: str = _DEFAULT_YEAR_LABEL
    noon_hour: int = _DEFAULT_NOON_HOUR
    evening_hour: int = _DEFAULT_EVENING_HOUR

    DAY_HOURS: ClassVar[int] = DAY_HOURS
    DAY_SECONDS: ClassVar[int] = DAY_SECONDS

    @property
    def year_days(self) -> int:
        """Days in one year — the sum of all season lengths."""
        return sum(s.days for s in self.seasons)

    @property
    def season_starts(self) -> Tuple[int, ...]:
        """0-based day offset each season starts at (cumulative lengths)."""
        starts: List[int] = []
        acc = 0
        for s in self.seasons:
            starts.append(acc)
            acc += s.days
        return tuple(starts)

    def season_by_key(self, key: str) -> Optional[Season]:
        for s in self.seasons:
            if s.key == key:
                return s
        return None

    def season_index_for_day(self, day_of_year_0based: int) -> int:
        """Index of the season the given 0-based day of the year falls into.

        Days outside the year wrap (modulo ``year_days``) so callers never
        have to guard the boundary themselves.
        """
        total = self.year_days
        if total <= 0:
            return 0
        day = day_of_year_0based % total
        idx = 0
        for i, start in enumerate(self.season_starts):
            if day >= start:
                idx = i
            else:
                break
        return idx

    # -- construction -------------------------------------------------------

    @classmethod
    def default(cls) -> "Calendar":
        """The shipped default: 4 seasons × 30 days, 06:00/18:00, no weeks.

        Each season also ships an atmosphere (spring mild/rain, summer hot/dry,
        autumn cold/rain, winter freezing/snow) so a fresh world has a visible,
        editable starting point instead of an empty list.
        """
        return cls(
            seasons=tuple(
                Season(key=key, name=name, days=30,
                       sunrise_min=_DEFAULT_SUNRISE_MIN,
                       sunset_min=_DEFAULT_SUNSET_MIN,
                       temperature=temperature, weather=weather)
                for key, name, temperature, weather in _DEFAULT_SEASONS
            ),
            week_days=(),
            year_label=_DEFAULT_YEAR_LABEL,
            noon_hour=_DEFAULT_NOON_HOUR,
            evening_hour=_DEFAULT_EVENING_HOUR,
        )

    @classmethod
    def from_config(cls, cfg_calendar: Any, cfg_seasons: Any) -> "Calendar":
        """Build a calendar from the two config sections — tolerant by design.

        A broken calendar must never take the server down: every unusable
        value falls back to its default (garbage weekday list → no weeks,
        invalid ``HH:MM`` → 06:00/18:00, ``days`` < 1 → 1, unknown temperature
        or weather level → ``mild``/``dry``, empty or unusable season list →
        the default seasons). Duplicate season keys get a numeric suffix so
        ``season_by_key`` stays unambiguous.
        """
        cal = cfg_calendar if isinstance(cfg_calendar, dict) else {}

        raw_week = cal.get("week_days")
        if isinstance(raw_week, str):
            week_days = tuple(p.strip() for p in raw_week.split(",") if p.strip())
        elif isinstance(raw_week, (list, tuple)):
            week_days = tuple(str(p).strip() for p in raw_week if str(p).strip())
        else:
            week_days = ()

        raw_label = cal.get("year_label")
        year_label = raw_label if isinstance(raw_label, str) else _DEFAULT_YEAR_LABEL

        noon = _to_int(cal.get("day_bucket_noon"), _DEFAULT_NOON_HOUR)
        evening = _to_int(cal.get("day_bucket_evening"), _DEFAULT_EVENING_HOUR)
        noon = min(max(noon, 0), DAY_HOURS - 1)
        evening = min(max(evening, 0), DAY_HOURS - 1)

        seasons: List[Season] = []
        seen: Dict[str, int] = {}
        raw_seasons = cfg_seasons if isinstance(cfg_seasons, (list, tuple)) else []
        for i, raw in enumerate(raw_seasons):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            key = str(raw.get("key") or "").strip()
            if not key:
                key = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or f"season{i + 1}"
            if key in seen:
                seen[key] += 1
                key = f"{key}_{seen[key]}"
            seen.setdefault(key, 1)
            days = max(1, _to_int(raw.get("days"), 30))
            names = {
                k[len("name_"):]: str(v)
                for k, v in raw.items()
                if k.startswith("name_") and isinstance(v, str) and v.strip()
            }
            note = raw.get("weather_note")
            seasons.append(Season(
                key=key,
                name=name or key.replace("_", " ").title(),
                days=days,
                sunrise_min=_parse_hhmm(raw.get("sunrise"), _DEFAULT_SUNRISE_MIN),
                sunset_min=_parse_hhmm(raw.get("sunset"), _DEFAULT_SUNSET_MIN),
                names=names,
                temperature=_pick_level(raw.get("temperature"),
                                        TEMPERATURE_LEVELS, _DEFAULT_TEMPERATURE),
                weather=_pick_level(raw.get("weather"),
                                    WEATHER_KINDS, _DEFAULT_WEATHER),
                weather_note=str(note).strip() if isinstance(note, str) else "",
            ))

        if not seasons:
            seasons = list(cls.default().seasons)

        return cls(
            seasons=tuple(seasons),
            week_days=week_days,
            year_label=year_label,
            noon_hour=noon,
            evening_hour=evening,
        )


_CALENDAR_CACHE: Optional[Calendar] = None


def get_calendar() -> Calendar:
    """The current world's calendar (module-cached).

    Config sections are TOP-LEVEL keys of ``worlds/<w>/config.json``, so the
    two schema sections map to ``config.get("game_calendar")`` (an object —
    ``week_days``, ``year_label``, ``day_bucket_noon``, ``day_bucket_evening``)
    and ``config.get("game_seasons")`` (an ``is_array`` section, i.e. a plain
    list of season dicts). The array section has no schema-level default
    items, so an unconfigured world arrives here with an empty list and gets
    :meth:`Calendar.default` seasons.

    Call :func:`invalidate_calendar_cache` after a config save.
    """
    global _CALENDAR_CACHE
    if _CALENDAR_CACHE is None:
        try:
            from app.core import config
            cfg_calendar = config.get("game_calendar")
            cfg_seasons = config.get("game_seasons")
        except Exception:
            cfg_calendar, cfg_seasons = None, None
        _CALENDAR_CACHE = Calendar.from_config(cfg_calendar, cfg_seasons)
    return _CALENDAR_CACHE


def invalidate_calendar_cache() -> None:
    """Drop the cached calendar — call after the config changed."""
    global _CALENDAR_CACHE
    _CALENDAR_CACHE = None


def _cal(calendar: Optional[Calendar]) -> Calendar:
    return calendar if calendar is not None else get_calendar()


def calendar_to_dict(calendar: Optional[Calendar] = None, lang: str = "en") -> dict:
    """Calendar payload for the API (clients render, they never compute)."""
    cal = _cal(calendar)
    return {
        "seasons": [
            {
                "key": s.key,
                "name": s.name_for(lang),
                "days": s.days,
                "sunrise": s.sunrise,
                "sunset": s.sunset,
                "temperature": s.temperature,
                "weather": s.weather,
                "weather_note": s.weather_note,
            }
            for s in cal.seasons
        ],
        "year_days": cal.year_days,
        "week_days": list(cal.week_days),
        "year_label": cal.year_label,
    }


def default_seasons_config() -> List[dict]:
    """The shipped seasons as ``game_seasons`` config items.

    Used to MATERIALIZE the section for a world that has none, so the admin
    page shows the four seasons that are actually in effect instead of an
    empty list (the next admin save then persists them).
    """
    return [s.to_config() for s in Calendar.default().seasons]


def default_calendar_config() -> dict:
    """The shipped ``game_calendar`` object (same values as the schema)."""
    return {
        "week_days": "",
        "year_label": _DEFAULT_YEAR_LABEL,
        "day_bucket_noon": _DEFAULT_NOON_HOUR,
        "day_bucket_evening": _DEFAULT_EVENING_HOUR,
    }


# ---------------------------------------------------------------------------
# GameDuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class GameDuration:
    """A span of GAME time in whole seconds. The ``timedelta`` replacement."""

    total_seconds: int

    ZERO: ClassVar["GameDuration"]

    def __post_init__(self) -> None:
        if not isinstance(self.total_seconds, int) or isinstance(self.total_seconds, bool):
            object.__setattr__(self, "total_seconds", int(self.total_seconds))

    @classmethod
    def of(cls, days: float = 0, hours: float = 0,
           minutes: float = 0, seconds: float = 0) -> "GameDuration":
        total = (days * DAY_SECONDS) + (hours * 3600) + (minutes * 60) + seconds
        return cls(int(round(total)))

    @property
    def seconds(self) -> float:
        return float(self.total_seconds)

    @property
    def minutes(self) -> float:
        return self.total_seconds / 60.0

    @property
    def hours(self) -> float:
        return self.total_seconds / 3600.0

    @property
    def days(self) -> float:
        return self.total_seconds / float(DAY_SECONDS)

    def __add__(self, other: "GameDuration") -> "GameDuration":
        if not isinstance(other, GameDuration):
            return NotImplemented
        return GameDuration(self.total_seconds + other.total_seconds)

    def __sub__(self, other: "GameDuration") -> "GameDuration":
        if not isinstance(other, GameDuration):
            return NotImplemented
        return GameDuration(self.total_seconds - other.total_seconds)

    def __neg__(self) -> "GameDuration":
        return GameDuration(-self.total_seconds)

    def __abs__(self) -> "GameDuration":
        return GameDuration(abs(self.total_seconds))

    def __mul__(self, factor: float) -> "GameDuration":
        if not isinstance(factor, (int, float)) or isinstance(factor, bool):
            return NotImplemented
        return GameDuration(int(round(self.total_seconds * factor)))

    __rmul__ = __mul__

    def __bool__(self) -> bool:
        return self.total_seconds != 0

    def __str__(self) -> str:
        sign = "-" if self.total_seconds < 0 else ""
        rest = abs(self.total_seconds)
        days, rest = divmod(rest, DAY_SECONDS)
        hours, rest = divmod(rest, 3600)
        minutes, seconds = divmod(rest, 60)
        body = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{sign}{days}d {body}" if days else f"{sign}{body}"


GameDuration.ZERO = GameDuration(0)


# ---------------------------------------------------------------------------
# GameTime
# ---------------------------------------------------------------------------


class GameTimeParts(NamedTuple):
    """Calendar breakdown of a :class:`GameTime` (all fields as documented)."""

    year: int
    day_of_year: int
    day_index: int
    season_index: int
    day_of_season: int
    hour: int
    minute: int
    second: int


@dataclass(frozen=True, order=True)
class GameTime:
    """A point in world time — whole GAME seconds since Year 1, Day 1, 00:00.

    Ordering and equality run over ``total_seconds`` ONLY; the calendar is not
    part of the value, it is looked up when a derived property is asked for.
    That keeps a stamp valid after the world's season lengths changed: the
    instant stays the same, only its label moves.

    There is deliberately NO ``strftime``, NO ``weekday()`` method mimicking
    ``datetime``, NO ``month``/``date``/``astimezone``/``isoformat`` (see
    plan-game-calendar.md §1.2). Their absence is the type border: a call site
    that still thinks in real dates fails loudly instead of silently mixing
    system time into the world.
    """

    total_seconds: int

    def __post_init__(self) -> None:
        value = self.total_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"GameTime needs a number of seconds, got {value!r}")
        value = int(value)
        if value < 0:
            raise ValueError(f"GameTime cannot be before the epoch (got {value})")
        object.__setattr__(self, "total_seconds", value)

    # -- breakdown ----------------------------------------------------------

    def parts(self, calendar: Optional[Calendar] = None) -> GameTimeParts:
        """Full calendar breakdown in one pass (one calendar lookup)."""
        cal = _cal(calendar)
        day_index, sec_of_day = divmod(self.total_seconds, DAY_SECONDS)
        year_days = cal.year_days or 1
        year, doy0 = divmod(day_index, year_days)
        season_index = cal.season_index_for_day(doy0)
        starts = cal.season_starts
        start = starts[season_index] if starts else 0
        hour, rest = divmod(sec_of_day, 3600)
        minute, second = divmod(rest, 60)
        return GameTimeParts(
            year=year + 1,
            day_of_year=doy0 + 1,
            day_index=day_index,
            season_index=season_index,
            day_of_season=doy0 - start + 1,
            hour=hour,
            minute=minute,
            second=second,
        )

    @property
    def day_index(self) -> int:
        """Days since the epoch, 0-based (calendar-independent)."""
        return self.total_seconds // DAY_SECONDS

    @property
    def seconds_of_day(self) -> int:
        return self.total_seconds % DAY_SECONDS

    @property
    def minutes_of_day(self) -> int:
        return self.seconds_of_day // 60

    @property
    def hour(self) -> int:
        return self.seconds_of_day // 3600

    @property
    def minute(self) -> int:
        return (self.seconds_of_day % 3600) // 60

    @property
    def second(self) -> int:
        return self.seconds_of_day % 60

    @property
    def hour_fraction(self) -> float:
        """Hour as a float (14.5 = 14:30) — the 3D client's sun position."""
        return self.hour + self.minute / 60.0 + self.second / 3600.0

    @property
    def year(self) -> int:
        return self.parts().year

    @property
    def day_of_year(self) -> int:
        return self.parts().day_of_year

    @property
    def season_index(self) -> int:
        return self.parts().season_index

    @property
    def day_of_season(self) -> int:
        return self.parts().day_of_season

    @property
    def season(self) -> str:
        """Stable season key (what rules and schedules compare against)."""
        cal = get_calendar()
        return cal.seasons[self.parts(cal).season_index].key if cal.seasons else ""

    def season_name(self, lang: str = "en",
                    calendar: Optional[Calendar] = None) -> str:
        cal = _cal(calendar)
        if not cal.seasons:
            return ""
        return cal.seasons[self.parts(cal).season_index].name_for(lang)

    def atmosphere(self, lang: str = "en",
                   calendar: Optional[Calendar] = None) -> dict:
        """Temperature/weather of the season this instant falls into.

        ``{"season", "temperature", "weather", "note", "label"}`` — the label
        reads e.g. ``"freezing, snow — often fog in the morning"``. This is
        what the LLM gets alongside the game time (``game_weather``) and what
        clients render; a calendar without seasons yields the shipped default
        levels and an empty season key.
        """
        cal = _cal(calendar)
        if not cal.seasons:
            return Season(key="", name="", days=1).atmosphere(lang)
        return cal.seasons[self.parts(cal).season_index].atmosphere(lang)

    @property
    def weekday(self) -> Optional[int]:
        """0-based weekday index, or None when the world has no weeks."""
        cal = get_calendar()
        if not cal.week_days:
            return None
        return self.day_index % len(cal.week_days)

    @property
    def weekday_name(self) -> str:
        cal = get_calendar()
        if not cal.week_days:
            return ""
        return cal.week_days[self.day_index % len(cal.week_days)]

    @property
    def sunrise_min(self) -> int:
        return self._sun_bounds()[0]

    @property
    def sunset_min(self) -> int:
        return self._sun_bounds()[1]

    def _sun_bounds(self, calendar: Optional[Calendar] = None) -> Tuple[int, int]:
        cal = _cal(calendar)
        if not cal.seasons:
            return _DEFAULT_SUNRISE_MIN, _DEFAULT_SUNSET_MIN
        s = cal.seasons[self.parts(cal).season_index]
        return s.sunrise_min, s.sunset_min

    # -- day phase ----------------------------------------------------------

    def is_night(self, calendar: Optional[Calendar] = None) -> bool:
        """Night = before the season's sunrise or at/after its sunset."""
        sunrise, sunset = self._sun_bounds(calendar)
        m = self.minutes_of_day
        return m < sunrise or m >= sunset

    def is_day(self, calendar: Optional[Calendar] = None) -> bool:
        return not self.is_night(calendar)

    def day_bucket(self, calendar: Optional[Calendar] = None) -> str:
        """``morning`` | ``afternoon`` | ``evening`` | ``night``.

        Night wins outright (outside the season's sunrise..sunset); the
        remaining daylight is split by the calendar's noon/evening hours.
        """
        cal = _cal(calendar)
        if self.is_night(cal):
            return "night"
        hour = self.hour
        if hour < cal.noon_hour:
            return "morning"
        if hour < cal.evening_hour:
            return "afternoon"
        return "evening"

    # -- strings ------------------------------------------------------------

    def time_hhmm(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"

    def canonical(self) -> str:
        """``Y0003-D047T14:23:45`` — persisted, sortable, human-readable."""
        p = self.parts()
        return (f"Y{p.year:04d}-D{p.day_of_year:03d}"
                f"T{p.hour:02d}:{p.minute:02d}:{p.second:02d}")

    def day_key(self) -> str:
        """``Y0003-D047`` — the game day, e.g. for day consolidation."""
        p = self.parts()
        return f"Y{p.year:04d}-D{p.day_of_year:03d}"

    def __str__(self) -> str:
        return self.canonical()

    def label(self, lang: str = "en", calendar: Optional[Calendar] = None) -> str:
        """Human label, e.g. ``Summer, day 17 · 14:23 · Year 3``.

        Weekday name is prefixed when the world has weeks; the year part is
        omitted when ``year_label`` is empty. One function, deterministic —
        every surface (header, prompt, log) shows the same string.
        """
        return self._label(lang, _cal(calendar), with_time=True)

    def date_label(self, lang: str = "en",
                   calendar: Optional[Calendar] = None) -> str:
        """Same as :meth:`label` without the clock time."""
        return self._label(lang, _cal(calendar), with_time=False)

    def _label(self, lang: str, cal: Calendar, with_time: bool) -> str:
        p = self.parts(cal)
        season = cal.seasons[p.season_index].name_for(lang) if cal.seasons else ""
        head = f"{season}, day {p.day_of_season}" if season else f"day {p.day_of_season}"
        if cal.week_days:
            head = f"{cal.week_days[p.day_index % len(cal.week_days)]}, {head}"
        chunks = [head]
        if with_time:
            chunks.append(f"{p.hour:02d}:{p.minute:02d}")
        if cal.year_label:
            try:
                chunks.append(cal.year_label.format(n=p.year))
            except (KeyError, IndexError, ValueError):
                chunks.append(cal.year_label)
        return " · ".join(chunks)

    # -- parsing / construction --------------------------------------------

    @classmethod
    def is_canonical(cls, text: Any) -> bool:
        """Cheap format probe (regex only) — used by migrations to skip
        stamps that were already converted."""
        return isinstance(text, str) and bool(_CANONICAL_RE.match(text))

    @classmethod
    def parse(cls, text: str, calendar: Optional[Calendar] = None) -> "GameTime":
        """Parse a canonical string. Strict — anything else raises ValueError.

        A ``day_of_year`` LARGER than the current calendar's year length is
        accepted and simply rolls into the next year: the string is read as
        ``((year-1)*year_days + (doy-1))*86400 + …`` seconds. That is
        deliberate — season lengths may have shrunk since the stamp was
        written, and the instant must survive that unclamped.
        """
        if not isinstance(text, str):
            raise ValueError(f"not a GameTime string: {text!r}")
        m = _CANONICAL_RE.match(text)
        if not m:
            raise ValueError(f"not a canonical GameTime string: {text!r}")
        year, doy, hour, minute, second = (int(g) for g in m.groups())
        return cls.from_parts(year, doy, hour, minute, second, calendar=calendar)

    @classmethod
    def from_parts(cls, year: int, day_of_year: int, hour: int = 0,
                   minute: int = 0, second: int = 0,
                   calendar: Optional[Calendar] = None) -> "GameTime":
        """Build from calendar parts (1-based year and day-of-year)."""
        cal = _cal(calendar)
        if year < 1:
            raise ValueError(f"year is 1-based, got {year}")
        if day_of_year < 1:
            raise ValueError(f"day_of_year is 1-based, got {day_of_year}")
        if not (0 <= hour < DAY_HOURS and 0 <= minute < 60 and 0 <= second < 60):
            raise ValueError(f"invalid time {hour}:{minute}:{second}")
        year_days = cal.year_days or 1
        day_index = (year - 1) * year_days + (day_of_year - 1)
        return cls(day_index * DAY_SECONDS + hour * 3600 + minute * 60 + second)

    @classmethod
    def from_season(cls, year: int, season_key: str, day_of_season: int,
                    hour: int = 0, minute: int = 0, second: int = 0,
                    calendar: Optional[Calendar] = None) -> "GameTime":
        """Build from a season key + the day within that season (1-based)."""
        cal = _cal(calendar)
        season = cal.season_by_key(season_key)
        if season is None:
            raise ValueError(f"unknown season key: {season_key!r}")
        if not 1 <= day_of_season <= season.days:
            raise ValueError(
                f"day_of_season {day_of_season} out of range for "
                f"{season_key!r} (1..{season.days})")
        idx = cal.seasons.index(season)
        day_of_year = cal.season_starts[idx] + day_of_season
        return cls.from_parts(year, day_of_year, hour, minute, second, calendar=cal)

    # -- derived values -----------------------------------------------------

    def replace(self, hour: Optional[int] = None, minute: Optional[int] = None,
                second: Optional[int] = None) -> "GameTime":
        """Same day, different clock time."""
        h = self.hour if hour is None else hour
        m = self.minute if minute is None else minute
        s = self.second if second is None else second
        if not (0 <= h < DAY_HOURS and 0 <= m < 60 and 0 <= s < 60):
            raise ValueError(f"invalid time {h}:{m}:{s}")
        return GameTime(self.day_index * DAY_SECONDS + h * 3600 + m * 60 + s)

    def start_of_day(self) -> "GameTime":
        return GameTime(self.day_index * DAY_SECONDS)

    def next_day_start(self) -> "GameTime":
        return GameTime((self.day_index + 1) * DAY_SECONDS)

    # -- arithmetic ---------------------------------------------------------

    def __add__(self, other: GameDuration) -> "GameTime":
        if not isinstance(other, GameDuration):
            return NotImplemented
        return GameTime(self.total_seconds + other.total_seconds)

    def __sub__(self, other: Any) -> Any:
        """``GameTime - GameDuration`` → GameTime (ValueError below epoch);
        ``GameTime - GameTime`` → GameDuration (may be negative)."""
        if isinstance(other, GameDuration):
            return GameTime(self.total_seconds - other.total_seconds)
        if isinstance(other, GameTime):
            return GameDuration(self.total_seconds - other.total_seconds)
        return NotImplemented

    def minus_clamped(self, duration: GameDuration) -> "GameTime":
        """Subtract, clamping at the epoch — for cutoff windows ("everything
        in the last 3 game days") that may reach behind the world's start."""
        if not isinstance(duration, GameDuration):
            raise TypeError(f"expected GameDuration, got {type(duration).__name__}")
        return GameTime(max(0, self.total_seconds - duration.total_seconds))

    # -- payload ------------------------------------------------------------

    def to_dict(self, lang: str = "en",
                calendar: Optional[Calendar] = None) -> dict:
        """Everything a client needs to render this instant — no client math."""
        cal = _cal(calendar)
        p = self.parts(cal)
        season = cal.seasons[p.season_index] if cal.seasons else None
        weekday = p.day_index % len(cal.week_days) if cal.week_days else None
        return {
            "canonical": (f"Y{p.year:04d}-D{p.day_of_year:03d}"
                          f"T{p.hour:02d}:{p.minute:02d}:{p.second:02d}"),
            "total_seconds": self.total_seconds,
            "year": p.year,
            "day_of_year": p.day_of_year,
            "season": season.key if season else "",
            "season_name": season.name_for(lang) if season else "",
            "day_of_season": p.day_of_season,
            "hour": p.hour,
            "minute": p.minute,
            "second": p.second,
            "hour_fraction": p.hour + p.minute / 60.0 + p.second / 3600.0,
            "weekday": weekday,
            "weekday_name": cal.week_days[weekday] if weekday is not None else "",
            "label": self._label(lang, cal, with_time=True),
            "date_label": self._label(lang, cal, with_time=False),
            "time": f"{p.hour:02d}:{p.minute:02d}",
            "is_night": self.is_night(cal),
            "day_bucket": self.day_bucket(cal),
            "atmosphere": (season.atmosphere(lang) if season
                           else Season(key="", name="", days=1).atmosphere(lang)),
        }


EPOCH = GameTime(0)


__all__ = [
    "Calendar",
    "Season",
    "GameTime",
    "GameTimeParts",
    "GameDuration",
    "EPOCH",
    "DAY_HOURS",
    "DAY_SECONDS",
    "TEMPERATURE_LEVELS",
    "WEATHER_KINDS",
    "get_calendar",
    "invalidate_calendar_cache",
    "calendar_to_dict",
    "default_seasons_config",
    "default_calendar_config",
]
