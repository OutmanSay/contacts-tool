# contacts-tool

本地通讯录管理 + ASR 人名纠错 | Local contacts manager with ASR name correction

语音输入时人名经常识别错误？这个工具帮你维护一个本地通讯录，越用越准地纠正 ASR 人名错误。

## 解决什么问题

语音输入（ASR）识别中文人名经常出错：
- "陈曦" 被识别为 "陈希"
- "赵琦" 被识别为 "赵奇"
- "林薇" 被识别为 "林为"

传统方案是训练输入法，但太慢。这个工具的思路是：
1. 维护一个结构化的通讯录（SQLite）
2. 用模糊匹配 + 同姓优先找到正确的名字
3. 每次纠正都记录映射，下次直接命中
4. **越用越准**，不依赖输入法训练

## 功能

- **导入** (`import`)：从 Markdown 表格或列表格式的通讯录文件批量导入
- **搜索** (`search`)：模糊搜索联系人（名字、团队、职位）
- **ASR 纠错** (`correct`)：输入错误的名字，返回最接近的真名
- **别名映射** (`alias`)：手动记录 ASR 误识别 → 真名映射
- **添加** (`add`)：手动添加联系人（支持分组：work/personal/kids-school 等）
- **详情** (`get`)：查看联系人完整信息 + ASR 别名历史
- **统计** (`stats`)：总人数、分组分布、高频纠错映射

## 快速开始

```bash
# 安装拼音匹配依赖（推荐，大幅提升纠错准确率）
pip install pypinyin

# 核心功能无额外依赖，只需 Python 3.8+

# 从 Markdown 通讯录导入
python3 contacts_tool.py import /path/to/通讯录目录/

# 搜索联系人
python3 contacts_tool.py search "陈曦"

# ASR 纠错
python3 contacts_tool.py correct "陈希"
# 输出: ✅ 陈希 → 陈曦（拼音匹配）

# 记录误识别映射（下次直接命中）
python3 contacts_tool.py alias "陈曦" "陈希"

# 手动添加联系人
python3 contacts_tool.py add "周然" --group personal --phone "138-0000-0000" --note "大学同学"

# 查看详情
python3 contacts_tool.py get "陈曦"

# 统计
python3 contacts_tool.py stats
```

## 支持的导入格式

### 格式 1：Markdown 表格

```markdown
| 姓名 | 职位 | 手机 | 邮箱 |
|------|------|------|------|
| 陈曦 | 产品经理 | 138-0000-0000 | chenxi@example.com |
```

自动识别的列名：姓名、员工编号、职位、座机、IP电话、手机、邮箱、岗位描述

### 格式 2：Markdown 列表

```markdown
### 1. 陈曦
- 职位：产品经理
- 手机：138-0000-0000
- 邮箱：chenxi@example.com
```

## ASR 纠错原理

```
用户语音输入 "汤乔说要开会"
         ↓
contacts_tool.py correct "汤乔"
         ↓
1. 查 aliases 表（已知映射，毫秒级）     → 命中则直接返回
2. 精确匹配 contacts 表                  → 名字本身就对
3. 拼音匹配（pypinyin，核心）            → 汤乔(tāng qiáo) ≈ 唐桥(táng qiáo) ✅
4. 字形模糊匹配（difflib + 同姓优先）    → 补充候选
5. 合并排序：拼音精确 > 同姓字形 > 拼音相近 > 其他
         ↓
返回: ✅ 汤乔 → 唐桥（拼音匹配）
```

**拼音优先**：ASR 最常见的错误是"音对字错"。通过拼音匹配（忽略声调），能准确识别：
- 延延 → 严言（yán yán）
- 陈希 → 陈曦（chén xī）
- 吴茜 → 吴倩（wú qiàn）
- 汤乔 → 唐桥（táng qiáo）

**同姓优先**：ASR 错误通常只错名不错姓。字形匹配时优先选择同姓的候选人。

**持续学习**：每次 `alias` 记录映射，`correct` 命中 alias 时自动 +1 计数。高频映射优先匹配。

## AI Agent 集成

配合 AI agent（Claude Code、OpenClaw 等），可以在处理语音输入时自动纠错：

1. Agent 收到语音转录的文本
2. 遇到疑似人名，调用 `correct` 查找真名
3. 纠正后自动调用 `alias` 记录映射
4. 会议纪要、语音笔记中的人名同样适用

项目中提供了 `skill.md` 作为 AI agent 技能模板。

## 数据存储

- 数据库：SQLite，默认 `./contacts.db`
- 可通过 `CONTACTS_DB` 环境变量指定路径
- 两张表：`contacts`（联系人）+ `aliases`（ASR 误识别映射）
- 纯本地，无网络请求，无隐私泄露风险

## License

MIT
