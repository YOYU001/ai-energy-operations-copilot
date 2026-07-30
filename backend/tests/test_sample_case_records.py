"""Step 11 Sub-step 2A: validates data/sample_case_records.json's structure.

Pure file/schema validation -- no DB, no API calls. This is the fixture a
future seed script (Sub-step 2B) will read; catching a malformed entry here
is cheaper than discovering it mid-seed.
"""

import json
import re
from pathlib import Path

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PATH = REPO_ROOT / "data" / "sample_case_records.json"

REQUIRED_CASE_FIELDS = {
    "case_id",
    "site_id",
    "event_time",
    "event_type",
    "symptoms",
    "root_cause",
    "operator_action",
    "resolution_result",
    "severity",
    "tags",
    "related_dataset_id",
    "related_time_range",
}


def _load():
    with open(SAMPLE_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_sample_file_exists_and_parses():
    data = _load()
    assert "metadata" in data
    assert "cases" in data


def test_metadata_marks_data_as_synthetic():
    data = _load()
    assert data["metadata"]["synthetic"] is True


def test_case_count_within_planned_range():
    data = _load()
    assert 10 <= len(data["cases"]) <= 15


def test_every_case_has_all_required_fields():
    data = _load()
    for case in data["cases"]:
        missing = REQUIRED_CASE_FIELDS - set(case.keys())
        assert not missing, f"{case.get('case_id')} missing fields: {missing}"


def test_case_ids_are_unique_and_stable_strings():
    data = _load()
    case_ids = [c["case_id"] for c in data["cases"]]
    assert len(case_ids) == len(set(case_ids))
    for case_id in case_ids:
        assert isinstance(case_id, str)
        assert case_id  # non-empty
        # deliberately not a random UUID -- must be stable across re-seeds
        assert not _UUID_RE.match(case_id)


def test_tags_are_comma_separated_strings_not_json_arrays():
    data = _load()
    for case in data["cases"]:
        tags = case["tags"]
        assert isinstance(tags, str)
        assert not tags.strip().startswith("[")


def test_no_sample_case_is_missing_symptoms_text():
    data = _load()
    for case in data["cases"]:
        assert case["symptoms"], f"{case['case_id']} has empty symptoms"


def test_scenario_groups_referenced_in_metadata_match_actual_case_ids():
    data = _load()
    case_ids = {c["case_id"] for c in data["cases"]}
    groups = data["metadata"]["scenario_groups"]
    referenced_ids = {case_id for group in groups.values() for case_id in group}
    assert referenced_ids.issubset(case_ids)
