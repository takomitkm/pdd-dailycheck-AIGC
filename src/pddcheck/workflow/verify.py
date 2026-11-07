"""verify_light 的决策核（T11，B04/I09 落点）——pdd.sh:1299-1389 的纯函数化。

输入是执行器按阶段收集的**观察记录**（每阶段至多一条，顺序固定）：
  AFTER_BACK     浏览完 BACK 后读的进度（browse 路径才有）
  AFTER_REENTER  BACK 落频道页、点胶囊回活动页后读的进度
  AFTER_DIRECT   （无 browse 或 BACK 直达时）原地读的进度
  AFTER_POPUP    清浮层后：奖励浮层/pend/done 与再读一次的进度
  AFTER_REENTER_BAG  备用路线（重进福袋页）后读的进度；路线失败单独标记

输出 VerifyOutcome：rc(0|1|4) + lit(3|4|None) + proof_kind + why。
证据分档（I09）：COUNTER_DECREASE / SCREEN_DONE / PRIZE / PENDING /
LEGACY_TEXT_WITHOUT_COUNTER（B04 兼容弱证明，如实标注，不写成数字已核实）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VerifyStage(StrEnum):
    AFTER_BACK = "after_back"
    AFTER_REENTER = "after_reenter"
    AFTER_DIRECT = "after_direct"
    AFTER_POPUP = "after_popup"
    AFTER_REENTER_BAG = "after_reenter_bag"


class ProofKind(StrEnum):
    COUNTER_DECREASE = "counter_decrease"
    SCREEN_DONE = "screen_done"
    PRIZE = "prize"
    PENDING = "pending"
    LEGACY_TEXT_WITHOUT_COUNTER = "legacy_text_without_counter"   # B04 兼容弱证明
    NONE = "none"


@dataclass(frozen=True, slots=True)
class VerifyObservation:
    stage: VerifyStage
    after_count: int | None = None     # 该阶段读到的进度数字（None=读不到）
    done_text: bool = False
    prize_text: bool = False
    pend_text: bool = False
    reenter_failed: bool = False       # 备用路线（重进福袋页）失败


@dataclass(frozen=True, slots=True)
class VerifyOutcome:
    rc: int                            # 0=点亮核实过 / 1=没核实成功(rc6) / 4=待兑换
    lit: int | None                    # 3 / 4 / None
    proof_kind: ProofKind
    why: str


def verify_light_decision(
    before: int | None,
    method: str,                       # 'coord' | 'ocr' | 'xml' | 'band' | 'pill'
    observations: tuple[VerifyObservation, ...],
) -> VerifyOutcome:
    """按旧 verify_light 的阶段顺序判结局。observations 无序也可（按阶段表取）。"""
    by_stage: dict[VerifyStage, VerifyObservation] = {}
    for obs in observations:
        by_stage.setdefault(obs.stage, obs)   # 同阶段重复取第一条（执行器不该重复）

    def after_at(stage: VerifyStage) -> int | None:
        obs = by_stage.get(stage)
        return obs.after_count if obs else None

    after = after_at(VerifyStage.AFTER_BACK)
    if after is None:
        after = after_at(VerifyStage.AFTER_REENTER)

    def text_at(stage: VerifyStage, attr: str) -> bool:
        obs = by_stage.get(stage)
        return bool(obs and getattr(obs, attr))

    # —— 无 browse / BACK 直达：原地判定（旧 L1330-1336）
    if after is None:
        if text_at(VerifyStage.AFTER_DIRECT, "done_text"):
            return VerifyOutcome(0, 3, ProofKind.SCREEN_DONE, "点完读到「已点亮」类字样")
        after = after_at(VerifyStage.AFTER_DIRECT)

    # —— 进度行读不到的救场阶梯（旧 L1339-1359）
    if after is None:
        if text_at(VerifyStage.AFTER_POPUP, "prize_text"):
            return VerifyOutcome(0, 3, ProofKind.PRIZE, "进度行读不到，但奖励浮层在场=点着了的凭据")
        if text_at(VerifyStage.AFTER_POPUP, "pend_text"):
            return VerifyOutcome(4, 4, ProofKind.PENDING, "进度行读不到，页面是任务已完成/待兑换")
        if text_at(VerifyStage.AFTER_POPUP, "done_text"):
            return VerifyOutcome(0, 3, ProofKind.SCREEN_DONE, "点掉浮层读到「已点亮」类字样")
        after = after_at(VerifyStage.AFTER_POPUP)

    # —— 备用路线：重进福袋页（旧 L1361-1373）
    bag_reenter = by_stage.get(VerifyStage.AFTER_REENTER_BAG)
    if after is None and bag_reenter is not None:
        if bag_reenter.reenter_failed:
            return VerifyOutcome(1, None, ProofKind.NONE, "重进福袋页失败，进度读不到")
        after = bag_reenter.after_count

    # —— 前后对比（旧 L1374-1381）
    if before is not None and after is not None:
        if after < before:
            return VerifyOutcome(0, 3, ProofKind.COUNTER_DECREASE,
                                 f"进度从 {before} 次变成 {after} 次")
        return VerifyOutcome(1, None, ProofKind.NONE,
                             f"进度行的 {after} 次没变小（点前 {before} 次），这一枪没打进去")

    # —— 进度行始终读不到（旧 L1382-1388）：坐标枪不能算成功；认到字的枪按旧兼容放行
    if method == "coord":
        return VerifyOutcome(1, None, ProofKind.NONE,
                             "读不到进度行里那个次数，而这一枪只有坐标兜底能打到，无法核实")
    return VerifyOutcome(0, 3, ProofKind.LEGACY_TEXT_WITHOUT_COUNTER,
                         "读不到进度行，但这一枪点的是认到的字，按原样算过（弱证明）")
