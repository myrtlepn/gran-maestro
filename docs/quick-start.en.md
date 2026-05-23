[한국어](quick-start.md) | [English](quick-start.en.md)

[← Back to README](../README.en.md)

# Quick Start

## 0. Prerequisites

> **Run from your project directory.** Gran Maestro analyzes your existing codebase to operate. Always launch Claude Code from your project root before using the plugin.

Gran Maestro uses Codex CLI and Gemini CLI as external execution agents. Please install both CLIs before installing the plugin.

```bash
# Codex CLI
npm install -g @openai/codex

# Gemini CLI
npm install -g @google/gemini-cli
```

**Gran Maestro calls each CLI directly.** It does not proxy through another server or intercept APIs; it behaves exactly like running the commands yourself in terminal. Authentication and data only pass between each CLI and its service, so trusting Codex/Gemini is sufficient.

### CLI settings are applied as-is

Because Gran Maestro uses the CLI capabilities directly, your per-agent configuration also applies identically while running Gran Maestro.

- **Codex**: agent instruction files such as `AGENTS.md`, `CODEX.md` in the project root are applied when Codex is invoked.
- **Gemini**: files in `GEMINI.md` or `.gemini/` are applied when Gemini is invoked.

When you align agent-specific settings (model configuration, system prompts, forbidden behaviors), consistency and quality remain stable inside Gran Maestro.

### Run each CLI once directly after installation

After installation, run each CLI directly at least once. The first run starts an interactive auth flow (login/API key registration), and if this is incomplete, Gran Maestro may fail in non-interactive mode when invoking the CLI.

```bash
codex   # first run: complete auth flow
gemini  # first run: complete Google login
```

Authentication methods:

- Codex: interactive login on first run or set `OPENAI_API_KEY` environment variable
- Gemini: Google account OAuth login on first run or set `GEMINI_API_KEY` environment variable

> **Tip.** After install, verify PATH registration with `which codex` and `which gemini`.

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

### Codex plugin migration install, update, uninstall, and validation

Claude Code plugin installation is the canonical path. Codex plugin migration artifacts are repository-local parity validation targets, and real Codex user environments are managed explicitly by the user.

1. **Prepare**: review repository-local artifacts such as `.codex-plugin/`, `.agents/plugins/`, root `marketplace.json`, `plugins/mst`, `skills/`, `agents/`, and `hooks/hooks.json`.
2. **Install**: load the git source directly through Codex CLI.
   ```bash
   codex plugin marketplace add myrtlepn/gran-maestro
   codex plugin add mst@gran-maestro
   ```
   Gran Maestro validation does not automatically run install, cache refresh, or reload commands against the user's Codex environment.
3. **Update**: before release, run `npm test` and the DOD-012 generator below, then update the user environment separately.
4. **Uninstall**: remove user-owned Codex plugin registrations and caches manually. Repository validation does not automatically execute uninstall or cache deletion commands.
5. **Validate**:
   ```bash
   node scripts/codex-plugin-local-install-smoke.mjs
   node scripts/codex-plugin-git-source-readiness.mjs
   node scripts/generate-dod-012-docs-release-integration.mjs /tmp/dod-012-docs-release-integration-check.json
   npm test
   ```
   After publishing the git source, validate the same install path with `node scripts/codex-plugin-local-install-smoke.mjs --source myrtlepn/gran-maestro`.

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
/mst:approve REQ-001             # Approve spec → Codex/Gemini starts implementation
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
| `/mst:approve` | Approve spec and dispatch to Codex/Gemini dev team |
| `/mst:review` | Multi-AI review against acceptance criteria |
| `/mst:dashboard` | Start dashboard server and open browser |
| `/mst:recover` | Resume incomplete requests after session termination |

> For the full skill list, see [Skills Reference](skills-reference.en.md).

## 5. Troubleshooting

**Authentication error** — Run Codex/Gemini CLI directly once to complete the auth flow. Execute `codex` or `gemini` to finish interactive login first.

**Command not found** — Verify PATH registration with `which codex` and `which gemini`. If not globally installed, run `npm install -g @openai/codex @google/gemini-cli`.

**Plugin not found** — Ensure Claude Code version is v1.0.33 or later. Run `/plugin marketplace add myrtlepn/gran-maestro` followed by `/plugin install mst@gran-maestro` again.

## 6. Next Steps

- [Configuration](configuration.en.md) — Full config.json options reference
- [Best Practices](best-practices.en.md) — Efficient workflow patterns
- [Skills Reference](skills-reference.en.md) — Detailed usage for 35+ skills
- [Dashboard](dashboard.en.md) — Hub structure, views, API endpoints
- [Chrome Extension Setup](extension-setup.md) — Browser capture extension installation guide
