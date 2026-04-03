---
name: contacts
description: 通讯录查询与 ASR 人名纠错。搜联系人、查电话邮箱、语音人名纠正。触发词：通讯录、联系人、谁是、电话、邮箱、查人、人名纠正。
metadata:
  openclaw:
    emoji: "📇"
---

# 通讯录管理

通过 `contacts_tool.py` 管理结构化通讯录，支持搜索和 ASR 人名纠错。

```bash
SCRIPTS=~/.openclaw/workspace/scripts
```

## When to Use

✅ 触发场景：
- "XX 的电话/邮箱是什么" / "查一下 XX 的联系方式"
- "谁是 XX" / "XX 是做什么的"
- "搜联系人 XX" / "通讯录里有没有 XX"
- 处理语音输入时遇到疑似人名错误
- 会议纪要中需要确认人名
- "添加联系人 XX" / "把 XX 加到通讯录"

## When NOT to Use

❌ 不触发：
- 查日程（用 gcal skill）
- 发消息（直接用渠道发送）

## 命令

### 搜索联系人

```bash
# 按名字搜索（支持模糊匹配）
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py search "张伟"

# 查看详情
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py get "张伟"
```

### ASR 人名纠错

```bash
# 纠正 ASR 识别错误的名字
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py correct "张卫"

# 手动添加误识别映射（持续积累）
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py alias "张伟" "张卫"
```

### 添加联系人

```bash
# 添加工作联系人
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py add "李明" --group work --team "产品部" --phone "138-0000-0000"

# 添加私人联系人
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py add "王芳" --group personal --note "大学同学"

# 添加孩子相关联系人
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py add "张老师" --group kids-school --note "煎包班主任"
```

### 导入通讯录

```bash
# 从 Markdown 文件或目录批量导入
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py import "/path/to/通讯录.md"
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py import "/path/to/目录/"
```

### 统计

```bash
source ~/.openclaw/.env.local && python3 $SCRIPTS/contacts_tool.py stats
```

## 自动纠错规则

处理语音输入时，如果遇到疑似人名但不确定是否正确：

1. 调用 `correct` 命令查找最接近的真名
2. 如果纠正成功且用户确认，调用 `alias` 记录映射
3. 下次遇到同样的误识别，直接命中（越用越准）

## 交互规则

| 用户说 | 执行 |
|--------|------|
| "XX 电话多少" / "XX 邮箱" | `search` 或 `get` |
| "谁是 XX" / "XX 是哪个团队的" | `get` |
| "把 XX 加到通讯录" | `add` |
| "导入通讯录" | `import` |
| 语音输入中人名疑似有误 | `correct` → 确认后 `alias` |

## Output

| 命令 | 输出 |
|------|------|
| search | 匹配的联系人列表（姓名、职位、团队、电话、邮箱） |
| get | 联系人完整详情 + ASR 别名历史 |
| correct | 纠错结果（✅ 确认 / ❓ 候选 / ❌ 未找到） |
| stats | 总人数、分组统计、高频纠错映射 |

## Environment

- `CONTACTS_DB`：数据库路径（默认 `~/.openclaw/runtime/contacts.db`）
