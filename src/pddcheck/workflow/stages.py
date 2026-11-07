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
                 prove_max: int = 3, min_conf: int = 40,
                 allow_coord_fallback: bool = True,
                 step_wait_s: float = 4.0, sleep=None) -> None:
        self.pkg = pkg
        self.home_activity = home_activity
        self.entry_retry = entry_retry
        self.prove_max = prove_max
        self.min_conf = min_conf
        # 坐标兜底（旧脚本同款）：入口是图片、字认不到时用标定坐标。
        # 兜底只允许在**主线**（不在恢复链路）用——旧脚本的 I04/I05 口径。
        self.allow_coord_fallback = allow_coord_fallback
        # 点击后等页面跳转（旧脚本 STEP_WAIT=4）——真机实测：不等就判「没进去」
        self.step_wait_s = step_wait_s
        self._sleep = sleep or (lambda s: __import__("time").sleep(s))

    def wait_step(self) -> None:
        if self.step_wait_s > 0:
            self._sleep(self.step_wait_s)


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
    def scroll_to_top(self, swipes: int = 3) -> None:
        """滑回页面顶部（旧脚本 TOP_RETRY_KEY 的做法）。坐标按 720×1280 点空间的默认比例。"""
        for _ in range(swipes):
            self._act("swipe", (360, 300, 360, 1000))
        self.policy.wait_step()

    def enter_subsidy(self, spec: TargetLocateSpec, *, scroll_to_top=None,
                      swipes: int = 3) -> None:
        """进补贴活动页。

        scroll_to_top：可选回调（滚回页面顶部再认一轮）——旧脚本的做法是
        「认不到字多半页面没在顶端 → 滑到最顶端再认一次」（旧 L1074-1078）。
        没提供该回调时不滚动（纯文本判定环境用）。
        """
        attempts = self.policy.entry_retry + 1
        for attempt in range(attempts):
            v = self._read()
            if v.focus_activity and v.focus_activity != self.policy.home_activity \
                    and v.focus_package == self.policy.pkg:
                return                                     # 已在活动页
            page = _Page(v.ocr_text)
            res = locate_all(page.frame("entry"), {spec.key: spec}, min_conf=self.policy.min_conf)
            r = res[spec.key]
            if r.winning is not None:
                self._act("tap", r.winning.tap_point)
                self.policy.wait_step()                   # 等页面跳转（真机实测必需）
                v2 = self._read()
                if v2.focus_activity and v2.focus_activity != self.policy.home_activity:
                    return
            elif spec.coord is not None and self.policy.allow_coord_fallback:
                # 认不到字就用标定坐标点一次（旧脚本同款：入口是图片，字未必认得到）
                # 护栏：AdbDevice 会校验前台是 pdd，否则拒绝动作。
                pt = (int(spec.coord[0] * 720), int(spec.coord[1] * 1280))
                self._act("tap", pt)
                self.policy.wait_step()                   # 等跳转（真机实测：不等等于没点）
                v2 = self._read()
                if v2.focus_activity and v2.focus_activity != self.policy.home_activity:
                    return
            if attempt < attempts - 1:
                if scroll_to_top is not None and attempt == 0:
                    scroll_to_top(swipes)               # 滑到顶再认一轮
                else:
                    self._act("back", None)                # 退掉遮罩再试
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
                self.policy.wait_step()
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
