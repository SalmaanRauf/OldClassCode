# ProConnect Transition Harness Run Guide

Use this file as the exact runbook for the separate device.

## Files that must be current

Make sure these files are the latest versions before you run anything:

- `proconnect_client.py`
- `proconnect_lookup_logic.py`
- `proconnect_stakeholder_payload.py`
- `proconnect_stakeholder_test.py`
- `proconnect_scenario_runner.py`
- `proconnect_stakeholder_scenarios.sample.json`

## 1) Go to the test folder

```powershell
cd C:\Users\salrau01\prcttry
```

## 2) Put the raw JWT into `token.txt`

```powershell
Set-Content -Path .\token.txt -Value 'PASTE_RAW_JWT_HERE' -NoNewline
```

## 3) Run the primary demo scenario

```powershell
py .\proconnect_stakeholder_test.py --person "Jennifer Brady" --from-company "Capital One" --from-account-id "00130000000BYU2AAO" --to-company "Fannie Mae" --department "C-Suite" --token-file ".\token.txt"
```

Expected result for this patch:

- `Exact person match` stays `PASS`
- `PERSON PROFILE` should now keep the correct match and also backfill richer fields from source-side probe data even when ProConnect returns PascalCase field names
- `last_updated`, `title_external`, `in_salesforce`, `protiviti_alumni`, `contact_at_robert_half`, and `photo_url` should populate if they are present in ProConnect
- `FROM COMPANY RELATIONSHIP NETWORK` can now include probe-discovered internal connections
- `optional_sections.from_company` and `optional_sections.to_company` can now surface `intent_signals` and `recent_activity`
- `probe_payload_shapes` now captures a lightweight summary of raw probe response structure, including `raw_text_preview` when the endpoint returns plain text instead of JSON

## 4) Only if needed: rerun with a real destination account override

Use this only if you know the real Fannie Mae account id value.
Do not paste placeholder text like `<FANNIE_MAE_ACCOUNT_ID>`.

```powershell
py .\proconnect_stakeholder_test.py --person "Jennifer Brady" --from-company "Capital One" --from-account-id "00130000000BYU2AAO" --to-company "Fannie Mae" --to-account-id "REAL_FANNIE_MAE_ACCOUNT_ID" --department "C-Suite" --token-file ".\token.txt"
```

## 5) Run the scenario batch

```powershell
py .\proconnect_scenario_runner.py --payload-type stakeholder --scenarios-file ".\proconnect_stakeholder_scenarios.sample.json" --token-file ".\token.txt"
```

## 6) List the newest artifacts

```powershell
Get-ChildItem .\output\proconnect_runs | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name,LastWriteTime
```

## 7) Print the latest transition artifact summary

Paste this whole block as-is:

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
"\nPERSON MATCH EVIDENCE:"
$j.transition_payload.movement_evidence.person_match | Format-List
"\nFROM COMPANY CONTEXT:"
$j.transition_payload.from_company_context | Format-List
"\nFROM COMPANY ACCOUNT TEAM:"
$j.transition_payload.from_company_context.account_team | Format-List
"\nFROM COMPANY RELATIONSHIP NETWORK:"
$j.transition_payload.from_company_context.relationship_network | Format-List
"\nFROM COMPANY OPTIONAL SECTIONS:"
$j.transition_payload.optional_sections.from_company | Format-List
"\nFROM COMPANY PROBE SHAPES:"
$j.transition_payload.optional_sections.from_company.probe_payload_shapes | Format-Table -Wrap -AutoSize
"\nTO COMPANY ACCOUNT CONTEXT:"
$j.transition_payload.to_company_context.account_context | Format-List
"\nTO COMPANY ACCOUNT TEAM:"
$j.transition_payload.to_company_context.account_team | Format-List
"\nTO COMPANY WORK BY SOLUTION:"
$j.transition_payload.to_company_context.work_by_solution | Format-List
"\nTO COMPANY RELATIONSHIP NETWORK:"
$j.transition_payload.to_company_context.relationship_network | Format-List
"\nTO COMPANY OPTIONAL SECTIONS:"
$j.transition_payload.optional_sections.to_company | Format-List
"\nTO COMPANY PROBE SHAPES:"
$j.transition_payload.optional_sections.to_company.probe_payload_shapes | Format-Table -Wrap -AutoSize
"\nTO COMPANY COUNTS:"
[PSCustomObject]@{
  projects = ($j.transition_payload.to_company_context.projects.items | Measure-Object).Count
  opportunities = ($j.transition_payload.to_company_context.opportunities.items | Measure-Object).Count
  key_buyers = ($j.transition_payload.to_company_context.key_buyers.items | Measure-Object).Count
  org_chart = ($j.transition_payload.to_company_context.org_chart.items | Measure-Object).Count
  technologies = ($j.transition_payload.to_company_context.technologies.items | Measure-Object).Count
  alumni = ($j.transition_payload.to_company_context.relationship_network.protiviti_alumni.items | Measure-Object).Count
  connected_colleagues = ($j.transition_payload.to_company_context.relationship_network.connected_colleagues.items | Measure-Object).Count
} | Format-List
"\nTOP 5 PROJECTS:"
$j.transition_payload.to_company_context.projects.items | Select-Object -First 5 project_name,solution,emd,em,primary_key_buyer,project_status,ended_date | Format-Table -Wrap -AutoSize
"\nTOP 5 KEY BUYERS:"
$j.transition_payload.to_company_context.key_buyers.items | Select-Object -First 5 name,title,wins_5y,last_opportunity_won_date,last_opportunity_stage,function,email_address | Format-Table -Wrap -AutoSize
"\nFROM INTERNAL CONNECTIONS:"
$j.transition_payload.from_company_context.relationship_network.connected_colleagues.items | Select-Object -First 10 name,title,last_connected_method,last_connected_date,number_of_interactions | Format-Table -Wrap -AutoSize
"\nTO INTERNAL CONNECTIONS:"
$j.transition_payload.to_company_context.relationship_network.connected_colleagues.items | Select-Object -First 10 name,title,last_connected_method,last_connected_date,number_of_interactions | Format-Table -Wrap -AutoSize
"\nFROM INTENT SIGNALS:"
$j.transition_payload.optional_sections.from_company.intent_signals | Select-Object -First 10 topic,strength,date,source | Format-Table -Wrap -AutoSize
"\nTO INTENT SIGNALS:"
$j.transition_payload.optional_sections.to_company.intent_signals | Select-Object -First 10 topic,strength,date,source | Format-Table -Wrap -AutoSize
"\nFROM RECENT ACTIVITY:"
$j.transition_payload.optional_sections.from_company.recent_activity | Select-Object -First 10 type,date,description,source | Format-Table -Wrap -AutoSize
"\nTO RECENT ACTIVITY:"
$j.transition_payload.optional_sections.to_company.recent_activity | Select-Object -First 10 type,date,description,source | Format-Table -Wrap -AutoSize
"\nTOP 10 RANKED OPPORTUNITIES:"
$j.transition_payload.movement_evidence.ranked_opportunities_top10 | Select-Object -First 10 rank,rank_score,rank_band,opportunity,stage,primary_key_buyer | Format-Table -Wrap -AutoSize
"\nHTTP (first 10):"
$j.http_calls | Select-Object -First 10 endpoint,status_code,error,elapsed_ms | Format-Table -AutoSize
"\nHTTP (last 10):"
$j.http_calls | Select-Object -Last 10 endpoint,status_code,error,elapsed_ms | Format-Table -AutoSize
```

## 8) Print the latest scenario artifact summary

Paste this whole block as-is:

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

## 9) Optional sanity run for a known non-match

```powershell
py .\proconnect_stakeholder_test.py --person "Jenna Jerry" --from-company "Capital One" --to-company "American Express" --department "C-Suite" --token-file ".\token.txt"
```

## Troubleshooting

- `401`: token invalid, expired, or malformed.
- `403`: token valid but not authorized for one or more endpoints/accounts.
- `Token is near expiry (<= 10 minutes)`: refresh `token.txt` before rerunning so long org-chart/probe passes do not get cut off mid-run.
- `HTTP 400` on `/api/accounts/...`: bad account id override.
- `CommandNotFoundException` with `py.\script.py`: missing space. Use `py .\script.py`.
- Repeated org chart `500` warnings are currently non-blocking and can still result in an expected overall `WARN`.
