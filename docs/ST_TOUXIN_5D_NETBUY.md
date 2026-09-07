# st-touxin-5d-v0 — 投信 5 日買超％／名次（CONDITIONAL only）

Observation-only 5-trading-session institutional (投信) net-buy metrics for
EvidencePack and `/research/touxin-5d-netbuy`. **T5 scope:** data contract +
append-only ledger + CONDITIONAL display — **not** a buy signal, not
DecisionContext, not breakout, not PDF scrape-as-FACT.

## Contract summary

| Field | Value / rule |
|-------|----------------|
| `contractId` | `st-touxin-5d-v0` |
| `window` | **5** TW trading sessions ending at `asOf` (inclusive) |
| `netBuyShares` | `Σ trust_net_shares` over the window (股；TWSE T86「投信買賣超股數」) |
| `netBuyPct` | `netBuyShares / volume5d` when `volume5d > 0`; else `null` |
| `volume5d` | `Σ volume_shares` over the same window (股；當日成交量) |
| `rankAmongUniverse` | Optional cross-section rank by `netBuyShares` among symbols with a **complete** 5-session window in the ledger at PIT; rank **1** = highest net buy |
| `universe` | TW listed symbols present in `touxin_ledger` with all 5 sessions knowable at `knowledgeCutoff` |
| `label` | Always **`CONDITIONAL`** |
| `hostApprovalHash` | Always `null` (no FACT in this PR) |
| `disclaimerKey` | `st-touxin-5d-v0-non-recommendation` |

### Formula (verifiable)

```
netBuyShares  = sum(trust_net_shares[d] for d in window)
volume5d      = sum(volume_shares[d] for d in window)   # may be partial/null
netBuyPct     = netBuyShares / volume5d   # dimensionless ratio; UI may show ×100 as %
rankAmongUniverse = 1 + count(peer where peer.netBuyShares > netBuyShares)
```

**Denominator choice:** 5-day cumulative **share volume** (`volume_shares`), not
shares outstanding. Volume is optional per row; when any session lacks volume,
`volume5d` may be incomplete and `netBuyPct` stays `null` with `pitLimitation`.

## Source & ingest

| Priority | Path | `source` value |
|----------|------|----------------|
| 1 | Append-only SQLite ledger `data/touxin_ledger/touxin_ledger.db` | e.g. `twse/T86`, `fixture/test` |
| 2 | Adapter from `chip_history_tracker` (T86 batch) | `chip_history/T86` (trust only; volume often null) |
| 3 | Fixture-driven tests / offline tooling | `fixture/test` |

Rows are **append-only** (`INSERT OR IGNORE`). Schema:

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT | e.g. `2330` |
| `session_date` | TEXT | `YYYY-MM-DD` TW session |
| `trust_net_shares` | REAL | 投信買賣超股數（可正可負） |
| `volume_shares` | REAL | 當日成交量（股）；可 NULL |
| `source` | TEXT | Provenance |
| `ingested_at` | TEXT | ISO-8601 ingestion time |

`chip_history_tracker.py` may call `touxin_ledger.ingest_chip_history_file()` after
each T86 snapshot so ledger stays aligned with existing chip ingest.

When the ledger is empty or incomplete, `touxin_5d.build_observation()` may read
`data/chip_history/*.json` as a **fallback** with `source: chip_history/snapshot`
and `pitLimitation` explaining missing volume / ingestion audit. Response remains
**CONDITIONAL**.

## PIT / availability

A ledger row is visible at decision time when **both** hold:

1. `session_date <= asOf`
2. `ingested_at <= knowledgeCutoff`

Helpers mirror T2 (`ohlc_ledger`):

- `touxin_ledger.availability_predicate(row, as_of=..., knowledge_cutoff=...)`
- `touxin_ledger.query_rows_pit(...)`
- `touxin_ledger.filter_rows_pit(...)`

Publication lag: TWSE T86 is typically available **T+0 after close**; treat
`knowledgeCutoff` no earlier than session close (13:30 Asia/Taipei) for same-day
rows unless fixture-backed.

## Modules

| Path | Role |
|------|------|
| `server/touxin_ledger.py` | Append-only store + PIT query + chip_history adapter |
| `server/touxin_5d.py` | 5d metrics + EvidencePack attach helper |
| `server/touxin_5d_routes.py` | `GET /research/touxin-5d-netbuy?symbol=` |
| `src/ui/touxin_5d_v5.js` | CONDITIONAL card (postmarket + stats panel) |
| `tests/test_touxin_5d.py` | Unit tests (ledger, PIT, rank, label) |

EvidencePack wiring: `postmarket_report.build_evidence_pack()` adds
`touxin5dNetBuy` when flag `shadowTouxin5d` is enabled.

## Feature flag

| Key | Env | Default |
|-----|-----|---------|
| `shadowTouxin5d` | `ST_SHADOW_TOUXIN_5D` | **on** (fixture / observation path OK) |

Set `ST_SHADOW_TOUXIN_5D=0` or `data/feature_flags.local.json` →
`"shadowTouxin5d": false` to hide UI and skip EvidencePack attach.

Master switch: `ST_ENABLE_SHADOW_RESEARCH=1` enables all shadow flags.

## Explicit non-goals (this PR)

- Not a buy / sell / deploy signal
- No DecisionContext / `actionEnvelope` writes
- No dual-axis composite score or sim positions
- No PDF auto-import as truth (T6b)
- No LLM-invented 買超 numbers
- No FACT label or `hostApprovalHash`

## Red lines

UI must show a **always-visible non-recommendation disclaimer**. Card must **not**
sit next to deploy / entry controls. Epistemic badge: **CONDITIONAL** only.

## Related

- Chip snapshots: `server/chip_history_tracker.py`, `data/chip_history/`
- T2 OHLC ledger pattern: `docs/OHLC_LEDGER.md`
- Peak observation (CONDITIONAL template): `docs/ST_PEAK_V01.md`
- Epistemic badges: `src/core/epistemic_badges_v5.js`
