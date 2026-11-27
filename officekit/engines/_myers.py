"""Bounded linear-space Myers O(ND) diff shared by the developer slice (D04 and D17).

The search follows Myers (1986) section 4b: each range is split at its middle
snake, so memory stays linear in the input. The edit-distance bound is enforced
by capping the number of search rounds, so a pathological pair is rejected
instead of running quadratically.
"""

from collections.abc import Hashable, Sequence

MAX_EDIT_DISTANCE = 10_000
# Work units (diagonal visits plus snake steps) one diff may spend across all of
# its search rounds. About 4 million units is roughly a second of CPython, so a
# pathological pair is rejected early instead of spending the whole edit bound (CR-1).
MAX_SEARCH_WORK = 4_000_000

EQUAL = "equal"
DELETE = "delete"
INSERT = "insert"


class EditDistanceExceeded(ValueError):
    """The two sequences differ by more edits than the allowed bound, or the search ran out of work."""


class WorkBudget:
    """Counts search work units; ``spend`` raises once the budget is overdrawn."""

    def __init__(self, units: int = MAX_SEARCH_WORK) -> None:
        self.left = units

    def spend(self, units: int) -> None:
        self.left -= units
        if self.left < 0:
            raise EditDistanceExceeded("search work exceeds the budget")


def diff_ops(
    a: Sequence[Hashable],
    b: Sequence[Hashable],
    max_edits: int = MAX_EDIT_DISTANCE,
    budget: WorkBudget | None = None,
) -> list[tuple[str, int | None, int | None]]:
    """Return a minimal edit script as (kind, index_in_a, index_in_b) tuples.

    Equal items carry both indices; deletes carry only an index in ``a`` and
    inserts only an index in ``b``. Raises ``EditDistanceExceeded`` when the
    minimal number of edits is greater than ``max_edits`` or when the search
    overdraws ``budget`` (a fresh ``MAX_SEARCH_WORK`` budget by default). Callers
    that run several diffs under one request pass one shared budget.
    """
    if abs(len(a) - len(b)) > max_edits:
        raise EditDistanceExceeded("edit distance exceeds the bound")
    if budget is None:
        budget = WorkBudget()
    ops: list = []
    # Pending work is a stack of either (a0, a1, b0, b1) ranges or ready-made op lists.
    pending: list = [(0, len(a), 0, len(b))]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            ops.extend(item)
            continue
        a0, a1, b0, b1 = item
        while a0 < a1 and b0 < b1 and a[a0] == b[b0]:
            ops.append((EQUAL, a0, b0))
            a0 += 1
            b0 += 1
        suffix: list = []
        while a0 < a1 and b0 < b1 and a[a1 - 1] == b[b1 - 1]:
            a1 -= 1
            b1 -= 1
            suffix.append((EQUAL, a1, b1))
        suffix.reverse()
        split = None
        if a0 < a1 and b0 < b1:
            split = _middle_split(a, b, a0, a1, b0, b1, max_edits, budget)
        if split is None or split in ((a0, b0), (a1, b1)):
            # One side is empty, or no common element exists in this range
            # (the minimal script is then all deletes followed by all inserts).
            # If the search stopped at the bound instead, the final edit count
            # check below rejects the input.
            ops.extend((DELETE, i, None) for i in range(a0, a1))
            ops.extend((INSERT, None, j) for j in range(b0, b1))
            ops.extend(suffix)
            continue
        x, y = split
        pending.append(suffix)
        pending.append((x, a1, y, b1))
        pending.append((a0, x, b0, y))
    edits = sum(1 for kind, _, _ in ops if kind != EQUAL)
    if edits > max_edits:
        raise EditDistanceExceeded("edit distance exceeds the bound")
    return ops


def _middle_split(
    a: Sequence[Hashable],
    b: Sequence[Hashable],
    a0: int,
    a1: int,
    b0: int,
    b1: int,
    max_edits: int,
    budget: WorkBudget,
) -> tuple[int, int] | None:
    """Return an absolute split point on an optimal path, or None past the bound."""
    n = a1 - a0
    m = b1 - b0
    delta = n - m
    front = delta % 2 != 0
    max_d = (n + m + 1) // 2
    rounds = min(max_d, max_edits + 1)
    offset = max_d + 1
    size = 2 * max_d + 3
    forward = [-1] * size
    reverse = [-1] * size
    forward[offset + 1] = 0
    reverse[offset + 1] = 0
    f_lo = f_hi = r_lo = r_hi = 0
    for d in range(rounds):
        for k in range(-d + f_lo, d + 1 - f_hi, 2):
            idx = offset + k
            if k == -d or (k != d and forward[idx - 1] < forward[idx + 1]):
                x = forward[idx + 1]
            else:
                x = forward[idx - 1] + 1
            y = x - k
            start = x
            while x < n and y < m and a[a0 + x] == b[b0 + y]:
                x += 1
                y += 1
            budget.spend(1 + x - start)
            forward[idx] = x
            if x > n:
                f_hi += 2
            elif y > m:
                f_lo += 2
            elif front:
                other = offset + delta - k
                if 0 <= other < size and reverse[other] != -1 and x >= n - reverse[other]:
                    return a0 + x, b0 + y
        for k in range(-d + r_lo, d + 1 - r_hi, 2):
            idx = offset + k
            if k == -d or (k != d and reverse[idx - 1] < reverse[idx + 1]):
                x = reverse[idx + 1]
            else:
                x = reverse[idx - 1] + 1
            y = x - k
            start = x
            while x < n and y < m and a[a1 - x - 1] == b[b1 - y - 1]:
                x += 1
                y += 1
            budget.spend(1 + x - start)
            reverse[idx] = x
            if x > n:
                r_hi += 2
            elif y > m:
                r_lo += 2
            elif not front:
                other = offset + delta - k
                if 0 <= other < size and forward[other] != -1:
                    x_fwd = forward[other]
                    y_fwd = x_fwd - (delta - k)
                    if x_fwd >= n - x:
                        return a0 + x_fwd, b0 + y_fwd
    return None
