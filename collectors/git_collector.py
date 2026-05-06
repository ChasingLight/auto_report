"""Git 数据采集模块 - 从本地仓库采集本周 commit log 和 diff"""

import subprocess
import os
from datetime import datetime, timedelta
from typing import Optional


def _run_git(repo_path: str, args: list[str]) -> str:
    """在指定仓库目录执行 git 命令，返回输出"""
    result = subprocess.run(
        ["git"] + args,
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def get_commits(repo_path: str, since: str, until: Optional[str] = None,
                author: Optional[str] = None) -> list[dict]:
    """获取指定时间范围内的 commit 列表

    Args:
        repo_path: 本地仓库路径
        since: 起始日期 (YYYY-MM-DD)
        until: 结束日期 (YYYY-MM-DD)，默认为当前时间
        author: 作者过滤（git 用户名），为空则不过滤

    Returns:
        commit 信息列表 [{hash, author, date, message, repo_name}]
    """
    until_arg = until or datetime.now().strftime("%Y-%m-%d")
    log_format = "--pretty=format:%H|%an|%ad|%s"
    args = ["log", log_format, "--date=short", "--no-merges",
            f"--since={since}", f"--until={until_arg}"]
    if author:
        args.append(f"--author={author}")
    output = _run_git(repo_path, args)

    if not output:
        return []

    repo_name = os.path.basename(repo_path)
    commits = []
    for line in output.split("\n"):
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        commits.append({
            "hash": parts[0],
            "author": parts[1],
            "date": parts[2],
            "message": parts[3],
            "repo": repo_name,
        })
    return commits


def get_diff(repo_path: str, commit_hash: str, max_length: int = 5000) -> str:
    """获取指定 commit 的 diff 内容

    Args:
        repo_path: 本地仓库路径
        commit_hash: commit SHA
        max_length: diff 内容最大长度，超出截断

    Returns:
        diff 内容字符串
    """
    diff = _run_git(repo_path, ["diff", f"{commit_hash}^..{commit_hash}", "--stat"])
    diff_detail = _run_git(repo_path, ["diff", f"{commit_hash}^..{commit_hash}"])

    combined = f"--- 统计 ---\n{diff}\n\n--- 详情 ---\n{diff_detail}"

    if len(combined) > max_length:
        combined = combined[:max_length] + "\n...[截断]"

    return combined


def get_stats(repo_path: str, since: str, until: Optional[str] = None,
              author: Optional[str] = None) -> dict:
    """获取指定时间范围内的整体统计

    Returns:
        {total_commits, files_changed, insertions, deletions}
    """
    until_arg = until or datetime.now().strftime("%Y-%m-%d")
    args = ["log", "--oneline", "--no-merges",
            f"--since={since}", f"--until={until_arg}",
            "--shortstat"]
    if author:
        args.append(f"--author={author}")
    output = _run_git(repo_path, args)

    total_commits = 0
    files_changed = 0
    insertions = 0
    deletions = 0

    for line in output.split("\n"):
        if not line.strip():
            continue
        if "|" in line or line.strip().startswith((" ", "\t")):
            # shortstat 行，如 "3 files changed, 10 insertions(+), 5 deletions(-)"
            parts = line.split(",")
            for part in parts:
                part = part.strip()
                if "file" in part:
                    files_changed += int(part.split()[0])
                elif "insertion" in part:
                    insertions += int(part.split()[0])
                elif "deletion" in part:
                    deletions += int(part.split()[0])
        else:
            total_commits += 1

    return {
        "total_commits": total_commits,
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
    }


def collect(repos: list[dict], since: str, until: Optional[str] = None,
            max_diff_length: int = 5000, author: Optional[str] = None) -> dict:
    """采集所有仓库的本周数据

    Args:
        repos: 仓库配置列表 [{name, path}]
        since: 起始日期
        until: 结束日期
        max_diff_length: 单个 diff 最大长度
        author: 作者过滤（git 用户名），为空则不过滤

    Returns:
        {repo_name: {commits, stats, diffs}}
    """
    result = {}

    for repo in repos:
        name = repo["name"]
        path = repo["path"]

        if not os.path.isdir(path):
            result[name] = {"error": f"仓库路径不存在: {path}"}
            continue

        commits = get_commits(path, since, until, author=author)
        stats = get_stats(path, since, until, author=author)

        diffs = {}
        for commit in commits:
            try:
                diffs[commit["hash"][:8]] = get_diff(path, commit["hash"], max_diff_length)
            except Exception as e:
                diffs[commit["hash"][:8]] = f"[获取 diff 失败: {e}]"

        result[name] = {
            "commits": commits,
            "stats": stats,
            "diffs": diffs,
        }

    return result
