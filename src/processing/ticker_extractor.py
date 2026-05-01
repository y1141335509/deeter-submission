import re
from typing import List
from config.tickers import TICKER_UNIVERSE, TICKER_BLACKLIST

# $TICKER mentions — high confidence, accept $tsla and $TSLA alike.
_DOLLAR_PATTERN = re.compile(r"\$([A-Za-z]{1,5})\b")

# Bare ALL-CAPS word — must already be uppercase in the source text and
# surrounded by non-letter characters. Prevents English words like "low",
# "are", "all" from matching tickers (LOW, ARE, ALL) after a naive upper().
_BARE_PATTERN = re.compile(r"(?<![A-Za-z$])([A-Z]{2,5})(?![A-Za-z])")


def extract(text: str) -> List[str]:
    """Return deduplicated list of known tickers mentioned in text."""
    if not text:
        return []

    found = set()

    for match in _DOLLAR_PATTERN.finditer(text):
        ticker = match.group(1).upper()
        if ticker in TICKER_UNIVERSE:
            found.add(ticker)

    for match in _BARE_PATTERN.finditer(text):
        ticker = match.group(1)
        if ticker in TICKER_UNIVERSE and ticker not in TICKER_BLACKLIST:
            found.add(ticker)

    return sorted(found)
