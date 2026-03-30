param(
    [string]$PythonLauncher = "py",
    [string]$TokenFile = ".\token.txt",
    [string]$FromCompany = "Capital One",
    [string]$FromAccountId = "00130000000BYU2AAO",
    [string]$ToCompany = "Fannie Mae",
    [string]$ToAccountId = "00130000000BYUIAA4",
    [string]$ScenariosFile = ".\proconnect_stakeholder_scenarios.sample.json",
    [switch]$SkipDynamicResolutionDemo,
    [switch]$SkipAnchoredJennifer,
    [switch]$SkipQuickChecks,
    [switch]$SkipFullChecks,
    [switch]$SkipScenarioRunner
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-Host "`n=== $Label ===" -ForegroundColor Cyan
    & $PythonLauncher @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Step '$Label' failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $TokenFile)) {
    throw "Token file not found at '$TokenFile'. Create or update it manually before running this battery."
}

if (-not $SkipDynamicResolutionDemo) {
    Invoke-Step -Label "PRIMARY DEMO: Jennifer Brady (dynamic destination resolution)" -Arguments @(
        ".\proconnect_stakeholder_test.py",
        "--person", "Jennifer Brady",
        "--from-company", $FromCompany,
        "--from-account-id", $FromAccountId,
        "--to-company", $ToCompany,
        "--department", "C-Suite",
        "--token-file", $TokenFile
    )
}

if (-not $SkipAnchoredJennifer) {
    Invoke-Step -Label "ANCHORED CHECK: Jennifer Brady (explicit destination account)" -Arguments @(
        ".\proconnect_stakeholder_test.py",
        "--person", "Jennifer Brady",
        "--from-company", $FromCompany,
        "--from-account-id", $FromAccountId,
        "--to-company", $ToCompany,
        "--to-account-id", $ToAccountId,
        "--department", "C-Suite",
        "--token-file", $TokenFile
    )
}

if (-not $SkipQuickChecks) {
    $quickChecks = @(
        @{ Person = "Cissy Yang"; Dept = "Finance" },
        @{ Person = "Jason Dandridge"; Dept = "Operations" },
        @{ Person = "Nancy Jardini"; Dept = "Legal" },
        @{ Person = "Danielle McCoy"; Dept = "Legal" }
    )

    foreach ($check in $quickChecks) {
        Invoke-Step -Label "QUICK CHECK: $($check.Person)" -Arguments @(
            ".\proconnect_company_person_test.py",
            "--company", $ToCompany,
            "--person", $check.Person,
            "--department", $check.Dept,
            "--token-file", $TokenFile
        )
    }
}

if (-not $SkipFullChecks) {
    $fullChecks = @(
        @{ Person = "Jennifer Brady"; Dept = "C-Suite" },
        @{ Person = "Cissy Yang"; Dept = "Finance" },
        @{ Person = "Jason Dandridge"; Dept = "Operations" },
        @{ Person = "Nancy Jardini"; Dept = "Legal" },
        @{ Person = "Danielle McCoy"; Dept = "Legal" }
    )

    foreach ($check in $fullChecks) {
        Invoke-Step -Label "FULL CHECK: $($check.Person)" -Arguments @(
            ".\proconnect_stakeholder_test.py",
            "--person", $check.Person,
            "--from-company", $FromCompany,
            "--from-account-id", $FromAccountId,
            "--to-company", $ToCompany,
            "--to-account-id", $ToAccountId,
            "--department", $check.Dept,
            "--token-file", $TokenFile
        )
    }
}

if (-not $SkipScenarioRunner) {
    Invoke-Step -Label "SCENARIO RUNNER" -Arguments @(
        ".\proconnect_scenario_runner.py",
        "--payload-type", "stakeholder",
        "--scenarios-file", $ScenariosFile,
        "--token-file", $TokenFile
    )
}

Write-Host "`n=== LATEST ARTIFACTS ===" -ForegroundColor Yellow
Get-ChildItem .\output\proconnect_runs |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 Name, LastWriteTime |
    Format-Table -AutoSize
