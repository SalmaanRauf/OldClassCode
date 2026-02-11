# ProConnect Local Harness Run Guide

This is the shortest path to test the latest harness on Windows.

## 0) Go to folder

```powershell
cd C:\Users\salrau01\prcttry
```

## 1) Put token in `token.txt`

`token.txt` must contain only the raw JWT token text.

- No `Bearer `
- No variable names
- No `< >`

Create/update it:

```powershell
Set-Content -Path .\token.txt -Value 'PASTE_RAW_JWT_HERE' -NoNewline
```

## 2) Run quick smoke test

Important: there is a space after `py`.

```powershell
py .\proconnect_smoke_test.py --account-id "00130000000BYU2AAO" --token-file ".\token.txt"
```

You can also omit `--token-file` if `token.txt` is in the same folder:

```powershell
py .\proconnect_smoke_test.py --account-id "00130000000BYU2AAO"
```

## 3) Run dynamic company/person test

```powershell
py .\proconnect_company_person_test.py --company "Capital One" --person "Jerry" --department "C-Suite" --token-file ".\token.txt"
```

## 4) Run scenario batch

```powershell
py .\proconnect_scenario_runner.py --scenarios-file ".\proconnect_scenarios.sample.json" --token-file ".\token.txt"
```

## 5) View output files

```powershell
Get-ChildItem .\output\proconnect_runs | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name,LastWriteTime
```

## Common issues

- `CommandNotFoundException` with `py.\...`:
  - You missed a space.
  - Correct format: `py .\script.py ...`
- `403`:
  - Token is valid but not authorized for that endpoint/account/session.
- `401`:
  - Token invalid/expired/malformed.
