from __future__ import annotations

import html
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import requests
import yt_dlp

if TYPE_CHECKING:
    from bot import Bot
    from bot.player.track import Track


class SubtitleManager:
    def __init__(self) -> None:
        self.enabled: bool = False
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._fetching: set = set()
        self._lock = threading.Lock()
        self.cookiefile: Optional[str] = None
        self.preferred_locale: str = "vi"
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

    def initialize(self, bot: Bot) -> None:
        self.enabled = getattr(bot.config.general, "video_subtitles", False)
        if hasattr(bot, "translator") and bot.translator:
            locale = bot.translator.get_locale()
            if locale:
                self.preferred_locale = locale
        yt_config = getattr(bot.config.services, "yt", None)
        if yt_config:
            cookiefile = getattr(yt_config, "cookiefile_path", "")
            if cookiefile and os.path.isfile(cookiefile):
                self.cookiefile = cookiefile
                logging.debug(f"[SubtitleManager] Using YouTube cookie file: {cookiefile}")

    def _get_ydl_opts(self) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "source_address": "0.0.0.0",
        }
        if self.cookiefile and os.path.isfile(self.cookiefile):
            opts["cookiefile"] = self.cookiefile
        return opts

    def _clean_title(self, title: str) -> str:
        title = html.unescape(title)
        title = re.split(r"\s+[|•]\s+|\|", title)[0]
        patterns = [
            r"\[.*?(?:official|m/?v|video|audio|lyrics?|hd|4k|1080p|remix|version|teaser|live|cover).*?\]",
            r"\(.*?(?:official|m/?v|video|audio|lyrics?|hd|4k|1080p|remix|version|teaser|live|cover).*?\)",
            r"【.*?】",
        ]
        for p in patterns:
            title = re.sub(p, "", title, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", title).strip()

    def _get_cache_key(self, track: Track) -> str:
        info = getattr(track, "extra_info", {}) or {}
        orig = getattr(track, "_original_track", None)
        if orig and getattr(orig, "extra_info", None):
            info = {**orig.extra_info, **info}
        vid = info.get("videoId") or info.get("id") or info.get("contentId")
        if vid and isinstance(vid, str) and len(vid) == 11:
            return f"yt:{vid}"
        webpage_url = (
            info.get("webpage_url")
            or getattr(orig, "_url", None)
            or getattr(track, "_url", None)
            or getattr(track, "url", "")
        )
        if webpage_url:
            m = re.search(r"(?:v=|\/|be\/|^)([0-9A-Za-z_-]{11})(?:[&?/\s]|$)", webpage_url)
            if m:
                return f"yt:{m.group(1)}"
            return webpage_url
        return getattr(track, "name", "") or str(id(track))

    def _get_youtube_url(self, track: Track) -> Optional[str]:
        info = getattr(track, "extra_info", {}) or {}
        orig = getattr(track, "_original_track", None)
        if orig and getattr(orig, "extra_info", None):
            info = {**orig.extra_info, **info}

        vid = info.get("videoId") or info.get("id") or info.get("contentId")
        if vid and isinstance(vid, str) and len(vid) == 11:
            return f"https://www.youtube.com/watch?v={vid}"

        for candidate_url in [
            info.get("webpage_url"),
            info.get("url"),
            getattr(orig, "_url", None),
            getattr(orig, "url", None),
            getattr(track, "_url", None),
            getattr(track, "url", None),
        ]:
            if candidate_url and isinstance(candidate_url, str):
                m = re.search(r"(?:v=|\/|be\/|^)([0-9A-Za-z_-]{11})(?:[&?/\s]|$)", candidate_url)
                if m:
                    return f"https://www.youtube.com/watch?v={m.group(1)}"
                if any(h in candidate_url for h in ["youtube.com", "youtu.be"]):
                    return candidate_url
        return None

    def _parse_json3(self, json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        cues: List[Dict[str, Any]] = []
        for ev in json_data.get("events", []):
            start = ev.get("tStartMs", 0) / 1000.0
            dur = ev.get("dDurationMs", 0) / 1000.0
            text = "".join(s.get("utf8", "") for s in ev.get("segs", [])).strip()
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            if text and text != "\n":
                cues.append({
                    "start": start,
                    "end": start + dur,
                    "text": text,
                })
        return cues

    def _parse_vtt(self, vtt_text: str) -> List[Dict[str, Any]]:
        cues: List[Dict[str, Any]] = []
        blocks = vtt_text.replace("\r\n", "\n").strip().split("\n\n")
        for block in blocks:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            for i, line in enumerate(lines):
                m = re.match(
                    r"(?:(\d{1,2}):)?(\d{2}):(\d{2}\.\d{1,3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2}\.\d{1,3})",
                    line,
                )
                if m:
                    h1, m1, s1 = int(m.group(1) or 0), int(m.group(2)), float(m.group(3))
                    h2, m2, s2 = int(m.group(4) or 0), int(m.group(5)), float(m.group(6))
                    start = h1 * 3600 + m1 * 60 + s1
                    end = h2 * 3600 + m2 * 60 + s2
                    text = " ".join(lines[i + 1 :])
                    text = re.sub(r"<[^>]+>", "", text)
                    text = html.unescape(text)
                    text = re.sub(r"\s+", " ", text).strip()
                    if text:
                        cues.append({"start": start, "end": end, "text": text})
                    break
        return cues

    def _parse_lrc(self, lrc_text: str) -> List[Dict[str, Any]]:
        cues: List[Dict[str, Any]] = []
        for line in lrc_text.splitlines():
            m = re.match(r"\[(\d{1,2}):(\d{2}(?:\.\d{1,3})?)\](.*)", line.strip())
            if m:
                t = int(m.group(1)) * 60 + float(m.group(2))
                txt = re.sub(r"\[[a-zA-Z]+:[^\]]*\]", "", m.group(3)).strip()
                txt = html.unescape(txt)
                txt = re.sub(r"\s+", " ", txt).strip()
                if txt:
                    cues.append({"start": t, "text": txt})
        cues.sort(key=lambda c: c["start"])
        for i in range(len(cues)):
            if i + 1 < len(cues):
                gap = cues[i + 1]["start"] - cues[i]["start"]
                cues[i]["end"] = cues[i]["start"] + (min(gap, 7.0) if gap > 0 else 5.0)
            else:
                cues[i]["end"] = cues[i]["start"] + 6.0
        return cues

    def _get_caption_candidates(
        self,
        subs: Dict[str, Any],
        auto_subs: Dict[str, Any],
        pref_lang: str,
    ) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
        candidates: List[Tuple[str, str, List[Dict[str, Any]]]] = []
        seen = set()

        def add(tag: str, lang_code: str, fmts: List[Dict[str, Any]]) -> None:
            if lang_code not in seen and fmts:
                seen.add(lang_code)
                candidates.append((tag, lang_code, fmts))

        # 1. Manual subtitles in preferred language (e.g. vi, vi-VN)
        for k, v in subs.items():
            if k == pref_lang or k.startswith(f"{pref_lang}-") or k.startswith(f"{pref_lang}_"):
                add("manual-pref", k, v)

        # 2. Original auto-generated subtitles in preferred language (e.g. vi-orig, or vi direct)
        if f"{pref_lang}-orig" in auto_subs:
            add("auto-pref-orig", f"{pref_lang}-orig", auto_subs[f"{pref_lang}-orig"])
        if pref_lang in auto_subs:
            fmts = auto_subs[pref_lang]
            if any("tlang=" not in f.get("url", "") for f in fmts):
                add("auto-pref-direct", pref_lang, fmts)

        # 3. Manual subtitles in English (if preferred language is not English)
        if pref_lang != "en":
            for k, v in subs.items():
                if k == "en" or k.startswith("en-") or k.startswith("en_"):
                    add("manual-en", k, v)

        # 4. Original auto-generated subtitles in English
        if pref_lang != "en":
            if "en-orig" in auto_subs:
                add("auto-en-orig", "en-orig", auto_subs["en-orig"])
            if "en" in auto_subs:
                fmts = auto_subs["en"]
                if any("tlang=" not in f.get("url", "") for f in fmts):
                    add("auto-en-direct", "en", fmts)

        # 5. Any creator-uploaded manual subtitles
        for k, v in subs.items():
            add("manual-other", k, v)

        # 6. Any original auto-generated subtitles (*-orig or non-translated)
        for k, v in auto_subs.items():
            if k.endswith("-orig") or any("tlang=" not in f.get("url", "") for f in v):
                add("auto-orig", k, v)

        # 7. Translated auto-generated subtitles in preferred language
        if pref_lang in auto_subs:
            add("auto-pref-trans", pref_lang, auto_subs[pref_lang])

        # 8. Remaining auto-generated subtitles
        for k, v in auto_subs.items():
            add("auto-trans", k, v)

        return candidates

    def _download_caption_cues(
        self,
        ydl: yt_dlp.YoutubeDL,
        fmts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        # 1. Try json3 format
        json3_fmt = next((f for f in fmts if f.get("ext") == "json3"), None)
        if json3_fmt and json3_fmt.get("url"):
            try:
                resp = ydl.urlopen(json3_fmt["url"])
                import json
                data = json.loads(resp.read().decode("utf-8"))
                cues = self._parse_json3(data)
                if cues:
                    return cues
            except Exception:
                try:
                    r = requests.get(json3_fmt["url"], headers=self._headers, timeout=6)
                    if r.status_code == 200:
                        cues = self._parse_json3(r.json())
                        if cues:
                            return cues
                except Exception:
                    pass

        # 2. Try vtt format
        vtt_fmt = next((f for f in fmts if f.get("ext") == "vtt"), None)
        if vtt_fmt and vtt_fmt.get("url"):
            try:
                resp = ydl.urlopen(vtt_fmt["url"])
                text = resp.read().decode("utf-8", errors="replace")
                cues = self._parse_vtt(text)
                if cues:
                    return cues
            except Exception:
                try:
                    r = requests.get(vtt_fmt["url"], headers=self._headers, timeout=6)
                    if r.status_code == 200:
                        cues = self._parse_vtt(r.text)
                        if cues:
                            return cues
                except Exception:
                    pass

        return []

    def _fetch_subtitles(self, track: Track) -> List[Dict[str, Any]]:
        cues: List[Dict[str, Any]] = []
        yt_url = self._get_youtube_url(track)
        pref_lang = self.preferred_locale or "vi"

        # 1. Try YouTube official and auto-generated captions
        if yt_url:
            try:
                # Check if track.extra_info already has subtitles or automatic_captions
                info = getattr(track, "extra_info", {}) or {}
                orig = getattr(track, "_original_track", None)
                if orig and getattr(orig, "extra_info", None):
                    info = {**orig.extra_info, **info}

                subs = info.get("subtitles") or {}
                auto_subs = info.get("automatic_captions") or {}

                ydl_opts = self._get_ydl_opts()
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # If not already present in extra_info, extract via yt-dlp
                    if not subs and not auto_subs:
                        extracted = ydl.extract_info(yt_url, download=False)
                        subs = extracted.get("subtitles") or {}
                        auto_subs = extracted.get("automatic_captions") or {}

                    candidates = self._get_caption_candidates(subs, auto_subs, pref_lang)
                    for tag, lang_code, fmts in candidates:
                        cues = self._download_caption_cues(ydl, fmts)
                        if cues:
                            logging.info(
                                f"[SubtitleManager] Successfully fetched YouTube subtitles "
                                f"({tag}: {lang_code}, {len(cues)} cues) for '{getattr(track, 'name', yt_url)}'"
                            )
                            break
            except Exception as e:
                logging.debug(f"[SubtitleManager] YouTube caption extraction error: {e}")

        # 2. Try syncedlyrics (LRC) fallback for songs if YouTube has no captions
        if not cues and getattr(track, "name", None):
            try:
                import syncedlyrics
                clean = self._clean_title(track.name)
                lrc = syncedlyrics.search(clean, synced_only=True)
                if lrc:
                    cues = self._parse_lrc(lrc)
                    if cues:
                        logging.info(
                            f"[SubtitleManager] Fetched syncedlyrics LRC ({len(cues)} cues) for '{track.name}'"
                        )
            except Exception as e:
                logging.debug(f"[SubtitleManager] syncedlyrics fetch error: {e}")

        cues.sort(key=lambda c: c["start"])
        return cues

    def load_subtitles_async(self, track: Track) -> None:
        if not self.enabled or not track:
            return
        key = self._get_cache_key(track)
        if not key:
            return
        with self._lock:
            if key in self._cache or key in self._fetching:
                return
            self._fetching.add(key)

        def _worker() -> None:
            try:
                cues = self._fetch_subtitles(track)
                with self._lock:
                    self._cache[key] = cues
                    logging.info(
                        f"[SubtitleManager] Loaded {len(cues)} subtitle cues for '{getattr(track, 'name', key)}'"
                    )
            except Exception as e:
                logging.error(f"[SubtitleManager] Error loading subtitles: {e}", exc_info=True)
                with self._lock:
                    self._cache[key] = []
            finally:
                with self._lock:
                    self._fetching.discard(key)

        threading.Thread(target=_worker, daemon=True, name="SubtitleLoader").start()

    def get_current_subtitle(self, track: Track, current_pos: float) -> Optional[str]:
        if not self.enabled or not track:
            return None
        key = self._get_cache_key(track)
        if not key:
            return None
        with self._lock:
            cues = self._cache.get(key)
        if cues is None:
            self.load_subtitles_async(track)
            return None

        # Search reversed to get the latest active cue in case of overlapping ASR lines
        for cue in reversed(cues):
            if cue["start"] <= current_pos < cue["end"]:
                return cue["text"]
        return None

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()


subtitle_manager = SubtitleManager()
