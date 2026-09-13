"""Launch the bot in background (dev convenience)."""

import subprocess

subprocess.Popen(
    [".venv/Scripts/python.exe", "-m", "app.bot.main"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
