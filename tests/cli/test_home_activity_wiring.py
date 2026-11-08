"""生产回归（2026-11-08 首跑翻车）：run 的 AdbDevice 必须带显式 home_activity，
否则 ensure_ready 的 start 一枪被护栏拒绝 → rc7/进程失败。"""

from __future__ import annotations

import inspect

from pddcheck.cli import app


def test_run_passes_explicit_home_activity_to_adb_device():
    """护栏口径：AdbDevice 构造必须传 home_activity=cfg.home_activity。"""
    src = inspect.getsource(app)
    assert "AdbDevice(" in src
    assert "home_activity=cfg.home_activity" in src


def test_pipeline_config_has_real_home_activity_default():
    from pddcheck.cli.bootstrap import PipelineConfig
    cfg = PipelineConfig(business_date="2026-11-08", run_id="r",
                         evidence_dir="/tmp/ev", endpoint=None)
    assert cfg.home_activity == "com.xunmeng.pinduoduo.ui.activity.HomeActivity"
