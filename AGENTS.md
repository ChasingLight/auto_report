# AGENTS.md — 周报自动化系统

## 项目概述

自动化生成每周工作周报（钉钉格式），面向领导汇报。系统从 Git 仓库和本地 MD 知识库采集数据，通过三阶段 LLM 流水线生成结构化周报草稿，人工审核后粘贴到钉钉。

定位：**预处理工具**。系统汇总所有工作条目并按项目归组，用户自行审阅润色后生成最终周报。

## 技术栈

- Python 3.12 + uv 包管理
- OpenAI Python SDK（兼容千问/DeepSeek/智谱）
- macOS launchd 定时调度
- 包依赖：openai, pyyaml

## 项目结构

```
auto_report/
├── config.yaml                  # 配置文件（API key、仓库路径、作者过滤）
├── pyproject.toml               # uv 项目配置
├── weekly_report.py             # CLI 主入口（三阶段流水线 + Stage 2 交互）
├── collectors/
│   ├── git_collector.py         # Git 数据采集（git log + diff，支持作者过滤）
│   └── md_collector.py          # MD 知识库扫描（支持 YAML frontmatter 和简化首行格式）
├── analyzer/
│   ├── llm_analyzer.py          # LLM 分析引擎（三阶段函数 + 项目归属注入 + 解析器）
│   └── prompts.py               # Stage 1/2/3 独立系统 prompt + user prompt 构建
├── formatter/
│   └── report_formatter.py      # 周报文件保存
├── scripts/
│   └── install_launcher.sh      # launchd 定时任务安装脚本
├── output/                      # 周报草稿输出目录
```

## CLI 用法

```bash
# 默认：三阶段流水线生成本周周报
python weekly_report.py

# 指定日期范围
python weekly_report.py --from 2026-04-28 --to 2026-05-02

# 指定 ISO 周
python weekly_report.py --week 2026-W17

# 交互式补录无痕工作
python weekly_report.py --interactive

# 自动确认 Stage 2 归类，跳过交互
python weekly_report.py --yes

# 回退到原始单阶段模式
python weekly_report.py --mode single

# 调试模式：展示每阶段 prompt，LLM 调用前需手动确认
python weekly_report.py --debug

# 仅采集数据，不调用 LLM
python weekly_report.py --dry-run
```

## 三阶段流水线

```
原始数据 (git + md + manual)
       │
       ▼
┌─ Stage 1: 提取候选条目 ─────────────────┐
│  LLM 逐条翻译 commit/MD → 业务语言       │
│  标签: [fix]/[pref]/[feat]/[noise]      │
│  同主题去重（只保留最新 commit）          │
│  注入项目归属（Git hash → repo name）     │
│  不聚类、不归纳                          │
└──────────────┬──────────────────────────┘
               ▼
┌─ Stage 2: LLM 自动归类 + 用户审核 ───────┐
│  LLM 按项目+类型归类（控制每组 1-2 个）    │
│  所有条目均保留，不做过滤                  │
│  [noise] 条目归入同项目"其他"组           │
│                                           │
│  交互命令: [y]确认 [e N]编辑 [d N]删除    │
│            [q]退出                        │
└──────────────┬──────────────────────────┘
               ▼
┌─ Stage 3: 生成最终周报 ─────────────────┐
│  按项目维度组织输出                        │
│  每个子条目独占一行（不合并）              │
│  few-shot 风格模仿 + 反 hallucination     │
└──────────────┬──────────────────────────┘
               ▼
          保存 → 打开编辑器
```

**回退**：`--mode single` 使用原始单阶段 `generate()`。

## 核心设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| Git 数据获取 | 本地 clone + git log/diff | 内网 GitLab |
| MD 知识库采集 | frontmatter date 必填 | 避免噪音；支持简化首行格式 |
| 项目归属 | 程序注入（hash → repo + MD project 字段） | 确定性，不依赖 LLM |
| 生成策略 | 不做过滤，全部汇总 | 系统定位为预处理，用户自行润色 |
| 条目展示 | 子条目独占一行，不合并 | 保证可读性 |
| 风格传递 | Stage 3 prompt 嵌入 2 份手写周报 | few-shot 才能模仿 |
| LLM 输出格式 | 直接输出 Markdown | 灵活可读 |
| 周报发送 | 生成草稿 → 人工粘贴钉钉 | 权限待确认 |

## 输出结构

```
**上周困难与问题是否已解决：** xxx

## *本周工作重点
1. 项目A一句话总述；进度
2. 项目B一句话总述；进度

## *本周工作详情

项目A名称
1. 任务1简述
   具体子条目1
   具体子条目2
2. 任务2简述
   具体子条目1

项目B名称
1. 任务1简述
   具体子条目1
```

**关键格式规则**：每个子条目独占一行、3 空格缩进，禁止用分号合并。

## 本地 MD 工作记录格式

支持两种格式，推荐格式 2：

**格式 1：传统 YAML frontmatter（兼容旧文件）**
```markdown
---
date: 2026-04-29
tags: [tag1, tag2]
project: 管理与服务
---

正文内容...
```

**格式 2：简化首行（推荐）**
```markdown
date: 2026-04-29
project: 管理与服务

正文内容...
```

- `date` 必填（格式 `YYYY-MM-DD`）
- `project` 可选，用于项目维度分组（无则归入 `knowledge_base`）
- `tags` 可选
- 格式 2 中，`key: value` 连续行遇到空行或非 key:value 行即停止解析

## Commit 规范（配合周报自动化）

**唯一要求 —— "不空"**：每个 commit message 能独立回答"做了什么 + 为什么"。

禁止：`fixbug`、`fix：创意打磨师相关bug。`

允许示例：
- `fix：赛事赛道信息，引号处理`
- `pref：基于对话历史润色必填槽位，消除割裂感`

## 周报质量标准（领导要求）

1. 有明确的进展百分比或过程量
2. 有量化数据（几个环境、几个服务、几个 bug）
3. 不出现无结论的模糊描述
4. 每条工作详情 3-6 行，编号列表展开

## config.yaml 关键配置

```yaml
git:
  author: jinhaodong
  repos:
    - name: qwen_all
    - name: dify
    - name: ai_edu_assistant
  max_diff_length: 5000

knowledge_base:
  root_path: /Users/jadenoliver/JadenData/17_AI大模型开发-Python

llm:
  provider: qwen
  providers:
    deepseek: ...
    qwen: ...
    zhipu: ...

output:
  dir: ./output
  auto_open: true
  editor: code
```

## 信息源优先级

1. **Git commit 摘要**：作者自己写的，优先信任
2. **MD 知识沉淀**：最新快照，直接作为事实依据
3. **Git diff**：仅用于补充 commit 未提及的细节

## 注意事项

- `config.yaml` 包含 API Key，已在 `.gitignore` 中排除
- MD 知识库文件需日期标记（frontmatter `date` 或首行 `date:`）才会被采集
- 无痕工作（运维/配置类）通过本地 MD 记录，推荐加 `project:` 字段实现项目归属
- `--mode single` 可回退到原始单阶段模式
- 系统无侵入性，随时可回退到手动写周报
- 输出周报为草稿，建议人工审阅微调后发布
