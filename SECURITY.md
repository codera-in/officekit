# Security policy

## Reporting a vulnerability

Please report security problems **privately**. Do not open a public issue or pull request for them.

- Use GitHub's **Report a vulnerability** button on the repository's Security tab (private vulnerability reporting), or
- email **support@officekit.app** with "Security" in the subject.

Include the OfficeKit version (shown in the app footer), your macOS version, what you did, what happened, and what
you expected. A proof of concept helps. Do not include real personal files; a small synthetic file is enough.

We will acknowledge your report within 5 working days, keep you informed, and credit you in the release notes if you
wish. Please give us a reasonable time to ship a fix before you disclose publicly.

## What is in scope

- The OfficeKit desktop app, its local Python API and the Rust shell in this repository.
- The way the app handles files, paths, archives, the clipboard, microphone and calendar data.
- The licence check in the client (for example a way to read another user's data or run code through it).

## What is out of scope

- A modified build that has the licence check removed. The source is open under GPL-3.0-only, so anyone can change
  it; that is not a vulnerability.
- The licensing and support services, which are operated privately. Report problems in them the same way and we will
  route them.
- Findings that need physical access to an unlocked Mac, or a malicious local administrator.
- Missing hardening that has no demonstrated impact.

## Design promises we hold ourselves to

OfficeKit processes files locally, does not log file contents or secrets, keeps its local API bound to the machine
behind a per-run token, and downloads speech models only from pinned sources, checked by size and SHA-256.
If you find a case where it does not, that is a security bug.
