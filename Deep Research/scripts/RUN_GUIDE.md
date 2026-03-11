# ProConnect Transition Harness Run Guide (Current)

This guide is only for the current **ProConnect transition flow**.

## Required files in your test folder

- `proconnect_client.py`
- `proconnect_lookup_logic.py`
- `proconnect_stakeholder_payload.py`
- `proconnect_stakeholder_test.py`
- `proconnect_scenario_runner.py`
- `proconnect_stakeholder_scenarios.sample.json`

## 1) Go to folder

```powershell
cd C:\Users\salrau01\prcttry
```

## 2) Put token in `token.txt`

`token.txt` must contain only the raw JWT token text.

```powershell
Set-Content -Path .\token.txt -Value 'PASTE_RAW_JWT_HERE' -NoNewline
```

## 3) Run primary transition test

```powershell
py .\proconnect_stakeholder_test.py --person "Jenna Jerry" --from-company "Capital One" --to-company "American Express" --department "C-Suite" --token-file ".\token.txt"
```

Compatibility alias (`--company` maps to destination):

```powershell
py .\proconnect_stakeholder_test.py --person "Jenna Jerry" --from-company "Capital One" --company "American Express" --token-file ".\token.txt"
```

## 4) Run transition scenario batch

```powershell
py .\proconnect_scenario_runner.py --payload-type stakeholder --scenarios-file ".\proconnect_stakeholder_scenarios.sample.json" --token-file ".\token.txt"
```

## 5) List latest artifacts

```powershell
Get-ChildItem .\output\proconnect_runs | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name,LastWriteTime
```

## 6) Compact summary commands (paste output back)

### Transition artifact summary

```powershell
$latest = Get-ChildItem .\output\proconnect_runs\proconnect_stakeholder_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$j = Get-Content $latest.FullName -Raw | ConvertFrom-Json
"FILE: $($latest.Name)"
"OVERALL: $($j.pass_fail.status)"
"WARNINGS: $($j.warnings.Count)"
"ERRORS: $($j.errors.Count)"
"\nCHECKS:"
$j.pass_fail.checks | Select-Object check,status,http,details | Format-Table -Wrap -AutoSize
"\nMOVEMENT EVENT:"
$j.transition_payload.movement_event | Format-List
"\nPERSON PROFILE:"
$j.transition_payload.person_profile | Format-List
"\nFROM COMPANY LITE:"
$j.transition_payload.from_company_context | Format-List
"\nTO COMPANY COUNTS:"
[PSCustomObject]@{
  projects = ($j.transition_payload.to_company_context.projects.items | Measure-Object).Count
  opportunities = ($j.transition_payload.to_company_context.opportunities.items | Measure-Object).Count
  key_buyers = ($j.transition_payload.to_company_context.key_buyers.items | Measure-Object).Count
  org_chart = ($j.transition_payload.to_company_context.org_chart.items | Measure-Object).Count
  technologies = ($j.transition_payload.to_company_context.technologies.items | Measure-Object).Count
} | Format-List
"\nTOP 10 RANKED OPPORTUNITIES:"
$j.transition_payload.movement_evidence.ranked_opportunities_top10 | Select-Object -First 10 rank,rank_score,rank_band,opportunity,stage,primary_key_buyer | Format-Table -Wrap -AutoSize
"\nHTTP (first 10):"
$j.http_calls | Select-Object -First 10 endpoint,status_code,error,elapsed_ms | Format-Table -AutoSize
"\nHTTP (last 10):"
$j.http_calls | Select-Object -Last 10 endpoint,status_code,error,elapsed_ms | Format-Table -AutoSize
```

### Scenario artifact summary

```powershell
$latest = Get-ChildItem .\output\proconnect_runs\proconnect_scenarios_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$j = Get-Content $latest.FullName -Raw | ConvertFrom-Json
"FILE: $($latest.Name)"
"OVERALL: $($j.pass_fail.status)"
"HAS_STATUS_MISMATCH: $($j.pass_fail.has_status_mismatch)"
"HAS_UNEXPECTED_FAILURE: $($j.pass_fail.has_unexpected_failure)"
"WARNINGS: $($j.warnings.Count)"
"ERRORS: $($j.errors.Count)"
"\nSCENARIO SUMMARY:"
$j.scenario_results | ForEach-Object {
 [PSCustomObject]@{
   name = $_.name
   payload_type = $_.payload_type
   actual_status = $_.status
   expected_status = $_.expected_status
   status_match = $_.status_match
   checks = ($_.checks | ForEach-Object { "$($_.check):$($_.status):$($_.http)" }) -join " | "
   warnings = ($_.warnings -join " || ")
   errors = ($_.errors -join " || ")
 }
} | Format-Table -Wrap -AutoSize
```

## Troubleshooting

- `401`: token invalid/expired/malformed.
- `403`: token valid but unauthorized for one or more endpoints/accounts.
- `CommandNotFoundException` with `py.\script.py`: missing space. Use `py .\script.py`.
- Overall `WARN` is expected when person match is unresolved or optional sections are missing.
