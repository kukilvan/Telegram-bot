# Set console encoding to UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Start the bot
cd E:\LocalAI\Bionic\Telegram-bot
.venv\Scripts\Activate.ps1
python -m app.bot.main
