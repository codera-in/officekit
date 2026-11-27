# LLD: Everyday Percentages

Version: 1.0.0 · 2026-10-08

## API operations

| Route | Input | Result |
| --- | --- | --- |
| `POST /api/calculator/percent-of` | `{percent, value}` | Echoed inputs, `result`, assumptions |
| `POST /api/calculator/percentage-change` | `{original_value, new_value}` | Echoed inputs, signed `change_value`, `change_percent`, `direction`, assumptions |
| `POST /api/calculator/discount` | `{price, discount_percent}` | Echoed inputs, `savings`, `discounted_price`, assumptions |

All DTOs reject unknown fields and numeric strings/booleans. Each response declares `{rounding: "half_up", precision: "0.01", currency: "not_inferred", taxes: "excluded"}`.

## Calculation details

- Convert validated numbers with `Decimal(str(value))`; compute with a 40-digit local decimal context.
- Quantize displayed values to `0.01` using `ROUND_HALF_UP`.
- Percent-of: `value × percent ÷ 100`.
- Change: `(new − original)` and `(new − original) × 100 ÷ original`; zero original is invalid. Direction is increase, decrease, or no-change based on the unrounded difference.
- Discount: `price × rate ÷ 100`; subtract rounded savings from price for the final amount.

## UI lifecycle

Stable registry ID: `everyday_percentages`; operation IDs passed to the shared calculator client: `percent_of`, `percentage_change`, and `discount`. The workbench has a mode selector with mode-specific fields. `officekitCalculateFinancialUtility` enforces exact request keys and verifies response keys, input echo, arithmetic, direction and assumptions. Render results through `officekitRenderCalculationActions` under the stable tool ID; include the operation in saved inputs for exact reuse.

## Verification

`tests/test_everyday_percentages.py` covers engine and HTTP behavior. `tests/everyday-percentages-ui.test.mjs` covers the strict client and workbench wiring. `ui-tests/calculator-flow.spec.mjs` covers the real API, three modes, stale output clearing, saved result reopen, and input reuse. The dev catalogue count increases by one; the private beta remains at 23 IDs.
