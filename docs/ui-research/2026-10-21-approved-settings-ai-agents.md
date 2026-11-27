# Approved Settings screen with Connect AI agents

On 2026-10-21 the user approved the Settings screen mock ("approve the mock") after requesting a Settings page and asking that it match the design guidelines. The first mock used hand-written styles and was rejected; the approved mock was rebuilt on the compiled `officekit.css`, the real sidebar markup and daisyUI components. It was reviewed in the Superset Browser in dark and light themes with a clean console and no horizontal overflow. Visual evidence: `docs/ui-research/2026-10-21-settings-ai-agents-approved-mock.png`. The temporary mock HTML and preview server were removed after approval.

## Approved decisions

- **Settings destination:** a sidebar item with the gear icon, pinned at the bottom of the rail above the disk-usage pill, following the existing "Help & feedback and Settings at the bottom" rule. The page uses the shared `ok-page-heading` title and bordered panels.
- **No Save/Reset bar:** switches apply immediately and the page states that agent apps pick changes up on their next start. This avoids a new action-bar pattern.
- **Connect an agent:** tabs for Claude Code, Claude Desktop, Cursor and Codex with a copy-ready command or config built from the real installed binary path, a "helper found" status badge and one primary Copy action.
- **What agents can use:** six daisyUI switches (PDF, Images, Calculators and units, Privacy, Developer and security, System info) with the estimated tool-definition cost stated (about 770 tokens with all six on).
- **Files agents can use:** read-from folders (Documents, Downloads, Desktop) with Change…, and the save-results folder (`~/OfficeKit Output`) with Show in Finder. Originals are never changed.
- **Agent skill:** a panel that installs the OfficeKit skill into `~/.claude/skills/officekit`.
- **Try asking your agent:** three example prompts.
- **Privacy note:** results returned to an agent go to its AI provider; a password given to an agent is visible to it; clipboard history, snippets, dictation and transcripts are never shared.

## Constraints carried into implementation

- Use only `--ok-*` tokens and classes already present in the compiled stylesheet; no literal colours, spacing or type sizes.
- The Developer and security group offers JSON/YAML/Base64/URL/JWT tools and hashes only; password and passphrase generators are not offered to agents.
- The 64px collapsed rail and compact widths were not mocked; verify them against the shared shell behaviour during implementation.
- Resolved 2026-10-21: the user directed "skill first". The Agent skill panel (marked Recommended) precedes Connect through MCP, because the skill costs about 80 tokens until used against about 766 for MCP tool definitions.

## Implementation notes (2026-10-21)

- Settings is a browsing destination like Activity: it is listed with the screens that do not auto-collapse the rail and in the shared action bar's browsing set, so primary buttons stay inside their panels. The built screen first hoisted Copy into the bottom bar and collapsed the rail; both were fixed and are covered by `ui-tests/agent-settings.spec.mjs`.
- The rail's Settings entry is non-shrinking so it never overlaps the scrolling category list.
- Verified in WebKit at desktop and compact widths with the native commands faked. The collapsed 64px rail uses the shared icon-only link styling but was not separately inspected.
