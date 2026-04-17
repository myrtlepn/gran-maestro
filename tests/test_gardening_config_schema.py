def test_gardening_auto_archive_defaults():
    import json

    with open("templates/defaults/config.json", encoding="utf-8") as f:
        d = json.load(f)

    assert d["gardening"]["auto_archive"]["enabled"] is False
    assert d["gardening"]["auto_archive"]["dry_run"] is True
    assert d["gardening"]["auto_archive"]["thresholds"]["req_stale_days"] == 14
    assert d["gardening"]["auto_archive"]["session_init_guard_seconds"] == 86400
