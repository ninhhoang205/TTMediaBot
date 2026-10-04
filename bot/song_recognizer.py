from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from typing import Any, Dict, Optional, TYPE_CHECKING

import requests
import static_ffmpeg
static_ffmpeg.add_paths()

import speech_recognition as sr
from shazamio import Shazam

if TYPE_CHECKING:
    from bot.player import Player
    from bot.player.track import Track


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "00:00"
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class SongRecognizer:
    def __init__(self) -> None:
        self._sr_recognizer: Optional[sr.Recognizer] = None

    @property
    def sr_recognizer(self) -> sr.Recognizer:
        if self._sr_recognizer is None:
            self._sr_recognizer = sr.Recognizer()
        return self._sr_recognizer

    def check_chapters(self, player: Player, current_pos: float) -> Optional[Dict[str, Any]]:
        # 1. Check native mpv chapter list
        try:
            mpv_instance = getattr(player, "_player", None)
            if mpv_instance:
                ch_list = getattr(mpv_instance, "chapter_list", []) or []
                curr_ch = getattr(mpv_instance, "chapter", None)
                if curr_ch is not None and 0 <= curr_ch < len(ch_list):
                    raw_title = ch_list[curr_ch].get("title", "").strip()
                    if raw_title and not re.match(r"^chapter\s*\d+$", raw_title, re.IGNORECASE):
                        return {
                            "title": raw_title,
                            "artist": "",
                            "source": "YouTube Chapter",
                        }
        except Exception as e:
            logging.debug(f"[SongRecognizer] MPV chapter check error: {e}")

        # 2. Check track.extra_info chapters
        try:
            track: Track = player.track
            info = getattr(track, "extra_info", {}) or {}
            chapters = info.get("chapters")
            if chapters and isinstance(chapters, list):
                for ch in chapters:
                    start = ch.get("start_time", 0.0)
                    end = ch.get("end_time", float("inf"))
                    if start <= current_pos <= end:
                        title = (ch.get("title") or "").strip()
                        if title and not re.match(r"^chapter\s*\d+$", title, re.IGNORECASE):
                            return {
                                "title": title,
                                "artist": "",
                                "source": "YouTube Chapter",
                            }
        except Exception as e:
            logging.debug(f"[SongRecognizer] extra_info chapters check error: {e}")

        return None

    def check_description_tracklist(self, player: Player, current_pos: float) -> Optional[Dict[str, Any]]:
        try:
            track: Track = player.track
            info = getattr(track, "extra_info", {}) or {}
            desc = info.get("description", "")
            if not desc:
                return None

            lines = desc.splitlines()
            entries = []
            pattern = re.compile(
                r"(?:^|\[|\()(\d{1,2}:\d{2}(?::\d{2})?)(?:\]|\))?\s*[-–—:]?\s*(.+)$"
            )
            for line in lines:
                line = line.strip()
                match = pattern.search(line)
                if match:
                    time_str = match.group(1)
                    title = match.group(2).strip()
                    parts = [int(p) for p in time_str.split(":")]
                    if len(parts) == 2:
                        sec = parts[0] * 60 + parts[1]
                    elif len(parts) == 3:
                        sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
                    else:
                        continue
                    if title:
                        entries.append((sec, title))

            if len(entries) >= 2:
                entries.sort(key=lambda x: x[0])
                for i in range(len(entries)):
                    t_start, title = entries[i]
                    t_end = (
                        entries[i + 1][0]
                        if i + 1 < len(entries)
                        else float("inf")
                    )
                    if t_start <= current_pos < t_end:
                        return {
                            "title": title,
                            "artist": "",
                            "source": "YouTube Tracklist",
                        }
        except Exception as e:
            logging.debug(f"[SongRecognizer] Description tracklist error: {e}")

        return None

    def _cut_audio_clip(
        self,
        url: str,
        track: Track,
        pos: float,
        duration_seconds: int = 10,
    ) -> Optional[str]:
        start_sec = max(0, int(pos - 1))
        track_dur = getattr(track, "duration", None)
        if track_dur and track_dur > 0 and start_sec + duration_seconds > track_dur:
            start_sec = max(0, int(track_dur - duration_seconds))

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        def cut_ffmpeg(target_url: str) -> bool:
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start_sec),
                "-i",
                target_url,
                "-t",
                str(duration_seconds),
                "-vn",
                "-sn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-threads",
                "2",
                "-nostdin",
                "-loglevel",
                "error",
                tmp_path,
            ]
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                if res.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 1000:
                    return True
                logging.warning(f"[SongRecognizer] ffmpeg cut failed at {start_sec}s: {res.stderr}")
            except Exception as ex:
                logging.error(f"[SongRecognizer] ffmpeg cut error: {ex}")
            return False

        try:
            success = cut_ffmpeg(url)
            if not success and hasattr(track, "refresh_stream"):
                try:
                    logging.info("[SongRecognizer] Refreshing stream URL and retrying cut...")
                    new_url = track.refresh_stream()
                    if new_url:
                        success = cut_ffmpeg(new_url)
                except Exception as refresh_err:
                    logging.error(f"[SongRecognizer] Stream refresh failed: {refresh_err}")

            if success:
                return tmp_path
        except Exception as e:
            logging.error(f"[SongRecognizer] _cut_audio_clip exception: {e}")

        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return None

    def _recognize_shazam(self, wav_path: str, timeout: float = 4.5) -> Optional[Dict[str, Any]]:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)

            async def _do() -> Dict[str, Any]:
                shazam = Shazam()
                return await asyncio.wait_for(shazam.recognize(wav_path), timeout=timeout)

            result = loop.run_until_complete(_do())
            shazam_track = result.get("track")
            if shazam_track:
                return {
                    "title": shazam_track.get("title", ""),
                    "artist": shazam_track.get("subtitle", ""),
                    "source": "Shazam Audio Recognition",
                    "url": shazam_track.get("url", ""),
                    "genre": (shazam_track.get("genres") or {}).get("primary", ""),
                }
        except Exception as e:
            logging.debug(f"[SongRecognizer] Shazam recognition error: {e}")
        finally:
            loop.close()
        return None

    def _search_youtube_fast(self, query: str, timeout: float = 5.0) -> Optional[Dict[str, str]]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "vi,en;q=0.9",
        }
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', r.text)
                video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', r.text)
                if titles:
                    raw_title = titles[0]
                    cleaned = re.sub(r"[\(\[\{].*?[\)\]\}]", "", raw_title)
                    cleaned = re.sub(
                        r"(?i)(official\s*(music\s*)?video|lyrics\s*video|mv|audio|karaoke|beat|remix|hd|4k|cover|nhạc\s*sống|giọng\s*ca\s*để\s*đời).*",
                        "",
                        cleaned,
                    ).strip(" -–—|")
                    final_title = cleaned if len(cleaned) >= 2 else raw_title
                    title_part = final_title
                    artist_part = ""
                    if " - " in final_title:
                        pts = final_title.split(" - ", 1)
                        title_part = pts[0].strip()
                        artist_part = pts[1].strip()
                    elif " | " in final_title:
                        pts = final_title.split(" | ", 1)
                        title_part = pts[0].strip()
                        artist_part = pts[1].strip()

                    vid_url = f"https://www.youtube.com/watch?v={video_ids[0]}" if video_ids else ""
                    return {
                        "title": title_part,
                        "artist": artist_part,
                        "url": vid_url,
                    }
        except Exception as e:
            logging.debug(f"[SongRecognizer] Fast YouTube search error: {e}")

        # Fallback to yt-dlp if fast HTTP search yielded no results
        try:
            import yt_dlp
            ydl_opts = {
                "quiet": True,
                "extract_flat": "in_playlist",
                "skip_download": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                s_res = ydl.extract_info(f"ytsearch1:{query}", download=False)
                entries = s_res.get("entries") or []
                if entries:
                    raw_title = entries[0].get("title", "")
                    cleaned = re.sub(r"[\(\[\{].*?[\)\]\}]", "", raw_title)
                    cleaned = re.sub(
                        r"(?i)(official\s*(music\s*)?video|lyrics\s*video|mv|audio|karaoke|beat|remix|hd|4k|cover).*",
                        "",
                        cleaned,
                    ).strip(" -–—|")
                    final_title = cleaned if len(cleaned) >= 2 else raw_title
                    title_part = final_title
                    artist_part = ""
                    if " - " in final_title:
                        pts = final_title.split(" - ", 1)
                        title_part = pts[0].strip()
                        artist_part = pts[1].strip()
                    return {
                        "title": title_part,
                        "artist": artist_part,
                        "url": entries[0].get("url") or "",
                    }
        except Exception as yt_err:
            logging.debug(f"[SongRecognizer] yt-dlp fallback search error: {yt_err}")

        return None

    def _recognize_lyrics(self, wav_path: str) -> Optional[Dict[str, Any]]:
        try:
            with sr.AudioFile(wav_path) as source:
                audio_data = self.sr_recognizer.record(source)

            recognized_text = None
            for lang in ("vi-VN", "en-US"):
                try:
                    text = self.sr_recognizer.recognize_google(audio_data, language=lang)
                    if text and len(text.strip().split()) >= 3:
                        recognized_text = text.strip()
                        logging.info(f"[SongRecognizer] Google Voice recognized ({lang}): {recognized_text}")
                        break
                except (sr.UnknownValueError, sr.RequestError):
                    continue
                except Exception as ex:
                    logging.debug(f"[SongRecognizer] Google Speech exception ({lang}): {ex}")

            if not recognized_text:
                return None

            clean_lyrics = re.sub(r"[^\w\s]", "", recognized_text)
            query = f"lời bài hát {clean_lyrics}"
            search_res = self._search_youtube_fast(query)
            if search_res:
                return {
                    "title": search_res.get("title", ""),
                    "artist": search_res.get("artist", ""),
                    "lyrics": recognized_text,
                    "source": "Google Voice / Lyrics Recognition",
                    "url": search_res.get("url", ""),
                }

            return {
                "title": recognized_text,
                "artist": "",
                "lyrics": recognized_text,
                "source": "Google Voice Recognition",
                "url": "",
            }
        except Exception as e:
            logging.error(f"[SongRecognizer] Lyrics recognition error: {e}", exc_info=True)
            return None

    def _recognize_concurrent(self, wav_path: str) -> Optional[Dict[str, Any]]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f_shazam = executor.submit(self._recognize_shazam, wav_path, 4.5)
            f_lyrics = executor.submit(self._recognize_lyrics, wav_path)

            shazam_res = None
            lyrics_res = None

            done, _ = concurrent.futures.wait(
                [f_shazam, f_lyrics],
                timeout=4.5,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )

            if f_shazam in done:
                try:
                    shazam_res = f_shazam.result()
                except Exception:
                    shazam_res = None
                if shazam_res:
                    return shazam_res

            if f_lyrics in done:
                try:
                    lyrics_res = f_lyrics.result()
                except Exception:
                    lyrics_res = None

            if lyrics_res and not shazam_res:
                try:
                    shazam_res = f_shazam.result(timeout=1.5)
                    if shazam_res:
                        return shazam_res
                except Exception:
                    pass
                return lyrics_res

            if not lyrics_res:
                try:
                    lyrics_res = f_lyrics.result(timeout=2.5)
                    if lyrics_res:
                        return lyrics_res
                except Exception:
                    pass

            if not shazam_res and not f_shazam.done():
                try:
                    shazam_res = f_shazam.result(timeout=1.5)
                    if shazam_res:
                        return shazam_res
                except Exception:
                    pass

        return None

    def _sample_and_recognize(
        self,
        url: str,
        track: Track,
        pos: float,
        duration_seconds: int = 10,
    ) -> Optional[Dict[str, Any]]:
        t0 = time.time()
        wav_path = self._cut_audio_clip(url, track, pos, duration_seconds)
        if not wav_path:
            return None
        t_cut = time.time() - t0
        logging.info(f"[SongRecognizer] Audio clip cut in {t_cut:.2f}s at {pos:.1f}s")
        try:
            t1 = time.time()
            res = self._recognize_concurrent(wav_path)
            t_rec = time.time() - t1
            logging.info(f"[SongRecognizer] Recognition completed in {t_rec:.2f}s (found: {bool(res)})")
            return res
        finally:
            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass

    def recognize_audio(
        self,
        player: Player,
        current_pos: float,
        duration_seconds: int = 10,
    ) -> Optional[Dict[str, Any]]:
        track: Track = player.track
        url = track.url
        if not url:
            return None
        return self._sample_and_recognize(url, track, current_pos, duration_seconds)

    def recognize_lyrics(
        self,
        player: Player,
        current_pos: float,
        duration_seconds: int = 10,
    ) -> Optional[Dict[str, Any]]:
        return self.recognize_audio(player, current_pos, duration_seconds)

    def identify(self, player: Player, force_audio: bool = False) -> Optional[Dict[str, Any]]:
        current_pos = 0.0
        try:
            current_pos = float(getattr(player._player, "time_pos", 0.0) or 0.0)
        except Exception:
            pass

        duration = 0.0
        try:
            duration = float(player.get_duration() or 0.0)
        except Exception:
            pass

        pos_str = (
            f"{format_duration(current_pos)} / {format_duration(duration)}"
            if duration > 0
            else format_duration(current_pos)
        )

        # Tier 1: Check Chapters and Description Tracklist (Instant 0.001s)
        if not force_audio:
            ch_res = self.check_chapters(player, current_pos)
            if ch_res:
                ch_res["position_str"] = pos_str
                return ch_res

            desc_res = self.check_description_tracklist(player, current_pos)
            if desc_res:
                desc_res["position_str"] = pos_str
                return desc_res

        track: Track = player.track
        url = getattr(track, "url", None)
        if not url:
            logging.warning("[SongRecognizer] No track URL available to capture audio.")
            return None

        # Sample 1: At current position (Parallel Shazam + Google Voice)
        res = self._sample_and_recognize(url, track, current_pos, duration_seconds=10)
        if res:
            res["position_str"] = pos_str
            return res

        # Sample 2: If early in the video (<45s), retry once ahead to skip intro/jingles
        if current_pos < 45:
            logging.info("[SongRecognizer] Early position (<45s) had no match. Retrying at pos+18s to skip intro...")
            res2 = self._sample_and_recognize(url, track, current_pos + 18, duration_seconds=10)
            if res2:
                res2["position_str"] = pos_str
                return res2

        return None


song_recognizer = SongRecognizer()
