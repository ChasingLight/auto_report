"""周报格式化模块 - 将 LLM 输出格式化为钉钉周报 Markdown"""


def format_report(report: dict, week_tag: str) -> str:
    """将结构化周报数据格式化为 Markdown 文本

    Args:
        report: LLM 生成的结构化周报
        week_tag: 周标签（如 "2026-W18"）

    Returns:
        格式化后的 Markdown 字符串
    """
    lines = []

    lines.append(f"# 员工周报 - {week_tag}")
    lines.append("")

    # 上周问题解决状态
    resolved = report.get("last_week_resolved", "已解决")
    lines.append(f"**上周困难与问题是否已解决：** {resolved}")
    lines.append("")

    # 本周工作重点
    lines.append("## *本周工作重点")
    lines.append("")
    highlights = report.get("highlights", [])
    for i, h in enumerate(highlights, 1):
        lines.append(f"{i}. {h}")
    lines.append("")

    # 本周工作详情
    lines.append("## *本周工作详情")
    lines.append("")
    details = report.get("details", [])
    for i, item in enumerate(details, 1):
        project = item.get("project", "")
        task = item.get("task", "")
        progress = item.get("progress", "")
        description = item.get("description", "")
        thinking = item.get("thinking", "")

        lines.append(f"### {i}. [{project}] {task}")
        if progress:
            lines.append(f"**进度：** {progress}")
        lines.append("")
        lines.append(description)
        if thinking:
            lines.append("")
            lines.append(f"**思考：** {thinking}")
        lines.append("")

    # 下周计划
    next_week = report.get("next_week_plan", "")
    if next_week:
        lines.append("## 下周计划")
        lines.append("")
        lines.append(next_week)
        lines.append("")

    return "\n".join(lines)


def save_report(content: str, output_dir: str, week_tag: str) -> str:
    """保存周报到文件

    Args:
        content: 格式化后的周报内容
        output_dir: 输出目录
        week_tag: 周标签

    Returns:
        保存的文件路径
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    file_path = os.path.join(output_dir, f"{week_tag}.md")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return file_path
