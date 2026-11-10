# Run every end-to-end test in one go (requires dev_preview.py running locally on 8098).
#
#   .\scripts\run-e2e.ps1                 # all suites
#   .\scripts\run-e2e.ps1 -Only login    # run one suite only
#
# Each suite uses its own port + its own Chrome profile dir, and the browser is closed
# via CDP when it finishes, to avoid attaching to a leftover instance (a pitfall we hit).
param(
    [string]$Base = 'http://127.0.0.1:8098',
    [string[]]$Only = @(),
    [int]$StartPort = 9500
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$node = 'C:\Users\Admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'

if (-not (Test-Path $node)) { $node = (Get-Command node -ErrorAction SilentlyContinue).Source }
if (-not (Test-Path $chrome)) { throw "Chrome not found: $chrome" }

$suites = @(
    @{ name = 'login';    script = 'e2e_login.mjs';    args = @() },
    @{ name = 'standard'; script = 'e2e_pipeline.mjs'; args = @('standard') },
    @{ name = 'complex';  script = 'e2e_pipeline.mjs'; args = @('complex') },
    @{ name = 'pgctx';    script = 'e2e_pg_contexts.mjs'; args = @() },
    @{ name = 'tts';      script = 'e2e_tts.mjs';      args = @() },
    @{ name = 'ops';      script = 'e2e_ops.mjs';      args = @() }
)

# Is the preview service running?
try {
    $health = Invoke-RestMethod "$Base/api/health" -TimeoutSec 5
    Write-Host "Preview service: $($health.name) $($health.version) @ $Base" -ForegroundColor Cyan
} catch {
    throw "Preview service $Base is unreachable; start it first: .venv\Scripts\python.exe scripts\dev_preview.py"
}

$results = @()
$port = $StartPort

foreach ($suite in $suites) {
    if ($Only.Count -and ($Only -notcontains $suite.name)) { continue }

    # A Chrome left over from an earlier run on the same port would be re-attached
    # (same profile, stale HTTP cache), so kill anything still listening first.
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 300

    $profile = Join-Path $env:TEMP "dpchrome\e2e-$($suite.name)-$port-$PID"
    Remove-Item -Recurse -Force $profile -ErrorAction SilentlyContinue

    Write-Host "`n========== $($suite.name) ==========" -ForegroundColor Cyan
    Start-Process -FilePath $chrome -ArgumentList @(
        '--headless', '--disable-gpu', '--no-sandbox',
        "--remote-debugging-port=$port", "--user-data-dir=$profile", 'about:blank'
    ) -WindowStyle Hidden

    # Wait for the debug port to be ready, and confirm it is a fresh instance
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $targets = Invoke-RestMethod "http://127.0.0.1:$port/json/list" -TimeoutSec 2
            if ($targets) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) {
        Write-Host "  [x] debug port $port not ready" -ForegroundColor Red
        $results += [pscustomobject]@{ Suite = $suite.name; Exit = 99 }
        continue
    }

    $scriptPath = Join-Path $root "scripts\$($suite.script)"
    # When node writes to stderr (warnings / exception stacks), EAP=Stop treats it as a
    # terminating error and aborts the whole test run; merge the two streams and relax EAP here.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $output = & $node $scriptPath $Base $port @($suite.args) 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $saved
    $output | ForEach-Object { Write-Host $_ }
    # A suite can print FAIL lines yet still exit 0 (e.g. an assertion helper that only
    # counts). Treat printed failures as failures too, so the summary can never lie.
    $printedFails = @($output | Where-Object { $_ -match '^\s*FAIL' }).Count
    if ($code -eq 0 -and $printedFails -gt 0) { $code = 1 }
    $results += [pscustomobject]@{ Suite = $suite.name; Exit = $code; Failed = $printedFails }
    Write-Host "  exit=$code$(if ($printedFails) { " ($printedFails printed FAIL)" })" -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Red' })
    Start-Sleep -Seconds 1
    $port++
}

Write-Host "`n========== Summary ==========" -ForegroundColor Cyan
$results | ForEach-Object {
    $mark = if ($_.Exit -eq 0) { 'PASS' } else { "FAIL($($_.Exit))" }
    "{0,-12} {1}" -f $_.Suite, $mark
}
$failed = ($results | Where-Object { $_.Exit -ne 0 }).Count
if ($failed) { Write-Host "`n$failed suite(s) failed" -ForegroundColor Red; exit 1 }
Write-Host "`nAll passed" -ForegroundColor Green
