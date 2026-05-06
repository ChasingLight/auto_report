#!/usr/bin/env python3
"""周报自动化系统 - 主入口

用法:
    python weekly_report.py                           # 生成本周周报
    python weekly_report.py --interactive             # 交互式补录无痕工作
    python weekly_report.py --week 2026-W17           # 指定历史周
    python weekly_report.py --from 2026-04-28 --to 2026-05-02  # 指定日期范围
    python weekly_report.py --dry-run                 # 仅采集数据，不调用 LLM
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, date

import yaml

from collectors import git_collector, md_collector
from analyzer import llm_analyzer
from formatter import report_formatter


def load_config() -> dict:
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(config_path):
        print(f"[错误] 配置文件不存在: {config_path}")
        print("请先复制 config.yaml.example 并填写配置")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_week_range(week_tag: str | None = None, from_date: str | None = None,
                   to_date: str | None = None) -> tuple[date, date, str]:
    """计算周日期范围

    Args:
        week_tag: 周标签（如 "2026-W18"），为空则自动计算本周
        from_date: 起始日期 (YYYY-MM-DD)，优先级高于 week_tag
        to_date: 结束日期 (YYYY-MM-DD)，优先级高于 week_tag

    Returns:
        (since, until, week_tag)
    """
    if from_date and to_date:
        since = datetime.strptime(from_date, "%Y-%m-%d").date()
        until = datetime.strptime(to_date, "%Y-%m-%d").date()
        tag = f"{since}_to_{until}"
        return since, until, tag

    if week_tag:
        # 解析 ISO 周标签
        year, week = week_tag.split("-W")
        # ISO 周的周一
        d = date.fromisocalendar(int(year), int(week), 1)
        since = d
        until = d + timedelta(days=6)
        return since, until, week_tag

    # 自动计算本周（周一到周日）
    today = date.today()
    since = today - timedelta(days=today.weekday())  # 本周一
    until = since + timedelta(days=6)  # 本周日
    iso = today.isocalendar()
    tag = f"{iso[0]}-W{iso[1]:02d}"
    return since, until, tag


def prompt_manual_input() -> str:
    """交互式引导用户输入无痕工作"""
    print("\n" + "=" * 50)
    print("  请输入本周非 Git 记录的工作内容")
    print("  （输入空行结束，支持多行）")
    print("=" * 50)

    lines = []
    while True:
        line = input("> ")
        if not line.strip():
            break
        lines.append(line)

    return "\n".join(lines)


def open_in_editor(file_path: str, editor: str | None = None) -> None:
    """用编辑器打开文件"""
    if editor:
        try:
            subprocess.run([editor, file_path])
        except FileNotFoundError:
            print(f"[警告] 编辑器 '{editor}' 未找到，使用系统默认打开")
            subprocess.run(["open", file_path])
    else:
        subprocess.run(["open", file_path])


def stage2_interaction(stage2_result: dict) -> list[dict] | None:
    """Stage 2 交互：展示归类结果，用户审核确认

    Args:
        stage2_result: cluster_candidates() 的返回结果

    Returns:
        用户确认后的 groups 列表；用户取消则返回 None
    """
    groups = stage2_result.get("groups", [])

    while True:
        # --- 展示归类结果 ---
        print("\n" + "=" * 55)
        print("  本周工作归组（所有条目均保留，无过滤）")
        print("=" * 55)
        if groups:
            for gi, g in enumerate(groups, 1):
                print(f"\n  [{gi}] {g['name']} ({g['type']})")
                for item in g["items"]:
                    print(f"      - [{item['label']}] {item['description']}")
        else:
            print("  (无)")

        # --- 用户操作 ---
        print("\n" + "-" * 55)
        print("[y] 确认生成  [e N] 编辑描述  [d N] 删除条目  [q] 退出")
        print("-" * 55)

        cmd = input("> ").strip()

        if cmd in ("y", ""):
            return groups

        if cmd == "q":
            return None

        # 编辑条目描述
        if cmd.startswith("e "):
            try:
                idx = int(cmd.split()[1]) - 1
                flat_items = []
                for g in groups:
                    for item in g["items"]:
                        flat_items.append(item)
                if 0 <= idx < len(flat_items):
                    new_desc = input(f"  新描述 [{flat_items[idx]['label']}]: ").strip()
                    if new_desc:
                        flat_items[idx]["description"] = new_desc
                        print(f"  ✓ 已更新")
                else:
                    print(f"  ✗ 无效编号: {idx + 1}")
            except (ValueError, IndexError):
                print("  ✗ 格式错误，用法: e <编号>")

        # 删除条目
        elif cmd.startswith("d "):
            try:
                idx = int(cmd.split()[1]) - 1
                flat_refs = []
                for g in groups:
                    for item in g["items"]:
                        flat_refs.append((g, item))
                if 0 <= idx < len(flat_refs):
                    g, item = flat_refs[idx]
                    g["items"].remove(item)
                    print(f"  ✓ 已删除: [{item['label']}] {item['description']}")
                    groups[:] = [g for g in groups if g["items"]]
                else:
                    print(f"  ✗ 无效编号: {idx + 1}")
            except (ValueError, IndexError):
                print("  ✗ 格式错误，用法: d <编号>")

        else:
            print("  ✗ 未知命令")


def main():
    parser = argparse.ArgumentParser(description="周报自动化系统")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="交互式补录无痕工作内容")
    parser.add_argument("--week", "-w", type=str, default=None,
                        help="指定周标签（如 2026-W17）")
    parser.add_argument("--from", "-f", type=str, default=None, dest="from_date",
                        help="指定起始日期（YYYY-MM-DD），需配合 --to 使用")
    parser.add_argument("--to", "-t", type=str, default=None, dest="to_date",
                        help="指定结束日期（YYYY-MM-DD），需配合 --from 使用")
    parser.add_argument("--dry-run", "-d", action="store_true",
                        help="仅采集数据，不调用 LLM")
    parser.add_argument("--debug", "-D", action="store_true",
                        help="调试模式：展示中间过程（采集数据、最终 prompt），LLM 调用前需手动确认")
    parser.add_argument("--mode", "-m", type=str, default="three_stage",
                        choices=["three_stage", "single"],
                        help="生成模式：three_stage（三阶段流水线，默认）/ single（原始单阶段）")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="自动确认 Stage 2 归类结果，跳过交互")
    args = parser.parse_args()

    # 参数校验
    if (args.from_date or args.to_date) and not (args.from_date and args.to_date):
        parser.error("--from 和 --to 必须同时指定")

    # 加载配置
    config = load_config()

    # 计算周范围
    since, until, week_tag = get_week_range(args.week, args.from_date, args.to_date)
    week_range_str = f"{week_tag} ({since} ~ {until})"
    print(f"[周报] {week_range_str}")

    # 1. 采集 Git 数据
    print("\n[1/4] 采集 Git 数据...")
    git_repos = config.get("git", {}).get("repos", [])
    max_diff = config.get("git", {}).get("max_diff_length", 5000)
    git_author = config.get("git", {}).get("author", None)
    git_data = git_collector.collect(
        repos=git_repos,
        since=since.strftime("%Y-%m-%d"),
        until=until.strftime("%Y-%m-%d"),
        max_diff_length=max_diff,
        author=git_author,
    )
    total_commits = sum(
        v.get("stats", {}).get("total_commits", 0)
        for v in git_data.values() if "error" not in v
    )
    print(f"  采集完成：{len(git_repos)} 个仓库，{total_commits} 次提交")

    # Debug: 展示 Git 采集详情
    if args.debug:
        print("\n" + "=" * 60)
        print("  [DEBUG] Git 采集详情")
        print("=" * 60)
        for name, info in git_data.items():
            if "error" in info:
                print(f"\n  [{name}] {info['error']}")
                continue
            stats = info.get("stats", {})
            print(f"\n  [{name}] {stats.get('total_commits', 0)} commits, "
                  f"{stats.get('files_changed', 0)} files, "
                  f"+{stats.get('insertions', 0)} / -{stats.get('deletions', 0)}")
            for commit in info.get("commits", []):
                print(f"    - [{commit['date']}] {commit['message']}")
        print()

    # 2. 扫描 MD 知识库
    print("\n[2/4] 扫描本地知识库...")
    kb_config = config.get("knowledge_base", {})
    md_data = md_collector.scan(
        root_path=kb_config.get("root_path", ""),
        since=since,
        until=until,
        pattern=kb_config.get("pattern", "**/*.md"),
        fallback_to_mtime=kb_config.get("fallback_to_mtime", True),
    )
    print(f"  扫描完成：{len(md_data)} 个相关文件")

    # Debug: 展示 MD 采集详情
    if args.debug:
        print("\n" + "=" * 60)
        print("  [DEBUG] MD 知识库采集详情")
        print("=" * 60)
        for md in md_data:
            tags = md.get("metadata", {}).get("tags", [])
            tag_str = f" [tags: {', '.join(tags)}]" if tags else ""
            print(f"\n  [{md['title']}]{tag_str}")
            print(f"  路径: {md['relative_path']}")
            print(f"  内容预览: {md['content'][:200]}...")
        if not md_data:
            print("  (无匹配文件)")
        print()

    # 3. 手动补录
    manual_input = ""
    if args.interactive:
        print("\n[3/4] 手动补录无痕工作...")
        manual_input = prompt_manual_input()
    else:
        print("\n[3/4] 跳过手动补录（使用 --interactive 启用）")

    # Dry-run 模式：只输出采集结果
    if args.dry_run:
        print("\n[DRY RUN] 采集数据摘要：")
        print(f"  Git: {total_commits} commits")
        for name, info in git_data.items():
            if "error" in info:
                print(f"    {name}: {info['error']}")
            else:
                stats = info.get("stats", {})
                print(f"    {name}: {stats.get('total_commits', 0)} commits, "
                      f"{stats.get('files_changed', 0)} files changed")
        print(f"  MD: {len(md_data)} files")
        for md in md_data:
            print(f"    {md['title']} ({md['relative_path']})")
        if manual_input:
            print(f"  手动补录: {manual_input[:100]}...")
        print("\n使用 --dry-run 以外模式运行以生成周报。")
        return

    # 4. 调用 LLM 生成周报
    llm_config = config.get("llm", {})

    if args.mode == "single":
        # --- 原始单阶段模式 ---
        print("\n[4/4] 调用 LLM 生成周报...")

        if args.debug:
            from analyzer.llm_analyzer import _build_user_prompt, SYSTEM_PROMPT
            user_prompt = _build_user_prompt(git_data, md_data, manual_input, week_range_str)
            print("\n" + "=" * 60)
            print("  [DEBUG] 系统 Prompt")
            print("=" * 60)
            print(SYSTEM_PROMPT)
            print()
            print("=" * 60)
            print("  [DEBUG] 用户 Prompt（发送给 LLM 的完整内容）")
            print("=" * 60)
            print(user_prompt)
            print("=" * 60)
            confirm = input("\n[DEBUG] 确认发送给 LLM？(y/n): ")
            if confirm.lower() != "y":
                print("[取消] 已中止 LLM 调用")
                return

        try:
            report = llm_analyzer.generate(
                git_data=git_data,
                md_data=md_data,
                manual_input=manual_input,
                week_range=week_range_str,
                llm_config=llm_config,
            )
        except ValueError as e:
            print(f"\n[错误] {e}")
            sys.exit(1)
        except Exception as e:
            print(f"\n[错误] LLM 调用失败: {e}")
            sys.exit(1)

    else:
        # --- 三阶段流水线模式 ---
        # Stage 1: 提取候选条目
        print("\n[4/6] Stage 1: 提取候选条目...")
        if args.debug:
            from analyzer.prompts import STAGE1_SYSTEM_PROMPT, build_stage1_user_prompt
            print("\n" + "=" * 60)
            print("  [DEBUG] Stage 1 系统 Prompt")
            print("=" * 60)
            print(STAGE1_SYSTEM_PROMPT)
            print()
            user_prompt = build_stage1_user_prompt(git_data, md_data, week_range_str)
            print("=" * 60)
            print("  [DEBUG] Stage 1 用户 Prompt")
            print("=" * 60)
            print(user_prompt)
            print("=" * 60)
            confirm = input("\n[DEBUG] 确认执行 Stage 1？(y/n): ")
            if confirm.lower() != "y":
                print("[取消] 已中止")
                return

        try:
            candidates = llm_analyzer.extract_candidates(
                git_data=git_data,
                md_data=md_data,
                week_range=week_range_str,
                llm_config=llm_config,
            )
        except Exception as e:
            print(f"\n[错误] Stage 1 失败: {e}")
            sys.exit(1)

        print(f"  Stage 1 完成：提取 {len(candidates)} 条候选条目")
        for i, c in enumerate(candidates, 1):
            print(f"    [{c['label']}] {c['description']}")

        if not candidates:
            print("  [警告] 未提取到任何候选条目，请检查数据源")
            return

        # Stage 2: 自动归类
        print("\n[5/6] Stage 2: 自动归类...")
        if args.debug:
            from analyzer.prompts import STAGE2_SYSTEM_PROMPT, build_stage2_user_prompt
            from analyzer.llm_analyzer import _format_candidates_for_display
            print("\n" + "=" * 60)
            print("  [DEBUG] Stage 2 系统 Prompt")
            print("=" * 60)
            print(STAGE2_SYSTEM_PROMPT)
            print()
            candidates_text = _format_candidates_for_display(candidates)
            user_prompt = build_stage2_user_prompt(candidates_text)
            print("=" * 60)
            print("  [DEBUG] Stage 2 用户 Prompt")
            print("=" * 60)
            print(user_prompt)
            print("=" * 60)
            confirm = input("\n[DEBUG] 确认执行 Stage 2？(y/n): ")
            if confirm.lower() != "y":
                print("[取消] 已中止")
                return

        try:
            stage2_result = llm_analyzer.cluster_candidates(candidates, llm_config)
        except Exception as e:
            print(f"\n[错误] Stage 2 失败: {e}")
            sys.exit(1)

        groups_preview = stage2_result.get("groups", [])
        print(f"  Stage 2 完成：{len(groups_preview)} 个任务组（全部保留）")

        # 展示归类结果
        print("\n" + "=" * 55)
        print("  本周工作归组（所有条目均保留）")
        print("=" * 55)
        if groups_preview:
            for gi, g in enumerate(groups_preview, 1):
                print(f"\n  [{gi}] {g['name']} ({g['type']})")
                for item in g["items"]:
                    print(f"      - [{item['label']}] {item['description']}")
        else:
            print("  (无)")

        if args.yes:
            confirmed_groups = groups_preview
            print("\n[--yes] 自动确认归类结果")
        else:
            # Stage 2 交互
            confirmed_groups = stage2_interaction(stage2_result)
        if confirmed_groups is None:
            print("[取消] 用户退出")
            return
        if not confirmed_groups:
            print("[取消] 无任务组，请检查数据或手动补充")
            return

        # Stage 3: 生成最终周报
        print("\n[6/6] Stage 3: 生成最终周报...")
        if args.debug:
            from analyzer.prompts import STAGE3_SYSTEM_PROMPT, build_stage3_user_prompt
            from analyzer.llm_analyzer import _format_groups_for_display
            print("\n" + "=" * 60)
            print("  [DEBUG] Stage 3 系统 Prompt")
            print("=" * 60)
            print(STAGE3_SYSTEM_PROMPT)
            print()
            groups_text = _format_groups_for_display(confirmed_groups)
            user_prompt = build_stage3_user_prompt(groups_text, week_range_str)
            print("=" * 60)
            print("  [DEBUG] Stage 3 用户 Prompt")
            print("=" * 60)
            print(user_prompt)
            print("=" * 60)
            confirm = input("\n[DEBUG] 确认执行 Stage 3？(y/n): ")
            if confirm.lower() != "y":
                print("[取消] 已中止")
                return

        try:
            report = llm_analyzer.build_final_report(
                groups=confirmed_groups,
                week_range=week_range_str,
                llm_config=llm_config,
            )
        except Exception as e:
            print(f"\n[错误] Stage 3 失败: {e}")
            sys.exit(1)

    # 5. 保存输出（LLM 已直接输出 Markdown）
    output_dir = config.get("output", {}).get("dir", "./output")
    file_path = report_formatter.save_report(report, output_dir, week_tag)
    print(f"\n[完成] 周报已保存: {file_path}")

    # 6. 自动打开编辑器
    auto_open = config.get("output", {}).get("auto_open", True)
    editor = config.get("output", {}).get("editor", None)
    if auto_open:
        print("[提示] 正在打开编辑器，请审核微调后复制到钉钉...")
        open_in_editor(file_path, editor)


if __name__ == "__main__":
    main()
