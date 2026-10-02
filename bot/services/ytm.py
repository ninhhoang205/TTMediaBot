from __future__ import annotations
import logging
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bot import Bot

from bot.config.models import YtmModel
from bot.player.track import Track
from bot.services.yt import YtService


class YtmService(YtService):
    def __init__(self, bot: Bot, config: YtmModel):
        super().__init__(bot, config)  # type: ignore
        self.name = "ytm"
        self.hostnames = [
            "music.youtube.com",
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
        ]
        self.is_enabled = self.config.enabled

    def search(self, query: str, limit: Optional[int] = None) -> List[Track]:
        return super().search(query, limit)
