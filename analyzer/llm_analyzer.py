"""LLM 分析引擎 - 调用大模型分析数据，生成结构化周报"""

import os
import re
from openai import OpenAI


SYSTEM_PROMPT = """你是一个周报撰写助手，根据工程师本周的研发数据生成面向领导汇报的周报。

---

## 一、你收到的两类数据

### 1. Git 数据（时间线型）
包含本周的 commit 摘要和代码 diff。注意：
- commit 摘要是作者自己写的，**优先信任**，作为主要内容源
- diff 是代码改动详情，**仅用于补充** commit 未提及的细节
- 数据已做时间线去重：同一功能的多次改动，只保留了最终状态的 diff
- commit 摘要仍然保留完整时间线，供你了解工作演进过程

### 2. MD 知识沉淀（快照型）
作者本地记录的技术文档，反映的是最新认知和结论，直接作为事实依据。

---

## 二、核心原则

周报是给领导看的，不是代码 review。
领导要看到的是：
**做了什么 → 解决了什么问题 → 结果如何 → 下一步怎么走**

---

## 三、周报风格参考

好的周报（模仿这种风格）：

本周工作重点:
1. AI 管理与服务4个部署环境，阿里百炼 apikey 独立分配与配置，已完成
2. 双创-创意打磨师，bug 解决与效果优化

本周工作详情:
1. 阿里百炼 apikey 独立分配与配置
   1. 6940 apikey 之前管理与服务4个部署环境共用，不方便区分且一旦泄露影响范围广；
   2. 针对 AI 管服 4个部署环境（公测、云正式、演示、应急演示），协调运维分配独立的阿里百炼 apikey 并配置对应环境的 IP 访问白名单。
   3. 对涉及的 qwen_all 和 dify 2个服务，使用新的阿里百炼 apikey 替换升级；同时协调回归测试，所有环境业务功能正常。
2. 双创-创意打磨师，bug 解决与效果优化
   1. 解决商业计划书上传 OSS 后链接包含特殊字符无法下载；
   2. 解决开放问答环节 + 用户上传附件，qwen-long inline 提示词超限：qwen-long 只对附件进行解析提取，业务回答使用 qwen-plus 长上下文模型；
   3. 核心槽位类型统一为 string，避免类型不一致问题。

坏的周报（禁止）：
- 罗列代码细节：识别出 config.py 中 2 处硬编码 key...
- 模糊无结论：完成了 XX 沟通
- 过度技术化：验证其 name/value 行为及字典 key 兼容性...

---

## 四、质量标准

1. 每项工作有明确进度（已完成 / 进行中 XX%）
2. 有量化数据（涉及几个环境、几个服务、解决几个 bug）
3. 不出现无结论的模糊描述
4. 每条工作详情 3-6 行，编号列表展开

---

## 五、处理规则

1. **信息源优先级**：commit 摘要 > MD 知识沉淀 > diff 补充
2. **时间线意识**：如果数据中同一功能有多次改动描述，以最终状态为准
3. **组织方式**：按"项目 > 任务/问题"分组，多个相关 commit 合并为一项工作
4. **语言要求**：不提文件名、变量名、函数名，用业务语言描述
5. **过滤噪音**：琐碎改动（typo、格式调整）合并或忽略
6. **忠于数据**：只基于给定数据，不得编造

---

## 六、输出格式（直接输出 Markdown，不要代码块包裹）

**上周困难与问题是否已解决：** 已解决/部分解决

## *本周工作重点
1. 工作重点1（一句话概括 + 状态）
2. 工作重点2

## *本周工作详情

### 项目A：项目概括
1. 任务1（进度）
   1. 具体细节1
   2. 具体细节2
   思考：下一步或风险（可选）
2. 任务2（进度）
   1. 具体细节1

### 项目B：项目概括
1. ...

## 下周计划
下周重点方向（1-2句话）"""


def _deduplicate_diffs(commits: list[dict], diffs: dict) -> dict:
    """对 diff 做时间线去重：同一文件被多次改动时，只保留最新一次的 diff

    Args:
        commits: commit 列表（按时间倒序，最新在前）
        diffs: {short_hash: diff_content}

    Returns:
        去重后的 diffs dict，被覆盖的 diff 标记为 [已被后续提交覆盖]
    """
    # 从 diff 中提取涉及的文件名
    import re

    def extract_files(diff_text: str) -> set[str]:
        """从 diff 统计段提取变更文件列表"""
        files = set()
        for line in diff_text.split("\n"):
            # 匹配 diff --git a/path b/path 格式
            m = re.match(r"diff --git a/.+ b/(.+)", line)
            if m:
                files.add(m.group(1).strip())
        return files

    # commits 是按时间倒序的（git log 默认），最新的在前面
    file_to_latest_hash = {}  # file -> 最新的 commit short_hash
    overridden_hashes = set()

    for commit in commits:
        short_hash = commit["hash"][:8]
        if short_hash not in diffs:
            continue

        files = extract_files(diffs[short_hash])
        is_all_overridden = True

        for f in files:
            if f not in file_to_latest_hash:
                file_to_latest_hash[f] = short_hash
                is_all_overridden = False
            else:
                overridden_hashes.add(short_hash)

    # 被覆盖的 commit，标记其 diff
    result = {}
    for short_hash, diff_text in diffs.items():
        if short_hash in overridden_hashes:
            result[short_hash] = "[已被后续提交覆盖，仅供参考演进过程]"
        else:
            result[short_hash] = diff_text

    return result


def _build_user_prompt(git_data: dict, md_data: list, manual_input: str, week_range: str) -> str:
    """构建用户 prompt，将所有数据组织后发送给 LLM"""
    sections = []

    sections.append(f"## 时间范围：{week_range}\n")

    # Git 数据
    for repo_name, repo_info in git_data.items():
        if "error" in repo_info:
            sections.append(f"### 项目：{repo_name}\n[采集失败: {repo_info['error']}]\n")
            continue

        commits = repo_info.get("commits", [])
        stats = repo_info.get("stats", {})
        raw_diffs = repo_info.get("diffs", {})

        if not commits:
            sections.append(f"### 项目：{repo_name}\n本周无提交。\n")
            continue

        # 时间线去重
        deduped_diffs = _deduplicate_diffs(commits, raw_diffs)

        section = f"### 项目：{repo_name}\n"
        section += f"统计：{stats.get('total_commits', 0)} 次提交，"
        section += f"变更 {stats.get('files_changed', 0)} 个文件，"
        section += f"+{stats.get('insertions', 0)} / -{stats.get('deletions', 0)} 行\n\n"

        # 第一层：commit 摘要（完整时间线，作者自己的总结）
        section += "**提交摘要（完整时间线，优先参考）：**\n"
        for commit in commits:
            short_hash = commit["hash"][:8]
            section += f"- [{commit['date']}] {commit['message']} ({short_hash})\n"

        # 第二层：diff 补充（去重后，只保留最终状态）
        section += "\n**代码改动补充（已去重，仅保留最终状态，补充 commit 未提及的细节）：**\n"
        for commit in commits:
            short_hash = commit["hash"][:8]
            if short_hash in deduped_diffs:
                diff_content = deduped_diffs[short_hash]
                section += f"[{commit['message']}] diff:\n```\n{diff_content}\n```\n"

        sections.append(section + "\n")

    # MD 知识库数据
    if md_data:
        sections.append("### 本周知识沉淀（最新快照，直接作为事实依据）\n")
        for md in md_data:
            tags = md.get("metadata", {}).get("tags", [])
            tag_str = f" [标签: {', '.join(tags)}]" if tags else ""
            sections.append(f"**{md['title']}**{tag_str}\n来源：{md['relative_path']}\n\n{md['content']}\n")

    # 手动补录
    if manual_input:
        sections.append(f"### 手动补充的工作内容\n{manual_input}\n")

    return "\n".join(sections)


def _get_client(config: dict) -> tuple[OpenAI, str]:
    """根据配置创建 OpenAI 客户端"""
    provider_name = config.get("provider", "deepseek")
    providers = config.get("providers", {})
    provider = providers.get(provider_name, {})

    api_key = provider.get("api_key", "")
    # 支持 ${ENV_VAR} 格式的环境变量引用
    if api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        api_key = os.environ.get(env_var, "")

    if not api_key:
        raise ValueError(f"未配置 LLM API Key（provider: {provider_name}），请检查 config.yaml 或设置环境变量")

    base_url = provider.get("base_url", "")
    model = provider.get("model", "")

    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model


def generate(git_data: dict, md_data: list, manual_input: str,
             week_range: str, llm_config: dict) -> str:
    """调用 LLM 生成周报

    Returns:
        Markdown 格式的周报文本
    """
    client, model = _get_client(llm_config)
    user_prompt = _build_user_prompt(git_data, md_data, manual_input, week_range)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        # qwen 关闭深度思考
        extra_body={"enable_thinking": False},
    )

    return response.choices[0].message.content


# ============================================================
# 三阶段流水线
# ============================================================

def _build_project_map(git_data: dict) -> dict[str, str]:
    """构建 short_commit_hash → repo_name 的映射"""
    mapping = {}
    for repo_name, repo_info in git_data.items():
        if "error" in repo_info:
            continue
        for commit in repo_info.get("commits", []):
            short_hash = commit["hash"][:8]
            mapping[short_hash] = repo_name
    return mapping


def _parse_stage1_output(text: str) -> list[dict]:
    """解析 Stage 1 LLM 输出为结构化候选条目

    输入格式: [label] 描述 | source: xxx
    容错：匹配不到的行跳过
    """
    candidates = []
    pattern = re.compile(r"^\[(fix|pref|feat|noise)\]\s+(.+?)\s*\|\s*source:\s*(.+)$", re.MULTILINE)
    for m in pattern.finditer(text):
        candidates.append({
            "label": m.group(1),
            "description": m.group(2).strip(),
            "source": m.group(3).strip(),
        })
    return candidates


def _enrich_candidates_with_project(candidates: list[dict], git_data: dict,
                                     md_data: list[dict]) -> list[dict]:
    """为候选条目注入项目归属信息

    - Git commit hash → 匹配 repo_name
    - MD 文件路径 → 匹配 md_data 中的 project 字段，否则用 'knowledge_base'
    """
    project_map = _build_project_map(git_data)
    # 构建 MD relative_path → project 映射
    md_project_map = {}
    for md in md_data:
        proj = md.get("metadata", {}).get("project", "")
        if proj:
            md_project_map[md["relative_path"]] = proj

    for c in candidates:
        source = c["source"]
        # 8 位 hex = git commit short hash
        if re.match(r"^[0-9a-f]{8}$", source) and source in project_map:
            c["project"] = project_map[source]
        elif source in md_project_map:
            c["project"] = md_project_map[source]
        else:
            c["project"] = "knowledge_base"
    return candidates


def _parse_stage2_output(text: str) -> dict:
    """解析 Stage 2 LLM 输出为结构化任务组

    Returns:
        {"groups": [{"name": str, "type": str, "items": [dict]}],
         "filtered": [dict]}
    """
    groups = []

    # 条目匹配（格式：- [label] 描述 | project: xxx | source: xxx）
    item_pattern = re.compile(
        r"^\s*-\s*\[(fix|pref|feat|noise)\]\s+(.+?)\s*\|"
        r"\s*(?:project:\s*(.+?)\s*\|\s*)?source:\s*(.+?)\s*$",
        re.MULTILINE,
    )

    # 匹配 ### 组名 (类型) 或 ### 组名（类型）
    group_header = re.compile(
        r"^###\s+(.+?)\s*[（(]([^)）]+)[）)]\s*$",
        re.MULTILINE,
    )

    group_splits = list(group_header.finditer(text))
    if group_splits:
        for i, gm in enumerate(group_splits):
            group_name = gm.group(1).strip()
            group_type = gm.group(2).strip()
            start = gm.end()
            end = group_splits[i + 1].start() if i + 1 < len(group_splits) else len(text)
            group_text = text[start:end]

            items = []
            for im in item_pattern.finditer(group_text):
                items.append({
                    "label": im.group(1),
                    "description": im.group(2).strip(),
                    "project": (im.group(3) or "").strip(),
                    "source": im.group(4).strip(),
                })
            if items:
                groups.append({"name": group_name, "type": group_type, "items": items})
    else:
        # 兜底：无分组标题时，所有条目放入一个默认组
        items = []
        for im in item_pattern.finditer(text):
            items.append({
                "label": im.group(1),
                "description": im.group(2).strip(),
                "project": (im.group(3) or "").strip(),
                "source": im.group(4).strip(),
            })
        if items:
            groups.append({"name": "本周工作", "type": "综合", "items": items})

    return {"groups": groups, "filtered": []}


def _format_candidates_for_display(candidates: list[dict]) -> str:
    """将候选条目列表格式化为可读文本"""
    lines = []
    for c in candidates:
        project = c.get("project", "")
        proj_str = f" | project: {project}" if project else ""
        lines.append(f"[{c['label']}] {c['description']}{proj_str} | source: {c['source']}")
    return "\n".join(lines)


def _format_groups_for_display(groups: list[dict]) -> str:
    """将任务组格式化为可读文本"""
    lines = []
    # 按 project 分组展示
    by_project: dict[str, list[dict]] = {}
    for g in groups:
        # 取第一个 item 的 project 作为组的 project
        proj = g["items"][0].get("project", "") if g["items"] else ""
        by_project.setdefault(proj, []).append(g)

    for proj, proj_groups in by_project.items():
        if proj:
            lines.append(f"## 项目: {proj}")
        for g in proj_groups:
            lines.append(f"### {g['name']} ({g['type']})")
            for item in g['items']:
                proj_str = f" | project: {item.get('project', '')}" if item.get('project') else ""
                lines.append(f"- [{item['label']}] {item['description']}{proj_str} | source: {item['source']}")
            lines.append("")
    return "\n".join(lines)


def extract_candidates(git_data: dict, md_data: list,
                       week_range: str, llm_config: dict) -> list[dict]:
    """Stage 1: 提取候选条目

    Returns:
        [{"label": "fix"/"pref"/"feat"/"noise", "description": str, "source": str}]
    """
    from analyzer.prompts import STAGE1_SYSTEM_PROMPT, build_stage1_user_prompt

    client, model = _get_client(llm_config)
    user_prompt = build_stage1_user_prompt(git_data, md_data, week_range)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        extra_body={"enable_thinking": False},
    )

    raw = response.choices[0].message.content
    candidates = _parse_stage1_output(raw)
    return _enrich_candidates_with_project(candidates, git_data, md_data)


def cluster_candidates(candidates: list[dict], llm_config: dict) -> dict:
    """Stage 2: 自动归类候选条目

    Returns:
        {"groups": [{"name": str, "type": str, "items": [dict]}],
         "filtered": [dict]}
    """
    from analyzer.prompts import STAGE2_SYSTEM_PROMPT, build_stage2_user_prompt

    client, model = _get_client(llm_config)
    candidates_text = _format_candidates_for_display(candidates)
    user_prompt = build_stage2_user_prompt(candidates_text)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": STAGE2_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        extra_body={"enable_thinking": False},
    )

    raw = response.choices[0].message.content
    return _parse_stage2_output(raw)


def build_final_report(groups: list[dict], week_range: str,
                       llm_config: dict) -> str:
    """Stage 3: 生成最终周报

    Args:
        groups: 用户确认后的任务组列表（包含所有条目，无过滤）
        week_range: 周范围描述
        llm_config: LLM 配置

    Returns:
        Markdown 格式的周报文本
    """
    from analyzer.prompts import STAGE3_SYSTEM_PROMPT, build_stage3_user_prompt

    client, model = _get_client(llm_config)
    groups_text = _format_groups_for_display(groups)
    user_prompt = build_stage3_user_prompt(groups_text, week_range)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": STAGE3_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        extra_body={"enable_thinking": False},
    )

    return response.choices[0].message.content
