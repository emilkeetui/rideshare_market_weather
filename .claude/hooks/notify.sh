#!/usr/bin/env bash
# Hook: notify.sh
# Cross-platform desktop notification on Stop/Notification events.
# Adapted from pedrohcgs/claude-code-my-workflow.

TITLE="Claude Code — fhv_extreme_weather"
MESSAGE="${1:-Task complete or attention needed}"

notify() {
  if command -v osascript &>/dev/null; then
    # macOS
    osascript -e "display notification \"$MESSAGE\" with title \"$TITLE\""
  elif command -v notify-send &>/dev/null; then
    # Linux (libnotify)
    notify-send "$TITLE" "$MESSAGE"
  elif command -v powershell.exe &>/dev/null; then
    # Windows
    powershell.exe -Command "
      Add-Type -AssemblyName System.Windows.Forms
      \$notify = New-Object System.Windows.Forms.NotifyIcon
      \$notify.Icon = [System.Drawing.SystemIcons]::Information
      \$notify.Visible = \$true
      \$notify.ShowBalloonTip(5000, '$TITLE', '$MESSAGE', [System.Windows.Forms.ToolTipIcon]::Info)
      Start-Sleep -Milliseconds 5000
      \$notify.Dispose()
    " 2>/dev/null
  fi
}

notify
exit 0
