from __future__ import annotations
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import yt_dlp

if TYPE_CHECKING:
    from bot import Bot

from bot.config.models import YtModel
from bot.player.enums import TrackType
from bot.player.track import Track
from bot.services import Service as _Service
from bot import errors


class YtService(_Service):
    def __init__(self, bot: Bot, config: YtModel):
        self.bot = bot
        self.config = config
        self.name = "yt"
        self.hostnames = [
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "music.youtube.com",
        ]
        self.is_enabled = self.config.enabled
        self.error_message = ""
        self.warning_message = ""
        self.help = ""
        self.hidden = False
        self._max_retries = 2
        self._ydl_opts_base: Dict[str, Any] = {}

    def initialize(self) -> None:
        self._ydl_opts_base = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "source_address": "0.0.0.0",
        }
        cookiefile = getattr(self.config, "cookiefile_path", "")
        if cookiefile and os.path.isfile(cookiefile):
            self._ydl_opts_base["cookiefile"] = cookiefile
            logging.info(f"{self.name.upper()} Service: Cookie file found at {cookiefile}")
        else:
            logging.debug(f"{self.name.upper()} Service: No cookie file configured or not found.")

    def search(self, query: str, limit: Optional[int] = None) -> List[Track]:
        if limit is None:
            limit = self.config.search_results or 1

        # Direct URL check
        if any(h in query for h in ["youtube.com", "youtu.be", "music.youtube.com"]):
            return self.get(query)

        search_query = f"ytsearch{limit + 5}:{query}"
        opts = dict(self._ydl_opts_base)
        opts.update({
            "extract_flat": "in_playlist",
            "skip_download": True,
        })

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
        except Exception as e:
            logging.error(f"YT search error for '{query}': {e}")
            raise errors.ServiceError(f"YouTube search error: {e}") from e

        entries = info.get("entries") or []
        tracks: List[Track] = []
        for entry in entries:
            if not entry:
                continue
            if entry.get("ie_key") == "YoutubeTab":
                continue
            entry_url = entry.get("url") or ""
            if any(p in entry_url for p in ["/channel/", "/@", "/user/"]):
                continue

            vid = entry.get("id") or entry.get("videoId")
            title = entry.get("title") or self.bot.translator.translate("Unknown Title")
            uploader = entry.get("uploader") or entry.get("channel")
            full_title = f"{title} - {uploader}" if uploader and uploader not in title else title
            url = entry_url if "watch?v=" in entry_url else f"https://www.youtube.com/watch?v={vid}"
            tracks.append(
                Track(
                    service=self.name,
                    url=url,
                    name=full_title,
                    type=TrackType.Dynamic,
                    extra_info=entry,
                )
            )
            if len(tracks) >= limit:
                break

        if not tracks:
            raise errors.NothingFoundError()
        return tracks

    def get(
        self,
        url: str,
        extra_info: Optional[Dict[str, Any]] = None,
        process: bool = False,
    ) -> List[Track]:
        start_time = time.perf_counter()
        if not (url or extra_info):
            raise errors.InvalidArgumentError()

        info = dict(extra_info or {})
        video_id = info.get("videoId") or info.get("id") or info.get("contentId")

        if not process:
            # If extra_info has valid title and id, return dynamic track without network call
            if info.get("title") and (video_id or url):
                title = info.get("title")
                uploader = info.get("uploader") or info.get("channel")
                full_title = f"{title} - {uploader}" if uploader and uploader not in title else title
                source_url = info.get("webpage_url") or url or f"https://www.youtube.com/watch?v={video_id}"
                return [
                    Track(
                        service=self.name,
                        url=source_url,
                        name=full_title,
                        type=TrackType.Dynamic,
                        extra_info=info,
                    )
                ]

            lower_url = url.lower() if url else ""
            if (
                "list=" in lower_url
                or "/channel/" in lower_url
                or "/@" in lower_url
                or "/c/" in lower_url
                or "/user/" in lower_url
                or "/playlist" in lower_url
            ):
                opts = dict(self._ydl_opts_base)
                opts.update({
                    "extract_flat": "in_playlist",
                    "skip_download": True,
                })
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        pl_info = ydl.extract_info(url, download=False)
                    entries = pl_info.get("entries") or []
                    tracks: List[Track] = []
                    for entry in entries:
                        if not entry:
                            continue
                        e_id = entry.get("id")
                        e_title = entry.get("title") or self.bot.translator.translate("Unknown Title")
                        e_uploader = entry.get("uploader") or pl_info.get("uploader")
                        e_full = f"{e_title} - {e_uploader}" if e_uploader and e_uploader not in e_title else e_title
                        e_url = entry.get("url") or f"https://www.youtube.com/watch?v={e_id}"
                        tracks.append(
                            Track(
                                service=self.name,
                                url=e_url,
                                name=e_full,
                                type=TrackType.Dynamic,
                                extra_info=entry,
                            )
                        )
                    duration = (time.perf_counter() - start_time) * 1000
                    logging.info(f"YT Get (Playlist) finished in {duration:.2f}ms for {url} ({len(tracks)} tracks)")
                    return tracks
                except Exception as e:
                    logging.error(f"YT Playlist extraction failed: {e}")
                    raise errors.ServiceError(f"Playlist extraction failed: {e}") from e

            # Single video fallback
            return [
                Track(
                    service=self.name,
                    url=url,
                    name=self.bot.translator.translate("YouTube Track"),
                    type=TrackType.Dynamic,
                    extra_info=info,
                )
            ]

        # Process: Extract direct stream URL
        source_url = url or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        if not source_url:
            raise errors.ServiceError("No URL provided for stream extraction")

        opts = dict(self._ydl_opts_base)
        opts["skip_download"] = True
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                extracted = ydl.extract_info(source_url, download=False)
        except Exception as e:
            logging.error(f"YT stream extraction failed for '{source_url}': {e}")
            raise errors.ServiceError(f"Failed to extract stream: {e}") from e

        stream_url = extracted.get("url")
        if not stream_url:
            raise errors.ServiceError("yt-dlp returned no stream URL for this video")

        title = extracted.get("title") or info.get("title") or self.bot.translator.translate("Unknown Title")
        uploader = extracted.get("uploader") or extracted.get("channel") or info.get("uploader")
        full_title = f"{title} - {uploader}" if uploader and uploader not in title else title
        fmt = extracted.get("ext") or "m4a"
        is_live = bool(extracted.get("is_live"))
        track_type = TrackType.Live if is_live else TrackType.Default

        duration = (time.perf_counter() - start_time) * 1000
        logging.info(f"YT Get (Stream) resolved in {duration:.2f}ms format={fmt} for {full_title}")

        return [
            Track(
                service=self.name,
                url=stream_url,
                name=full_title,
                format=fmt,
                type=track_type,
                extra_info=extracted,
                extracted_at=time.perf_counter(),
            )
        ]

    def download(self, track: Track, file_path: str, video: bool = False) -> None:
        info = track.extra_info or {}
        video_id = info.get("videoId") or info.get("id") or info.get("contentId")
        source_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else track.url

        opts = dict(self._ydl_opts_base)
        opts["outtmpl"] = file_path
        if video:
            opts["format"] = "bestvideo+bestaudio/best"
        else:
            opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([source_url])

    def get_related(self, video_id: str, count: int = 5) -> List[Track]:
        if not video_id:
            return []
        url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
        opts = dict(self._ydl_opts_base)
        opts.update({
            "extract_flat": "in_playlist",
            "skip_download": True,
            "playlist_items": f"2-{count + 1}",
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = info.get("entries") or []
            tracks: List[Track] = []
            for entry in entries:
                if not entry or entry.get("ie_key") == "YoutubeTab":
                    continue
                vid = entry.get("id") or entry.get("videoId")
                if not vid or vid == video_id:
                    continue
                title = entry.get("title") or self.bot.translator.translate("Unknown Title")
                uploader = entry.get("uploader") or entry.get("channel")
                full_title = f"{title} - {uploader}" if uploader and uploader not in title else title
                tracks.append(
                    Track(
                        service=self.name,
                        url=f"https://www.youtube.com/watch?v={vid}",
                        name=full_title,
                        type=TrackType.Dynamic,
                        extra_info=entry,
                    )
                )
            return tracks
        except Exception as e:
            logging.warning(f"Failed to fetch related tracks for {video_id}: {e}")
            return []

    def _fetch_autoplay_sync(self, video_id: str) -> bool:
        if not video_id or not hasattr(self.bot, "player"):
            return False
        related = self.get_related(video_id, count=5)
        if not related:
            return False

        existing_ids = set()
        for t in self.bot.player.track_list:
            info = getattr(t, "extra_info", None) or {}
            vid = info.get("id") or info.get("videoId")
            if vid:
                existing_ids.add(vid)

        added = 0
        for track in related:
            info = getattr(track, "extra_info", None) or {}
            vid = info.get("id") or info.get("videoId")
            if vid and vid not in existing_ids:
                self.bot.player.track_list.append(track)
                existing_ids.add(vid)
                added += 1

        if added > 0:
            logging.info(f"[Autoplay] Appended {added} related tracks to player track_list")
            # Immediately pre-resolve the direct m4a stream URL for the next track in this background thread
            try:
                next_idx = self.bot.player.track_index + 1
                if next_idx < len(self.bot.player.track_list):
                    next_t = self.bot.player.track_list[next_idx]
                    if not next_t._is_fetched:
                        logging.info(f"[Autoplay] Pre-resolving direct m4a stream for next track: {next_t.name}")
                        _ = next_t.url
                        logging.info(f"[Autoplay] Next track m4a stream ready: {next_t.name}")
            except Exception as e:
                logging.warning(f"[Autoplay] Error pre-resolving next track: {e}")

            # Schedule player prefetch for subsequent tracks
            if hasattr(self.bot.player, "_schedule_prefetch"):
                self.bot.player._schedule_prefetch()
            return True
        return False

    def _fetch_autoplay_async(self, video_id: str) -> None:
        if not video_id:
            return
        t = threading.Thread(
            target=self._fetch_autoplay_sync,
            args=(video_id,),
            daemon=True,
            name="YT_Autoplay_Fetcher",
        )
        t.start()
