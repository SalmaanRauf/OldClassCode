# ProConnect Local Testing Harness (Standalone)

This folder provides local-only scripts to validate ProConnect retrieval logic with a manually supplied bearer token.

- No wiring to `Deep Research/chainlit_app/main.py`.
- No mutation of existing Deep Research runtime flow.
- Python standard library only (no new pip dependencies required).
- Fast Windows copy-paste instructions: `RUN_GUIDE.md`.

## Files

- `proconnect_client.py`: shared HTTP client, auth/token helpers, artifact writers, console table output.
- `proconnect_lookup_logic.py`: company resolution + tiered person resolution helpers.
- `proconnect_smoke_test.py`: direct account-first smoke test.
- `proconnect_company_person_test.py`: dynamic company + person workflow test.
- `proconnect_scenario_runner.py`: run many scenarios and produce one aggregate artifact.
- `proconnect_scenarios.sample.json`: sample scenario input file.

## Token Input Priority

All scripts resolve token in this order:

1. CLI flag `--token`
2. Environment variable `PROCONNECT_BEARER_TOKEN`
3. Token file (`--token-file` if provided, otherwise `./token.txt` or script-folder `token.txt` when present)
4. Secure terminal prompt (hidden input)

You can paste either:

- raw JWT token
- `Bearer <token>`

If your token is in a file, create `token.txt` in this folder:

```text
eyJ...<your_jwt>...
```

The scripts normalize it to `Authorization: Bearer <token>`.

## Optional Extra Headers

Use `--extra-headers-file` with a JSON object:

```json
{
  "X-Requested-With": "XMLHttpRequest",
  "Referer": "https://proconnect.protiviti.com/"
}
```

`Authorization` from this file is ignored intentionally so token handling remains centralized.

## Commands

Run commands from:

`/Users/salmaanrauf/Documents/BD Tool`

### 1) Smoke test (direct account first)

```bash
python3 "Deep Research/scripts/proconnect_smoke_test.py" \
  --account-id "00130000000BYU2AAO"
```

Using explicit token file:

```bash
python3 "Deep Research/scripts/proconnect_smoke_test.py" \
  --account-id "00130000000BYU2AAO" \
  --token-file "Deep Research/scripts/token.txt"
```

Optional search add-on:

```bash
python3 "Deep Research/scripts/proconnect_smoke_test.py" \
  --account-id "00130000000BYU2AAO" \
  --search "Capital One"
```

### 2) Dynamic company/person test

```bash
python3 "Deep Research/scripts/proconnect_company_person_test.py" \
  --company "Capital One" \
  --person "Replace With Known Executive" \
  --department "C-Suite"
```

### 3) Scenario runner (aggregate report)

```bash
python3 "Deep Research/scripts/proconnect_scenario_runner.py" \
  --scenarios-file "Deep Research/scripts/proconnect_scenarios.sample.json"
```

## Auth Troubleshooting

- `401`: token is invalid/expired/malformed.
- `403`: token is valid but not authorized for target endpoint/account.
- Smoke test automatically runs `/api/user` auth check when account call returns `401/403`, which helps distinguish "token rejected globally" vs "account-level access denied".

## Output Artifacts

Default output directory:

`/Users/salmaanrauf/Documents/BD Tool/Deep Research/scripts/output/proconnect_runs`

Each run writes a JSON artifact with top-level structure:

- `run_id`
- `timestamp_utc`
- `inputs_redacted`
- `http_calls`
- `company_resolution`
- `person_resolution`
- `account_summary`
- `errors`
- `pass_fail`

`person_resolution.status` values used by lookup flows:

- `matched`
- `not_found`
- `not_requested`

## Runtime Behavior

- `proconnect_smoke_test.py`: `GET /api/accounts/{accountId}` first; optional prospects + org chart checks.
- `proconnect_company_person_test.py`:
  1. `GET /api/prospects?search='{company}'`
  2. Resolve best account candidate
  3. `GET /api/accounts/{accountId}`
  4. Person resolution tiers:
     - key buyers in account payload
     - executive org chart (`department=C-Suite`, `sfdcJobFunction=Executive`)
     - department sweep fallback (mapped `sfdcJobFunction` list)
- `proconnect_scenario_runner.py`: repeats the same logic over many scenarios and writes one aggregate JSON report.

## Notes

- JWT payload is decoded without signature verification only for local expiry warning display.
- `401/403` responses are surfaced in console checks and artifact `http_calls`.
- Rotate/revoke any bearer token copied from browser devtools after local testing.
