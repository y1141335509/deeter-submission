# Top 150 tickers by Reddit mention frequency + market cap.
# Used for ticker extraction from post text.

TICKER_UNIVERSE = {
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AVGO", "ORCL",
    "ADBE", "CRM", "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC",
    "SNPS", "CDNS", "MRVL", "NFLX", "UBER", "LYFT", "SNAP", "PINS", "RBLX", "COIN",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "V", "MA", "AXP", "C",
    "BRK", "BRK.A", "BRK.B", "SCHW", "COF", "SQ", "PYPL",
    # Healthcare / Pharma
    "UNH", "JNJ", "LLY", "MRK", "ABBV", "PFE", "MRNA", "BNTX", "BMY", "AMGN",
    "GILD", "BIIB", "REGN", "VRTX", "HCA",
    # Energy
    "XOM", "CVX", "COP", "SLB", "OXY", "MPC", "VLO", "PSX",
    # Consumer
    "WMT", "COST", "TGT", "AMZN", "HD", "LOW", "MCD", "SBUX", "NKE", "DIS",
    "NFLX", "CMCSA", "T", "VZ",
    # Industrials / Other
    "BA", "LMT", "RTX", "GE", "CAT", "DE", "HON", "MMM", "UPS", "FDX",
    "NEE", "DUK", "SO", "D", "AEP",
    # ETFs (high volume mentions)
    "SPY", "QQQ", "IWM", "VTI", "VOO", "GLD", "SLV", "USO", "VXX", "TQQQ", "SQQQ",
    "SPXU", "UPRO", "ARKK", "ARKW", "ARKG",
    # Meme / high-sentiment stocks
    "GME", "AMC", "BB", "NOK", "BBBY", "MSTR", "RIOT", "MARA", "HUT", "CLSK",
    # Other commonly mentioned
    "PLTR", "SOFI", "HOOD", "LCID", "RIVN", "F", "GM", "NIO", "LI", "XPEV",
    "BABA", "JD", "PDD", "TCEHY", "TSM", "ASML",
}

# Tickers to exclude — common English words that match ticker patterns
TICKER_BLACKLIST = {
    "A", "I", "IT", "BE", "DO", "GO", "IN", "IS", "ME", "MY", "NO", "OF",
    "ON", "OR", "SO", "TO", "UP", "US", "WE", "AT", "BY", "IF", "AN",
    "ALL", "ANY", "ARE", "BUT", "CAN", "CEO", "CFO", "COO", "CTO", "DID",
    "FOR", "GET", "GOT", "HAS", "HIM", "HIS", "HOW", "ITS", "LET", "LOL",
    "MAY", "NEW", "NOT", "NOW", "OLD", "OUR", "OUT", "OWN", "PAY", "PUT",
    "SAY", "SEE", "SET", "SHE", "THE", "TOO", "TWO", "USE", "WAS", "WAY",
    "WHO", "WHY", "WIN", "YOU", "YOLO", "APES", "HOLD", "BULL", "BEAR",
    "MOON", "PUMP", "DUMP", "CALL", "PUTS", "LONG", "NEXT", "LAST",
}
