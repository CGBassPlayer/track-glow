from track_glow.models import Flag, Series


def test_flag_values_match_feed():
    assert [Flag(v) for v in (1, 2, 3, 4, 5, 8, 9)] == [
        Flag.GREEN,
        Flag.YELLOW,
        Flag.RED,
        Flag.WHITE,
        Flag.CHECKERED,
        Flag.HOT_TRACK,
        Flag.COLD_TRACK,
    ]


def test_flag_key_label_and_color():
    assert Flag.HOT_TRACK.key == "hot_track"
    assert Flag.WHITE.label == "WHITE · LAST LAP"
    assert Flag.GREEN.color == "#2e7d32"
    assert all(f.color.startswith("#") and f.label for f in Flag)


def test_series_labels():
    assert Series(2).label == "Xfinity"
    assert [s.label for s in Series] == ["Cup", "Xfinity", "Truck"]
