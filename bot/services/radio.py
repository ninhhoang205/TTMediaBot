from __future__ import annotations
import logging
import threading
import unicodedata
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from bot import Bot

from bot import errors
from bot.config.models import RadioModel
from bot.player.enums import TrackType
from bot.player.track import Track
from bot.services import Service as _Service


# Radio Browser (https://api.radio-browser.info) is a free community directory of
# internet radio stations. "all." is a round-robin alias, the others are fallbacks.
API_HOSTS = [
    "https://all.api.radio-browser.info",
    "https://de1.api.radio-browser.info",
    "https://de2.api.radio-browser.info",
    "https://fi1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
]
USER_AGENT = "TTMediaBot-RadioStation/1.0"
REQUEST_TIMEOUT = 10

# Common country names (without accents) that differ from the English names used
# by Radio Browser. Value is the ISO 3166-1 alpha-2 country code.
COUNTRY_ALIASES: Dict[str, str] = {
    "viet nam": "VN",
    "vietnam": "VN",
    "vn": "VN",
    "hoa ky": "US",
    "usa": "US",
    "uk": "GB",
    "anh": "GB",
    "england": "GB",
    "phap": "FR",
    "duc": "DE",
    "nhat": "JP",
    "nhat ban": "JP",
    "han quoc": "KR",
    "korea": "KR",
    "south korea": "KR",
    "trung quoc": "CN",
    "thai lan": "TH",
    "nga": "RU",
    "australia": "AU",
    "lao": "LA",
    "campuchia": "KH",
    "an do": "IN",
    "italia": "IT",
    "tay ban nha": "ES",
    "bo dao nha": "PT",
}


def _normalize(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


class RadioService(_Service):
    def __init__(self, bot: Bot, config: RadioModel):
        self.bot = bot
        self.config = config
        self.name = "radio"
        self.hostnames: List[str] = []
        self.is_enabled = self.config.enabled
        self.error_message = ""
        self.warning_message = ""
        self.help = self.bot.translator.translate(
            "Radio Station searches internet radio stations (Radio Browser directory). "
            "Use NAME or NAME COUNTRY, for example: vov1 vietnam. "
            "Related commands: ra, raf, rar"
        )
        self.hidden = False
        self._countries: Dict[str, str] = {}
        self._countries_lock = threading.Lock()
        self._host_index = 0

    def initialize(self) -> None:
        pass

    # ------------------------------------------------------------------ HTTP
    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        last_error: Optional[Exception] = None
        count = len(API_HOSTS)
        for step in range(count):
            index = (self._host_index + step) % count
            url = API_HOSTS[index] + path
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={"User-Agent": USER_AGENT},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                self._host_index = index
                return response.json()
            except Exception as e:
                last_error = e
                logging.warning(f"Radio Browser request failed ({url}): {e}")
        raise errors.ServiceError(f"Radio Browser is unavailable: {last_error}")

    # ------------------------------------------------------------- countries
    def _load_countries(self) -> Dict[str, str]:
        with self._countries_lock:
            if self._countries:
                return self._countries
            data = self._request("/json/countries")
            countries: Dict[str, str] = {}
            for item in data or []:
                code = (item.get("iso_3166_1") or "").upper()
                name = item.get("name") or ""
                if not code or not name:
                    continue
                normalized = _normalize(name)
                countries[normalized] = code
                # "The United States Of America" -> "united states of america",
                # "united states"; "Korea, Republic Of" -> "korea"
                if normalized.startswith("the "):
                    normalized = normalized[4:]
                    countries.setdefault(normalized, code)
                countries.setdefault(normalized.split(" of ")[0], code)
                countries.setdefault(_normalize(name.split(",")[0]), code)
                countries.setdefault(code.lower(), code)
            for alias, code in COUNTRY_ALIASES.items():
                countries.setdefault(alias, code)
            self._countries = countries
            return countries

    def _find_country(self, text: str) -> Optional[str]:
        key = _normalize(text)
        if not key:
            return None
        if len(key) == 2 and key not in COUNTRY_ALIASES and not text.isupper():
            # Two-letter country codes (VN, US...) only count when typed in
            # upper case, so ordinary words like "me" or "in" stay in the name
            return None
        try:
            return self._load_countries().get(key)
        except errors.ServiceError:
            return COUNTRY_ALIASES.get(key)

    def parse_query(self, query: str) -> Tuple[str, Optional[str]]:
        """Splits 'NAME COUNTRY' into (name, country_code). The country is the
        trailing word(s) of the query, e.g. 'vov1 vietnam' or 'bbc united kingdom'."""
        words = query.split()
        if len(words) >= 2:
            for size in (3, 2, 1):
                if len(words) < size + 1:
                    continue
                code = self._find_country(" ".join(words[-size:]))
                if code:
                    return " ".join(words[:-size]), code
        if len(words) == 1:
            code = self._find_country(words[0])
            if code and len(words[0]) > 2:
                return "", code
        return query.strip(), None

    # ---------------------------------------------------------------- tracks
    def _make_track(self, station: Dict[str, Any]) -> Track:
        name = (station.get("name") or "").strip() or self.bot.translator.translate(
            "Unknown Title"
        )
        country = station.get("countrycode") or ""
        display = f"{name} ({country})" if country else name
        info = {
            "radio": {
                "stationuuid": station.get("stationuuid") or "",
                "name": name,
                "country": station.get("country") or "",
                "countrycode": country,
                "codec": station.get("codec") or "",
                "bitrate": station.get("bitrate") or 0,
                "homepage": station.get("homepage") or "",
                "url": station.get("url_resolved") or station.get("url") or "",
            }
        }
        return Track(
            service=self.name,
            url=info["radio"]["url"],
            name=display,
            format=(station.get("codec") or "").lower(),
            type=TrackType.Dynamic,
            extra_info=info,
        )

    def search(self, query: str, limit: Optional[int] = None) -> List[Track]:
        if limit is None:
            limit = self.config.search_results or 1
        query = (query or "").strip()
        if not query:
            raise errors.InvalidArgumentError()
        name, country_code = self.parse_query(query)

        stations = self._search_stations(name, country_code, limit)
        if not stations and country_code and name:
            # The last word may have been part of the station name
            stations = self._search_stations(query, None, limit)
        if not stations:
            raise errors.NothingFoundError()
        return [self._make_track(s) for s in stations]

    def _search_stations(
        self, name: str, country_code: Optional[str], limit: int
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "hidebroken": "true",
            "order": "votes",
            "reverse": "true",
            "limit": max(limit * 3, 10),
        }
        if name:
            params["name"] = name
        if country_code:
            params["countrycode"] = country_code
        data = self._request("/json/stations/search", params)
        result: List[Dict[str, Any]] = []
        seen = set()
        for station in data or []:
            url = station.get("url_resolved") or station.get("url")
            if not url:
                continue
            key = station.get("stationuuid") or url
            if key in seen:
                continue
            seen.add(key)
            result.append(station)
            if len(result) >= limit:
                break
        return result

    def get(
        self,
        url: str,
        extra_info: Optional[Dict[str, Any]] = None,
        process: bool = False,
    ) -> List[Track]:
        info = dict(extra_info or {})
        radio = dict(info.get("radio") or {})
        uuid = radio.get("stationuuid") or ""
        if not (url or radio):
            raise errors.InvalidArgumentError()

        name = radio.get("name") or self.bot.translator.translate("Radio")
        country = radio.get("countrycode")
        display = f"{name} ({country})" if country else name

        if not process:
            return [
                Track(
                    service=self.name,
                    url=url or radio.get("url", ""),
                    name=display,
                    type=TrackType.Dynamic,
                    extra_info=info,
                )
            ]

        # Resolve the current stream address (also registers a click on Radio Browser)
        stream_url = ""
        if uuid:
            try:
                data = self._request(f"/json/url/{uuid}")
                if isinstance(data, dict) and data.get("ok", True):
                    stream_url = data.get("url") or ""
            except errors.ServiceError:
                logging.warning("Radio Browser could not resolve station, using saved URL")
        stream_url = stream_url or radio.get("url") or url
        if not stream_url:
            raise errors.ServiceError("No stream URL found for this radio station")

        return [
            Track(
                service=self.name,
                url=stream_url,
                name=display,
                format=(radio.get("codec") or "").lower(),
                type=TrackType.Direct,
                extra_info=info,
            )
        ]
