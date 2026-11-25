# -*- coding: utf-8 -*-
"""probe-11 · 之二：结栏 / 站点汇总账 / 影子对账。

覆盖题面：
- 夹具「单探头成片」结出本探头正式均值；
- 夹具「邻探头——双写本键净且归档有邻」；
- 失败测乙：汇总对账把串扰影子均值当本探头正式绿则红；
- 串扰影子均值不得充本探头正式；
- 贯验主链仍对齐（不得改坏 happy path）。
"""
import pytest

from app.services import 装载, 结栏, 目录, 贯验

站 = "站-河东"
指标 = "PM25"


def _ev(编号, 探头, 读数, 分, 隔离键=None):
    e = {
        "报文编号": 编号,
        "站点键": 站,
        "指标键": 指标,
        "读数": 读数,
        "观测时": f"2026-11-24T09:{分:02d}:00Z",
        "探头键": 探头,
    }
    if 隔离键 is not None:
        e["隔离键"] = 隔离键
    return e


def _河东PM25汇总():
    return [
        dict(r)
        for r in 目录.汇总列表()
        if r["站点键"] == 站 and r["指标键"] == 指标
    ]


def test_单探头成片_结出正式均值():
    装载.装一批({"批次编号": "iso2-film", "报文": [
        _ev("f-1", "P-A", 10.0, 1),
        _ev("f-2", "P-A", 12.0, 2),
        _ev("f-3", "P-A", 14.0, 3),
    ]})
    结 = 结栏.结当前栏()
    assert 结["汇总数"] == 1

    rows = _河东PM25汇总()
    assert len(rows) == 1
    assert rows[0].get("探头键") == "P-A"
    assert rows[0]["报文数"] == 3
    assert rows[0]["均值"] == pytest.approx(12.0)
    assert rows[0].get("隔离键")


def test_异探头同指标_汇总分轨不混():
    装载.装一批({"批次编号": "iso2-two", "报文": [
        _ev("t-a1", "P-A", 10.0, 11),
        _ev("t-a2", "P-A", 12.0, 12),
        _ev("t-b1", "P-B", 40.0, 13),
        _ev("t-b2", "P-B", 42.0, 14),
    ]})
    结栏.结当前栏()

    rows = _河东PM25汇总()
    by_probe = {r.get("探头键"): r for r in rows}
    assert set(by_probe) >= {"P-A", "P-B"}
    assert by_probe["P-A"]["报文数"] == 2
    assert by_probe["P-A"]["均值"] == pytest.approx(11.0)
    assert by_probe["P-B"]["报文数"] == 2
    assert by_probe["P-B"]["均值"] == pytest.approx(41.0)


def test_失败测乙_影子均值不得充本探头正式():
    # 本探头 P-A 两点，正式均值 11。
    装载.装一批({"批次编号": "iso2-yi-a", "报文": [
        _ev("yi-a1", "P-A", 10.0, 21),
        _ev("yi-a2", "P-A", 12.0, 22),
    ]})
    键A = next(
        r["隔离键"] for r in 目录.缓冲列表() if r["报文编号"] == "yi-a1"
    )

    # 邻探头 P-B 的高读数硬串本探头键：只准进只读归档为影子，不准正式入栏。
    装载.装一批({"批次编号": "iso2-yi-b", "报文": [
        _ev("yi-b1", "P-B", 70.0, 23, 隔离键=键A),
    ]})

    结栏.结当前栏()

    rows = _河东PM25汇总()
    a = [r for r in rows if r.get("探头键") == "P-A"]
    assert len(a) == 1, "本探头须恰好一条正式汇总"
    assert a[0]["报文数"] == 2, "串扰影子不得计入正式报文数"
    assert a[0]["均值"] == pytest.approx(11.0), "串扰影子均值不得充本探头正式均值"

    # 绝不能出现三点混合均值 (10+12+70)/3 = 30.6667。
    for r in rows:
        assert r["报文数"] != 3
        assert r["均值"] != pytest.approx(30.666666, abs=1e-3)

    # 影子在只读归档里，且对账把「正式均值」与「影子均值」分列。
    from app.services import 隔离
    归档 = 隔离.归档列表()
    邻 = [x for x in 归档 if x["报文编号"] == "yi-b1"]
    assert len(邻) == 1, "双写形态：归档须有邻探头串扰点"
    assert 邻[0].get("探头键") == "P-B"
    assert 邻[0].get("隔离键") == 键A
    assert "影子" in str(邻[0].get("性质", "")) or "串扰" in str(邻[0].get("来源", ""))

    对账 = 隔离.影子对账()
    条 = [x for x in 对账 if x.get("隔离键") == 键A]
    assert 条, "对账须覆盖被串扰的键"
    c = 条[0]
    assert c["正式均值"] == pytest.approx(11.0)
    assert c["正式报文数"] == 2
    assert c["影子均值"] == pytest.approx(70.0)
    assert c["影子数"] >= 1
    assert c.get("是否污染") is False


def test_结栏后主链贯验仍对齐且隔离干净():
    装载.装一批({"批次编号": "iso2-verify", "报文": [
        _ev("v-a1", "P-A", 10.0, 31),
        _ev("v-b1", "P-B", 40.0, 32),
    ]})
    结栏.结当前栏()
    v = 贯验.跑一次()
    assert v["是否对齐"] is True
    # 隔离专项检查不得报撕裂。
    隔离问题 = [s for s in v.get("检查", []) if ("串扰" in s or "探头" in s or "隔离" in s) and "异常" in s]
    assert 隔离问题 == []
