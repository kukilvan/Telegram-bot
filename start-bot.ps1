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

# Docker портит знак $ в значениях .env (пароль перестаёт подходить), а "${" ломает все его команды: с таким .env не запускаем.
# Значение строки не выводим (там может быть пароль), только номер строки и имя настройки
$withDollar = 0
$lineNumber = 0
foreach ($envLine in (Get-Content ".env" -Encoding UTF8)) {
    $lineNumber++
    $trimmed = $envLine.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
    if ($envLine.Contains('$')) {
        $name = if ($envLine.Contains("=")) { ($envLine -split "=", 2)[0].Trim() } else { "строка без знака равенства" }
        Write-Host "В файле .env в строке $lineNumber ($name) есть знак `$ — Docker его портит, и значение (например, пароль) перестанет подходить."
        $withDollar++
    }
}
if ($withDollar -gt 0) {
    Write-Host "Уберите знак `$ из значения (для WEB_PASSWORD — придумайте пароль без него) и запустите скрипт снова."
    exit 1
}

# Бот может работать только в одном экземпляре: старого, запущенного не через Docker (из .venv), останавливаем.
# Только целая команда "-m app.main" или "-m app.bot.main": чужие "uvicorn app.main:app", "-m app.mainframe", "-m myapp.main" не трогаем
$oldBotPattern = '(^|\s)-m\s+app\.(bot\.)?main(\s|"|$)'
$old = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match $oldBotPattern })
if ($old.Count -gt 0) {
    $old | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Write-Host "Остановлен старый бот, запущенный не через Docker"
}

$port = "8080"
$line = Select-String -Path ".env" -Pattern '^\s*WEB_PORT\s*=\s*(\d+)' | Select-Object -First 1
if ($line) { $port = $line.Matches[0].Groups[1].Value }

# Пересборка после обновления файлов; без изменений кэш делает её быстрой. Каждая строка Docker (и обычная, и "ошибочная":
# он пишет ход сборки в поток ошибок) появляется сразу, как обычный текст, и запоминается для подсказки про порт
$buildLines = New-Object System.Collections.Generic.List[string]
docker compose up -d --build 2>&1 | ForEach-Object {
    $text = "$_"
    Write-Host $text
    $buildLines.Add($text)
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось запустить, ошибка выше"
    if (($buildLines -join "`n") -match 'port is already allocated|bind') {
        Write-Host "Порт занят другой программой: впишите в .env строку WEB_PORT=8081 и запустите снова"
    }
    exit 1
}

# Ждём итог: здоров ли контейнер. Число перезапусков запоминаем сразу, чтобы заметить новые
$inspectFormat = '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.RestartCount}}|{{.State.StartedAt}}'
function Get-ContainerState {
    $id = (docker compose ps -q tracker 2>$null | Select-Object -First 1)
    if (-not $id) { return $null }
    $parts = ("$(docker inspect -f $inspectFormat $id 2>$null)").Trim() -split "\|"
    if ($parts.Count -lt 4) { return $null }
    return [pscustomobject]@{ Id = "$id"; Status = $parts[0]; Health = $parts[1]; Restarts = [int]$parts[2]; StartedAt = $parts[3] }
}

$first = Get-ContainerState
$baseRestarts = if ($first) { $first.Restarts } else { 0 }
$outcome = "waiting"
$state = $null
Write-Host "Жду запуска приложения (до 90 секунд)…"
for ($waited = 0; $waited -le 90; $waited += 2) {
    $state = Get-ContainerState
    if (-not $state) { $outcome = "failed"; break }
    if ($state.Health -eq "healthy") { $outcome = "healthy"; break }
    if (@("restarting", "exited", "dead") -contains $state.Status -or $state.Restarts -gt $baseRestarts -or $state.Health -eq "unhealthy") {
        $outcome = "failed"
        break
    }
    Start-Sleep -Seconds 2
}

if ($outcome -eq "failed") {
    Write-Host "Запуск не удался. Последние строки журнала:"
    docker compose logs --no-color --tail 30 tracker 2>&1 | ForEach-Object { Write-Host "$_" }
    Write-Host "Полный журнал: .\logs-bot.ps1. Docker будет пробовать запустить снова каждую минуту; остановить — .\stop-bot.ps1. Исправьте причину и запустите этот скрипт снова."
    exit 1
}

if ($outcome -eq "waiting") {
    Write-Host "Приложение запускается дольше обычного. Через минуту откройте http://localhost:$port/health или посмотрите журнал: .\logs-bot.ps1"
    exit 0
}

Write-Host "Готово. Бот работает в Docker. Приложение: http://localhost:$port"

# Веб работает и без бота: токен неверного вида (например, пустой или из .env.example) контейнер не роняет, так что говорим сами
$sinceStart = docker logs --since $state.StartedAt $state.Id 2>&1 | ForEach-Object { "$_" }
if (($sinceStart -join "`n") -match 'токен бота неверного вида') {
    Write-Host "Внимание: бот не подключён к Telegram — токен бота неверного вида. Проверьте TELEGRAM_BOT_TOKEN в .env и запустите скрипт снова. Веб работает."
}
exit 0
