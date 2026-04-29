# Atlas MS Foundry Kimi Setup for OpenCode

This guide configures OpenCode to use the Protiviti Atlas MS Foundry deployment
`Kimi-K2.6-1` through a separate local compatibility proxy.

Keep the known-working GPT-5.4 proxy exactly as-is. Do not replace
`scripts\atlas_opencode_proxy.py`, do not change the GPT-5.4 environment
commands, and do not reuse port `8010` for Kimi. Kimi gets its own script,
provider ID, model selector, and local port.

Do not commit the subscription key. Store it only in your shell, PowerShell
profile, OS credential store, or a local ignored file.

## What Is Different About This Foundry Setup

- Use the unified MS Foundry base URL: `https://dev.atlas.protiviti.com/msf`.
- Use the model/deployment name: `Kimi-K2.6-1`.
- Use the APIM subscription header John provided: `MSF-Subscription-Key`.
- Include `AtlasAuthType: EntraID` because the Atlas thread called it out for
  JWT-related errors.
- Start with the OpenAI v1 endpoint:
  `/openai/v1/chat/completions`, passing `"model": "Kimi-K2.6-1"` in the
  request body. Current Microsoft Foundry docs recommend this v1 path for
  non-OpenAI provider models that support OpenAI chat-completions syntax, and
  John included this path in the Atlas examples.
- Keep OpenCode pointed at the local deployment-shaped proxy URL. This preserves
  the original Atlas/OpenCode setup shape while letting the proxy translate to
  the upstream Foundry route.
- If Atlas says the v1 route is not mapped for Kimi, switch the proxy to the
  Azure deployment-shaped endpoint:
  `/openai/deployments/Kimi-K2.6-1/chat/completions?api-version=2025-01-01-preview`.
- If Atlas says to use the model-inference route, switch the proxy to:
  `/models/chat/completions?api-version=2024-05-01-preview`.

The local proxy is still needed because OpenCode can send fields such as
`max_tokens` and `reasoningSummary`. Existing Atlas deployments rejected those,
so the proxy rewrites `max_tokens` to `max_completion_tokens` and removes
`reasoningSummary` before forwarding. Kimi's own OpenAI-compatible docs use
`max_tokens`, so this proxy makes the token parameter configurable per upstream
route instead of assuming the GPT-specific rewrite is always correct.

## Files Added In This Repo

- `scripts/atlas_kimi_opencode_proxy.py`: Kimi-only local FastAPI proxy.
- `scripts/smoke_test_atlas_kimi_proxy.py`: optional Kimi proxy smoke test.

The proxy supports three upstream modes:

| Mode | Upstream path | When to use |
| --- | --- | --- |
| `openai-v1` | `/openai/v1/chat/completions` with model in body | Recommended first try for Kimi |
| `deployments` | `/openai/deployments/<model>/chat/completions` | Use if Atlas mapped Kimi like GPT deployments |
| `models` | `/models/chat/completions` with model in body | Use if Atlas asks for the model-inference route |

## One-Time Proxy Dependency Install

Run this on the work laptop from this repo root:

```powershell
cd "C:\path\to\BD Tool"
python -m pip install fastapi uvicorn httpx python-dotenv
```

Use the active Python environment you normally use with this repo. These deps
are for the local proxy only.

## Shell 1: Start The Proxy

Open a new PowerShell window for Kimi. Leave your GPT-5.4 proxy window alone.
Replace the placeholder with the subscription key John issued for Salmaan. Do
not paste the key into repo files.

```powershell
cd "C:\path\to\BD Tool"

$env:ATLAS_API_KEY = "<paste Salmaan's MSF subscription key here>"
$env:ATLAS_BASE_URL = "https://dev.atlas.protiviti.com/msf"
$env:ATLAS_SUBSCRIPTION_HEADER = "MSF-Subscription-Key"
$env:ATLAS_AUTH_TYPE = "EntraID"
$env:ATLAS_UPSTREAM_STYLE = "openai-v1"
$env:ATLAS_INCLUDE_API_VERSION = "false"
$env:ATLAS_TOKEN_PARAMETER = "max_tokens"
$env:ATLAS_PROXY_HOST = "127.0.0.1"
$env:ATLAS_PROXY_PORT = "8011"

python scripts\atlas_kimi_opencode_proxy.py
```

Leave this shell running.

In a separate PowerShell window, verify the local process:

```powershell
Invoke-RestMethod http://127.0.0.1:8011/health
```

Expected: `ok: true`, `base_url: https://dev.atlas.protiviti.com/msf`,
`subscription_header: MSF-Subscription-Key`, `upstream_style: openai-v1`,
`token_parameter: max_tokens`, and `has_api_key: true`.

## Optional Entra Token

If Atlas returns a JWT, Entra, or authorization error even with the MSF
subscription key set, get an Entra token under Salmaan's identity and restart
the proxy with `ATLAS_ENTRA_TOKEN`.

```powershell
az login --tenant 16532572-d567-4d67-8727-f12f7bb6aed3

$env:ATLAS_ENTRA_TOKEN = az account get-access-token `
  --tenant 16532572-d567-4d67-8727-f12f7bb6aed3 `
  --scope api://67976cef-1f94-4486-b8f4-dd27f4f418ae/.default `
  --query accessToken -o tsv

python scripts\atlas_kimi_opencode_proxy.py
```

The proxy sends this as `Authorization: Bearer <token>` and still sends the
MSF subscription key headers.

## OpenCode Config

Edit the global OpenCode config on the work laptop:

```powershell
notepad "$env:USERPROFILE\.config\opencode\opencode.jsonc"
```

Add or merge this provider. If you already have an `atlas` provider, keep your
existing GPT-5.4 `atlas` provider untouched. Add this as a second provider named
`atlas-kimi`.

This config deliberately keeps the real MSF key out of OpenCode. The proxy
shell owns upstream authentication and injects the Atlas headers. OpenCode only
needs a non-secret placeholder key for the local provider.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "atlas-kimi": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Atlas MS Foundry",
      "options": {
        "baseURL": "http://127.0.0.1:8011/openai/deployments",
        "apiKey": "atlas-local-proxy",
        "headers": {
          "AtlasAuthType": "EntraID"
        }
      },
      "models": {
        "Kimi-K2.6-1": {
          "name": "Kimi K2.6 Atlas",
          "limit": {
            "context": 200000,
            "output": 32000
          }
        }
      }
    }
  },
  "model": "atlas-kimi/Kimi-K2.6-1",
  "small_model": "atlas-kimi/Kimi-K2.6-1"
}
```

If your current `opencode.jsonc` already has `"provider": { "atlas": ... }`,
do not paste this as a full replacement. Add only the `"atlas-kimi": { ... }`
block next to `"atlas"`. Then use `atlas-kimi/Kimi-K2.6-1` when you want Kimi
and keep using `atlas/gpt-5-4-20260305-gs` when you want GPT-5.4.

OpenCode config files are merged. A project-level `opencode.json` can override
the global file, so if OpenCode ignores this config, check for project config
in the repo you launched from.

## Shell 2: Run OpenCode

Open a second PowerShell window. This shell does not need the MSF subscription
key when you use the preferred local-proxy config above.

```powershell
opencode --print-logs --log-level DEBUG run --format json `
  -m atlas-kimi/Kimi-K2.6-1 `
  "Reply with exactly: Hello from OpenCode"
```

Success criteria:

- Output includes `Hello from OpenCode`.
- Logs show `providerID=atlas-kimi`.
- Logs show the URL starts with `http://127.0.0.1:8011/openai/deployments`.
- No Atlas error reports `max_tokens`, `max_completion_tokens`, or
  `reasoningSummary` as unsupported or unknown.

The local request URL is intentionally deployment-shaped because that is the
known-good OpenCode/Atlas integration shape from the original setup. The proxy
forwards it to `/openai/v1/chat/completions` while keeping
`"model": "Kimi-K2.6-1"` in the body.

## Direct Proxy Smoke Test

If OpenCode fails, isolate OpenCode from Atlas by testing the proxy directly:

```powershell
python scripts\smoke_test_atlas_kimi_proxy.py --model Kimi-K2.6-1
```

This command still reaches Atlas through the proxy, so only run it on the work
laptop with your Atlas access.

## If The First Route Fails

If Atlas returns a route error for `/openai/v1/chat/completions`, first try the
deployment-style route John showed for GPT examples:

```powershell
$env:ATLAS_UPSTREAM_STYLE = "deployments"
$env:ATLAS_INCLUDE_API_VERSION = "true"
$env:ATLAS_API_VERSION = "2025-01-01-preview"
$env:ATLAS_TOKEN_PARAMETER = "max_completion_tokens"
python scripts\atlas_kimi_opencode_proxy.py
```

That forwards to:

```text
https://dev.atlas.protiviti.com/msf/openai/deployments/Kimi-K2.6-1/chat/completions?api-version=2025-01-01-preview
```

If Atlas returns `404`, `deployment not found`, or says Kimi must use the
model-inference endpoint, restart the proxy with the Foundry models route:

```powershell
$env:ATLAS_UPSTREAM_STYLE = "models"
$env:ATLAS_INCLUDE_API_VERSION = "true"
$env:ATLAS_API_VERSION = "2024-05-01-preview"
$env:ATLAS_TOKEN_PARAMETER = "max_tokens"
$env:ATLAS_EXTRA_PARAMETERS = "pass-through"
python scripts\atlas_kimi_opencode_proxy.py
```

Keep the OpenCode config the same for the first retest. The proxy will receive
OpenCode's deployment-shaped local URL but forward to:

```text
https://dev.atlas.protiviti.com/msf/models/chat/completions?api-version=2024-05-01-preview
```

with `"model": "Kimi-K2.6-1"` in the JSON body.

If Atlas rejects `max_tokens` with a message like `Use max_completion_tokens
instead`, keep the same route and restart with:

```powershell
$env:ATLAS_TOKEN_PARAMETER = "max_completion_tokens"
python scripts\atlas_kimi_opencode_proxy.py
```

If Kimi rejects fixed sampling parameters from OpenCode, strip only the exact
field named in the Atlas error. For example:

```powershell
$env:ATLAS_STRIP_PARAMS = "temperature,top_p,presence_penalty,frequency_penalty"
python scripts\atlas_kimi_opencode_proxy.py
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `ConnectionRefused` to `127.0.0.1:8011` | Kimi proxy is not running | Start the Kimi proxy shell first |
| `Attribute "app" not found` | Wrong proxy file or module | Use `scripts/atlas_kimi_opencode_proxy.py` |
| `No module named scripts` | Uvicorn launched from wrong folder | Run `python scripts\atlas_kimi_opencode_proxy.py` from repo root |
| `Unsupported parameter: max_tokens` | OpenCode is bypassing proxy | Confirm `baseURL` is local proxy |
| `Unsupported parameter: max_tokens` while using proxy | Upstream route wants `max_completion_tokens` | Set `ATLAS_TOKEN_PARAMETER=max_completion_tokens` |
| `Unsupported parameter: max_completion_tokens` | Upstream route wants Kimi/OpenAI-style `max_tokens` | Set `ATLAS_TOKEN_PARAMETER=max_tokens` |
| `Unknown parameter: reasoningSummary` | OpenCode is bypassing proxy or old proxy | Use the proxy in this repo |
| `401 invalid subscription key` | Missing/wrong MSF key or header | Check `ATLAS_API_KEY` and `ATLAS_SUBSCRIPTION_HEADER=MSF-Subscription-Key` |
| JWT or Entra error | Atlas requires bearer token too | Set `ATLAS_ENTRA_TOKEN` using the Azure CLI steps |
| `404` or model not found | Wrong endpoint style or model name | Try `openai-v1`, then `deployments`, then `models`; verify `Kimi-K2.6-1` casing |
| Kimi rejects `temperature`, `top_p`, or penalties | Kimi has fixed parameter support | Add only the rejected field to `ATLAS_STRIP_PARAMS` |
| OpenCode uses another provider | Config merge/override issue | Run with `-m atlas-kimi/Kimi-K2.6-1` and inspect debug logs |

## Security Notes

- Rotate the key if it was pasted into any shared channel, committed file, or
  logs.
- Do not store the subscription key in `opencode.jsonc`.
- Prefer keeping the real subscription key only in the proxy shell. The
  OpenCode config can use a non-secret local placeholder because it talks only
  to `127.0.0.1`.
- Do not commit PowerShell profiles, `.env` files, screenshots, or logs
  containing the key.
- Keep the proxy bound to `127.0.0.1`, not `0.0.0.0`.

## Source Notes

- Local Atlas OpenCode skill reference:
  `/Users/salmaanrauf/.codex/skills/atlas-opencode-proxy/references/atlas-opencode-setup.md`.
- User-provided Atlas thread: unified MSF base URL, `MSF-Subscription-Key`,
  `AtlasAuthType: EntraID`, tenant/client/scope, and deployment
  `Kimi-K2.6-1`.
- Official OpenCode docs: JSON/JSONC config, config precedence, provider
  options, env substitution, `@ai-sdk/openai-compatible`, `baseURL`, `apiKey`,
  custom headers, and model limits.
  https://opencode.ai/docs/config
  https://opencode.ai/docs/providers
- Official Microsoft Foundry docs: Foundry deployments are addressed by
  deployment name, the current OpenAI v1 path supports non-OpenAI provider
  models with model name in the body, deployment-shaped chat completions still
  exist with `api-version`, and the model-inference route is
  `/models/chat/completions?api-version=2024-05-01-preview`.
  https://learn.microsoft.com/en-us/azure/foundry/openai/reference
  https://learn.microsoft.com/en-us/azure/foundry/openai/latest
  https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints
  https://learn.microsoft.com/en-us/rest/api/aifoundry/model-inference/get-chat-completions/get-chat-completions?view=rest-aifoundry-model-inference-2024-05-01-preview
- Official Kimi K2.6 docs: Kimi is OpenAI-compatible and documents
  `max_tokens`; that is why the Kimi path starts with
  `ATLAS_TOKEN_PARAMETER=max_tokens` instead of blindly applying the older GPT
  Atlas rewrite.
  https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart

The attached `atlas.docx` from the pasteboard could not be read here because it
is Intune/MAM encrypted rather than a normal DOCX zip package.
