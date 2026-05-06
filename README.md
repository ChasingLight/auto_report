# auto_report

周报自动化系统 — 从 Git 仓库和本地 MD 知识库采集数据，通过三阶段 LLM 流水线生成结构化周报草稿。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置
cp config_example.yaml config.yaml
# 编辑 config.yaml 填入你的 Git 仓库路径、API Key 等

# 3. 生成本周周报
python weekly_report.py

# 4. 指定日期范围
python weekly_report.py --from 2026-04-28 --to 2026-05-02
```

## 完整文档

→ **[AGENTS.md](AGENTS.md)**
