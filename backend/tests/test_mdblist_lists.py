from integrations.mdblist import parse_list_items


def test_parse_list_items_orders_by_rank_and_keeps_language():
    payload = {"movies": [
        {"id": 2, "title": "B", "release_year": 2026, "language": "ta", "rank": 2000},
        {"id": 1, "title": "A", "release_year": 2026, "language": "hi", "rank": 1000},
        {"id": 0, "title": "bad"}, {"title": "no id"},
    ], "shows": []}
    items = parse_list_items(payload, "movies")
    assert [i["tmdbId"] for i in items] == [1, 2]
    assert items[0]["language"] == "hi" and items[1]["language"] == "ta"


def test_parse_list_items_tolerates_garbage():
    assert parse_list_items(None) == [] and parse_list_items({"movies": "x"}) == []
