# Запуск бота в Docker. Работает из любой папки: сначала переходит в папку, где лежит сам скрипт.
Set-Location $PSScriptRoot

# Консоль в UTF-8, чтобы русский текст не превращался в "кракозябры"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Не найден Docker. Установите Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Desktop не запущен: откройте его, дождитесь зелёной надписи Engine running и запустите этот скрипт снова"
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "Нет файла .env: скопируйте .env.example в .env и заполните"
    exit 1
}

# Бот может работать только в одном экземпляре: старого, запущенного не через Docker (из .venv), останавливаем
$old = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'app\.(bot\.)?main' })
if ($old.Count -gt 0) {
    $old | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Write-Host "Остановлен старый бот, запущенный не через Docker"
}

# Пересборка после обновления файлов; без изменений кэш делает её быстрой
$output = docker compose up -d --build 2>&1
$output | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось запустить, ошибка выше"
    if (($output | Out-String) -match 'port is already allocated|bind') {
        Write-Host "Порт занят другой программой: впишите в .env строку WEB_PORT=8081 и запустите снова"
    }
    exit 1
}

$port = "8080"
$line = Select-String -Path ".env" -Pattern '^\s*WEB_PORT\s*=\s*(\d+)' | Select-Object -First 1
if ($line) { $port = $line.Matches[0].Groups[1].Value }
Write-Host "Готово. Бот работает в Docker. Приложение: http://localhost:$port"
