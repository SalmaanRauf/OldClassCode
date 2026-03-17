# Transition Playbook Run Guide

Use this file as the exact runbook for the VPN-enabled machine.

This guide is for the live Chainlit app workflow, not the standalone ProConnect harness scripts.

## Files that must be current

Make sure these files are the latest versions before you run anything:

- `Deep Research/chainlit_app/main.py`
- `Deep Research/public/elements/TransitionForm.jsx`
- `Deep Research/services/transition_playbook_orchestrator.py`
- `Deep Research/services/proconnect_transition_service.py`
- `Deep Research/services/transition_prompt_builder.py`
- `Deep Research/services/transition_presenter.py`
- `Deep Research/services/transition_brief_formatter.py`
- `Deep Research/services/transition_form_mapper.py`
- `Deep Research/services/deep_research_client.py`
- `Deep Research/tools/orchestrators.py`
- `Deep Research/config/config.py`
- `Deep Research/scripts/proconnect_client.py`

## 1) Go to the app folder

```powershell
cd C:\Users\salrau01\prcttry\Deep Research
```

## 2) Refresh the ProConnect bearer token

Recommended:

```powershell
Set-Content -Path .\token.txt -Value 'PASTE_RAW_JWT_HERE' -NoNewline
```

Notes:

- The file can contain either the raw JWT or `Bearer <token>`.
- Raw JWT is fine; the app normalizes it.
- The token is only used server-side. MDs will never see it.

## 3) Point the app to the token file

Put this in `.env`:

```env
PROCONNECT_TOKEN_FILE=C:\Users\salrau01\prcttry\Deep Research\token.txt
ENABLE_DEEP_RESEARCH=true
```

Important:

- `PROCONNECT_TOKEN_FILE` is the safest option.
- If you do not set it, fallback lookup will try:
  - `.\token.txt` from the current working directory
  - `Deep Research\scripts\token.txt`

## 4) Confirm the rest of the required env is present

At minimum, `.env` must still contain the existing Deep Research configuration:

```env
OPENAI_API_KEY=...
BASE_URL=...
PROJECT_ID=...
API_VERSION=...
MODEL=...
PROJECT_ENDPOINT=...
MODEL_DEPLOYMENT_NAME=...
AZURE_BING_CONNECTION_ID=...
DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME=...
BING_CONNECTION_NAME=...
```

If these are missing, the app will not start.

## 5) Launch the app

```powershell
py .\launch_chainlit.py
```

Expected:

- terminal prints `Launching Chainlit at http://localhost:8000`
- browser app becomes available at `http://localhost:8000`

## 6) Open the app and select the new mode

In the Chainlit UI:

1. Click `Transition Playbook`
2. Fill the form with:

```text
Person: Jennifer Brady
From Company: Capital One
To Company: Fannie Mae
New Role: Chief Information Officer
Synthetic scenario: On
```

Optional:

- `Department Hint`: `C-Suite`

## 7) Expected preflight behavior

After submit, the app should automatically run the ProConnect preflight and show a live progress card.

Expected visible checkpoints:

- `Transition Playbook In Progress`
- move summary: `Capital One -> Fannie Mae`
- factual progress stages such as:
  - resolving transition
  - building relationship context
  - generating research plan

Then the validation screen should appear with:

- person match status
- warm path indicator
- prior work indicators
- inferred industry context
- actions:
  - `Run Research`
  - `Edit Prompt`
  - `Adjust Transition`
  - `View Generated Prompt`

## 8) Expected prompt behavior

Click `View Generated Prompt`.

Expected:

- the generated transition research prompt appears in a separate message
- it is not dumped inline in the main validation card

Optional:

1. Click `Edit Prompt`
2. Paste a revised prompt as the next chat message
3. Expected result: the app confirms the updated prompt and re-renders the validation screen

## 9) Run the full workflow

Click `Run Research`.

Expected run stages:

- ProConnect preflight is already done
- Deep Research runs with live polling-style activity
- Credentials validation runs after Deep Research
- final ProConnect actioning runs after Credentials
- compact transition brief is rendered at the end

## 10) Expected final output

The default visible output should be compact.

You should see:

- a transition summary
- top opportunities
- proof and warm-path summaries
- recommended next actions

You should not see:

- the full Deep Research report dumped inline by default
- the full ProConnect dossier dumped inline by default

Instead, you should get secondary actions for:

- `View Full Research Report`
- `View ProConnect Dossier`
- `View Source Evidence`

## 11) Expected demo outcome for the synthetic Jennifer Brady scenario

This is not a factual public-move validator. It is a supervised planning workflow.

For this specific demo, you are validating:

- the structured transition form works
- ProConnect preflight resolves the source/destination context
- the generated prompt is visible and editable
- the research run completes end-to-end
- the final screen is a compact action brief rather than a wall of text
- artifact buttons expose the detailed research and dossier data on demand

## 12) Fast troubleshooting

### App fails before launch

Likely cause:

- missing Deep Research env vars

Fix:

- compare `.env` against `env.example`

### Transition preflight fails immediately

Likely causes:

- expired ProConnect token
- VPN not connected
- `PROCONNECT_TOKEN_FILE` points to the wrong path

Fix:

1. refresh `token.txt`
2. confirm VPN is connected
3. confirm the exact path in `.env`

### Transition preflight returns auth-like errors

Likely causes:

- token expired
- token pasted with bad whitespace

Fix:

```powershell
Set-Content -Path .\token.txt -Value 'PASTE_FRESH_RAW_JWT_HERE' -NoNewline
```

### Deep Research starts but final run fails

Likely causes:

- Azure Deep Research configuration issue
- model deployment / Bing connection issue

Fix:

- re-check the existing Deep Research env vars
- confirm those settings already work in normal `Deep Research` mode

### No ProConnect detail shows up in the transition flow

Likely causes:

- token not being picked up
- no VPN
- running from the wrong folder with fallback token lookup

Fix:

- prefer `PROCONNECT_TOKEN_FILE` over implicit fallback

## 13) Recommended one-pass validation

Run this exact sequence:

1. Refresh `token.txt`
2. Launch Chainlit
3. Select `Transition Playbook`
4. Submit the Jennifer Brady synthetic scenario
5. Confirm preflight screen appears
6. Confirm `View Generated Prompt` works
7. Click `Run Research`
8. Confirm compact brief appears
9. Confirm `View Full Research Report` works
10. Confirm `View ProConnect Dossier` works

If all 10 pass, the implementation is behaving as intended for the demo.
