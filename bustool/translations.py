"""
bustool/translations.py
-----------------------
Chinese translations for Brisbane bus stop names and areas.
Keyword-based: checks for known place names within the stop name.
"""

# Suburb / area keyword → Chinese
_KEYWORDS: list[tuple[str, str]] = [
    # Universities & hospitals
    ("University of Queensland", "昆士兰大学"),
    ("UQ Lakes", "昆大湖区"),
    ("UQ", "昆士兰大学"),
    ("Wesley Hospital", "卫斯理医院"),
    ("Mater Hospital", "慈悲医院"),
    ("PA Hospital", "亲王亚历山大医院"),
    ("Royal Brisbane", "皇家布里斯班医院"),

    # Train stations / landmarks
    ("Indooroopilly Station", "英德鲁皮利火车站"),
    ("Toowong Station", "托旺火车站"),
    ("Taringa Station", "塔林加火车站"),
    ("Auchenflower Station", "奥肯弗劳尔火车站"),
    ("Chelmer Station", "切尔默火车站"),
    ("Graceville Station", "格雷斯维尔火车站"),
    ("Sherwood Station", "舍伍德火车站"),
    ("Corinda Station", "科林达火车站"),
    ("Oxley Station", "奥克斯利火车站"),
    ("Milton Station", "米尔顿火车站"),
    ("Roma Street", "罗马街站"),
    ("Central Station", "中央车站"),
    ("Central", "中央车站"),
    ("South Bank", "南岸"),
    ("South Brisbane", "南布里斯班"),
    ("King George Square", "乔治国王广场"),
    ("Queen Street", "皇后街"),
    ("Garden City", "花园城"),

    # Shopping centres
    ("Indooroopilly Shopping", "英德鲁皮利购物中心"),
    ("Toowong Village", "托旺购物村"),
    ("Westfield", "西田购物中心"),

    # Suburbs
    ("Indooroopilly", "英德鲁皮利"),
    ("Toowong", "托旺"),
    ("St Lucia", "圣路西亚"),
    ("Taringa", "塔林加"),
    ("Auchenflower", "奥肯弗劳尔"),
    ("Chelmer", "切尔默"),
    ("Graceville", "格雷斯维尔"),
    ("Sherwood", "舍伍德"),
    ("Corinda", "科林达"),
    ("Oxley", "奥克斯利"),
    ("Milton", "米尔顿"),
    ("Kenmore", "肯莫尔"),
    ("Chapel Hill", "查普尔山"),
    ("Fig Tree Pocket", "榕树湾"),
    ("Jindalee", "金达利"),
    ("Moggill", "莫吉尔"),
    ("Brookfield", "布鲁克菲尔德"),
    ("Fig Tree", "榕树"),
    ("West End", "西区"),
    ("Highgate Hill", "海格特山"),
    ("Dutton Park", "达顿公园"),
    ("Fairfield", "费尔菲尔德"),
    ("Yeronga", "耶龙加"),
    ("Moorooka", "穆鲁卡"),
    ("Salisbury", "索尔兹伯里"),
    ("Nathan", "内森"),
    ("Rochedale", "罗奇代尔"),
    ("Spring Mountain", "春山"),
    ("City", "市区"),
    ("Brisbane", "布里斯班"),
]


def translate_stop(stop_name: str) -> str:
    """Return a Chinese translation hint for a stop name, or '' if unknown."""
    for keyword, chinese in _KEYWORDS:
        if keyword.lower() in stop_name.lower():
            return chinese
    return ""
