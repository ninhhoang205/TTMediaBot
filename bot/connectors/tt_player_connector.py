from __future__ import annotations
import logging
from threading import Thread
import time
from typing import TYPE_CHECKING, Optional

from bot.player import State
from bot import app_vars
from bot.subtitle_manager import subtitle_manager

if TYPE_CHECKING:
    from bot import Bot


class TTPlayerConnector(Thread):
    def __init__(self, bot: Bot):
        super().__init__(daemon=True)
        self.name = "TTPlayerConnector"
        self.bot = bot
        self.player = bot.player
        self.ttclient = bot.ttclient
        self.translator = bot.translator
        self.subtitle_manager = subtitle_manager
        self.subtitle_manager.initialize(bot)
        self._last_subtitle_status: Optional[str] = None
        self._last_sub_check_time: float = 0.0

    def get_default_playing_status(self) -> str:
        if getattr(self.player.track, "name", None):
            return self.translator.translate("Playing: {track_name}").format(
                track_name=self.player.track.name
            )
        elif getattr(self.player.track, "url", None):
            return self.translator.translate("Playing: {stream_url}").format(
                stream_url=self.player.track.url
            )
        return ""

    def get_default_paused_status(self) -> str:
        if getattr(self.player.track, "name", None):
            return self.translator.translate("Paused: {track_name}").format(
                track_name=self.player.track.name
            )
        elif getattr(self.player.track, "url", None):
            return self.translator.translate("Paused: {stream_url}").format(
                stream_url=self.player.track.url
            )
        return ""

    def toggle_subtitles(self) -> bool:
        self.subtitle_manager.enabled = not self.subtitle_manager.enabled
        self.bot.config.general.video_subtitles = self.subtitle_manager.enabled
        self._last_subtitle_status = None
        if self.subtitle_manager.enabled:
            if self.player.state == State.Playing and getattr(self.player, "track", None):
                self.subtitle_manager.load_subtitles_async(self.player.track)
        else:
            if self.player.state == State.Playing:
                self.ttclient.change_status_text(self.get_default_playing_status())
            elif self.player.state == State.Paused:
                self.ttclient.change_status_text(self.get_default_paused_status())
            elif self.player.state == State.Stopped:
                self.ttclient.change_status_text("")
        return self.subtitle_manager.enabled

    def run(self):
        last_player_state = State.Stopped
        last_track_meta = {"name": None, "url": None}
        self._close = False
        while not self._close:
            try:
                if self.player.state != last_player_state:
                    last_player_state = self.player.state
                    self._last_subtitle_status = None
                    if self.player.state == State.Playing:
                        self.ttclient.enable_voice_transmission()
                        last_track_meta = self.player.track.get_meta()
                        if self.subtitle_manager.enabled:
                            self.subtitle_manager.load_subtitles_async(self.player.track)
                        self.ttclient.change_status_text(self.get_default_playing_status())
                    elif self.player.state == State.Stopped:
                        self.ttclient.disable_voice_transmission()
                        self.ttclient.change_status_text("")
                    elif self.player.state == State.Paused:
                        self.ttclient.disable_voice_transmission()
                        self.ttclient.change_status_text(self.get_default_paused_status())

                if (
                    self.player.track.get_meta() != last_track_meta
                    and last_player_state != State.Stopped
                ):
                    last_track_meta = self.player.track.get_meta()
                    self._last_subtitle_status = None
                    if self.subtitle_manager.enabled:
                        self.subtitle_manager.load_subtitles_async(self.player.track)
                    self.ttclient.change_status_text(self.get_default_playing_status())

                # Live subtitle updating on bot status text
                if (
                    self.subtitle_manager.enabled
                    and self.player.state == State.Playing
                    and getattr(self.player, "track", None)
                ):
                    now = time.time()
                    if now - self._last_sub_check_time >= 0.25:
                        self._last_sub_check_time = now
                        current_pos = float(getattr(self.player._player, "time_pos", 0.0) or 0.0)
                        sub = self.subtitle_manager.get_current_subtitle(self.player.track, current_pos)
                        if sub:
                            sub_status = f"💬 {sub}"
                            if len(sub_status) > 250:
                                sub_status = sub_status[:247] + "..."
                            if sub_status != self._last_subtitle_status:
                                self._last_subtitle_status = sub_status
                                self.ttclient.change_status_text(sub_status)
                        else:
                            default_status = self.get_default_playing_status()
                            if self._last_subtitle_status != default_status:
                                self._last_subtitle_status = default_status
                                self.ttclient.change_status_text(default_status)

            except Exception:
                logging.error("", exc_info=True)
            time.sleep(app_vars.loop_timeout)

    def close(self):
        self._close = True

