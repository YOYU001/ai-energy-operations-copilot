from app.ingestion import EMS_MODE_VALUES, EQUIPMENT_STATUS_VALUES, parse_and_validate_csv


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _warnings_for_column(warnings, column):
    return [w for w in warnings if w["column"] == column]


def test_valid_canonical_enum_values_produce_no_warnings():
    csv_text = (
        "timestamp,site_id,ems_mode,equipment_status,electricity_price\n"
        "2026-07-10 08:00:00,site_demo_pv_001,auto,normal,3.5\n"
        "2026-07-10 09:00:00,site_demo_pv_001,tou_arbitrage,maintenance,4.0\n"
    )
    rows, warnings = parse_and_validate_csv(_csv_bytes(csv_text))

    assert rows[0]["ems_mode"] == "auto"
    assert rows[0]["equipment_status"] == "normal"
    assert rows[1]["ems_mode"] == "tou_arbitrage"
    assert rows[1]["equipment_status"] == "maintenance"
    assert _warnings_for_column(warnings, "ems_mode") == []
    assert _warnings_for_column(warnings, "equipment_status") == []


def test_case_and_whitespace_are_normalized():
    csv_text = (
        "timestamp,site_id,ems_mode,equipment_status,electricity_price\n"
        "2026-07-10 08:00:00,site_demo_pv_001, Manual ,  Warning ,3.5\n"
    )
    rows, warnings = parse_and_validate_csv(_csv_bytes(csv_text))

    assert rows[0]["ems_mode"] == "manual"
    assert rows[0]["equipment_status"] == "warning"
    assert _warnings_for_column(warnings, "ems_mode") == []
    assert _warnings_for_column(warnings, "equipment_status") == []


def test_invalid_ems_mode_produces_warning_and_stores_unknown():
    csv_text = (
        "timestamp,site_id,ems_mode,electricity_price\n"
        "2026-07-10 08:00:00,site_demo_pv_001,on,3.5\n"
    )
    rows, warnings = parse_and_validate_csv(_csv_bytes(csv_text))

    assert rows[0]["ems_mode"] == "unknown"
    ems_warnings = _warnings_for_column(warnings, "ems_mode")
    assert len(ems_warnings) == 1
    assert ems_warnings[0]["row"] == 2
    assert ems_warnings[0]["action"] == "stored as 'unknown'"


def test_invalid_equipment_status_produces_warning_and_stores_unknown():
    csv_text = (
        "timestamp,site_id,equipment_status,electricity_price\n"
        "2026-07-10 08:00:00,site_demo_pv_001,broken,3.5\n"
    )
    rows, warnings = parse_and_validate_csv(_csv_bytes(csv_text))

    assert rows[0]["equipment_status"] == "unknown"
    status_warnings = _warnings_for_column(warnings, "equipment_status")
    assert len(status_warnings) == 1
    assert status_warnings[0]["row"] == 2
    assert status_warnings[0]["action"] == "stored as 'unknown'"


def test_canonical_value_sets_match_data_schema_doc():
    assert EMS_MODE_VALUES == {
        "auto",
        "manual",
        "schedule",
        "tou_arbitrage",
        "peak_shaving",
        "self_consumption",
        "idle",
        "fallback",
        "error",
        "unknown",
    }
    assert EQUIPMENT_STATUS_VALUES == {
        "normal",
        "warning",
        "fault",
        "error",
        "offline",
        "maintenance",
        "unknown",
    }


def test_existing_timestamp_numeric_and_battery_health_validation_still_work():
    csv_text = (
        "timestamp,site_id,electricity_price,battery_soc,battery_health_status\n"
        "2026-07-10 08:00:00,site_demo_pv_001,3.5,55,Critical\n"
        "not-a-date,site_demo_pv_001,4.0,60,normal\n"
        "2026-07-10 10:00:00,site_demo_pv_001,not-a-number,70,bogus_status\n"
    )
    rows, warnings = parse_and_validate_csv(_csv_bytes(csv_text))

    # the row with an unparseable timestamp is dropped entirely
    assert len(rows) == 2

    # numeric conversion failure stores NULL but keeps the row
    assert rows[1]["electricity_price"] is None
    price_warnings = _warnings_for_column(warnings, "electricity_price")
    assert len(price_warnings) == 1

    # battery_health_status enum normalization and fallback still work
    assert rows[0]["battery_health_status"] == "critical"
    assert rows[1]["battery_health_status"] == "unknown"
    health_warnings = _warnings_for_column(warnings, "battery_health_status")
    assert len(health_warnings) == 1

    timestamp_warnings = _warnings_for_column(warnings, "timestamp")
    assert len(timestamp_warnings) == 1
