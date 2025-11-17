"""
Othman Discord Bot - Soccer Team Tag IDs
=========================================

Maps team names to their Discord forum tag IDs for automatic categorization.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# DESIGN: Soccer team tag ID mapping
# Maps AI-detected team names to Discord forum tag IDs
# These IDs are from the soccer forum channel configuration
# AI will return team name, we look up the tag ID for posting
SOCCER_TEAM_TAG_IDS: dict[str, int] = {
    "Barcelona": 1440030683992031282,
    "Real Madrid": 1440030713498828860,
    "Atletico Madrid": 1440030801508176014,
    "Liverpool": 1440030822496473189,
    "Bayern Munich": 1440030846416588861,
    "Manchester City": 1440030866452648057,
    "Manchester United": 1440030888128675881,
    "Arsenal": 1440030901512966185,
    "Chelsea": 1440030915182198866,
    "Paris Saint-Germain": 1440030936254255164,
    "Juventus": 1440030956806471752,
    "AC Milan": 1440030976288755937,
    "Inter Milan": 1440030992701198377,
    "Napoli": 1440031006236344595,
    "Borussia Dortmund": 1440031046069518448,
    "Roma": 1440031084845858928,
    "Tottenham Hotspur": 1440031117016043614,
    "International": 1440031141884334311,
    "Champions League": 1440031161094242365,
}
