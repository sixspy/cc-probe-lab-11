"""多探头串扰隔离（已落地，不再是空桩）。

契约：同站多探头同指标不得混进同一汇总。

工程形态（两轨同体）：
- 切流账册：入栏键按探头钉死，拒回刷无探头键混写（进程锁 + 主键兜底争用）；
- 双写两轨：串扰点进只读「串扰归档」，现行缓冲只读本探头键集，读引用不同。

本包是薄门面，真正编排在 app.services.隔离 与 装载/结栏 里。
"""
from __future__ import annotations

from app.services import 隔离 as _核心

NAME = "多探头串扰隔离"
CONTRACT = "同站多探头同指标不得混进同一汇总"
HOOKS = ("before_load", "after_load", "decide_gate", "before_close", "after_close", "extra_verify_checks")

# 直接转出核心 API，兼容 from app.modules.多探头串扰隔离 import 隔离态势 等。
默认探头键 = _核心.默认探头键
全局锁 = _核心.全局锁
探头串扰冲突 = _核心.探头串扰冲突
钉键结果 = _核心.钉键结果
取探头键 = _核心.取探头键
取声称键 = _核心.取声称键
计算隔离键 = _核心.计算隔离键
计算入栏键 = _核心.计算入栏键
钉住隔离键 = _核心.钉住隔离键
钉住入栏键 = _核心.钉住入栏键
隔离态势 = _核心.隔离态势
态势 = _核心.态势
账册列表 = _核心.账册列表
归档列表 = _核心.归档列表
探头册列表 = _核心.探头册列表
现行键集合 = _核心.现行键集合
影子对账 = _核心.影子对账
隔离检查 = _核心.隔离检查
缓冲按探头 = _核心.缓冲按探头
站点探头映射 = _核心.站点探头映射


def describe() -> dict:
    形态 = "切流账册+双写两轨"
    键模式 = "隔:{栏号}:{站点键}:{指标键}:{探头键}"
    try:
        s = _核心.隔离态势()
        形态 = s.get("工程形态") or s.get("择定形态") or 形态
        键模式 = s.get("隔离键模式") or 键模式
    except Exception:
        # 未初始化库时（如纯导入面检查）仍给出静态契约，不抛。
        s = {}
    return {
        "空桩": NAME,
        "特性": NAME,
        "契约": CONTRACT,
        "钩子": list(HOOKS),
        "默认启用": True,
        "启用": True,
        "工程形态": 形态,
        "择定形态": s.get("择定形态", 形态),
        "只读接口": "/api/串扰隔离",
        "隔离键模式": 键模式,
    }


def before_load(batch: dict) -> dict:
    # 探头缺省由装载层按默认探头兜底；这里仅透传，保持批次结构。
    return batch


def after_load(report: dict) -> dict:
    if isinstance(report, dict):
        report.setdefault("串扰", 0)
        report.setdefault("隔离冲突", 0)
    return report


def decide_gate(event: dict, rules: dict) -> str:
    # 门槛仍由 校验.过门槛 裁决；本钩子只表达隔离去向。
    if _核心.取声称键(event) and not _核心.取探头键(event):
        return "拒混写"
    return "入栏"


def before_close(pen_id: str) -> None:
    return None


def after_close(report: dict) -> dict:
    if isinstance(report, dict):
        report["探头隔离干净"] = not _核心.隔离检查()
    return report


def extra_verify_checks(snapshot: dict | None = None) -> list[str]:
    return _核心.隔离检查()


def __getattr__(name: str):
    # 其余未显式转出的名字，全部委托核心服务，扩大可对接面。
    return getattr(_核心, name)
