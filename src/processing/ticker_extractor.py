import re
from typing import List
from config.tickers import TICKER_UNIVERSE, TICKER_BLACKLIST

# Match $TICKER or standalone ALL-CAPS word that is a known ticker
_DOLLAR_PATTERN = re.compile(r"\$([A-Z]{1,5})")
_WORD_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")


def extract(text: str) -> List[str]:
    """Return deduplicated list of known tickers mentioned in text."""
    found = set()

    # $TICKER mentions — high confidence, check against universe
    for match in _DOLLAR_PATTERN.finditer(text):
        ticker = match.group(1)
        if ticker in TICKER_UNIVERSE:
            found.add(ticker)

    # ALL-CAPS word mentions — filter against universe and blacklist
    upper_text = text.upper()
    for match in _WORD_PATTERN.finditer(upper_text):
        ticker = match.group(1)
        if ticker in TICKER_UNIVERSE and ticker not in TICKER_BLACKLIST:
            found.add(ticker)

    return sorted(found)
