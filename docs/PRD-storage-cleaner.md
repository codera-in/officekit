# Storage analyser and cleaner

Version: 1.0.0

Requirement and acceptance source: review/storage-cleaner/requirements.md. Approved by the user with “lgtm” on 2026-10-14.

The tool scans the whole computer’s readable local disks, presents a multicolour storage overview by type, automatically identifies OS/application/package caches, Docker usage, old downloads and project leftovers, and lets users inspect and confirm exact cleanup candidates. Shared analysis and review logic use OS adapters so additional operating systems can be supported. Coverage gaps, cleanup impact and per-item outcomes must remain explicit. Source, protected OS data, secrets and Docker volumes are excluded from bulk cleanup. No automatic deletion.
