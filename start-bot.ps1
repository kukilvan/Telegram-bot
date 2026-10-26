# Запуск бота. Работает из любой папки: сначала переходит в папку, где лежит сам скрипт.
Set-Location $PSScriptRoot

# Консоль в UTF-8, чтобы русский текст не превращался в "кракозябры"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Не найдено виртуальное окружение: $PSScriptRoot\$python"
    Write-Host "Создайте его один раз (в этой папке): python -m venv .venv"
    Write-Host "Затем установите зависимости: .venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

& $python -m app.bot.main
