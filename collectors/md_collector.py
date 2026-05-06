"""本地 MD 知识库扫描模块 - 采集本周相关的知识沉淀"""

import os
import re
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional


def _parse_frontmatter(content: str) -> dict:
    """解析文件元数据，支持两种格式：

    格式 1（传统 YAML frontmatter）：
        ---
        date: 2026-04-29
        tags: [tag1, tag2]
        ---

    格式 2（简化首行，推荐）：
        date: 2026-04-29
        project: 管理与服务

    返回 {date, tags, project, ...}
    """
    metadata = {}

    # 尝试格式 1：YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    fm_text = fm_match.group(1) if fm_match else ""

    # 如果没匹配到 YAML frontmatter，尝试格式 2：首行 key: value
    if not fm_text:
        # 取文件头几行，遇到空行或非 key: value 格式就停
        lines = content.split("\n")
        header_lines = []
        for line in lines[:10]:  # 最多取前 10 行
            stripped = line.strip()
            if not stripped:
                break
            if re.match(r"^[\w]+\s*:", stripped):
                header_lines.append(stripped)
            else:
                break
        fm_text = "\n".join(header_lines)

    if not fm_text:
        return metadata

    for line in fm_text.split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if key == "date":
            try:
                metadata["date"] = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                pass
        elif key == "tags":
            # [tag1, tag2] 或 tag1, tag2
            tags = re.findall(r"[\w\u4e00-\u9fff-]+", value)
            if tags:
                metadata["tags"] = tags
        elif key == "project":
            metadata["project"] = value

    return metadata


def _is_in_date_range(file_path: str, since: date, until: date, fallback_to_mtime: bool = True) -> bool:
    """判断文件是否属于指定日期范围"""
    # 先读取文件内容尝试 frontmatter
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read(4096)  # 只读头部
        fm = _parse_frontmatter(content)
        if "date" in fm:
            return since <= fm["date"] <= until
    except Exception:
        pass

    # 兜底：使用文件 mtime
    if fallback_to_mtime:
        mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).date()
        return since <= mtime <= until

    return False


def _extract_relevant_sections(content: str, since: date, until: date) -> str:
    """从 MD 文件中提取可能属于本周的章节

    策略：如果文件很大（跨多月），尝试提取包含本周日期的章节
    """
    # 如果内容较短（<3000字符），直接返回全部
    if len(content) <= 3000:
        return content

    # 尝试按 ## 标题分节，提取包含本周日期的章节
    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    since_str = since.strftime("%Y-%m-%d")
    until_str = until.strftime("%Y-%m-%d")

    relevant = []
    for section in sections:
        # 检查章节中是否包含本周日期
        dates_in_section = re.findall(r"\d{4}-\d{2}-\d{2}", section)
        for d in dates_in_section:
            try:
                d_date = datetime.strptime(d, "%Y-%m-%d").date()
                if since <= d_date <= until:
                    relevant.append(section)
                    break
            except ValueError:
                continue

    if relevant:
        return "\n".join(relevant)

    # 如果没匹配到具体日期章节，返回前后各取一段（兜底）
    return content[:3000] + "\n...[内容过长，仅展示部分]"


def scan(root_path: str, since: date, until: date, pattern: str = "**/*.md",
         fallback_to_mtime: bool = True) -> list[dict]:
    """扫描知识库，返回本周相关的 MD 文件内容

    Args:
        root_path: 知识库根目录
        since: 起始日期
        until: 结束日期
        pattern: 文件匹配模式
        fallback_to_mtime: 无 frontmatter 时是否用 mtime 兜底

    Returns:
        [{path, relative_path, title, content, metadata}]
    """
    root = Path(root_path)
    if not root.exists():
        return []

    results = []

    for md_file in root.glob(pattern):
        if md_file.name.startswith("."):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        metadata = _parse_frontmatter(content)

        # 必须有 frontmatter 且包含 date 字段才采集
        if "date" not in metadata:
            continue

        if not (since <= metadata["date"] <= until):
            continue
        relative_path = md_file.relative_to(root)

        # 提取标题（第一个 # 标题）
        title_match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else md_file.stem

        # 提取本周相关内容
        relevant_content = _extract_relevant_sections(content, since, until)

        results.append({
            "path": str(md_file),
            "relative_path": str(relative_path),
            "title": title,
            "content": relevant_content,
            "metadata": metadata,
        })

    return results
