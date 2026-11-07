"""T10：推送渲染与发送测试——正文五分支逐字对齐、D07 严谨判定、脱敏、单次尝试。"""

from __future__ import annotations

import json

from pddcheck.notify import (
    DeliveryStatus,
    NotificationSender,
    NotifyInput,
    read_endpoint_file,
    render_notification,
)


def _inp(**kw) -> NotifyInput:
    base = dict(rc=0, lit=3, evidence_dir="/e/2026-11-07/100000")
    base.update(kw)
    return NotifyInput(**base)


# --------------------------------------------------------------- 渲染


def test_lit2_body_mentions_manual_and_ledger():
    title, body = render_notification(_inp(lit=2, rc=0, exc_msg="账本已记 0"))
    assert title == "PDD 需人工"
    assert "脚本不代点" in body and "账本已记 0" in body and "证据 /e/" in body


def test_lit4_body_carries_pend_line():
    title, body = render_notification(_inp(lit=4, rc=0, pend_line="点亮任务已完成 3天后可兑换",
                                           pend_msg="账本记成 3"))
    assert title == "PDD 💡"
    assert "点亮任务已完成 3天后可兑换" in body and "账本记成 3" in body


def test_lit3_and_lit1_first_lines():
    _, b3 = render_notification(_inp(lit=3, rc=0))
    assert "三步点完" in b3 and "下滑" in b3
    _, b1 = render_notification(_inp(lit=1, rc=0, done_word="今日已点亮"))
    assert "「今日已点亮」" in b1 and "没重复点" in b1


def test_rc6_body_carries_why_and_last_activity():
    title, body = render_notification(_inp(rc=6, lit=None,
                                           verify_why="进度行的 4 次没变小",
                                           last_activity=None))
    assert title == "PDD ⬛ 退出码 6"
    assert "进度行的 4 次没变小" in body and "读不到" in body


def test_other_rc_body_points_to_runlog():
    title, body = render_notification(_inp(rc=5, lit=None, last_activity="NewPageActivity"))
    assert title == "PDD ❌ 退出码 5"
    assert "NewPageActivity" in body and "run.log" in body


# --------------------------------------------------------------- 发送


def test_no_endpoint_means_zero_attempts():
    sender = NotificationSender(transport=lambda url, t: (_ for _ in ()).throw(AssertionError("不该发")))
    res = sender.send(None, "PDD ✅", "body")
    assert res.status is DeliveryStatus.NO_ENDPOINT and res.attempts == 0


def test_sent_on_json_code_zero():
    seen = {}
    def transport(url, timeout):
        seen["url"] = url
        return 200, json.dumps({"code": 0})
    sender = NotificationSender(transport=transport)
    res = sender.send("http://stub.push/send", "PDD ✅", "正文")
    assert res.status is DeliveryStatus.SENT and res.attempts == 1
    assert "title=PDD" in seen["url"]


def test_http_5xx_is_http_error():
    sender = NotificationSender(transport=lambda url, t: (500, "boom"))
    assert sender.send("http://s/x", "t", "d").status is DeliveryStatus.HTTP_ERROR


def test_200_non_json_is_business_nonzero_d07():
    sender = NotificationSender(transport=lambda url, t: (200, "<html>ok</html>"))
    res = sender.send("http://s/x", "t", "d")
    assert res.status is DeliveryStatus.BUSINESS_NONZERO
    assert res.attempts == 1          # 一次 attempt，绝不重试（I11）


def test_json_business_nonzero_is_failure():
    sender = NotificationSender(transport=lambda url, t: (200, json.dumps({"code": 400})))
    assert sender.send("http://s/x", "t", "d").status is DeliveryStatus.BUSINESS_NONZERO


def test_network_error_redacts_endpoint_token():
    def transport(url, timeout):
        raise ConnectionError("cannot reach https://sctapi.ftqq.com/SCU12345TOKENabcd.send?title=x")
    sender = NotificationSender(transport=transport)
    res = sender.send("https://sctapi.ftqq.com/SCU12345TOKENabcd.send", "t", "d")
    assert res.status is DeliveryStatus.NETWORK_ERROR
    assert "SCU12345TOKENabcd" not in res.error_tail
    assert "<endpoint>" in res.error_tail or "<token>" in res.error_tail


def test_endpoint_file_first_line(tmp_path):
    f = tmp_path / "push.url"
    f.write_text("https://sctapi.ftqq/KEY1.send\n第二行不该读\n", encoding="utf-8")
    assert read_endpoint_file(f) == "https://sctapi.ftqq/KEY1.send"
    assert read_endpoint_file(tmp_path / "absent") is None
