#!/usr/bin/env python3
"""通讯录管理工具：导入、搜索、ASR 人名纠错。

Usage:
  python3 contacts_tool.py import <md_file_or_dir>   # 从 Markdown 通讯录导入
  python3 contacts_tool.py search <query>             # 模糊搜索联系人
  python3 contacts_tool.py correct <garbled_name>     # ASR 纠错：匹配最接近的真名
  python3 contacts_tool.py alias <real_name> <asr_variant>  # 添加误识别映射
  python3 contacts_tool.py add <name> [--group G] [--team T] [--position P] [--phone PH] [--email E] [--note N]
  python3 contacts_tool.py get <name>                 # 查看联系人详情
  python3 contacts_tool.py stats                      # 统计信息
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(os.getenv("CONTACTS_DB", "./contacts.db"))


# ── 数据库 ──────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            group_name TEXT DEFAULT 'work',
            team TEXT DEFAULT '',
            position TEXT DEFAULT '',
            employee_id TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            note TEXT DEFAULT '',
            source TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(name, team)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            real_name TEXT NOT NULL,
            alias TEXT NOT NULL,
            hit_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(real_name, alias)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias)")
    conn.commit()
    return conn


# ── 导入 ──────────────────────────────────────────────────

COLUMN_MAP = {
    "姓名": "name",
    "名字": "name",
    "员工编号": "employee_id",
    "一事通ID": "employee_id",
    "一事通id": "employee_id",
    "职位": "position",
    "座机": "phone",
    "座机/IP电话": "phone",
    "IP电话": "phone",
    "手机": "phone",
    "邮箱": "email",
    "岗位描述": "note",
    "备注": "note",
    "状态": "_skip",
    "序号": "_skip",
}


def _parse_md_list(filepath: Path) -> list[dict]:
    """解析列表格式的通讯录（每人一个 ### 段落）。"""
    text = filepath.read_text(encoding="utf-8")

    team = ""
    title_match = re.search(r"^#\s+(.+?)(?:通讯录)?$", text, re.M)
    if title_match:
        team = title_match.group(1).strip()

    field_map = {
        "员工编号": "employee_id", "一事通ID": "employee_id", "一事通id": "employee_id",
        "职位": "position", "手机": "phone", "IP电话": "_landline",
        "座机": "_landline", "邮箱": "email", "岗位描述": "note",
    }

    results = []
    # 按 ### 切分
    sections = re.split(r"^###\s+\d+\.\s+", text, flags=re.M)

    for sec in sections[1:]:  # 跳过第一段（标题前的内容）
        lines = sec.strip().splitlines()
        if not lines:
            continue
        name = lines[0].strip()
        row = {"name": name, "team": team, "source": filepath.name}
        landline = ""

        for line in lines[1:]:
            line = line.strip().lstrip("- ").replace("**", "")
            if "：" not in line and ":" not in line:
                continue
            key, val = re.split(r"[：:]", line, 1)
            key = key.strip()
            val = val.strip().replace("--", "").strip()
            if not val or val == "-":
                continue

            for cn_key, field in field_map.items():
                if cn_key in key:
                    if field == "_landline":
                        landline = val
                    else:
                        row[field] = val
                    break

        # 如果没有手机号，用座机
        if "phone" not in row and landline:
            row["phone"] = landline

        if name:
            results.append(row)

    return results


def _parse_md_table(filepath: Path) -> list[dict]:
    """解析 Markdown 文件中的通讯录（自动检测表格或列表格式）。"""
    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 从文件名或内容提取团队名
    team = ""
    title_match = re.search(r"^#\s+(.+?)(?:通讯录)?$", text, re.M)
    if title_match:
        team = title_match.group(1).strip()

    # 检测格式：有 ### 编号段落 → 列表格式
    if re.search(r"^###\s+\d+\.\s+", text, re.M):
        return _parse_md_list(filepath)

    # 找表格头
    header_idx = None
    for i, line in enumerate(lines):
        if "|" in line and "姓名" in line:
            header_idx = i
            break

    if header_idx is None:
        return []

    # 解析表头
    header_cells = [c.strip() for c in lines[header_idx].split("|")]
    header_cells = [c for c in header_cells if c]

    col_mapping = []
    for cell in header_cells:
        mapped = None
        for cn_name, field in COLUMN_MAP.items():
            if cn_name in cell:
                mapped = field
                break
        col_mapping.append(mapped)

    # 解析数据行（跳过分隔行）
    results = []
    for line in lines[header_idx + 1:]:
        if not line.strip() or "|" not in line:
            continue
        if re.match(r"^\|[\s\-:|]+\|$", line.strip()):
            continue

        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c != ""]

        row = {"team": team, "source": filepath.name}
        phone_parts = []

        for j, cell in enumerate(cells):
            if j >= len(col_mapping) or col_mapping[j] is None or col_mapping[j] == "_skip":
                continue
            field = col_mapping[j]
            val = cell.strip().replace("- -", "").replace("--", "").strip()
            if not val or val == "-":
                continue

            if field == "phone":
                phone_parts.append(val)
            else:
                row[field] = val

        if phone_parts:
            # 优先用手机号（11位数字），否则用座机
            mobile = None
            landline = None
            for p in phone_parts:
                digits = re.sub(r"[^\d]", "", p)
                if len(digits) == 11 and digits[0] == "1":
                    mobile = p
                else:
                    landline = p
            row["phone"] = mobile or landline or phone_parts[0]

        if "name" in row and row["name"]:
            results.append(row)

    return results


def cmd_import(args):
    """从 Markdown 通讯录导入联系人。"""
    target = Path(args.path)
    files = []

    if target.is_dir():
        files = sorted(target.glob("*通讯录*.md"))
        if not files:
            files = sorted(target.glob("*.md"))
    elif target.is_file():
        files = [target]
    else:
        print(f"路径不存在: {target}", file=sys.stderr)
        return 1

    if not files:
        print("未找到 Markdown 文件", file=sys.stderr)
        return 1

    conn = get_db()
    total_new = 0
    total_updated = 0
    total_skipped = 0

    for f in files:
        contacts = _parse_md_table(f)
        if not contacts:
            print(f"  跳过 {f.name}（未找到通讯录表格）")
            continue

        new = 0
        updated = 0
        for c in contacts:
            name = c.get("name", "")
            team = c.get("team", "")
            if not name:
                continue

            existing = conn.execute(
                "SELECT id FROM contacts WHERE name = ? AND team = ?",
                (name, team)
            ).fetchone()

            if existing:
                # 更新非空字段
                updates = []
                values = []
                for field in ["position", "employee_id", "phone", "email", "note", "source"]:
                    if c.get(field):
                        updates.append(f"{field} = ?")
                        values.append(c[field])
                if updates:
                    values.append(existing["id"])
                    conn.execute(f"UPDATE contacts SET {', '.join(updates)} WHERE id = ?", values)
                    updated += 1
            else:
                conn.execute(
                    """INSERT INTO contacts (name, group_name, team, position, employee_id, phone, email, note, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, args.group or "work", team,
                     c.get("position", ""), c.get("employee_id", ""),
                     c.get("phone", ""), c.get("email", ""),
                     c.get("note", ""), c.get("source", ""))
                )
                new += 1

        conn.commit()
        print(f"  {f.name}: +{new} 新增, ~{updated} 更新, 共 {len(contacts)} 条")
        total_new += new
        total_updated += updated

    total = conn.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"]
    print(f"\n导入完成: +{total_new} 新增, ~{total_updated} 更新, 数据库共 {total} 人")
    conn.close()
    return 0


# ── 搜索 ──────────────────────────────────────────────────

def cmd_search(args):
    """模糊搜索联系人。"""
    conn = get_db()
    query = args.query

    # 精确匹配
    rows = conn.execute(
        "SELECT * FROM contacts WHERE name = ?", (query,)
    ).fetchall()

    if not rows:
        # LIKE 匹配
        rows = conn.execute(
            "SELECT * FROM contacts WHERE name LIKE ?", (f"%{query}%",)
        ).fetchall()

    if not rows:
        # 模糊匹配：取所有名字做 difflib
        all_names = conn.execute("SELECT DISTINCT name FROM contacts").fetchall()
        name_list = [r["name"] for r in all_names]
        close = difflib.get_close_matches(query, name_list, n=5, cutoff=0.4)
        if close:
            placeholders = ",".join("?" * len(close))
            rows = conn.execute(
                f"SELECT * FROM contacts WHERE name IN ({placeholders})", close
            ).fetchall()

    if not rows:
        # 查 aliases
        alias_rows = conn.execute(
            "SELECT real_name FROM aliases WHERE alias = ? OR alias LIKE ?",
            (query, f"%{query}%")
        ).fetchall()
        if alias_rows:
            names = list(set(r["real_name"] for r in alias_rows))
            placeholders = ",".join("?" * len(names))
            rows = conn.execute(
                f"SELECT * FROM contacts WHERE name IN ({placeholders})", names
            ).fetchall()

    if not rows:
        print(f"未找到匹配「{query}」的联系人")
        return 0

    for r in rows:
        parts = [f"**{r['name']}**"]
        if r["position"]:
            parts.append(r["position"])
        if r["team"]:
            parts.append(f"[{r['team']}]")
        if r["phone"]:
            parts.append(f"📱 {r['phone']}")
        if r["email"]:
            parts.append(f"✉️ {r['email']}")
        if r["note"]:
            parts.append(f"({r['note'][:50]})")
        print(" | ".join(parts))

    conn.close()
    return 0


# ── ASR 纠错 ──────────────────────────────────────────────

def cmd_correct(args):
    """ASR 人名纠错：从 aliases 和 contacts 中找最接近的真名。"""
    conn = get_db()
    garbled = args.name

    # 1. 先查 aliases 精确匹配（最快）
    alias_row = conn.execute(
        "SELECT real_name, hit_count FROM aliases WHERE alias = ? ORDER BY hit_count DESC LIMIT 1",
        (garbled,)
    ).fetchone()
    if alias_row:
        conn.execute(
            "UPDATE aliases SET hit_count = hit_count + 1 WHERE alias = ? AND real_name = ?",
            (garbled, alias_row["real_name"])
        )
        conn.commit()
        print(f"✅ {garbled} → {alias_row['real_name']}（已知映射，命中 {alias_row['hit_count'] + 1} 次）")
        conn.close()
        return 0

    # 2. 精确匹配 contacts
    exact = conn.execute("SELECT name FROM contacts WHERE name = ?", (garbled,)).fetchone()
    if exact:
        print(f"✅ {garbled}（精确匹配）")
        conn.close()
        return 0

    # 3. 模糊匹配 contacts
    all_names = conn.execute("SELECT DISTINCT name FROM contacts").fetchall()
    name_list = [r["name"] for r in all_names]

    # 也把 aliases 的 real_name 加进来
    all_aliases = conn.execute("SELECT DISTINCT real_name FROM aliases").fetchall()
    for r in all_aliases:
        if r["real_name"] not in name_list:
            name_list.append(r["real_name"])

    close = difflib.get_close_matches(garbled, name_list, n=5, cutoff=0.3)

    # 优先同姓：如果 garbled 的第一个字和某个候选的第一个字相同，优先级更高
    if close and garbled:
        same_surname = [n for n in close if n[0] == garbled[0]]
        diff_surname = [n for n in close if n[0] != garbled[0]]
        close = same_surname + diff_surname

    if close:
        best = close[0]
        diff_count = sum(a != b for a, b in zip(garbled, best)) if len(garbled) == len(best) else 99
        if len(close) == 1 or diff_count <= 1:
            print(f"✅ {garbled} → {best}（模糊匹配）")
            if len(close) > 1:
                print(f"   候选: {', '.join(close[:3])}")
        else:
            print(f"❓ {garbled} 可能是: {', '.join(close[:3])}")
            print(f"   最可能: {best}")
    else:
        print(f"❌ 未找到匹配「{garbled}」的联系人")
        # 列出拼音相近的（同音字场景）
        similar = _find_pinyin_similar(garbled, name_list)
        if similar:
            print(f"   拼音相近: {', '.join(similar)}")

    conn.close()
    return 0


def _find_pinyin_similar(query: str, names: list[str]) -> list[str]:
    """简单的同音字匹配：逐字比较，允许同音替换。"""
    # 简化版：只比较字数相同的名字，允许 1-2 个字不同
    results = []
    for name in names:
        if len(name) != len(query):
            continue
        diff = sum(1 for a, b in zip(query, name) if a != b)
        if 0 < diff <= 2:
            results.append(name)
    return results[:5]


# ── 别名管理 ──────────────────────────────────────────────

def cmd_alias(args):
    """添加 ASR 误识别映射。"""
    conn = get_db()
    real_name = args.real_name
    alias = args.alias_name

    # 检查 real_name 是否存在
    exists = conn.execute("SELECT 1 FROM contacts WHERE name = ?", (real_name,)).fetchone()
    if not exists:
        print(f"⚠️  联系人「{real_name}」不在数据库中，仍然添加映射")

    try:
        conn.execute(
            "INSERT INTO aliases (real_name, alias) VALUES (?, ?)",
            (real_name, alias)
        )
        conn.commit()
        print(f"✅ 已添加映射: {alias} → {real_name}")
    except sqlite3.IntegrityError:
        conn.execute(
            "UPDATE aliases SET hit_count = hit_count + 1 WHERE real_name = ? AND alias = ?",
            (real_name, alias)
        )
        conn.commit()
        print(f"✅ 映射已存在，命中次数 +1: {alias} → {real_name}")

    conn.close()
    return 0


# ── 添加联系人 ──────────────────────────────────────────────

def cmd_add(args):
    """手动添加联系人。"""
    conn = get_db()

    try:
        conn.execute(
            """INSERT INTO contacts (name, group_name, team, position, phone, email, note, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'manual')""",
            (args.name, args.group or "personal", args.team or "",
             args.position or "", args.phone or "", args.email or "", args.note or "")
        )
        conn.commit()
        print(f"✅ 已添加: {args.name} [{args.group or 'personal'}]")
    except sqlite3.IntegrityError:
        print(f"⚠️  联系人「{args.name}」已存在（同名同团队）")
        return 1

    conn.close()
    return 0


# ── 查看详情 ──────────────────────────────────────────────

def cmd_get(args):
    """查看联系人详情。"""
    conn = get_db()

    rows = conn.execute("SELECT * FROM contacts WHERE name = ?", (args.name,)).fetchall()
    if not rows:
        # 模糊匹配
        rows = conn.execute("SELECT * FROM contacts WHERE name LIKE ?", (f"%{args.name}%",)).fetchall()
    if not rows:
        # 查 aliases
        alias_rows = conn.execute("SELECT real_name FROM aliases WHERE alias = ?", (args.name,)).fetchall()
        if alias_rows:
            real = alias_rows[0]["real_name"]
            rows = conn.execute("SELECT * FROM contacts WHERE name = ?", (real,)).fetchall()

    if not rows:
        print(f"未找到「{args.name}」")
        return 1

    for r in rows:
        print(f"姓名: {r['name']}")
        if r["group_name"]:
            print(f"分组: {r['group_name']}")
        if r["team"]:
            print(f"团队: {r['team']}")
        if r["position"]:
            print(f"职位: {r['position']}")
        if r["employee_id"]:
            print(f"工号: {r['employee_id']}")
        if r["phone"]:
            print(f"电话: {r['phone']}")
        if r["email"]:
            print(f"邮箱: {r['email']}")
        if r["note"]:
            print(f"备注: {r['note']}")
        print(f"来源: {r['source']}")

        # 显示 aliases
        aliases = conn.execute(
            "SELECT alias, hit_count FROM aliases WHERE real_name = ? ORDER BY hit_count DESC",
            (r["name"],)
        ).fetchall()
        if aliases:
            alias_str = ", ".join(f"{a['alias']}({a['hit_count']})" for a in aliases)
            print(f"ASR别名: {alias_str}")

        print("---")

    conn.close()
    return 0


# ── 统计 ──────────────────────────────────────────────────

def cmd_stats(args):
    """统计信息。"""
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"]
    groups = conn.execute(
        "SELECT group_name, COUNT(*) c FROM contacts GROUP BY group_name ORDER BY c DESC"
    ).fetchall()
    teams = conn.execute(
        "SELECT team, COUNT(*) c FROM contacts WHERE team != '' GROUP BY team ORDER BY c DESC LIMIT 10"
    ).fetchall()
    alias_count = conn.execute("SELECT COUNT(*) c FROM aliases").fetchone()["c"]
    top_aliases = conn.execute(
        "SELECT real_name, alias, hit_count FROM aliases ORDER BY hit_count DESC LIMIT 5"
    ).fetchall()

    print(f"📊 通讯录统计")
    print(f"联系人总数: {total}")
    print(f"ASR 别名数: {alias_count}")
    print()

    if groups:
        print("按分组:")
        for g in groups:
            print(f"  {g['group_name']}: {g['c']} 人")

    if teams:
        print("\n按团队 (Top 10):")
        for t in teams:
            print(f"  {t['team']}: {t['c']} 人")

    if top_aliases:
        print("\n高频 ASR 纠错:")
        for a in top_aliases:
            print(f"  {a['alias']} → {a['real_name']} ({a['hit_count']} 次)")

    conn.close()
    return 0


# ── CLI ──────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="通讯录管理工具：导入、搜索、ASR 人名纠错",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    p_import = sub.add_parser("import", help="从 Markdown 通讯录导入")
    p_import.add_argument("path", help="Markdown 文件或目录路径")
    p_import.add_argument("--group", default="work", help="分组名（默认 work）")

    p_search = sub.add_parser("search", help="模糊搜索联系人")
    p_search.add_argument("query", help="搜索关键词")

    p_correct = sub.add_parser("correct", help="ASR 人名纠错")
    p_correct.add_argument("name", help="ASR 识别出的名字")

    p_alias = sub.add_parser("alias", help="添加 ASR 误识别映射")
    p_alias.add_argument("real_name", help="正确姓名")
    p_alias.add_argument("alias_name", help="ASR 常见误识别")

    p_add = sub.add_parser("add", help="添加联系人")
    p_add.add_argument("name", help="姓名")
    p_add.add_argument("--group", help="分组（work/personal/kids-school/...）")
    p_add.add_argument("--team", help="团队/部门")
    p_add.add_argument("--position", help="职位")
    p_add.add_argument("--phone", help="电话")
    p_add.add_argument("--email", help="邮箱")
    p_add.add_argument("--note", help="备注")

    p_get = sub.add_parser("get", help="查看联系人详情")
    p_get.add_argument("name", help="姓名")

    sub.add_parser("stats", help="统计信息")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        return 0

    handlers = {
        "import": cmd_import,
        "search": cmd_search,
        "correct": cmd_correct,
        "alias": cmd_alias,
        "add": cmd_add,
        "get": cmd_get,
        "stats": cmd_stats,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
