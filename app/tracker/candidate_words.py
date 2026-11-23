"""The word lists of the candidate rules (pure): kind words, name markers and the names that are never a title.

The kind words name a kind of work, the markers mark a name that is not the work's (a studio, a shop, a «like»
comparison).

`candidates` builds its patterns and its stop keys from them; a list grows here, the rules do not change.
"""

KIND_WORDS = (
    r"игр[аыуе]|гр[аиу]|сериал[аеу]?|серіал[уі]?|аниме|аніме|фильм[аеу]?|фільм[уі]?|мультфильм\w*|"
    r"экранизаци[яию]|екранізаці[яїю]|ремастер|ремейк|дорам[аыу]|экшн|экшен|лайфсим|симулятор|приключени[ея]"
)
# the serial «серии» after «известн… по» is not part of the marker: a name after it keeps its weight
MARKERS = (
    r"смес\w*|как в|как у|вроде|наподобие|аналог\w*|в духе|похож\w*|наследник\w*|наступник\w*|преемник\w*|"
    r"известн\w* по|відом\w* за|вытеснив|помимо|кроме|после|на основе|по мотивам|от|від|from|студи\w*|студі\w*|"
    r"компани\w*|компані\w*|издател\w*|видав\w*|разработчик\w*|розробник\w*|выходцами из|из|магазин\w*|фестивал\w*"
)

STOP_NAMES = (
    "Steam", "PC", "ПК", "PS4", "PS5", "PlayStation", "Xbox", "Xbox One", "Xbox Series", "Xbox Series X|S", "Nintendo",
    "Nintendo Switch", "Nintendo Switch 2", "Switch", "Switch 2", "Quest", "Meta", "Meta Horizon", "Netflix", "HBO",
    "Apple TV+", "Disney+", "Amazon Prime Video", "YouTube", "Twitch", "Telegram", "IGN", "Metacritic", "Opencritic",
    "VR", "AR", "XR", "NPC", "AI", "DLC", "RU", "EU", "US", "UA", "Hard", "Easy", "Normal", "MAPPA", "A24", "Sony",
    "Microsoft", "Epic Games Store", "GOG", "itch.io",
)
