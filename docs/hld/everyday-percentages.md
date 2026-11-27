# HLD: Everyday Percentages

Version: 1.0.0 · 2026-10-08

## Goal

Provide three common calculator tasks from one searchable OfficeKit tool: percent of a value, percentage change, and single discount. The feature remains part of the existing local desktop calculator architecture.

## Boundaries

- The React/HTML calculator workbench selects one operation and calls a typed local FastAPI route.
- `CalculatorEngine` owns deterministic arithmetic and input checks; it has no network, persistence, or currency-provider dependency.
- `engine_comms.TOOL_REGISTRY` contains one discoverable tool ID; its three API operations are counted as separate coded families.
- Existing result snapshots own save, history, reuse, and exports. The operation name is stored with the input snapshot so reuse restores the correct form.
- The private-beta allowlist is unchanged until this tool is deliberately promoted.

## Product rules

Use decimal arithmetic and half-up rounding to two decimal places. Results are unit-neutral. Currency, taxes, and jurisdiction are not inferred. Percentage change requires a positive original value. Discount rate is restricted to 0–100%; percent-of supports 0–1,000,000%.

## Failure behavior

Invalid, non-finite, non-JSON-numeric, unknown-field, or out-of-range inputs return HTTP 422. The UI clears stale results when values or operation change and validates response shape, arithmetic, and declared assumptions before displaying or saving.

## Quality evidence

Engine and HTTP tests cover independent reference vectors and boundary inputs. Browser tests use the real local API at desktop and compact widths and exercise calculation, save, reopen, and input reuse. Installed-Mac interaction remains a separate release gate.
