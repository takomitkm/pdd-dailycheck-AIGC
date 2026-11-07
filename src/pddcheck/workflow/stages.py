"""流程段（T11 扩展）：就绪 → 入口(subsidy) → 福袋(bag)，为完整签到补上点亮前的两段。

设计：逻辑与设备解耦——StageRunner 只依赖两个注入：
  read_page() -> PageView        观察一页（焦点包/activity/OCR 文本）
  act(kind, point) -> receipt    执行一个受护栏的动作（start/tap/back）
动作的真实护栏在 AdbDevice（前台校验）里；这里的每一发 tap 都带 expected_package，
不会对错页发动作（intent 校验兜底）。

失败用 StageFailure(rc) 表达：入口连续进不去 → rc4；福袋/证明失败 → rc5；
与 acceptance §5 的 4/5 语义一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from pddcheck.perception import TargetLocateSpec, locate_all, observe_frame
from pddcheck.perception.facts import facts_from_text
from pddcheck.perception.observe import XmlPolicy


class StageFailure(Exception):
    def __init__(self, rc: int, why: str) -> None:
        super().__init__(why)
        self.rc = rc
        self.why = why


@dataclass(frozen=True, slots=True)
class PageView:
    focus_package: str | None
    focus_activity: str | None
    ocr_text: str


class StagePolicy:
    def __init__(self, *, pkg: str, home_activity: str, entry_retry: int = 2,
                 prove_max: int = 3, min_conf: int = 40) -> None:
        self.pkg = pkg
        self.home_activity = home_activity
        self.entry_retry = entry_retry
        self.prove_max = prove_max
        self.min_conf = min_conf


class StageRunner:
    def __init__(self, read_page, act, policy: StagePolicy) -> None:
        self._read = read_page
        self._act = act
        self.policy = policy

    # ---- 就绪：唤醒/启动到 PDD -----------------------------------------
    def ensure_ready(self) -> None:
        v = self._read()
        if v.focus_package == self.policy.pkg:
            return
        # 显式 HOME_ACT 启动（禁止 monkey 兜底）
        self._act("wake", None)
        self._act("dismiss_keyguard", None)
        self._act("start", None)
        v2 = self._read()
        if v2.focus_package != self.policy.pkg:
            raise StageFailure(7, f"launch 后焦点不是 PDD（{v2.focus_package}）")

    # ---- 入口：回到/进入补贴活动页 --------------------------------------
    def enter_subsidy(self, spec: TargetLocateSpec) -> None:
        for attempt in range(self.policy.entry_retry + 1):
            v = self._read()
            if v.focus_activity and v.focus_activity != self.policy.home_activity \
                    and v.focus_package == self.policy.pkg:
                return                                     # 已在活动页
            page = _Page(v.ocr_text)
            res = locate_all(page.frame("entry"), {spec.key: spec}, min_conf=self.policy.min_conf)
            r = res[spec.key]
            if r.winning is not None:
                self._act("tap", r.winning.tap_point)
                v2 = self._read()
                if v2.focus_activity and v2.focus_activity != self.policy.home_activity:
                    return
            if attempt < self.policy.entry_retry:
                self._act("back", None)                    # 退掉遮罩再试
        raise StageFailure(4, "入口连着点还是没进补贴活动页")

    # ---- 福袋：点进福袋页并证明（进度/待兑换/已点亮 任一） ---------------
    def open_bag(self, spec: TargetLocateSpec) -> None:
        for attempt in range(self.policy.prove_max):
            v = self._read()
            page = _Page(v.ocr_text)
            res = locate_all(page.frame("bag"), {spec.key: spec}, min_conf=self.policy.min_conf)
            r = res[spec.key]
            if r.winning is not None:
                self._act("tap", r.winning.tap_point)
                v2 = self._read()
                f = facts_from_text(v2.ocr_text)
                if f.progress_count is not None or f.pend_text or f.done_text:
                    return                                 # 进对了福袋页
            if attempt < self.policy.prove_max - 1:
                self._act("back", None)                    # 轮播另一帧，退一步换一帧
        raise StageFailure(5, "福袋页进不去/证明失败")


class _Page:
    """把一段 OCR 文本包成 locate_all 需要的 ParsedFrame（单通道、无 XML）。

    纯文本 → 合成一行 level=5 的 TSV 词行（坐标取固定框）；生产路径不走这里
    （真实 OCR 给的是 TSV），这里是给流程段做决策用的文本视图。
    """

    def __init__(self, ocr_text: str) -> None:
        self.text = ocr_text

    def frame(self, frame_id: str):
        from pddcheck.domain import CoordinateSource
        from pddcheck.perception.observe import FrameObservation
        tsv = ("5\t1\t1\t1\t1\t1\t0\t0\t400\t40\t92\t"
               + self.text.replace("\t", " ").replace("\n", " ") + "\n")
        return FrameObservation(frame_id, "cap", 1, 720, 1280, xml_text=None,
                                ocr_texts={CoordinateSource.TESSERACT_PAGE: tsv})
