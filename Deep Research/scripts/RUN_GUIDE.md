# ProConnect Stakeholder Harness Run Guide (Current)

Use this guide for the latest stakeholder-focused scripts only.

## Files you must have in the folder

- `proconnect_client.py`
- `proconnect_lookup_logic.py`
- `proconnect_stakeholder_payload.py`
- `proconnect_stakeholder_test.py`
- `proconnect_scenario_runner.py`
- `proconnect_stakeholder_scenarios.sample.json`

Optional (debug/legacy checks):

- `proconnect_smoke_test.py`
- `proconnect_company_person_test.py`
- `proconnect_scenarios.sample.json`

## 1) Go to folder

```powershell
cd C:\Users\salrau01\prcttry
```

## 2) Put token in `token.txt`

`token.txt` must contain only the raw JWT token text:

- No `Bearer `
- No variable names
- No `< >`

```powershell
Set-Content -Path .\token.txt -Value 'PASTE_RAW_JWT_HERE' -NoNewline
```

## 3) (Optional but recommended) smoke-check auth/account first

```powershell
py .\proconnect_smoke_test.py --account-id "00130000000BYU2AAO" --token-file ".\token.txt"
```

## 4) Run stakeholder payload (primary test)

```powershell
py .\proconnect_stakeholder_test.py --company "Capital One" --person "Jenna Jerry" --department "C-Suite" --token-file ".\token.txt"
```

## 5) Run stakeholder scenario batch with expected statuses

```powershell
py .\proconnect_scenario_runner.py --payload-type stakeholder --scenarios-file ".\proconnect_stakeholder_scenarios.sample.json" --token-file ".\token.txt"
```

## 6) View latest artifacts

```powershell
Get-ChildItem .\output\proconnect_runs | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name,LastWriteTime
```

## Quick troubleshooting

- `CommandNotFoundException` using `py.\...`:
  - Missing space. Use `py .\script.py ...`
- `401`:
  - Token invalid/expired/malformed.
- `403`:
  - Token valid but unauthorized for endpoint/account/session.
- Stakeholder output `WARN`:
  - Often expected when person exact match not found or technologies/profile fields are unavailable.
- Scenario runner overall `FAIL`:
  - Means unexpected failure or expected-status mismatch.
