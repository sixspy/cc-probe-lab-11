# -*- coding: utf-8 -*-
"""probe-11 · 之一：装载 / 入栏缓冲的探头隔离键。

覆盖题面：
- 入栏键择定探头隔离形态，缓冲键与探头标识同票；
- 夹具「单探头成片」；
- 夹具「邻探头——切流本键净」；
- 失败测甲：邻探头正式写入本探头入栏键则红；
- 拒回刷无探头键混写。

先红：旧实现没有 探头键/隔离键，同站同指标全部挤进同一 (站点,指标) 键。
"""
from app.services import 装载, 目录

站 = "站-河东"
指标 = "PM25"


def _ev(编号, 探头=None, 隔离键=None, 读数=12.0, 分=1):
    e = {
        "报文编号": 编号,
        "站点键": 站,
        "指标键": 指标,
        "读数": 读数,
        "观测时": f"2026-11-24T08:{分:02d}:00Z",
    }
    if 探头 is not None:
        e["探头键"] = 探头
    if 隔离键 is not None:
        e["隔离键"] = 隔离键
    return e


def _缓冲():
    return [dict(r) for r in 目录.缓冲列表()]


def test_单探头成片_键钉探头且同票():
    体 = {"批次编号": "iso1-单片", "报文": [
        _ev("s-1", "P-A", 读数=10.0, 分=1),
        _ev("s-2", "P-A", 读数=12.0, 分=2),
        _ev("s-3", "P-A", 读数=14.0, 分=3),
        _ev("s-4", "P-A", 读数=16.0, 分=4),
    ]}
    报告 = 装载.装一批(体)
    assert 报告["入栏"] == 4

    rows = [r for r in _缓冲() if r["报文编号"].startswith("s-")]
    assert len(rows) == 4
    assert {r.get("探头键") for r in rows} == {"P-A"}

    键集 = {r.get("隔离键") for r in rows}
    assert len(键集) == 1, "单探头成片必须共用同一个钉住探头的隔离键"
    键 = next(iter(键集))
    assert 键 and "P-A" in 键, "隔离键形态须含探头标识"
    for r in rows:
        assert r.get("入栏键", r.get("隔离键")) == 键 or r.get("隔离键") == 键


def test_邻探头异探头_现行键集合可区分():
    装载.装一批({"批次编号": "iso1-a", "报文": [
        _ev("ka-1", "P-A", 读数=11.0, 分=11),
        _ev("ka-2", "P-A", 读数=13.0, 分=12),
    ]})
    装载.装一批({"批次编号": "iso1-b", "报文": [
        _ev("kb-1", "P-B", 读数=41.0, 分=13),
        _ev("kb-2", "P-B", 读数=43.0, 分=14),
    ]})

    rows = _缓冲()
    键A = {r["隔离键"] for r in rows if r.get("探头键") == "P-A"}
    键B = {r["隔离键"] for r in rows if r.get("探头键") == "P-B"}
    assert 键A and 键B, "两探头都应入栏"
    assert 键A.isdisjoint(键B), "同站同指标的邻探头不得与本探头共用入栏键"

    # 新增只读隔离接口给出的「现行键集合」须可区分两个探头。
    from app.services import 隔离
    态势 = 隔离.隔离态势()
    现行 = 态势["现行键集合"]
    钉 = {x["隔离键"]: x["探头键"] for x in 现行}
    for k in 键A:
        assert 钉.get(k) == "P-A"
    for k in 键B:
        assert 钉.get(k) == "P-B"
    assert len(键A | 键B) >= 2


def test_失败测甲_邻探头不得正式写入本探头入栏键():
    报告a = 装载.装一批({"批次编号": "iso1-jia-a", "报文": [
        _ev("jia-a1", "P-A", 读数=10.0, 分=21),
    ]})
    assert 报告a["入栏"] == 1

    行a = next(r for r in _缓冲() if r["报文编号"] == "jia-a1")
    键A = 行a["隔离键"]
    assert 键A

    # 邻探头 P-B 拿着本探头 P-A 的入栏键硬写。
    报告b = 装载.装一批({"批次编号": "iso1-jia-b", "报文": [
        _ev("jia-b1", "P-B", 隔离键=键A, 读数=70.0, 分=22),
    ]})

    # 装载侧不得给出 false green：邻探头这一笔不得计作正式入栏。
    assert 报告b["入栏"] == 0, "邻探头写本探头键不得正式入栏"
    assert 报告b.get("串扰", 0) == 1
    assert 报告b["驳回"] >= 1

    键rows = [r for r in _缓冲() if r.get("隔离键") == 键A]
    assert 键rows, "本探头键仍应在"
    assert all(r.get("探头键") == "P-A" for r in 键rows), "本探头键被邻探头污染"
    assert "jia-b1" not in {r["报文编号"] for r in 键rows}
    assert "jia-b1" not in {r["报文编号"] for r in _缓冲()}, "串扰笔不得进任何正式缓冲键"


def test_拒回刷无探头键_混写已钉键():
    装载.装一批({"批次编号": "iso1-mix-a", "报文": [
        _ev("mix-a1", "P-A", 读数=10.0, 分=31),
    ]})
    键A = next(r for r in _缓冲() if r["报文编号"] == "mix-a1")["隔离键"]

    # 回刷一笔：点名要写已钉给 P-A 的键，却不携带探头标识（不同票）。
    报告 = 装载.装一批({"批次编号": "iso1-mix-x", "报文": [
        _ev("mix-x1", None, 隔离键=键A, 读数=12.0, 分=32),
    ]})
    assert 报告["入栏"] == 0, "无探头键不得回刷混写进已钉探头的入栏键"

    键rows = [r for r in _缓冲() if r.get("隔离键") == 键A]
    assert {r.get("探头键") for r in 键rows} == {"P-A"}
    assert "mix-x1" not in {r["报文编号"] for r in _缓冲()}


def test_账册_缓冲键_探头标识同票():
    装载.装一批({"批次编号": "iso1-ledger", "报文": [
        _ev("lg-1", "P-A", 读数=10.0, 分=41),
        _ev("lg-2", "P-B", 读数=20.0, 分=42),
        _ev("lg-3", "P-B", 读数=22.0, 分=43),
    ]})
    from app.services import 隔离
    账册 = {x["隔离键"]: x["探头键"] for x in 隔离.账册列表()}
    assert 账册, "切流账册须按探头钉键"
    for r in _缓冲():
        assert r.get("隔离键") in 账册
        assert 账册[r["隔离键"]] == r.get("探头键"), "缓冲键与探头标识必须同票"
