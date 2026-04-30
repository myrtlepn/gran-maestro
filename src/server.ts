/**
 * Gran Maestro Dashboard Server
 *
 * Deno + Hono single-file web server with inline SPA.
 * Port 3847 (configurable via the runtime config file).
 *
 * Usage:
 *   deno run --allow-net --allow-read --allow-write src/server.ts
 *
 * NOTE: This file is excluded from `npx tsc --noEmit` because it uses Deno URL imports.
 *       Type checking is performed via `deno check src/server.ts` instead.
 */

import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { serveDir } from "https://deno.land/std@0.224.0/http/file_server.ts";

import { sseApi } from "./sse.ts";
import { projectConfigApi } from "./routes/config.ts";
import { projectDiscussionApi } from "./routes/discussion.ts";
import { projectIdeationApi } from "./routes/ideation.ts";
import { projectDebugApi } from "./routes/debug.ts";
import { projectDispatchApi } from "./routes/dispatch.ts";
import { projectExploreApi } from "./routes/explore.ts";
import { projectDesignsApi } from "./routes/designs.ts";
import { projectPlansApi } from "./routes/plans.ts";
import { projectRequestsApi } from "./routes/requests.ts";
import { projectStatsApi } from "./routes/stats.ts";
import { projectOverviewApi } from "./routes/overview.ts";
import { projectAgileApi } from "./routes/agile.ts";
import { projectTreeApi } from "./routes/tree.ts";
import { projectWorktreesApi } from "./routes/worktrees.ts";
import { projectRegistryApi } from "./routes/projects.ts";
import { projectManageApi } from "./routes/manage.ts";
import { projectArchivesApi } from "./routes/archives.ts";
import { projectCapturesApi } from "./routes/captures.ts";
import { projectPresetsApi } from "./routes/presets.ts";
import { projectIntentsApi } from "./routes/intents.ts";
import { projectFactChecksApi } from "./routes/fact-checks.ts";
import { projectReferencesApi } from "./routes/references.ts";
import { flowApi, initFlowWatcher } from "./routes/flowApi.ts";
import { normalizeGranMaestroBasePath } from "./core/paths.ts";

import {
  BASE_DIR,
  DEFAULT_PORT,
  HOST,
  HUB_DIR,
  HUB_MODE,
  loadConfig,
  loadRegistry,
  registry,
  resolveBaseDir,
  setRegistry,
} from "./config.ts";

const app = new Hono();
const projectApi = new Hono();
const DIST_DIR = new URL("../dist", import.meta.url).pathname;

app.get("/api/health", (c) => {
  return c.json({ ok: true });
});

type PolicyHistoryRow = Record<string, unknown> & {
  event?: Record<string, unknown>;
  timestamp?: string;
  session_id?: string;
};

type AllowlistFile = {
  entries?: unknown;
};

function safeEnvGet(name: string): string | undefined {
  try {
    return Deno.env.get(name) ?? undefined;
  } catch {
    return undefined;
  }
}

function policyBaseDir(projectId?: string): string {
  return normalizeGranMaestroBasePath(resolveBaseDir(projectId) ?? Deno.cwd());
}

function policyAllowlistPath(): string {
  const explicit = safeEnvGet("MST_POLICY_HOME")?.trim();
  if (explicit) {
    return join(explicit, "allowlist.json");
  }

  const home = safeEnvGet("HOME") ?? safeEnvGet("USERPROFILE") ?? ".";
  return join(home, ".claude", "gran-maestro-policy", "allowlist.json");
}

function parseLimit(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "100", 10);
  if (!Number.isFinite(parsed) || parsed < 0) return 100;
  return Math.min(parsed, 1000);
}

function policyEvent(row: PolicyHistoryRow): Record<string, unknown> {
  return typeof row.event === "object" && row.event !== null ? row.event : row;
}

function eventTimestamp(row: PolicyHistoryRow): string {
  const event = policyEvent(row);
  return typeof event.timestamp === "string"
    ? event.timestamp
    : typeof row.timestamp === "string"
    ? row.timestamp
    : "";
}

function isBlockedPolicyEvent(row: PolicyHistoryRow): boolean {
  const event = policyEvent(row);
  return event.type === "policy_block" || event.type === "core_block";
}

async function readPolicyHistoryFile(path: string, sessionId: string): Promise<PolicyHistoryRow[]> {
  let text = "";
  try {
    text = await Deno.readTextFile(path);
  } catch {
    return [];
  }

  const rows: PolicyHistoryRow[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const parsed = JSON.parse(line) as PolicyHistoryRow;
      if (typeof parsed === "object" && parsed !== null) {
        rows.push({ ...parsed, session_id: parsed.session_id ?? sessionId });
      }
    } catch {
      // Skip malformed history lines instead of failing the dashboard.
    }
  }
  return rows;
}

async function readPolicyHistory(baseDir: string, sessionId?: string): Promise<PolicyHistoryRow[]> {
  const sessionsDir = join(baseDir, "sessions");
  if (sessionId) {
    return await readPolicyHistoryFile(join(sessionsDir, sessionId, "history.ndjson"), sessionId);
  }

  const rows: PolicyHistoryRow[] = [];
  try {
    for await (const entry of Deno.readDir(sessionsDir)) {
      if (!entry.isDirectory) continue;
      const sessionRows = await readPolicyHistoryFile(
        join(sessionsDir, entry.name, "history.ndjson"),
        entry.name,
      );
      rows.push(...sessionRows);
    }
  } catch {
    return [];
  }
  return rows;
}

projectApi.get("/policy/timeline", async (c) => {
  const baseDir = policyBaseDir(c.req.param("projectId"));
  const sessionId = c.req.query("session")?.trim() || undefined;
  const limit = parseLimit(c.req.query("limit"));
  const rows = await readPolicyHistory(baseDir, sessionId);
  const blockedRows = rows
    .filter(isBlockedPolicyEvent)
    .sort((left, right) => eventTimestamp(left).localeCompare(eventTimestamp(right)));

  return c.json(limit > 0 ? blockedRows.slice(-limit) : []);
});

projectApi.get("/policy/rules", async (c) => {
  const baseDir = policyBaseDir(c.req.param("projectId"));
  const rows = await readPolicyHistory(baseDir);
  const counts: Record<string, number> = {};

  for (const row of rows) {
    if (!isBlockedPolicyEvent(row)) continue;
    const event = policyEvent(row);
    const ruleId = typeof event.rule_id === "string" && event.rule_id.trim()
      ? event.rule_id.trim()
      : "unknown";
    counts[ruleId] = (counts[ruleId] ?? 0) + 1;
  }

  return c.json(counts);
});

projectApi.get("/policy/allowlist", async (c) => {
  try {
    const text = await Deno.readTextFile(policyAllowlistPath());
    const data = JSON.parse(text) as AllowlistFile;
    return c.json(Array.isArray(data.entries) ? data.entries : []);
  } catch {
    return c.json([]);
  }
});

projectApi.route("/", projectConfigApi);
projectApi.route("/", projectRequestsApi);
projectApi.route("/", projectStatsApi);
projectApi.route("/", projectOverviewApi);
projectApi.route("/", projectAgileApi);
projectApi.route("/", projectDebugApi);
projectApi.route("/", projectExploreApi);
projectApi.route("/", projectDesignsApi);
projectApi.route("/", projectPlansApi);
projectApi.route("/", projectManageApi);
projectApi.route("/", projectArchivesApi);
projectApi.route("/", projectCapturesApi);
projectApi.route("/", projectPresetsApi);
projectApi.route("/", projectIntentsApi);
projectApi.route("/", projectFactChecksApi);
projectApi.route("/", projectReferencesApi);
projectApi.route("/", projectIdeationApi);
projectApi.route("/", projectDiscussionApi);
projectApi.route("/", projectDispatchApi);
projectApi.route("/", projectTreeApi);
projectApi.route("/", projectWorktreesApi);
projectApi.route("/", flowApi);

app.route("/api/projects", projectRegistryApi);
app.route("/api/projects/:projectId", projectApi);
app.route("/api", projectApi);
app.route("/", sseApi);

app.get("/*", async (c) => {
  const pathname = new URL(c.req.url).pathname;

  if (
    pathname.startsWith("/static/") ||
    pathname.startsWith("/assets/") ||
    pathname.includes(".")
  ) {
    const response = await serveDir(c.req.raw, {
      fsRoot: DIST_DIR,
      quiet: true,
    });
    if (response.status !== 404) {
      return response;
    }
  }

  try {
    const html = await Deno.readTextFile(`${DIST_DIR}/index.html`);
    return c.html(html);
  } catch {
    return c.text(
      "Dashboard not built. Run: cd frontend && npm install && npm run build",
      503,
    );
  }
});

const BANNER = `
  ╔═══════════════════════════════════════════╗
  ║                                           ║
  ║      ██████╗ ██████╗  █████╗ ███╗   ██╗   ║
  ║     ██╔════╝ ██╔══██╗██╔══██╗████╗  ██║   ║
  ║     ██║  ███╗██████╔╝███████║██╔██╗ ██║   ║
  ║     ██║   ██║██╔══██╗██╔══██║██║╚██╗██║   ║
  ║     ╚██████╔╝██║  ██║██║  ██║██║ ╚████║   ║
  ║      ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝ ║
  ║                                           ║
  ║     ███╗   ███╗ █████╗ ███████╗███████╗   ║
  ║     ████╗ ████║██╔══██╗██╔════╝██╔════╝   ║
  ║     ██╔████╔██║███████║█████╗  ███████╗   ║
  ║     ██║╚██╔╝██║██╔══██║██╔══╝  ╚════██║   ║
  ║     ██║ ╚═╝ ██║██║  ██║███████╗███████║   ║
  ║     ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝  ║
  ║                                           ║
  ║    ████████╗██████╗  ██████╗               ║
  ║    ╚══██╔══╝██╔══██╗██╔═══██╗              ║
  ║       ██║   ██████╔╝██║   ██║              ║
  ║       ██║   ██╔══██╗██║   ██║              ║
  ║       ██║   ██║  ██║╚██████╔╝              ║
  ║       ╚═╝   ╚═╝  ╚═╝ ╚═════╝              ║
  ║                                           ║
  ╚═══════════════════════════════════════════╝
`;

async function main() {
  if (HUB_MODE) {
    await Deno.mkdir(HUB_DIR, { recursive: true });
    setRegistry(await loadRegistry());
    for (const project of registry.projects) {
      void initFlowWatcher(project.path);
    }
    const hubPidPath = `${HUB_DIR}/hub.pid`;
    await Deno.writeTextFile(hubPidPath, `${Deno.pid}`);

    const removeHubPid = async () => {
      try {
        await Deno.remove(hubPidPath);
      } catch {
        // ignore
      }
    };

    const shutdown = async () => {
      await removeHubPid();
      Deno.exit(0);
    };

    Deno.addSignalListener("SIGINT", () => {
      void shutdown();
    });
    if (Deno.build.os !== "windows") {
      Deno.addSignalListener("SIGTERM", () => {
        void shutdown();
      });
    }
  }

  const config = await loadConfig();
  const port = config.dashboard_port ?? DEFAULT_PORT;

  console.log(BANNER);
  console.log(`  Dashboard: http://localhost:${port}`);
  console.log(`  Host:      ${HOST}`);
  console.log(`  Port:      ${port}`);
  console.log(`  Hub dir:   ${HUB_DIR}`);
  console.log(`  Projects:  ${registry.projects.length}`);
  console.log("");

  // Ensure base directory exists
  try {
    await Deno.mkdir(BASE_DIR, { recursive: true });
    if (!HUB_MODE) {
      void initFlowWatcher(BASE_DIR);
    }
  } catch {
    // already exists
  }

  serve(app.fetch, {
    hostname: HOST,
    port: port,
  });
}

main();
