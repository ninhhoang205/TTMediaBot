import logging

try:
    import pyshorteners
except ImportError:
    pyshorteners = None

from bot.config.models import ShorteningModel


class Shortener:
    def __init__(self, config: ShorteningModel) -> None:
        self.shorten_links = config.shorten_links and (pyshorteners is not None)
        if pyshorteners is not None and self.shorten_links:
            try:
                self.shortener = pyshorteners.Shortener(**config.service_params)
                if config.service not in self.shortener.available_shorteners:
                    logging.error("Unknown shortener service, this feature will be disabled")
                    self.shorten_links = False
                self.shorten_service = getattr(self.shortener, config.service, None)
            except Exception:
                self.shorten_links = False
        else:
            self.shortener = None
            self.shorten_service = None

    def get(self, url: str) -> str:
        try:
            if self.shorten_links and self.shorten_service:
                return self.shorten_service.short(url)
        except Exception:
            logging.error("", exc_info=True)
            self.shorten_links = False
        return url
