[한국어](quick-start.md) | [English](quick-start.en.md)

[← Back to README](../README.en.md)

# Quick Start

## 0. Prerequisites

> **Run from your project directory.** Gran Maestro analyzes your existing codebase to operate. Launch Claude Code or the Codex CLI plugin runtime from your project root before using the plugin.

Gran Maestro defaults to Codex-primary and `same-host-native-first`. Codex host → Codex provider and Claude Code host → Claude provider delegation use the host's native agents first, so no separate provider CLI is required solely for same-host delegation. The Codex runtime is still required to run the Codex plugin itself.

Existing `/mst:gemini`, `gemini`, and `gemini-dev` values remain deprecated aliases for one release, but new configuration should use `/mst:agy`, `agy`, and `agy-dev`.

If you plan to use an external lane, install and authenticate only the CLI for that provider.

```bash
# Optional: external Codex lane
npm install -g @openai/codex

# Optional: the AGY provider always uses the external lane
# Install Antigravity/AGY CLI, then verify it.
agy --version
```

### Native-first and external lanes

| Example | Default route | Additional provider CLI |
|---------|---------------|-------------------------|
| Codex host → Codex provider | Codex collaboration native agent | not required for same-host delegation alone |
| Claude Code host → Claude provider | Claude Task/Agent | not required for same-host delegation alone |
| Codex host → Claude provider or Claude Code host → Codex provider | managed external wrapper | target provider CLI required |
| headless, `external-only`, native disabled/scope excluded/capability unavailable | managed external wrapper | target provider CLI required |
| AGY provider | managed external wrapper | AGY CLI required |

If an external route cannot find its target CLI, it fails closed as `blocked` (`missing_cli`). After a native spawn, external fallback is allowed only when the host definitively reports that no task was created. Attach failure, timeout, an unknown result, or unconfirmed cancellation after spawn acknowledgement/provider task ID leaves the attempt in `reconciling` and blocks both a new native spawn and duplicate external execution. A native task failure is not automatically rerun on another transport.

An existing project-local `delegation.native_codex_subagents.enabled: false` remains a supported opt-out and can be migrated to the canonical settings. To use only the external wrapper in new configuration, set:

```
/mst:settings delegation.transport_policy external-only
/mst:settings delegation.native.enabled false
```

### If you selected an external CLI, run it once

Run each CLI selected for an external lane once to finish authentication. Skip this step if you use only native same-host routes.

```bash
codex   # only for an external Codex lane
claude  # only for an external Claude lane
agy     # when using the AGY provider
```

The external wrapper does not use a proxy server; it uses the target CLI's authentication and local settings directly. Codex instruction files such as project-root `AGENTS.md`/`CODEX.md` and project settings supported by AGY or Claude CLI also apply to that external execution. Verify that each selected CLI is on PATH with the corresponding `which codex`, `which claude`, or `which agy` command.

## 1. Installation

In Claude Code (v1.0.33 or later required):

```bash
# Step 1: add to marketplace
/plugin marketplace add myrtlepn/gran-maestro

# Step 2: install plugin
/plugin install mst@gran-maestro
```

You can also open the `/plugin` UI and install directly from the **Discover** tab.

### Update

```bash
/plugin marketplace update gran-maestro
```

### Uninstall

```bash
/plugin uninstall mst@gran-maestro
```

### Claude/Codex plugin install, update, uninstall, and validation

Claude Code and Codex use the same git repository as the marketplace source. Claude Code registers skills, agents, and hooks; Codex registers the same skill source as a hookless plugin surface for the same plan → request → approve → review → accept workflow. Delegation defaults are Codex-primary; the Claude provider is opt-in through Claude presets or `claude-dev` assignment. Real user environments are managed explicitly through each CLI.

1. **Prepare**: review repository-local artifacts such as `.claude-plugin/`, `.codex-plugin/`, `.agents/plugins/`, root `marketplace.json`, `plugins/mst`, `skills/`, `agents/`, and `hooks/hooks.json`.
2. **Install**: load the same git source in Claude Code and Codex CLI.
   ```bash
   /plugin marketplace add myrtlepn/gran-maestro
   /plugin install mst@gran-maestro

   codex plugin marketplace add myrtlepn/gran-maestro
   codex plugin add mst@gran-maestro
   ```
   Gran Maestro validation does not automatically run install, cache refresh, or reload commands against the user's Claude/Codex environment.
3. **Update**: before release, run `npm test` and the DOD-012 generator below, then update the user environment separately.
4. **Uninstall**: remove user-owned plugin registrations and caches manually. Repository validation does not automatically execute uninstall or cache deletion commands.
5. **Validate**:
   ```bash
   node scripts/claude-plugin-local-install-smoke.mjs
   node scripts/codex-plugin-local-install-smoke.mjs
   node scripts/codex-plugin-git-source-readiness.mjs
   node scripts/generate-dod-012-docs-release-integration.mjs /tmp/dod-012-docs-release-integration-check.json
   npm test
   ```
   After publishing the git source, validate the same install path with `node scripts/claude-plugin-local-install-smoke.mjs --source myrtlepn/gran-maestro` and `node scripts/codex-plugin-local-install-smoke.mjs --source myrtlepn/gran-maestro`.

## Stitch MCP setup (optional)

If you want `/mst:stitch` to generate UI mockups, add Stitch MCP to Claude Code first.

Stitch is Google's UI design tool. Add it through `/mcp add` command or Claude Code MCP settings, then enable it in Gran Maestro:

```
/mst:settings stitch.enabled true
```

> **Tip.** Gran Maestro default is `stitch.enabled: true`. If you add Stitch MCP, it is ready to use without extra setup.

## 2. Getting Started — Workflow Chain

The core of Gran Maestro is the **plan → request → approve → review → accept** chain.

### Golden Path: request → list → approve

The fastest route. Convert a request directly into an implementation spec and execute.

```
/mst:request "Add JWT-based user authentication"
/mst:list                        # Check request status
/mst:approve REQ-001             # Approve spec → Codex/AGY starts implementation
```

### Plan branch: when requirements are ambiguous

When requirements are complex or decisions are needed, refine with `/mst:plan` first.

```
/mst:plan "Improve the login screen"  # Refine requirements via Q&A → generates plan.md
/mst:request                          # Convert plan into implementation spec
/mst:approve REQ-001                  # Approve → implementation starts
```

> **Tip.** You can create multiple plans first and batch-approve them with `/mst:approve PLN-001 PLN-002`.

### review → accept: after implementation

Once implementation is complete, review and merge.

```
/mst:review REQ-001              # Multi-AI verification against acceptance criteria
/mst:accept REQ-001              # Merge + worktree cleanup
```

> **Tip.** Use `/mst:approve -a` for autonomous mode — it proceeds automatically through review → accept.

> **Tip.** If your session was interrupted, use `/mst:recover` to resume incomplete requests.

## 3. Dashboard

```
/mst:dashboard
```

Opens a real-time dashboard in your browser where you can:

- **Monitor status** — View Phase-level progress for all requests and tasks
- **Inline editing** — Edit plans, specs, and feedback directly in the dashboard
- **Live tracking** — Watch agent execution logs and results in real time

## 4. Key Commands

| Command | Description |
|---------|-------------|
| `/mst:plan` | Refine requirements via Q&A to produce an actionable plan |
| `/mst:request` | Convert a plan or direct input into an implementation spec |
| `/mst:approve` | Approve spec and dispatch to Codex/AGY dev team |
| `/mst:review` | Multi-AI review against acceptance criteria |
| `/mst:dashboard` | Start dashboard server and open browser |
| `/mst:recover` | Resume incomplete requests after session termination |

> For the full skill list, see [Skills Reference](skills-reference.en.md).

## 5. Troubleshooting

**Authentication error** — Run Codex/AGY CLI directly once to complete the auth flow. Execute `codex` or `agy` to finish interactive login first.

**Command not found** — Verify PATH registration with `which codex` and `which agy`. If not globally installed, run `npm install -g @openai/codex @google/agy-cli`.

**Plugin not found** — Ensure Claude Code version is v1.0.33 or later. Run `/plugin marketplace add myrtlepn/gran-maestro` followed by `/plugin install mst@gran-maestro` again.

## 6. Next Steps

- [Configuration](configuration.en.md) — Full config.json options reference
- [Best Practices](best-practices.en.md) — Efficient workflow patterns
- [Skills Reference](skills-reference.en.md) — Detailed usage for 35+ skills
- [Dashboard](dashboard.en.md) — Hub structure, views, API endpoints
- [Chrome Extension Setup](extension-setup.md) — Browser capture extension installation guide
