#!/bin/bash
# 周报自动化 - macOS launchd 定时任务安装脚本
# 使用方法: bash scripts/install_launcher.sh

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_NAME="com.weekly-report.auto"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
PYTHON_PATH="$(which python3)"

echo "[安装] 周报自动化定时任务"
echo "  Python: $PYTHON_PATH"
echo "  项目目录: $SCRIPT_DIR"
echo ""

# 生成 plist 文件
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${SCRIPT_DIR}/weekly_report.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>

    <!-- 每周五 17:30 (Calendar Interval 格式) -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>5</integer>
        <key>Hour</key>
        <integer>17</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/output/launchd.log</string>

    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/output/launchd_error.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

echo "[生成] plist 文件: $PLIST_PATH"

# 加载定时任务
launchctl unload "$PLIST_PATH" 2>/dev/null
launchctl load "$PLIST_PATH"

echo "[完成] 定时任务已安装：每周五 17:30 自动生成周报"
echo ""
echo "管理命令："
echo "  查看状态: launchctl list | grep weekly-report"
echo "  卸载任务: launchctl unload $PLIST_PATH"
echo "  手动触发: python3 ${SCRIPT_DIR}/weekly_report.py"
