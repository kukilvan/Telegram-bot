# Остановка бота и приложения. Работает из любой папки.
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

docker compose down
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось остановить, ошибка выше"
    exit 1
}
Write-Host "Бот и приложение остановлены"
