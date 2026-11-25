#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并发双请求脚本：两探头并发灌「同一个入栏隔离键」，断言只一正式成功。

用法：
    python3 scripts/并发双请求.py [base_url]
默认 base_url=http://127.0.0.1:8200 （docker compose 把容器 8100 映到 8200）。

判据（题面争用失败测的 HTTP 版）：
- 两个并发 POST /api/观测报文/装载，携带同一「隔离键」、不同「探头键」；
- 不加锁会 check-then-insert 双成功；正确实现须 入栏 合计恰为 1，
  输的一方 串扰=1 / 驳回=1，并进只读「串扰隔离」归档；
- 随后 GET /api/串扰隔离 复核：该键账册只一个探头，归档有邻探头。
脚本在双成功时以退出码 1 失败（可接 CI / 五页核后的并发核验）。
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
import urllib.parse
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8200"
RUN = uuid.uuid4().hex[:8]
KEY = f"隔:HTTP-并发-{RUN}"

results: dict[str, dict] = {}
barrier = threading.Barrier(2)


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    # 中文路由需百分号编码，否则 http.client 按 ascii 写请求行报错。
    parts = urllib.parse.urlsplit(path)
    safe_path = urllib.parse.quote(parts.path, safe="/%")
    safe_query = urllib.parse.quote(parts.query, safe="=&%")
    url = BASE + urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, safe_path, safe_query, parts.fragment)
    ) if parts.scheme else BASE + safe_path + (("?" + safe_query) if safe_query else "")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _body(probe: str, mid: str, read: float) -> dict:
    return {"批次编号": f"并发-{probe}-{RUN}", "报文": [{
        "报文编号": mid,
        "站点键": "站-河东",
        "指标键": "PM25",
        "读数": read,
        "观测时": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "探头键": probe,
        "隔离键": KEY,
    }]}


def worker(probe: str, mid: str, read: float) -> None:
    barrier.wait(5)  # 尽量同时打出两个请求，放大 check-then-act 竞态
    try:
        results[probe] = _req("POST", "/api/观测报文/装载", _body(probe, mid, read))
    except Exception as exc:  # noqa: BLE001
        results[probe] = {"_异常": repr(exc)}


def main() -> int:
    ta = threading.Thread(target=worker, args=(f"并发甲-{RUN}", f"cc-a-{RUN}", 11.0))
    tb = threading.Thread(target=worker, args=(f"并发乙-{RUN}", f"cc-b-{RUN}", 70.0))
    ta.start(); tb.start(); ta.join(25); tb.join(25)

    print("== 双请求装载回执 ==")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    if any("_异常" in r for r in results.values()):
        print("FAIL: 有请求异常")
        return 2

    formal = sum(int(r.get("入栏", 0)) for r in results.values())
    cross = sum(int(r.get("串扰", 0)) for r in results.values())
    print(f"正式入栏合计={formal}  串扰合计={cross}  争用键={KEY}")

    ok = formal == 1 and cross == 1

    try:
        iso = _req("GET", "/api/串扰隔离")
        账 = [x for x in iso.get("账册", []) if x.get("隔离键") == KEY]
        档 = [x for x in iso.get("归档", []) if x.get("隔离键") == KEY]
        print("== 隔离账册（争用键）==")
        print(json.dumps(账, ensure_ascii=False, indent=2))
        print(f"归档邻探头条数={len(档)}")
        if len(账) != 1:
            ok = False
            print(f"FAIL: 争用键账册应恰 1 行，实际 {len(账)}")
        if len({x.get('探头键') for x in 账}) != 1:
            ok = False
            print("FAIL: 并发同键出现两个探头")
        if len(档) < 1:
            ok = False
            print("FAIL: 双写形态要求归档有邻探头")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: 复核 /api/串扰隔离 失败：{exc!r}")

    print("PASS: 两探头并发同键只一正式成功，串扰进只读归档" if ok
          else "FAIL: 出现双成功或隔离/归档不符合预期")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
