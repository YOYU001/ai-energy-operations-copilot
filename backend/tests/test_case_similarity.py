"""Step 11 Sub-step 2A: unit tests for app/services/case_similarity.py.

Pure logic -- no DB, no embedding provider, no FastAPI. Candidate dicts are
hand-constructed with a chosen "distance" so tests can assert exact score
values without depending on any real embedding.
"""

from app.services.case_similarity import (
    CONFIDENCE_THRESHOLDS,
    SYMPTOMS_SIMILARITY_THRESHOLDS,
    WEIGHTS,
    clamp,
    confidence_for_score,
    normalize_tags,
    score_candidates,
    score_case,
    symptoms_similarity_label,
    tags_overlap_ratio,
)


def _candidate(
    case_id,
    distance,
    event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
    tags="peak_shaving,SOC",
    severity="high",
):
    return {
        "case_id": case_id,
        "site_id": "SITE-A",
        "event_time": "2026-01-15T13:30:00",
        "event_type": event_type,
        "symptoms": "text",
        "root_cause": "some root cause",
        "operator_action": "some action",
        "resolution_result": "some result",
        "severity": severity,
        "tags": tags,
        "related_dataset_id": None,
        "related_time_range": "2026-01-15T13:00:00~2026-01-15T14:00:00",
        "distance": distance,
    }


# ---------------------------------------------------------------------------
# 1. semantic score is the dominant ordering factor
# ---------------------------------------------------------------------------


def test_semantic_score_is_dominant_ordering_factor():
    candidates = [
        _candidate("far", distance=0.6, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="peak_shaving,SOC"),
        _candidate("near", distance=0.1, event_type="OTHER", tags="unrelated"),
    ]
    scored = score_candidates(candidates, query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", query_tags="peak_shaving,SOC")

    assert scored[0].case_id == "near"  # much closer semantically wins despite zero metadata boost


# ---------------------------------------------------------------------------
# 2. event_type boost cannot let a dissimilar case outrank a highly similar one
# ---------------------------------------------------------------------------


def test_event_type_boost_cannot_outrank_higher_semantic_similarity():
    candidates = [
        _candidate("dissimilar_but_matching_type", distance=0.5, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="none"),
        _candidate("similar_but_different_type", distance=0.05, event_type="OVER_CONTRACT_RISK", tags="none"),
    ]
    scored = score_candidates(candidates, query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", query_tags=None)

    assert scored[0].case_id == "similar_but_different_type"
    # even with the full event_type boost (0.5 semantic + 0.05 = 0.55), the
    # matching-type case must stay well below the non-matching case's score
    matching_type_case = next(s for s in scored if s.case_id == "dissimilar_but_matching_type")
    other_case = next(s for s in scored if s.case_id == "similar_but_different_type")
    assert matching_type_case.final_score < other_case.final_score
    assert matching_type_case.final_score == 0.5 + WEIGHTS["event_type_match"]


# ---------------------------------------------------------------------------
# 3. tags boost maximum value
# ---------------------------------------------------------------------------


def test_tags_boost_maximum_value_on_full_overlap():
    result = score_case(_candidate("x", distance=0.3, tags="a,b,c"), query_tags="a,b,c")
    assert result.tags_overlap_ratio == 1.0
    assert result.tags_boost == WEIGHTS["tags_overlap_max"]


def test_tags_boost_scales_with_partial_overlap():
    # query={a,b}, candidate={a,c} -> intersection={a} (1), union={a,b,c} (3) -> ratio 1/3
    result = score_case(_candidate("x", distance=0.3, tags="a,c"), query_tags="a,b")
    assert abs(result.tags_overlap_ratio - (1 / 3)) < 1e-9
    assert abs(result.tags_boost - WEIGHTS["tags_overlap_max"] * (1 / 3)) < 1e-9


def test_tags_overlap_ratio_zero_when_either_side_empty():
    assert tags_overlap_ratio(set(), {"a"}) == 0.0
    assert tags_overlap_ratio({"a"}, set()) == 0.0
    assert tags_overlap_ratio(set(), set()) == 0.0


# ---------------------------------------------------------------------------
# 4. final score never exceeds 1 or goes below 0
# ---------------------------------------------------------------------------


def test_final_score_clamped_to_one_even_with_all_boosts():
    # distance=0.0 -> semantic_score=1.0; both boosts also fire -> would be 1.10 unclamped
    result = score_case(
        _candidate("x", distance=0.0, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="a,b"),
        query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        query_tags="a,b",
    )
    assert result.final_score == 1.0


def test_final_score_clamped_to_zero_for_a_maximally_dissimilar_case():
    # distance > 1 is possible for cosine distance in principle (range [0, 2]);
    # semantic_score must not go negative in final_score.
    result = score_case(_candidate("x", distance=2.0), query_event_type=None, query_tags=None)
    assert result.final_score == 0.0


def test_clamp_helper():
    assert clamp(-0.5) == 0.0
    assert clamp(1.5) == 1.0
    assert clamp(0.42) == 0.42


# ---------------------------------------------------------------------------
# 5. confidence boundary values
# ---------------------------------------------------------------------------


def test_confidence_boundaries():
    high = CONFIDENCE_THRESHOLDS["high"]
    medium = CONFIDENCE_THRESHOLDS["medium"]
    assert confidence_for_score(high) == "high"
    assert confidence_for_score(high - 1e-9) == "medium"
    assert confidence_for_score(medium) == "medium"
    assert confidence_for_score(medium - 1e-9) == "low"
    assert confidence_for_score(0.0) == "low"
    assert confidence_for_score(1.0) == "high"


# ---------------------------------------------------------------------------
# 6. empty / malformed input handling
# ---------------------------------------------------------------------------


def test_normalize_tags_handles_none_and_empty():
    assert normalize_tags(None) == set()
    assert normalize_tags("") == set()
    assert normalize_tags("   ") == set()


def test_normalize_tags_handles_stray_commas_and_whitespace():
    assert normalize_tags("a, b ,,c ,") == {"a", "b", "c"}


def test_normalize_tags_lowercases():
    assert normalize_tags("PV,SOC") == {"pv", "soc"}


def test_score_case_with_no_query_event_type_never_sets_event_type_match():
    result = score_case(_candidate("x", distance=0.2, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT"), query_event_type=None)
    assert result.event_type_match is False
    assert result.final_score == result.semantic_score  # no boost applied at all


def test_score_case_with_no_query_tags_never_boosts():
    result = score_case(_candidate("x", distance=0.2, tags="a,b,c"), query_tags=None)
    assert result.tags_boost == 0.0


def test_score_case_with_malformed_candidate_tags_does_not_raise():
    result = score_case(_candidate("x", distance=0.2, tags=",,  ,"), query_tags="a,b")
    assert result.tags_boost == 0.0
    assert result.tags_overlap_ratio == 0.0


# ---------------------------------------------------------------------------
# 7. matches / differs output stability
# ---------------------------------------------------------------------------


def test_matches_and_differs_for_full_match():
    result = score_case(
        _candidate("x", distance=0.1, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="peak_shaving,soc", severity="high"),
        query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        query_tags="peak_shaving,soc",
    )
    assert "event_type: BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT" in result.matches
    assert any(m.startswith("tags:") for m in result.matches)
    assert any(m.startswith("severity:") for m in result.matches)
    assert result.differs == []


def test_matches_and_differs_for_event_type_mismatch():
    result = score_case(
        _candidate("x", distance=0.1, event_type="OVER_CONTRACT_RISK", tags="peak_shaving"),
        query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        query_tags=None,
    )
    assert any(d.startswith("event_type:") for d in result.differs)
    assert not any(m.startswith("event_type:") for m in result.matches)


def test_matches_and_differs_never_cite_root_cause_or_operator_action_as_a_match_reason():
    result = score_case(
        _candidate("x", distance=0.1, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="a"),
        query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        query_tags="a",
    )
    all_reasons = result.matches + result.differs
    assert not any("root_cause" in r or "operator_action" in r or "resolution_result" in r for r in all_reasons)
    # they must still be present as plain display fields, just not as scoring/citation reasons
    assert result.root_cause is not None
    assert result.operator_action is not None


# ---------------------------------------------------------------------------
# symptoms semantic-similarity description (matches/differs requirement #4)
# ---------------------------------------------------------------------------


def test_symptoms_similarity_label_boundaries():
    high = SYMPTOMS_SIMILARITY_THRESHOLDS["high"]
    medium = SYMPTOMS_SIMILARITY_THRESHOLDS["medium"]
    assert symptoms_similarity_label(high) == "高度語意相似"
    assert symptoms_similarity_label(high - 1e-9) == "中度語意相似"
    assert symptoms_similarity_label(medium) == "中度語意相似"
    assert symptoms_similarity_label(medium - 1e-9) == "低度語意相似"
    assert symptoms_similarity_label(0.0) == "低度語意相似"
    assert symptoms_similarity_label(1.0) == "高度語意相似"


def test_symptoms_description_never_claims_literal_text_match():
    result = score_case(_candidate("x", distance=0.0), query_event_type=None, query_tags=None)
    symptoms_entries = [r for r in (result.matches + result.differs) if r.startswith("symptoms:")]
    assert len(symptoms_entries) == 1
    # must describe a semantic-similarity level, never claim exact/literal match
    assert "非逐字相符" in symptoms_entries[0]
    assert "完全相符" not in symptoms_entries[0]


def test_symptoms_description_goes_to_matches_when_high_or_medium_similarity():
    # distance=0.1 -> semantic_score=0.9, well above the "medium" floor
    result = score_case(_candidate("x", distance=0.1), query_event_type=None, query_tags=None)
    assert any(m.startswith("symptoms:") for m in result.matches)
    assert not any(d.startswith("symptoms:") for d in result.differs)


def test_symptoms_description_goes_to_differs_when_low_similarity():
    # distance=0.9 -> semantic_score=0.1, below the "medium" floor
    result = score_case(_candidate("x", distance=0.9), query_event_type=None, query_tags=None)
    assert any(d.startswith("symptoms:") for d in result.differs)
    assert not any(m.startswith("symptoms:") for m in result.matches)


def test_symptoms_description_is_visible_even_when_boosts_inflate_final_score():
    # Low symptoms semantic similarity (distance=0.9 -> semantic_score=0.1),
    # but event_type + tags boosts still apply -- the symptoms differs entry
    # must still surface the weak semantic evidence, not be hidden by the
    # boosted final_score.
    result = score_case(
        _candidate("x", distance=0.9, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="a,b"),
        query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        query_tags="a,b",
    )
    assert any(d.startswith("symptoms:") for d in result.differs)
    expected = 0.1 + WEIGHTS["event_type_match"] + WEIGHTS["tags_overlap_max"]
    assert abs(result.final_score - expected) < 1e-9


def test_symptoms_description_does_not_affect_final_score():
    # Two candidates with identical distance/event_type/tags must have the
    # exact same final_score regardless of anything symptoms-description-
    # related -- the description is purely additive to matches/differs.
    a = score_case(_candidate("a", distance=0.3, tags="x"), query_tags="x")
    b = score_case(_candidate("b", distance=0.3, tags="x"), query_tags="x")
    assert a.final_score == b.final_score


def test_matches_and_differs_deterministic_across_repeated_calls():
    candidate = _candidate("x", distance=0.1, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="a,b,c")
    result1 = score_case(candidate, query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", query_tags="a,b,c")
    result2 = score_case(candidate, query_event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", query_tags="a,b,c")
    assert result1.matches == result2.matches
    assert result1.differs == result2.differs


# ---------------------------------------------------------------------------
# Stable sort tie-break (mirrors app/services/retrieval.py's precedent)
# ---------------------------------------------------------------------------


def test_score_candidates_stable_tie_break_on_equal_final_score():
    candidates = [
        _candidate("z_case", distance=0.4, event_type="OTHER", tags="none"),
        _candidate("a_case", distance=0.4, event_type="OTHER", tags="none"),
    ]
    scored = score_candidates(candidates, query_event_type=None, query_tags=None)
    assert [s.case_id for s in scored] == ["a_case", "z_case"]
