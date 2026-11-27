# OfficeKit MCP and agent skill support

Version: 1.1.1 (2026-10-21)

## What it is

`officekit-mcp` is a stdio [MCP](https://modelcontextprotocol.io) server that lets local AI
agents (Claude Desktop, Claude Code, Cursor, Codex) use OfficeKit's offline tools. It serves
requests by calling the existing FastAPI app **in-process** through an ASGI transport.

- No TCP port is opened, so the desktop sidecar's bearer token and origin checks are not
  involved; there is nothing for a web page or another process to reach.
- Every action maps to a route the app serves (`tests/mcp_server_unittest.py` checks method and path against the FastAPI routes)
  (`tests/mcp_server_unittest.py` fails if one is not), so request validation, size limits and
  release scope stay in one place.
- Not exposed: process control, storage cleaner, file jobs/workspaces (native file-grant flows),
  dictation. Nothing exposed deletes or overwrites a user file.
- Password and passphrase generators are not offered: the generated secret would be written into
  the agent's conversation. Users generate secrets in the app.
- **Never exposed, enforced in code:** clipboard history and snippets, dictation and transcript
  history, recents. They can hold passwords and other secrets the user never gave an agent.
  `assert_no_sensitive_actions()` in `officekit/mcp/registry.py` stops the server from starting if
  any registered route path contains one of those markers; a test covers it. Do not add an
  override flag.

## Tools (7)

| Tool | Actions |
| --- | --- |
| `officekit_help` | parameters for any action |
| `officekit_calc` | loan-emi, compound/simple-interest, vat-sales-tax, freelance-rate, margin-markup, break-even, depreciation, percent-of, percentage-change, discount, math-eval, units-convert, units-catalog, colors-convert |
| `officekit_dev` | devtools (JSON/YAML/Base64/URL/JWT), hashes |
| `officekit_pdf` | text, tables, tables-export, page-counts, merge, split-groups, delete-pages, reorder-pages, compress, strip-metadata, protect, unlock, to-images, extract-statement |
| `officekit_image` | convert, resize, strip-metadata |
| `officekit_privacy` | pii-scan, pii-redact |
| `officekit_system` | info, resources, metrics |

Grouping keeps the always-loaded tool definitions small; `officekit_help` returns exact
parameters on demand (generated from the app's OpenAPI schema for JSON actions).

## Safety model

- `pii-scan` returns findings as type, location and a partial hint (`•••••••••••••.com`), never
  the raw value, matching the app's default Mask behaviour. `pii-redact` works on finding ids.
- Inputs must be inside allowed folders: `OFFICEKIT_MCP_ALLOWED_DIRS` (path-separator list),
  default the working directory, `~/Documents`, `~/Downloads`, `~/Desktop` and the output folder.
  Symlinks are resolved first; hidden files and folders are refused; inputs over 256 MB are refused.
- Outputs go to `OFFICEKIT_MCP_OUTPUT_DIR` (default `~/OfficeKit Output`), created on demand,
  never overwriting (`name-2.ext`).
- `OFFICEKIT_MCP_TOOLS=pdf,calc` limits which groups are offered (`none` offers only `officekit_help`).
- Tool results are returned to the agent and therefore to its model provider; the app says so.

### Saved settings

Settings → Agent settings writes `~/.officekit/agent-settings.json` (mode 0600, written atomically;
override the path with `OFFICEKIT_AGENT_SETTINGS`):

```json
{ "version": 1, "tools": ["pdf", "calc"], "allowed_dirs": ["/Users/me/Documents"], "output_dir": "/Users/me/OfficeKit Output" }
```

Precedence per value: environment variable, then this file, then the built-in default. The Rust
commands refuse bad input and `officekit/mcp/settings.py` re-validates on every start, falling back
to the restrictive defaults when the file is missing or invalid. A whole drive, relative paths,
unknown keys and unknown tool groups are rejected. `allowed_dirs` is only written after the user
changes folders, so untouched installs keep the default list.

## Install

In the app: Settings (bottom of the left rail) offers, in order, **Install skill** (recommended:
about 80 tokens until used) and **Connect through MCP** (copy-ready config per client, about 770
tokens per session). Both launch the bundled helper `Contents/Resources/binaries/officekit-media`
with `--agent-cli` or `--agent-mcp`; the same launcher still serves the Media Toolkit through
`--mcp-server` and its CLI. The helper is only bundled on macOS today; elsewhere Settings says it
is unavailable and disables Install and Copy.

Claude Code: `claude mcp add officekit -- '<helper>' --agent-mcp`. Claude Desktop and Cursor take
`{"mcpServers":{"officekit":{"command":"<helper>","args":["--agent-mcp"]}}}`; Codex takes
`[mcp_servers.officekit]` with `command` and `args = ["--agent-mcp"]`.

The skill installer writes `~/.claude/skills/officekit/SKILL.md` with the helper path filled in.
It updates a file it previously wrote and refuses to overwrite any other skill of that name.

Development without the app: `python mcp_main.py` (MCP) or `python mcp_main.py call ...` (CLI).

## Measurements (2026-10-19, macOS, Python 3.14, source checkout, 30-page 28 KB PDF)

Token figures are character counts divided by 4 (estimates, not a tokenizer).

| Metric | Result |
| --- | --- |
| Tool definitions, shipped (7 grouped tools) | 3,064 chars, about 770 tokens |
| Baseline: one tool per route (41 tools, schemas from OpenAPI) | 17,663 chars, about 4,400 tokens |
| `initialize` | 67 ms |
| `tools/list` | under 1 ms |
| First tool call (imports the app) | 530 ms |
| Warm calculator call | 2.5 ms |
| PDF text, 2 pages | 68 ms, 4.5k chars returned inline |
| PDF text, 30 pages | 1.06 s; 69k chars saved to a file, about 500 chars preview returned |

Reading: the grouped design costs about 770 tokens per session, about 82% less than a flat
tool-per-route design. The 30-page extraction keeps about 69k characters (roughly 17k tokens)
out of the context unless the agent chooses to read the file.
Not measured: end-to-end token savings on real agent tasks (needs a client and model run),
the packaged binary's startup (PyInstaller build not done), Windows.

## Skill + CLI mode (no MCP)

The same binary also runs as a CLI, so a skill can use OfficeKit without an MCP connection:

```
officekit-mcp call <group> <action> [--file PATH]... [--params 'JSON']
officekit-mcp help <group> <action>
```

It reuses `OfficeKitMcpServer.call_tool`, so folder rules, masking and the sensitive-data guard
are identical (`tests/mcp_cli_unittest.py`). Exit code 0 prints the result to stdout; 1 prints the
error to stderr; 2 means unusable `--params`. `assets/agent-skill/SKILL.md` documents it with a
`{{OFFICEKIT_BIN}}` placeholder that the installer replaces with the real binary path.

### Skill vs MCP (2026-10-21, same machine; tokens are chars / 4 estimates)

| | MCP | Skill + CLI |
| --- | --- | --- |
| Always in context, every session | about 766 tokens (tool definitions) | about 80 tokens (skill description) |
| When actually used | nothing more | +394 tokens (skill body, loaded on demand) |
| One loan-EMI call | 34 tokens | 26 tokens (plus the Bash tool's own overhead) |
| Latency per call | 2.5 ms warm | about 920 ms (new process, imports the app each time) |

Reading: the skill is about 90% cheaper when OfficeKit is not used in a session, and about 38%
cheaper even in a session that uses it (474 vs 766) before counting calls. MCP is about 370 times
faster per call, so a task with many calls is slower through the CLI (10 calls is roughly 9 s).
Skills only work in clients that load skills; MCP works across clients. Not measured: real agent
runs, the Bash tool's per-call token overhead, Windows.

Default recommendation: Settings offers "Install skill" first and MCP as the alternative for
clients without skills or for call-heavy workflows.

## Settings screen

Implemented from the approved mock (`docs/ui-research/2026-10-21-approved-settings-ai-agents.md`),
skill first. Settings is a browsing destination like Activity: no persistent action bar and the rail
does not auto-collapse. Code: `assets/officekit-agents.js`, `src-tauri/src/agent_settings.rs`.
Tests: `tests/agent-settings-ui.test.mjs`, `ui-tests/agent-settings.spec.mjs` (desktop and compact
WebKit, native commands faked), `cargo test` module `agent_settings`, `tests/mcp_settings_unittest.py`.

Not verified here: the screen against a real packaged app (the native commands are covered by Rust
unit tests and the UI by a fake of them), and Windows (no bundled helper there yet).
