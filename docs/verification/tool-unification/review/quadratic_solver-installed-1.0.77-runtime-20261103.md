# Quadratic Solver installed-app check — 2026-11-03

## Build and input flow

The installed app reports version 1.0.77, while this worktree is version 1.0.76. The live screen initially showed `a=1`, `b=-3`, `c=2`; the result was two real roots, 1 and 2, with discriminant 1 and residual 0.

Blanking `a` kept `b=-3` and `c=2`, removed Copy / Save / Download, and displayed “Fill in every field to see the result.” Restoring `a=1` and setting `b=0`, `c=1` recovered to a complex conjugate pair (`0 - 1i` and `0 + 1i`), discriminant -4 and residual 0. Copy result, Save result and Download returned.

## Action placement and evidence

In installed 1.0.77, the three result actions appear inside the result card. Current-source screenshots show the actions in the shared fixed bottom dock:

- [Current-source real-root result](../after/quadratic_solver-real-roots-current-source-superset.png)
- [Current-source complex-root recovery](../after/quadratic_solver-valid-recovery-current-source-superset.png)

This visual difference is tracked as installed/source version mismatch; no source layout change was made for the older build. The CUA screenshot was visually inspected in-session, but saving a local installed-app capture failed because macOS `screencapture` reported “could not create image from display.” Installed output behavior was verified from the live accessibility tree. No result was saved or copied, so the user’s saved results and clipboard were untouched.

## Remaining checks

Compact keyboard navigation, actual Copy / Save / Download bytes, and a matching installed build remain open. The installed app was quit after the check.
