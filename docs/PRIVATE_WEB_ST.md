# Private Web ST

Private Web ST keeps the original Stock Terminal as the development and share
edition while adding a separately promoted, private website edition for one
long-horizon market/research user.

## Non-negotiable boundaries

- The original `START_TIP.cmd` workflow and port `18432` remain unchanged.
- ST and the private gateway both remain bound to loopback.
- The gateway is intended for Tailscale Serve or an equivalent private HTTPS
  tunnel. Do not forward ports `18432`, `18434` or `18435` from a router.
- WaveDeck, broker actions, notifications, credential changes, remote data
  backfills and trading-adjacent routes are not exposed.
- The private production release omits the WaveDeck subproject and its starter;
  the ordinary development/share tree remains the place for that optional tool.
- A dirty development worktree is never copied into production. A release is
  staged from an exact Git commit and requires a separate explicit promotion.
- Production `data/` and `logs/` survive code promotion and rollback.

## Two operating modes

### 1. Development-linked preview

Start the normal local ST first:

```powershell
.\START_TIP.cmd
```

Then start:

```powershell
.\START_PRIVATE_WEB.cmd
```

On first use, the setup tool creates two local-only credentials:

- `owner`: browser access and the approved research/control routes.
- `reader`: read-only browser/API access for invited users and integrations.

Open `http://127.0.0.1:18434/`. The gateway displays the ST login form. Choose
the matching role and enter its token. The gateway creates a signed,
persistent browser session with no application-level clock expiry. It remains
valid until the browser clears the site data or the administrator rotates the
Owner/Reader access tokens. This mode proxies directly to
the development ST on `18432`, so code changes are immediately visible.
Private Web injects the `personal-market` profile before UI boot, so WaveDeck
navigation and connection probes are disabled while the ordinary local UI is
unchanged.

For Tailscale invitations, Reader onboarding, iPhone steps and black-screen
troubleshooting, see [Private Web ST 註冊、邀請與登入指南](PRIVATE_WEB_LOGIN_GUIDE.md).

The unauthenticated health endpoint is intentionally minimal:

```powershell
Invoke-RestMethod http://127.0.0.1:18434/gateway/health
```

Read-only API example:

```powershell
$token = (Get-Content data\private_web_read.token -Raw).Trim()
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://127.0.0.1:18434/market/snapshot -Headers $headers
```

Owner API example:

```powershell
$token = (Get-Content data\private_web_owner.token -Raw).Trim()
$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }
$body = @{ symbols = @("2330", "2454") } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:18434/portfolio -Method Post -Headers $headers -Body $body
```

The route profile is available to the owner at `/gateway/routes`.

## Release gate

The normal development directory is never the production directory.

### Stage a mature commit

Commit the tested revision, then stage that exact commit or tag:

```powershell
py -3 scripts\private_web_release.py stage --ref <commit-or-tag>
```

Staging performs the following without changing the active website:

1. exports only the named Git commit;
2. verifies that the private gateway and host files are present;
3. rebuilds the generated ST HTML;
4. runs the Private Web regression tests; and
5. writes a release manifest under the private install root.

Uncommitted and untracked development changes cannot enter this release.

### Inspect release status

```powershell
py -3 scripts\private_web_release.py status
```

### Promote only after approval

```powershell
py -3 scripts\private_web_release.py promote --release <release-id> --approve
```

The explicit `--approve` flag is required. Promotion replaces managed code but
preserves the active production `data/` and `logs/`. Promoting a previously
staged, tested release provides the rollback path.

The default private install root is:

```text
%LOCALAPPDATA%\StockTerminalPrivateWeb
```

It can be overridden using `--install-root`.

## Isolated host mode

Inside the promoted `current` directory, run:

```powershell
.\START_PRIVATE_WEB_HOST.cmd
```

This supervisor runs:

- production ST backend: `127.0.0.1:18435`;
- authenticated gateway: `127.0.0.1:18434`;
- development ST, when desired: unchanged on `127.0.0.1:18432`.

Backend and gateway output goes to the production `logs/` directory. If a
child process exits unexpectedly, the supervisor restarts the pair with a
bounded restart budget.

## Private HTTPS publication

After host-mode testing succeeds, Tailscale Serve can publish only the gateway
inside the owner's tailnet:

```powershell
tailscale serve --bg http://127.0.0.1:18434
```

Use a restrictive Tailscale Grant for the EVO-T1 service rather than the
default broad policy. Do not use Tailscale Funnel; Funnel is public Internet
exposure.

Add the assigned `*.ts.net` hostname to `allowed_hosts` only if a future policy
removes the default `.ts.net` suffix allowance. A custom private hostname must
always be added explicitly.

## Remote route profile

Read-only access covers market snapshots, Pulse, DecisionContext, quotes,
bars, fundamentals, valuation, breadth, sectors, macro data and health.

Owner writes are limited to research calculations and personal state:

- portfolio and DecisionContext calculations;
- screeners and chain-momentum analysis;
- local AI research/report requests;
- watch rules/configuration; and
- chart drawings.

The following stay local-only:

- AI credential changes and unrestricted AI proxying;
- notification, email and alert transport configuration;
- universe/datasource/macro refresh and historical backfills;
- WaveDeck bridge, override and LLM execution-gate routes; and
- all trading or broker actions.

An intentionally added research endpoint can be enabled through
`extra_read_paths` or `extra_control_paths` in `data/private_web.json`. Keep
these lists exact; do not add `/` or broad prefixes.

## Secrets and audit

The following files are local-only and ignored by Git/share builds:

- `data/private_web.json`
- `data/private_web_owner.token`
- `data/private_web_read.token`
- `logs/private_web_audit.jsonl`
- `logs/private_web_client.jsonl`

Rotate both tokens with:

```powershell
py -3 scripts\setup_private_web.py --rotate
```

Rotation immediately revokes existing browser sessions/API credentials after
gateway restart. The audit log stores request metadata for writes and denials;
the client trace stores sanitized UI boot checkpoints. Neither stores request
bodies, Authorization headers or token values.

Stop the private Gateway/host without touching development ST on `18432`:

```powershell
.\STOP_PRIVATE_WEB.cmd
```
