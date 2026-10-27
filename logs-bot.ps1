# Журнал бота из Docker. Работает из любой папки.
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "Выход из журнала - Ctrl+C. Бот при этом продолжает работать."
docker compose logs -f --tail 100
