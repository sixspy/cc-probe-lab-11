from datetime import datetime, timezone
from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 栏规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 站点源 (
  源键 TEXT PRIMARY KEY,
  名称 TEXT NOT NULL,
  介质 TEXT NOT NULL DEFAULT '大气',
  区域 TEXT NOT NULL DEFAULT '',
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 观测报文 (
  报文编号 TEXT PRIMARY KEY,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已装载',
  批次编号 TEXT NOT NULL DEFAULT '',
  探头键 TEXT NOT NULL DEFAULT '默认探头'
);
CREATE TABLE IF NOT EXISTS 入栏缓冲 (
  报文编号 TEXT PRIMARY KEY,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  栏号 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '在栏',
  入栏时 TEXT NOT NULL,
  探头键 TEXT NOT NULL DEFAULT '默认探头',
  隔离键 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 站点汇总账 (
  汇总编号 TEXT PRIMARY KEY,
  栏号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  报文数 INTEGER NOT NULL,
  均值 REAL NOT NULL,
  物化时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已汇总',
  探头键 TEXT NOT NULL DEFAULT '默认探头',
  隔离键 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 坏点匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  报文编号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  原因 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  入匣时 TEXT NOT NULL,
  探头键 TEXT NOT NULL DEFAULT '默认探头'
);
CREATE TABLE IF NOT EXISTS 栏贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  在栏笔数 INTEGER NOT NULL,
  汇总报文数 INTEGER NOT NULL,
  坏点笔数 INTEGER NOT NULL,
  是否对齐 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  入流 INTEGER NOT NULL DEFAULT 0,
  入栏 INTEGER NOT NULL DEFAULT 0,
  坏点 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 结栏批次 (
  编号 TEXT PRIMARY KEY,
  栏号 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  汇总数 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 探头册 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  探头键 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  名称 TEXT NOT NULL DEFAULT '',
  指标键 TEXT NOT NULL DEFAULT '',
  介质 TEXT NOT NULL DEFAULT '',
  状态 TEXT NOT NULL DEFAULT '在册',
  登记时 TEXT NOT NULL,
  UNIQUE(站点键, 探头键)
);
CREATE TABLE IF NOT EXISTS 隔离键账册 (
  隔离键 TEXT PRIMARY KEY,
  探头键 TEXT NOT NULL,
  站点键 TEXT NOT NULL DEFAULT '',
  指标键 TEXT NOT NULL DEFAULT '',
  栏号 TEXT NOT NULL DEFAULT '',
  状态 TEXT NOT NULL DEFAULT '钉住',
  钉住时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 串扰归档 (
  归档编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  报文编号 TEXT NOT NULL,
  隔离键 TEXT NOT NULL,
  归属探头键 TEXT NOT NULL DEFAULT '',
  探头键 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  归档时 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '邻探头串扰',
  性质 TEXT NOT NULL DEFAULT '串扰影子',
  批次编号 TEXT NOT NULL DEFAULT ''
);
"""

# 旧库平滑补列（docker 数据卷里可能是 probe-11 之前的表结构）。
补列清单 = {
    "观测报文": [("探头键", "TEXT NOT NULL DEFAULT '默认探头'")],
    "入栏缓冲": [
        ("探头键", "TEXT NOT NULL DEFAULT '默认探头'"),
        ("隔离键", "TEXT NOT NULL DEFAULT ''"),
    ],
    "站点汇总账": [
        ("探头键", "TEXT NOT NULL DEFAULT '默认探头'"),
        ("隔离键", "TEXT NOT NULL DEFAULT ''"),
    ],
    "坏点匣": [("探头键", "TEXT NOT NULL DEFAULT '默认探头'")],
}


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _已有列(conn, 表: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({表})").fetchall()}


def _迁移补列(conn) -> None:
    for 表, 列s in 补列清单.items():
        现有 = _已有列(conn, 表)
        if not 现有:
            continue
        for 列, 声明 in 列s:
            if 列 not in 现有:
                conn.execute(f"ALTER TABLE {表} ADD COLUMN {列} {声明}")
    # 旧缓冲/汇总行回填探头形态隔离键，保证结栏分组不串。
    conn.execute(
        """UPDATE 入栏缓冲 SET 隔离键 =
           '隔:' || 栏号 || ':' || 站点键 || ':' || 指标键 || ':' || 探头键
           WHERE 隔离键 IS NULL OR 隔离键 = ''"""
    )
    conn.execute(
        """UPDATE 站点汇总账 SET 隔离键 =
           '隔:' || 栏号 || ':' || 站点键 || ':' || 指标键 || ':' || 探头键
           WHERE 隔离键 IS NULL OR 隔离键 = ''"""
    )


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _迁移补列(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 栏规").fetchone()["c"] == 0:
        for k, v in {
            "当前栏号": "B-demo",
            "PM25上限": "75",
            "PM25下限": "0",
            "标定偏移上限": "5",
            "栏策略": "按站点指标汇总均值",
        }.items():
            conn.execute("INSERT INTO 栏规(键,值) VALUES (?,?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 站点源").fetchone()["c"] == 0:
        for row in [
            ("站-河东", "河东大气站", "大气", "城区", "示范站"),
            ("站-湖西", "湖西水质站", "水质", "湖区", "示范站"),
            ("站-北岭", "北岭大气站", "大气", "近郊", "示范站"),
            ("站-江口", "江口大气站", "大气", "河口", "示范站"),
            ("站-林场", "林场微站", "大气", "林区", "示范站"),
        ]:
            conn.execute(
                "INSERT INTO 站点源(源键,名称,介质,区域,说明) VALUES (?,?,?,?,?)",
                row,
            )
    conn.commit()
    conn.close()
