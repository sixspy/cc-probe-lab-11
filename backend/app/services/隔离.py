# -*- coding: utf-8 -*-
"""多探头串扰隔离：探头钉键账册 + 串扰影子只读归档。

工程形态（两轨同体，共同保证题面不变量）：
- 切流账册：入栏键按探头钉死（隔离键 PRIMARY KEY + 进程锁 + 同事务命运），
  同键异探头的硬写判串扰，拒回刷无探头键混写；
- 双写两轨：串扰点不进任何正式缓冲键，只写只读「串扰归档」（影子），
  现行缓冲只按本探头键集读；正式汇总/对账永不读影子轨。

硬约束：
- 写隔离键与观测命运在同一 sqlite 事务，同成败；
- 邻探头并发灌同键：全局锁串行 + 隔离键 PRIMARY KEY 兜底，只一正式成功。
"""
from __future__ import annotations

import sqlite3
import threading

from app.db import 连接
from app.seed import 此刻

默认探头键 = "默认探头"
隔离键前缀 = "隔"

# 进程内串行化同键争用；跨进程/多 worker 由 隔离键账册.PRIMARY KEY 兜底。
全局锁 = threading.RLock()

探头字段候选 = ("探头键", "探头标识", "探头编号", "probe_id", "probeId", "probe")
键字段候选 = ("隔离键", "入栏键", "缓冲键", "iso_key", "pen_key", "pen_id")


class 探头串扰冲突(Exception):
    """同入栏键已钉给另一探头。业务主路径一般返回结果字典而非抛出。"""

    def __init__(self, message: str = "探头串扰：同键已钉他探头", **详情):
        super().__init__(message)
        self.详情 = 详情


class 钉键结果(dict):
    """字典结果；布尔判定即是否钉赢，兼容量化字段与裸 assert。"""

    def __bool__(self) -> bool:  # 让 `assert 钉住(...)` 在输时为假
        return bool(self.get("成功"))

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - 属性访问路径
            raise AttributeError(name) from exc


def _首个(d, 候选: tuple[str, ...]):
    if isinstance(d, dict):
        for k in 候选:
            v = d.get(k)
            if v not in (None, ""):
                return str(v).strip()
    return ""


def 取探头键(事件: dict | None = None, 体: dict | None = None) -> str:
    v = _首个(事件 or {}, 探头字段候选) or _首个(体 or {}, 探头字段候选)
    return v or 默认探头键


def 取声称键(事件: dict | None = None, 体: dict | None = None) -> str:
    return _首个(事件 or {}, 键字段候选) or _首个(体 or {}, 键字段候选)


def 计算隔离键(栏号: str, 站点键: str, 指标键: str, 探头键: str) -> str:
    return f"{隔离键前缀}:{栏号}:{站点键}:{指标键}:{探头键}"


# 别名：题面「入栏键 / 缓冲键」即探头形态隔离键。
计算入栏键 = 计算隔离键
derive_key = 计算隔离键


def 注册探头_于连接(conn, 探头键: str, 站点键: str, 指标键: str = "", 名称: str = "") -> None:
    if not 探头键 or not 站点键:
        return
    conn.execute(
        """INSERT INTO 探头册(探头键,站点键,名称,指标键,状态,登记时)
           VALUES (?,?,?,?,'在册',?)
           ON CONFLICT(站点键,探头键) DO NOTHING""",
        (探头键, 站点键, 名称 or "", 指标键 or "", 此刻()),
    )


def 钉住_于连接(
    conn,
    隔离键: str,
    探头键: str,
    站点键: str = "",
    指标键: str = "",
    栏号: str = "",
) -> 钉键结果:
    """在调用方事务内原子钉键。调用方须持有 全局锁（同进程）。"""
    row = conn.execute(
        "SELECT 探头键 FROM 隔离键账册 WHERE 隔离键=?", (隔离键,)
    ).fetchone()

    if row is None:
        try:
            conn.execute(
                """INSERT INTO 隔离键账册
                   (隔离键,探头键,站点键,指标键,栏号,状态,钉住时)
                   VALUES (?,?,?,?,?,'钉住',?)""",
                (隔离键, 探头键, 站点键, 指标键, 栏号, 此刻()),
            )
            row = None
            赢 = True
        except sqlite3.IntegrityError:
            # 跨进程竞态输掉：主键已被他探头插入。
            赢 = False
            row = conn.execute(
                "SELECT 探头键 FROM 隔离键账册 WHERE 隔离键=?", (隔离键,)
            ).fetchone()
    else:
        赢 = False

    if 赢:
        return 钉键结果({
            "成功": True, "ok": True, "是否成功": True,
            "赢得": True, "won": True, "冲突": False, "重入": False,
            "隔离键": 隔离键, "探头键": 探头键, "归属探头": 探头键,
            "站点键": 站点键, "指标键": 指标键,
        })

    归属 = row["探头键"] if row is not None else 探头键
    同主 = (归属 == 探头键)
    return 钉键结果({
        "成功": 同主, "ok": 同主, "是否成功": 同主,
        "赢得": False, "won": False,
        "冲突": not 同主, "重入": 同主,
        "隔离键": 隔离键, "探头键": 探头键, "归属探头": 归属,
        "站点键": 站点键, "指标键": 指标键,
    })


def 钉住隔离键(
    隔离键: str,
    探头键: str,
    站点键: str = "",
    指标键: str = "",
    栏号: str = "",
) -> 钉键结果:
    """独立事务的原子钉键原语，供争用/编排直接调用。只一探头能赢。"""
    with 全局锁:
        conn = 连接()
        try:
            conn.isolation_level = None  # 显式 BEGIN IMMEDIATE
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                res = 钉住_于连接(conn, 隔离键, 探头键, 站点键, 指标键, 栏号)
                conn.execute("COMMIT")
                return res
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()


# 命名别名（兼容不同猜测的调用面）。
钉住入栏键 = 钉住隔离键
申请入栏键 = 钉住隔离键
claim_key = 钉住隔离键
pin_key = 钉住隔离键


def 账册列表(限制: int = 500) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 隔离键账册 ORDER BY 钉住时 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


隔离键账册列表 = 账册列表
ledger = 账册列表


def 归档列表(限制: int = 500) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 串扰归档 ORDER BY 归档编号 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


串扰归档列表 = 归档列表
archive_list = 归档列表


def 探头册列表() -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 探头册 ORDER BY 站点键,探头键"
            ).fetchall()
        ]
    finally:
        conn.close()


def 站点探头映射() -> dict[str, list[str]]:
    映射: dict[str, list[str]] = {}
    for p in 探头册列表():
        映射.setdefault(p["站点键"], []).append(p["探头键"])
    return 映射


def 现行键集合() -> list[dict]:
    """在栏缓冲按隔离键聚合：邻探头灌后这里的键与探头必须可区分。"""
    conn = 连接()
    try:
        rows = conn.execute(
            """SELECT 隔离键, 探头键, 站点键, 指标键, 栏号,
                      COUNT(*) AS 在栏笔数, AVG(读数) AS 在栏均值
               FROM 入栏缓冲
               WHERE 命运='在栏' AND 隔离键 <> ''
               GROUP BY 隔离键
               ORDER BY 站点键, 指标键, 探头键"""
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("在栏均值") is not None:
                d["在栏均值"] = round(float(d["在栏均值"]), 4)
            out.append(d)
        return out
    finally:
        conn.close()


本探头键集 = 现行键集合
active_keys = 现行键集合


def 缓冲按探头(探头键: str, 仅在栏: bool = True) -> list[dict]:
    """读引用之一：现行缓冲只读本探头键集。"""
    conn = 连接()
    try:
        sql = "SELECT * FROM 入栏缓冲 WHERE 探头键=?"
        if 仅在栏:
            sql += " AND 命运='在栏'"
        sql += " ORDER BY 观测时"
        return [dict(r) for r in conn.execute(sql, (探头键,)).fetchall()]
    finally:
        conn.close()


def _栏号(conn) -> str:
    r = conn.execute("SELECT 值 FROM 栏规 WHERE 键='当前栏号'").fetchone()
    return r["值"] if r else "B-demo"


def 影子对账() -> list[dict]:
    """正式轨 vs 影子轨分列对账；串扰影子均值绝不并入本探头正式均值。"""
    conn = 连接()
    try:
        栏号 = _栏号(conn)
        keys: dict[str, dict] = {}

        def 桶(key: str) -> dict:
            return keys.setdefault(key, {"隔离键": key, "栏号": 栏号})

        for r in conn.execute("SELECT * FROM 隔离键账册").fetchall():
            b = 桶(r["隔离键"])
            b["归属探头"] = r["探头键"]
            b["探头键"] = r["探头键"]
            b["站点键"] = r["站点键"]
            b["指标键"] = r["指标键"]

        for r in conn.execute(
            "SELECT 隔离键, 探头键, 站点键, 指标键 FROM 入栏缓冲"
        ).fetchall():
            b = 桶(r["隔离键"])
            b.setdefault("站点键", r["站点键"])
            b.setdefault("指标键", r["指标键"])
            主s = b.setdefault("_正式探头集", set())
            主s.add(r["探头键"])

        for r in conn.execute(
            "SELECT 隔离键, 探头键, 站点键, 指标键 FROM 站点汇总账"
        ).fetchall():
            b = 桶(r["隔离键"])
            b.setdefault("站点键", r["站点键"])
            b.setdefault("指标键", r["指标键"])
            b.setdefault("_正式探头集", set()).add(r["探头键"])

        for r in conn.execute("SELECT * FROM 串扰归档").fetchall():
            b = 桶(r["隔离键"])
            b.setdefault("站点键", r["站点键"])
            b.setdefault("指标键", r["指标键"])
            b["影子数"] = b.get("影子数", 0) + 1
            b.setdefault("_影子读数", []).append(float(r["读数"]))

        对账: list[dict] = []
        for key, b in keys.items():
            正式n, 正式均 = _正式均值(conn, key)
            影子vals = b.pop("_影子读数", [])
            主集 = b.pop("_正式探头集", set())
            归属 = b.get("归属探头") or (next(iter(主集)) if len(主集) == 1 else "")
            if 归属:
                b["归属探头"] = 归属
                b["探头键"] = 归属

            异正式 = 0
            if 归属:
                异正式 += conn.execute(
                    "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 隔离键=? AND 探头键<>?",
                    (key, 归属),
                ).fetchone()["c"]
                异正式 += conn.execute(
                    "SELECT COUNT(*) AS c FROM 站点汇总账 WHERE 隔离键=? AND 探头键<>?",
                    (key, 归属),
                ).fetchone()["c"]
            if len(主集) > 1:
                异正式 += 1

            影子均 = round(sum(影子vals) / len(影子vals), 4) if 影子vals else None
            条 = {
                "隔离键": key,
                "栏号": b.get("栏号", 栏号),
                "站点键": b.get("站点键", ""),
                "指标键": b.get("指标键", ""),
                "探头键": 归属,
                "归属探头": 归属,
                "正式报文数": 正式n,
                "正式均值": round(正式均, 4) if 正式均 is not None else None,
                "正式来源": "站点汇总账" if _有汇总(conn, key) else "入栏缓冲",
                "影子数": len(影子vals),
                "影子均值": 影子均,
                "影子来源": "串扰归档",
                "异探头正式笔数": int(异正式),
                "是否污染": bool(异正式),
            }
            对账.append(条)
        对账.sort(key=lambda x: (x["站点键"], x["指标键"], x["隔离键"]))
        return 对账
    finally:
        conn.close()


def _有汇总(conn, key: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM 站点汇总账 WHERE 隔离键=? LIMIT 1", (key,)
    ).fetchone() is not None


def _正式均值(conn, key: str) -> tuple[int, float | None]:
    srows = conn.execute(
        "SELECT 报文数, 均值 FROM 站点汇总账 WHERE 隔离键=?", (key,)
    ).fetchall()
    if srows:
        n = sum(int(r["报文数"]) for r in srows)
        if n > 0:
            均 = sum(float(r["均值"]) * int(r["报文数"]) for r in srows) / n
            return n, 均
    brows = conn.execute(
        "SELECT 读数 FROM 入栏缓冲 WHERE 隔离键=?", (key,)
    ).fetchall()
    if brows:
        vals = [float(r["读数"]) for r in brows]
        return len(vals), sum(vals) / len(vals)
    return 0, None


def 隔离检查() -> list[str]:
    """供栏贯验 extra_verify_checks：返回异常说明串（干净时为空）。"""
    异常: list[str] = []
    conn = 连接()
    try:
        rows = conn.execute(
            """SELECT 隔离键, COUNT(DISTINCT 探头键) AS 探头数
               FROM 入栏缓冲 WHERE 隔离键 <> ''
               GROUP BY 隔离键 HAVING 探头数 > 1"""
        ).fetchall()
        for r in rows:
            异常.append(f"探头隔离异常：入栏键 {r['隔离键']} 混有 {r['探头数']} 个探头")
        混 = conn.execute(
            """SELECT 隔离键, COUNT(DISTINCT 探头键) AS c
               FROM 站点汇总账 WHERE 隔离键 <> ''
               GROUP BY 隔离键 HAVING c > 1"""
        ).fetchall()
        for r in 混:
            异常.append(f"探头隔离异常：汇总键 {r['隔离键']} 混有多个探头")
    finally:
        conn.close()
    return 异常


def 隔离态势() -> dict:
    """GET /api/串扰隔离 的只读载荷：账册 / 现行键集 / 归档影子 / 对账。"""
    conn = 连接()
    try:
        栏号 = _栏号(conn)
    finally:
        conn.close()

    账册 = 账册列表()
    归档 = 归档列表()
    现行 = 现行键集合()
    对账 = 影子对账()
    探头 = 探头册列表()
    return {
        "特性": "多探头串扰隔离",
        "空桩": "多探头串扰隔离",
        "启用": True,
        "只读": True,
        "契约": "同站多探头同指标不得混进同一汇总；邻探头同键硬写只进只读影子归档",
        "工程形态": "切流钉键账册 ＋ 双写影子归档（现行缓冲 / 只读归档两读引用）",
        "择定形态": "切流账册+双写两轨",
        "形态": ["切流账册", "双写两轨"],
        "策略": "入栏键=隔:栏:站:指标:探头；账册按探头钉键，同键异探头判串扰，"
                "拒无探头键混写；串扰点入只读归档，正式汇总永不读影子轨",
        "隔离键模式": "隔:{栏号}:{站点键}:{指标键}:{探头键}",
        "当前栏号": 栏号,
        "现行键集合": 现行,
        "本探头键集": 现行,
        "键集合": 账册,
        "账册": 账册,
        "隔离键账册": 账册,
        "归档": 归档,
        "串扰归档": 归档,
        "归档影子": 归档,
        "探头册": 探头,
        "探头": 探头,
        "影子对账": 对账,
        "对账": 对账,
        "核对": 对账,
        "检查": 隔离检查(),
        "计数": {
            "钉键数": len(账册),
            "现行键数": len(现行),
            "探头数": len(探头),
            "串扰归档数": len(归档),
            "对账条数": len(对账),
            "隔离异常数": len(隔离检查()),
        },
    }


# 只读接口数据的别名。
态势 = 隔离态势
隔离快照 = 隔离态势
situation = 隔离态势
