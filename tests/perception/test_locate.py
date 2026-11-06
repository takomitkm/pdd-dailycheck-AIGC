"""T12：定位纯函数与旧行为的一致性测试。

夹具形状取自 sandbox/sbx.sh 的 row()（level=5 的 TSV 词行）与 xml-channel-hit 用例，
期望值全部按旧算法手工推演，不是「跑通就行」。
"""

from __future__ import annotations

from pddcheck.domain import (
    BoxPrecision,
    CoordinateSource,
    LocateStatus,
)
from pddcheck.perception import (
    OcrPassInput,
    ParsedFrame,
    TargetLocateSpec,
    locate_candidates,
    longest_common_span,
    normalize,
    ocr_pass_candidates,
    parse_tsv,
    scale_5dp,
    xml_pass_candidates,
    emit_point,
)

# --------------------------------------------------------------- normalize / lcs


def test_normalize_strips_injected_spaces():
    assert normalize("立即 点 亮") == "立即点亮"
    assert normalize("5折 最高减15元 已使用") == "5折最高减15元已使用"
    assert normalize(None) == ""
    assert normalize("抽福袋。") == "抽福袋"        # 标点剥掉


def test_lcs_is_contiguous_span_not_subsequence():
    # 「abcXbc」与「bc」：连续段=2，位置取首个并列处（旧 DP 严格大于更新）
    assert longest_common_span("abcXbc", "bc") == (2, 1)
    # 子序列会给出 3（a,b,c）——连续段语义必须给出 1（a）
    assert longest_common_span("abc", "abc") == (3, 0)
    # 未规范化的原文只有「立即」连续命中 → (2, 0)（这就是为什么打分前必须先 normalize）
    assert longest_common_span("立即 点 亮 视野", "立即点亮") == (2, 0)


def test_normalize_before_lcs_matches_through_noise():
    hay = normalize("立即 点 亮 视野")
    assert longest_common_span(hay, normalize("立即点亮")) == (4, 0)


# --------------------------------------------------------------- TSV 合行


def tsv_row(block: int, line: int, left: int, top: int, w: int, h: int, text: str, conf: int = 92) -> str:
    return f"5\t1\t{block}\t1\t{line}\t1\t{left}\t{top}\t{w}\t{h}\t{conf}\t{text}"


def test_tsv_groups_by_block_par_line_and_inherits_word_boxes():
    tsv = "\n".join([
        tsv_row(1, 1, 60, 880, 110, 40, "抽福袋"),
        "5\t1\t2\t1\t3\t1\t500\t100\t40\t20\t95\t跳过广告",   # 另一行
        "5\t1\t2\t1\t3\t2\t540\t100\t40\t20\t95\t关闭",       # 同行第二词
    ])
    lines = parse_tsv(tsv)
    assert len(lines) == 2
    first = lines[0]
    assert first.normalized_text == "抽福袋"
    assert first.max_conf == 92
    # 词框并集 = 行框（单词）
    assert (first.left, first.top, first.right, first.bottom) == (60, 880, 170, 920)
    second = lines[1]
    assert second.normalized_text == "跳过广告关闭"
    # 每个字符继承整词框（TOKEN_UNION_APPROX 语义）
    assert second.char_boxes[0] == ("跳", (500, 100, 540, 120))
    assert second.char_boxes[4] == ("关", (540, 100, 580, 120))


def test_tsv_skips_dash_and_non_level5():
    tsv = "\n".join([
        tsv_row(1, 1, 10, 10, 10, 10, "-"),
        "4\t1\t1\t1\t1\t1\t1\t1\t1\t1\t99\t不该出现",
        tsv_row(1, 2, 20, 20, 10, 10, "字"),
    ])
    lines = parse_tsv(tsv)
    assert len(lines) == 1 and lines[0].normalized_text == "字"


# --------------------------------------------------------------- OCR 通道


def test_ocr_pass_orders_by_overlap_and_maps_coordinates():
    # 两行都命中「抽福袋」：分数 3 vs 2 → 高分行在前；中心 (115,900) 整页缩放 1:1
    tsv = "\n".join([
        tsv_row(1, 1, 100, 880, 30, 40, "抽福"),           # overlap 2
        tsv_row(2, 2, 100, 890, 30, 20, "抽福袋"),         # overlap 3 → 赢家
    ])
    cands = ocr_pass_candidates(
        "f1", "cap1", 3, OcrPassInput(source=CoordinateSource.TESSERACT_PAGE, tsv_text=tsv),
        "bag", ("抽福袋",), min_overlap=2, min_conf=40)
    assert [c.overlap for c in cands] == [3, 2]
    win = cands[0]
    assert win.tap_point == (115, 900)                      # 中心 (115,900) 截断
    assert win.source is CoordinateSource.TESSERACT_PAGE
    assert win.engine_id == "tesseract-cli"
    assert win.matched_text == "抽福袋"


def test_ocr_pass_max_conf_rule_is_preserved():
    # 行里目标词 conf=10（低于门槛）但同行无关词 conf=99 → max-line 规则放行（旧兼容怪癖）
    tsv = "\n".join([
        tsv_row(1, 1, 100, 880, 30, 40, "抽福袋", conf=10),
        tsv_row(1, 1, 500, 880, 30, 40, "百亿补贴", conf=99),
    ])
    cands = ocr_pass_candidates(
        "f1", "cap1", 3, OcrPassInput(source=CoordinateSource.TESSERACT_PAGE, tsv_text=tsv),
        "bag", ("抽福袋",), min_overlap=3, min_conf=40)
    assert len(cands) == 1 and cands[0].overlap == 3


def test_ocr_pass_band_scale_and_offset_use_5dp_and_truncation():
    # band ×2、偏移 (429,235)（sandbox 的 pill 桶形状）：scale=tap/2 的 5 位小数
    sx = scale_5dp(720, 1440)      # 0.5
    p = OcrPassInput(source=CoordinateSource.BAND, tsv_text=tsv_row(1, 1, 200, 100, 145, 20, "立即点亮"),
                     scale_x=sx, scale_y=sx, offset_x=429, offset_y=235)
    cands = ocr_pass_candidates("f1", "cap1", 3, p, "light", ("立即点亮",), min_overlap=4, min_conf=40)
    c = cands[0]
    # 中心 (272.5,110) → 272.5*0.5+429=565.25 截断 565；110*0.5+235=290
    assert c.tap_point == (565, 290)
    assert c.source is CoordinateSource.BAND
    assert emit_point(272.5, 110, 0.5, 0.5, 429, 235) == (565, 290)


# --------------------------------------------------------------- XML 通道


XML_SH = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" content-desc="百亿补贴" bounds="[60,600][200,660]" />
  <node index="1" text="抽福袋" resource-id="" content-desc="" bounds="[60,880][170,920]" />
</hierarchy>
"""


def test_xml_pass_scores_fields_in_order_and_prefers_clickable():
    cands = xml_pass_candidates("f1", "cap1", 3, XML_SH, "subsidy",
                                ("百亿补贴", "抽福袋"), min_overlap=3)
    assert [c.matched_text for c in cands] == ["百亿补贴", "抽福袋"]
    assert all(c.box_precision is BoxPrecision.ELEMENT for c in cands)
    assert cands[0].tap_point == (130, 630)          # 节点中心，截断
    assert cands[1].tap_point == (115, 900)


def test_xml_resource_id_scores_by_length_of_label_in_raw():
    xml = "<hierarchy><node text='' resource-id='com.xunmeng.pinduoduo.bag.btn' content-desc='' bounds='[0,0][100,50]' /></hierarchy>"
    cands = xml_pass_candidates("f1", "cap1", 3, xml, "bag", ("bag",), min_overlap=3)
    # resource-id 语义：label 在原始串里 → 分 = len(label)=3
    assert cands[0].overlap == 3


# --------------------------------------------------------------- locate 装配


def frame(xml: str | None = None, tsv: str = "", tap=(720, 1280)) -> ParsedFrame:
    passes = (OcrPassInput(source=CoordinateSource.TESSERACT_PAGE, tsv_text=tsv),) if tsv else ()
    return ParsedFrame("f1", "cap1", 3, tap[0], tap[1], xml_text=xml, ocr_passes=passes)


def test_locate_prefers_first_in_region_not_global_best():
    # 行 A overlap=3 但在 region 外；行 B overlap=2 在 region 内 → winner=B（pick() 文件序语义）
    tsv = "\n".join([
        tsv_row(1, 1, 100, 200, 30, 40, "抽福袋"),          # y=220 → region 外
        tsv_row(2, 2, 100, 880, 30, 40, "抽福袋"),          # y=900 → region 内
    ])
    res = locate_candidates(
        frame(tsv=tsv),
        TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                         region=(0.0, 0.35, 1.0, 0.85), coord=(0.13889, 0.69922)),
        min_conf=40)
    assert res.status is LocateStatus.MATCH
    assert res.winning is not None and res.winning.tap_point == (115, 900)
    outside = [c for c in res.ordered if "out_of_region" in c.rejection_reasons]
    assert len(outside) == 1 and outside[0].overlap == 3     # 区外候选留痕


def test_locate_coord_fallback_uses_half_up_rounding():
    # 无任何命中 + bag 坐标 (0.13889,0.69922)：720→int(100.0008+0.5)=100；1280→int(894.9984+0.5)=895
    res = locate_candidates(
        frame(tsv=""),
        TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                         coord=(0.13889, 0.69922)),
        min_conf=40)
    assert res.status is LocateStatus.MATCH
    assert res.winning is not None
    assert res.winning.source is CoordinateSource.CONFIG_COORD
    assert res.winning.tap_point == (100, 895)
    assert res.winning.matched_text is None                   # 坐标兜底没有识别文本


def test_locate_coord_forbidden_when_geometry_unknown():
    f = ParsedFrame("f1", "cap1", 3, 0, 0, ocr_passes=())
    res = locate_candidates(
        f, TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                            coord=(0.13889, 0.69922)), min_conf=40)
    assert res.status is LocateStatus.NO_MATCH
    assert res.error_code == "geometry_unknown"


def test_locate_no_match_keeps_rejected_candidates():
    tsv = tsv_row(1, 1, 100, 200, 30, 40, "抽福袋")
    res = locate_candidates(
        frame(tsv=tsv),
        TargetLocateSpec(key="bag", labels=("抽福袋",), min_overlap=3,
                         region=(0.0, 0.35, 1.0, 0.85), allow_coord=False),
        min_conf=40)
    assert res.status is LocateStatus.NO_MATCH
    assert len(res.ordered) == 1 and res.ordered[0].rejection_reasons == ("out_of_region",)
