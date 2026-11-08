# The restore of the database from a copy (spec 5 of stage 7.1). Works from any folder.
#   .\restore-bot.ps1                      - the list of the copies on this PC, choose a number
#   .\restore-bot.ps1 "path\to\file.7z"    - a copy downloaded from Google Drive (or a .db taken out of it by 7-Zip)
# The work is done by Python in a one-off container of the same image (app.utils.restore): no Python or 7-Zip on the PC.
# Nothing changes and the bot keeps working until the answer «да»; then the bot stops, the base is replaced, the bot starts.
param([string]$Path = "")

# A relative path counts from the folder the owner stands in: made whole before going to the script's folder
if ($Path) { $Path = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).ProviderPath, $Path)) }

Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# Answers piped from a file or a program are read as UTF-8 too; the keyboard gives Russian anyway
if ([Console]::IsInputRedirected) { [Console]::InputEncoding = [System.Text.Encoding]::UTF8 }

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

# A $ in .env breaks the Docker commands (as in start-bot.ps1). No value is printed; the backup password is read by the
# container, never here
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

$cancelled = "Отменено. Ничего не изменено."
$restoreDir = Join-Path $PSScriptRoot "data\restore"  # the container sees only data: a given file is copied here

function Clear-RestoreFolder {
    if (Test-Path -LiteralPath $restoreDir) {
        Get-ChildItem -LiteralPath $restoreDir -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# One command of app.utils.restore in a one-off container (the bot does not start in it; no stdin, so the answers stay
# for Read-Host). The lines of Python (stdout) and of Docker (stderr) are kept apart: Docker's are shown only on a failure
function Invoke-Restore([string[]]$Arguments) {
    $out = New-Object System.Collections.Generic.List[string]
    $err = New-Object System.Collections.Generic.List[string]
    docker compose run --rm --no-deps --build --quiet-build --interactive=false -T tracker python -m app.container_start app.utils.restore @Arguments 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $err.Add("$_") } else { $out.Add("$_") }
    }
    return [pscustomobject]@{ Code = $LASTEXITCODE; Lines = $out; Errors = $err }
}

# Lines that begin with @ are for the script, not for the owner
function Show-Lines($lines) {
    foreach ($line in $lines) {
        if (-not $line.StartsWith("@")) { Write-Host $line }
    }
}

# A refusal (code 1) is explained by Python; anything else (no image built, Python crashed): Docker's lines and a fallback
function Show-Failure($result, [string]$fallback) {
    $said = @($result.Lines | Where-Object { $_ -and -not $_.StartsWith("@") })
    if ($result.Code -eq 1 -and $said.Count -gt 0) {
        Show-Lines $said
        return
    }
    Show-Lines $result.Lines
    foreach ($line in $result.Errors) { Write-Host $line }
    Write-Host $fallback
}

function Invoke-Main {
    if ($Path) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            Write-Host "Файл не найден: $Path"
            return 1
        }
        $extension = [System.IO.Path]::GetExtension($Path).ToLower()
        if (@(".7z", ".db") -notcontains $extension) {
            Write-Host "Нужен файл .7z из Google Drive или .db из копий. Ничего не изменено."
            return 1
        }
        New-Item -ItemType Directory -Force $restoreDir | Out-Null
        $fileName = [System.IO.Path]::GetFileName($Path)
        Copy-Item -LiteralPath $Path -Destination (Join-Path $restoreDir $fileName) -Force
        $copyPath = "data/restore/$fileName"
    } else {
        Write-Host "Читаю список копий…"
        $listing = Invoke-Restore @("list")
        if ($listing.Code -ne 0) {
            Show-Failure $listing "Список копий не получить — ошибка выше. Ничего не изменено."
            return 1
        }
        Show-Lines $listing.Lines
        $copies = @{}
        foreach ($line in $listing.Lines) {
            if ($line -match '^@copy (\d+) (.+)$') { $copies[$Matches[1]] = $Matches[2] }
        }
        if ($copies.Count -eq 0) { return 0 }
        while ($true) {
            $answer = "$(Read-Host 'Номер копии (Enter — отмена)')".Trim()
            if ($answer -eq "") {
                Write-Host $cancelled
                return 0
            }
            $number = 0
            if ([int]::TryParse($answer, [ref]$number) -and $copies.ContainsKey("$number")) {
                $copyPath = $copies["$number"]
                break
            }
            Write-Host "Нет копии с номером $answer."
        }
    }

    Write-Host "Проверяю копию…"
    $checked = Invoke-Restore @("check", $copyPath)
    if ($checked.Code -ne 0) {
        Show-Failure $checked "Копию не проверить — ошибка выше. Ничего не изменено."
        return 1
    }
    Show-Lines $checked.Lines
    $phrase = "$($checked.Lines | Where-Object { $_.StartsWith('@when ') } | Select-Object -First 1)".Substring(6)

    $answer = "$(Read-Host "Вернуть базу к копии $phrase? Всё, что изменилось позже, пропадёт. Нынешняя база сохранится отдельно. (да/нет)")"
    if (($answer -replace '\s', '') -ne "да") {
        Write-Host $cancelled
        return 0
    }

    & "$PSScriptRoot\stop-bot.ps1" | Out-Host
    $stopped = $false
    for ($waited = 0; $waited -le 60; $waited += 2) {
        $running = docker compose ps -q tracker 2>$null | Select-Object -First 1
        if (-not $running) { $stopped = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $stopped) {
        Write-Host "Бот не остановился за 60 секунд. База не тронута. Остановите его: .\stop-bot.ps1 и запустите восстановление снова."
        return 1
    }

    $applied = Invoke-Restore @("apply", $copyPath)
    if ($applied.Code -ne 0) {
        Show-Failure $applied "Восстановление не прошло — ошибка выше. База не тронута."
        Write-Host "Запускаю бота на прежней базе…"
        & "$PSScriptRoot\start-bot.ps1" | Out-Host
        return 1
    }
    Show-Lines $applied.Lines
    Write-Host "Запускаю бота…"
    & "$PSScriptRoot\start-bot.ps1" | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "База восстановлена, но бот не запустился — ошибка выше. Вернуть прежнюю базу: .\restore-bot.ps1 и выберите копию «перед восстановлением»."
        return 1
    }
    Write-Host "Готово: бот работает на копии $phrase."
    return 0
}

# data\restore is emptied at the start and at the end, whatever happened (Ctrl+C too)
$exitCode = 1
Clear-RestoreFolder
try {
    $exitCode = Invoke-Main
} finally {
    Clear-RestoreFolder
}
exit $exitCode
