"""T02 骨架烟测：domain 校验规则与 JSON 往返（G0 公共合同的基础部分）。

覆盖契约 §3 的关键语义：错误不是「没找到」、焦点门禁、来源规则、
两种舍入、信封往返与未知键拒绝。
"""

from __future__ import annotations

import pytest

from pddcheck.domain import (
    BoxPrecision,
    Candidate,
    Capture,
    ComponentStatus,
    CoordinateSource,
    Deadline,
    FocusState,
    Geometry,
    InvalidDomain,
    LocateResult,
    LocateStatus,
    ReadStatus,
    RecipeSpec,
    Rect,
    Sample,
    WindowKind,
    ActionIntent,
    ActionKind,
    ActionReceipt,
    ExecutionStatus,
    from_envelope,
    envelope,
)

PKG = "com.xunmeng.pinduoduo"
SHA_A = "a" * 64
SHA_B = "b" * 64


def make_focus(**kw) -> FocusState:
    base = dict(window_kind=WindowKind.APP, sampled_ns=1000, focused_package=PKG)
    base.update(kw)
    return FocusState(**base)


def make_capture(**kw) -> Capture:
    base = dict(
        run_id="run-1",
        capture_id="cap-1",
        state_epoch=3,
        capture_started_ns=100,
        capture_finished_ns=800,
        focus_before=make_focus(),
        focus_after=make_focus(),
        tap_width=720,
        tap_height=1280,
        rotation=0,
        screenshot_encoding="png",
        capture_transport="adb-screencap",
        png_ref="frames/cap-1.png",
        png_sha256=SHA_A,
    )
    base.update(kw)
    return Capture(**base)


def make_candidate(**kw) -> Candidate:
    base = dict(
        candidate_id="c1",
        capture_id="cap-1",
        state_epoch=3,
        key="bag",
        source=CoordinateSource.OCR,
        overlap=4,
        rank_in_pass=0,
        matched_text="抽福袋",
        tap_point=(10, 20),
        box=Rect(0, 0, 10, 10),
        box_precision=BoxPrecision.LINE,
        engine_id="rapidocr",
        engine_version="1.3.2",
        model_hash=SHA_B,
        reading_ref="ocr/r1",
    )
    base.update(kw)
    return Candidate(**base)


# --------------------------------------------------------------- 几何与时钟


def test_rect_rejects_zero_width():
    with pytest.raises(InvalidDomain):
        Rect(0, 0, 0, 10)


def test_geometry_two_rounding_rules_differ():
    geo = Geometry(image_width=3, image_height=4, tap_width=1, tap_height=2, rotation=0, revision=0)
    # fx = 2/3：half_up -> 1，截断 -> 0；fy = 1.0：两者都是 1
    assert geo.scale_to_tap(2, 2, half_up=True) == (1, 1)
    assert geo.scale_to_tap(2, 2, half_up=False) == (0, 1)


def test_geometry_rotation_is_rejected_not_guessed():
    geo = Geometry(image_width=10, image_height=10, tap_width=10, tap_height=10, rotation=90, revision=0)
    with pytest.raises(InvalidDomain, match="rotation"):
        geo.scale_to_tap(1, 1, half_up=False)


def test_deadline_child_never_extends_parent():
    parent = Deadline(1000)
    assert parent.child(500, now_ns=100).at_ns == 600
    assert parent.child(5000, now_ns=100).at_ns == 1000
    assert parent.expired(1000)
    with pytest.raises(InvalidDomain):
        parent.child(0, now_ns=100)


# --------------------------------------------------------------- 读取语义


def test_sample_ok_requires_value():
    with pytest.raises(InvalidDomain):
        Sample(ReadStatus.OK, started_ns=1, ended_ns=2, source="x")


def test_sample_failure_requires_error_code():
    with pytest.raises(InvalidDomain):
        Sample(ReadStatus.TIMEOUT, started_ns=1, ended_ns=2, source="x")
    # ABSENT 是「没找到」，不是错误，允许无 error_code
    Sample(ReadStatus.ABSENT, started_ns=1, ended_ns=2, source="x")


def test_focus_gate_statusbar_never_passes_even_if_pdd_resumed():
    bar = FocusState(
        window_kind=WindowKind.STATUSBAR,
        sampled_ns=2000,
        resumed_package=PKG,
        window_label="StatusBar",
    )
    assert not bar.allows_business_action(PKG)
    assert make_focus().allows_business_action(PKG)


# --------------------------------------------------------------- Capture


def test_capture_sha_and_ref_must_pair():
    with pytest.raises(InvalidDomain):
        make_capture(png_sha256=None)
    with pytest.raises(InvalidDomain):
        make_capture(xml_ref="frames/cap-1.xml")


def test_capture_json_roundtrip():
    cap = make_capture(
        component_statuses=(("png", ComponentStatus.OK), ("focus", ComponentStatus.OK))
    )
    restored = from_envelope(envelope(cap), Capture)
    assert restored == cap
    assert restored.component_statuses[0][1] is ComponentStatus.OK


# --------------------------------------------------------------- 候选


def test_recipe_hash_ignores_param_order():
    r1 = RecipeSpec("band", "v1", params=(("a", "1"), ("b", "2")))
    r2 = RecipeSpec("band", "v1", params=(("b", "2"), ("a", "1")))
    assert r1.content_hash() == r2.content_hash()


def test_ocr_candidate_requires_engine_and_reading_ref():
    with pytest.raises(InvalidDomain):
        make_candidate(engine_id=None)


def test_config_coord_has_no_recognized_text():
    with pytest.raises(InvalidDomain):
        make_candidate(source=CoordinateSource.CONFIG_COORD, matched_text="抽福袋")
    coord = make_candidate(
        source=CoordinateSource.CONFIG_COORD,
        engine_id=None,
        engine_version=None,
        model_hash=None,
        reading_ref=None,
        matched_text=None,
    )
    assert coord.tap_point == (10, 20)


def test_xml_candidate_precision_must_be_element():
    with pytest.raises(InvalidDomain):
        make_candidate(source=CoordinateSource.XML, box_precision=BoxPrecision.LINE)
    xml_cand = make_candidate(
        source=CoordinateSource.XML,
        box_precision=BoxPrecision.ELEMENT,
        engine_id=None,
        engine_version=None,
        model_hash=None,
        reading_ref=None,
    )
    assert xml_cand.box_precision is BoxPrecision.ELEMENT


def test_candidate_json_roundtrip_keeps_tuples():
    cand = make_candidate(rejection_reasons=("out_of_region",))
    restored = from_envelope(envelope(cand), Candidate)
    assert restored == cand
    assert isinstance(restored.tap_point, tuple)
    assert isinstance(restored.rejection_reasons, tuple)


# --------------------------------------------------------------- 定位结果


def test_locate_match_requires_winning_in_ordered():
    with pytest.raises(InvalidDomain):
        LocateResult(LocateStatus.MATCH, "cap-1", "bag", 5)
    with pytest.raises(InvalidDomain):
        other = make_candidate(candidate_id="c2")
        LocateResult(LocateStatus.MATCH, "cap-1", "bag", 5, winning=make_candidate(), ordered=(other,))
    with pytest.raises(InvalidDomain):
        LocateResult(LocateStatus.READ_ERROR, "cap-1", "bag", 5)


# --------------------------------------------------------------- 动作


def test_business_action_requires_focus_and_evidence():
    base = dict(
        action_id="a1",
        run_id="run-1",
        kind=ActionKind.TAP,
        source_capture_id="cap-1",
        state_epoch=3,
        geometry_revision=0,
        deadline_ns=5000,
        reason="点亮胶囊",
    )
    with pytest.raises(InvalidDomain):
        ActionIntent(**base)
    intent = ActionIntent(
        **base,
        source_candidate_id="c1",
        expected_package=PKG,
        required_window_kind=WindowKind.APP,
    )
    assert intent.kind is ActionKind.TAP
    with pytest.raises(InvalidDomain):
        ActionIntent(**{**base, "kind": ActionKind.WAKE}, source_candidate_id="c1")


def test_unknown_execution_requires_error_code():
    with pytest.raises(InvalidDomain):
        ActionReceipt("a1", ExecutionStatus.UNKNOWN_EXECUTION, 10, 20)
    receipt = ActionReceipt("a1", ExecutionStatus.UNKNOWN_EXECUTION, 10, 20, error_code="reply_lost")
    assert from_envelope(envelope(receipt), ActionReceipt) == receipt


# --------------------------------------------------------------- 信封


def test_envelope_rejects_wrong_type_and_schema():
    cap = make_capture()
    data = envelope(cap)
    assert data["schema_version"] == 1 and data["type"] == "Capture"
    with pytest.raises(InvalidDomain):
        from_envelope(data, Candidate)
    with pytest.raises(InvalidDomain):
        from_envelope({**data, "schema_version": 99}, Capture)


def test_strict_fields_reject_unknown_key():
    data = envelope(make_capture())["data"]
    data["extra"] = 1
    with pytest.raises(InvalidDomain, match="字段不匹配"):
        Capture.from_jsonable(data)
