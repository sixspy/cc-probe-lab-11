# -*- coding: utf-8 -*-
"""probe-11 · 之三：争用锁、串扰隔离只读接口、HTTP 双请求、五页可见。

覆盖题面：
- 争用失败测：两探头并发双写同键则红（不加锁会双成功）；
- 新增串扰隔离只读接口；
- 并发双请求脚本；
- 站点源目录 / 入栏缓冲列表 / 站点汇总账详情 / 报文流卡片（及隔离页）页面可见探头隔离。
"""
import threading
from pathlib import Path

from app.services import 装载, 目录

站 = "站-河东"
指标 = "PM25"


def _body(probe, mid, key, read=12.0):
    return {"批次编号": f"race-{mid}", "报文": [{
        "报文编号": mid,
        "站点键": 站,
        "指标键": 指标,
        "读数": read,
        "观测时": "2026-11-24T10:00:00Z",
        "探头键": probe,
        "隔离键": key,
    }]}


def test_争用_钉住原语_两探头只一成功():
    from app.services import 隔离
    key = "隔:RACE-PRIM"
    bar = threading.Barrier(2)
    out = []

    def work(probe):
        bar.wait(5)
        out.append(隔离.钉住隔离键(key, probe, 站点键=站, 指标键=指标))

    ts = [threading.Thread(target=work, args=(p,)) for p in ("R-A", "R-B")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
        assert not t.is_alive(), "争用线程不得挂死"

    wins = [r for r in out if r["成功"]]
    assert len(wins) == 1, f"同键两探头并发钉住必须只一成功，实际 {out}"
    assert sum(1 for r in out if r.get("冲突")) == 1

    属 = {x["隔离键"]: x["探头键"] for x in 隔离.账册列表() if x["隔离键"] == key}
    assert 属 == {key: wins[0]["探头键"]}


def test_争用_并发装一批_同键异探头不得双成功():
    from app.services import 隔离
    for 轮 in range(3):
        key = f"隔:RACE-LOAD-{轮}"
        bar = threading.Barrier(2)
        reps = {}

        def work(probe, mid, read):
            bar.wait(5)
            reps[probe] = 装载.装一批(_body(probe, mid, key, read))

        ta = threading.Thread(target=work, args=("C-A", f"ra-{轮}-a", 11.0))
        tb = threading.Thread(target=work, args=("C-B", f"ra-{轮}-b", 70.0))
        ta.start(); tb.start()
        ta.join(15); tb.join(15)
        assert not ta.is_alive() and not tb.is_alive()

        正式 = sum(r["入栏"] for r in reps.values())
        assert 正式 == 1, f"第{轮}轮同键双探头并发出现双成功：{reps}"
        assert sum(r.get("串扰", 0) for r in reps.values()) == 1

        rows = [r for r in 目录.缓冲列表() if r.get("隔离键") == key]
        assert len(rows) == 1, "争用键只应有赢家一笔正式缓冲"
        assert len({r.get("探头键") for r in rows}) == 1, "并发不得同键双探头"

        账 = [x for x in 隔离.账册列表() if x["隔离键"] == key]
        assert len(账) == 1 and 账[0]["探头键"] == rows[0]["探头键"]


def test_只读隔离态势_结构齐全且只读():
    装载.装一批({"批次编号": "iso3-sit", "报文": [
        {"报文编号": "sit-a", "站点键": 站, "指标键": 指标, "读数": 10.0,
         "观测时": "2026-11-24T11:00:00Z", "探头键": "P-A"},
        {"报文编号": "sit-b", "站点键": 站, "指标键": 指标, "读数": 12.0,
         "观测时": "2026-11-24T11:01:00Z", "探头键": "P-B"},
    ]})
    from app.services import 隔离
    s = 隔离.隔离态势()
    for k in ("现行键集合", "账册", "归档", "影子对账", "策略", "工程形态"):
        assert k in s, f"只读态势缺 {k}"
    assert s.get("只读") is True
    # 两个探头键可区分。
    assert len({x["探头键"] for x in s["现行键集合"]}) >= 2


async def test_HTTP_串扰隔离只读接口_200():
    import httpx
    from app.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        for path in ("/api/串扰隔离", "/api/多探头串扰隔离", "/api/探头隔离"):
            r = await c.get(path)
            assert r.status_code == 200, path
            data = r.json()
            assert "现行键集合" in data


async def test_HTTP_并发双POST同键_只一正式成功():
    import asyncio
    import httpx
    from app.main import app
    key = "隔:HTTP-RACE"
    ba = _body("H-A", "http-a", key, 11.0)
    bb = _body("H-B", "http-b", key, 70.0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        ra, rb = await asyncio.gather(
            c.post("/api/观测报文/装载", json=ba),
            c.post("/api/观测报文/装载", json=bb),
        )
    assert ra.status_code == 200 and rb.status_code == 200
    正式 = ra.json()["入栏"] + rb.json()["入栏"]
    assert 正式 == 1, "HTTP 双请求并发同键不得双成功"


def test_五页_页面源码可见探头隔离():
    import app.main as m
    static = Path(m.__file__).resolve().parent / "static"
    pages = [
        "站点源.html",
        "入栏缓冲.html",
        "站点汇总账.html",
        "报文流.html",
        "串扰隔离.html",
    ]
    for name in pages:
        txt = (static / name).read_text(encoding="utf-8")
        assert "探头" in txt, f"{name} 须可见探头标识"
        assert "隔离" in txt, f"{name} 须可见探头隔离"


def test_并发双请求脚本_存在():
    root = Path(__file__).resolve().parents[2]
    脚本 = root / "scripts" / "并发双请求.py"
    assert 脚本.is_file(), "题面要求并发双请求脚本"
    txt = 脚本.read_text(encoding="utf-8")
    assert "串扰隔离" in txt or "隔离键" in txt
