# System-wide storage analyser and cleaner

Version: 1.0.1 · Approved design: user “lgtm”, 2026-10-14.

## Scope

Extend the existing Storage analyzer destination with explicit system-wide discovery and reviewed cleanup. One shared local service and UI; platform adapters enumerate local disks, identify known cache paths, classify generated leftovers and provide safe mutation capabilities. macOS is the initial cleanup target. Windows/Linux discovery and capability states share the contract; unsupported mutations fail closed. This local desktop feature has no database, tenant input, cloud processing or network-dependent analysis.

## Flow

Native command authorises a bounded asynchronous scan → UI polls progress/cancellation → report lists disks, exclusive storage categories, coverage gaps and cleanup candidates → user selects exact candidates → service issues an expiring identity-bound cleanup plan → review dialog describes Trash versus permanent actions → native command executes the plan once → per-item outcomes and disk metrics are shown.

## Surface and ownership

POST /api/storage-scans creates native-authorised discovery; GET /api/storage-scans/{id} reads status/report; DELETE requests cancellation. POST /api/storage-cleanup-plans creates a reviewed selection snapshot. POST /api/storage-cleanup-plans/{id}/execution requires native authorisation and consumes the plan once. Strict typed DTOs reject paths, arbitrary commands and unknown fields. Mutating routes use the existing app-authentication boundary plus the hidden native grant credential.

The UI uses the existing shell and storage tool route. Analysis action replaces generic file-run controls in the system-wide mode; the scan scope retains folder analysis as an optional route to existing file tooling. New controls each have a distinct job: scan age, scan/cancel, access coverage, candidate selection, plan review and confirmation. The proportional bar/legend report capacity by type and never imply that all category bytes can be cleaned.

## Safety and pitfalls

P-157: paths are not deletion authority. Plans retain identity and use held parent descriptors, no-follow traversal and no-replace publication into Trash; unsafe or changed items are skipped. P-162: report modification dates and true birth dates where available, never substitute inode-change time. P-034: system-owned and protected descendants remain excluded from cleanup even if discovered through broad system scope. Project context is required before identifying dependency/build folders; source and environments are excluded from bulk cleanup. No Docker-volume cleanup. Tool invocations are bounded argument vectors with local-context checks and no shell. Partial coverage and unavailable tools are explicit.

## Accounting

Disk capacity/free metrics are physical filesystem values. Discovered file-category sizes are estimates and mutually exclusive; deduplicate aliases and hard links. Unreadable or unclassified used space stays separate. Docker virtual storage is a subset/estimate, never added again to the host total. Moving items to Trash does not claim immediately freed space. Rescan/recheck disk availability after mutation.

## Validation

Final package-cache implementation uses a private 0700 staging directory on the same volume, atomic identity-bound moves, native tool commands against a real staging path, and no-replace cache restoration. It retains recovery data when another process recreates the original path. Real npm/pip3/uv disposable-cache integration passes; `/dev/fd` paths were rejected after real compatibility checks. Docker usage is a bounded local `system df` inspection, not host-volume accounting. macOS permission recovery opens Full Disk Access settings; granting access stays with the user. Largest-file/folder reports retain bounded recursive logical estimates and true dates; a fail-closed lsof check protects Trash candidates currently open by another process.

Fixture-driven platform discovery, identity/race/expiry/single-use tests, strict authenticated route tests, malformed-response UI tests, multicolour reconciliation, native compile/tests, browser flows with synthetic files and packaged/installed checks. Never clean the developer’s real files during testing. Installed Windows/Linux mutation support requires separate platform evidence.
