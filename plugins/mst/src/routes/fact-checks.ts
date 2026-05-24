import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { dirname } from "https://deno.land/std@0.224.0/path/mod.ts";
import { acquireLock, releaseLock } from "../core/concurrency.ts";
import { PLUGIN_ROOT, resolveBaseDir } from "../config.ts";

const projectFactChecksApi = new Hono();
const decoder = new TextDecoder();
const CLAIM_UPDATE_STATUSES = ["verified", "failed", "unverified"] as const;
const CLAIM_UPDATE_STATUS_SET = new Set<string>(CLAIM_UPDATE_STATUSES);

interface ClaimsSummary {
  total: number;
  verified: number;
  failed: number;
  unverified: number;
}

interface SearchMatchEntry {
  fact_check_id?: unknown;
  linked_plan?: unknown;
  fact_check_status?: unknown;
  claim?: {
    status?: unknown;
  };
}

interface NormalizedSearchFactCheckItem {
  id: string;
  linked_plan: string;
  status: string;
  claims_summary: ClaimsSummary;
}

function isInvalidPathPart(value: string): boolean {
  return !value || value.includes("..") || value.includes("/") || value.includes("\\");
}

function extractCommandError(output: Deno.CommandOutput): string {
  const stderr = decoder.decode(output.stderr).trim();
  const stdout = decoder.decode(output.stdout).trim();
  return stderr || stdout || "Fact-check command failed";
}

function createEmptyClaimsSummary(): ClaimsSummary {
  return {
    total: 0,
    verified: 0,
    failed: 0,
    unverified: 0,
  };
}

function normalizeClaimStatus(value: unknown): "verified" | "failed" | "unverified" {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (normalized === "verified" || normalized === "failed" || normalized === "unverified") {
    return normalized;
  }
  return "unverified";
}

function normalizeSearchResults(raw: unknown): NormalizedSearchFactCheckItem[] {
  if (!Array.isArray(raw)) return [];

  const grouped = new Map<string, NormalizedSearchFactCheckItem>();

  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const match = entry as SearchMatchEntry;
    if (typeof match.fact_check_id !== "string" || !match.fact_check_id.trim()) continue;

    const id = match.fact_check_id.trim().toUpperCase();
    const linkedPlan = typeof match.linked_plan === "string" ? match.linked_plan.trim().toUpperCase() : "";
    const status = typeof match.fact_check_status === "string" ? match.fact_check_status.trim() : "";

    let current = grouped.get(id);
    if (!current) {
      current = {
        id,
        linked_plan: linkedPlan,
        status,
        claims_summary: createEmptyClaimsSummary(),
      };
      grouped.set(id, current);
    }

    if (!current.linked_plan && linkedPlan) current.linked_plan = linkedPlan;
    if (!current.status && status) current.status = status;

    const claimStatus = normalizeClaimStatus(match.claim?.status);
    current.claims_summary.total += 1;
    current.claims_summary[claimStatus] += 1;
  }

  return Array.from(grouped.values()).sort((a, b) => a.id.localeCompare(b.id));
}

async function runFactCheckCommand<T>(
  baseDir: string,
  args: string[],
  json = true,
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  const commandArgs = [`${PLUGIN_ROOT}/scripts/mst.py`, "fact-check", ...args];
  if (json && !commandArgs.includes("--json")) {
    commandArgs.push("--json");
  }

  try {
    const output = await new Deno.Command("python3", {
      args: commandArgs,
      cwd: dirname(baseDir),
      stdout: "piped",
      stderr: "piped",
      signal: AbortSignal.timeout(10_000),
    }).output();

    if (output.code !== 0) {
      return { ok: false, error: extractCommandError(output) };
    }

    const stdout = decoder.decode(output.stdout).trim();
    if (!json) {
      return { ok: true, data: stdout as T };
    }

    try {
      return { ok: true, data: JSON.parse(stdout) as T };
    } catch {
      return { ok: false, error: "Invalid fact-check command JSON output" };
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return { ok: false, error: "Fact-check command timed out" };
    }
    return { ok: false, error: error instanceof Error ? error.message : "Fact-check command failed" };
  }
}

projectFactChecksApi.get("/fact-checks", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const q = c.req.query("q")?.trim();
  const plan = c.req.query("plan")?.trim();
  const status = c.req.query("status")?.trim();
  const tag = c.req.query("tag")?.trim();

  const shouldUseSearch = Boolean(q) || Boolean(tag);
  const args = shouldUseSearch
    ? ["search", q || tag || ""]
    : ["list"];

  if (plan) args.push("--plan", plan);
  if (status) args.push("--status", status);
  if (tag && shouldUseSearch) args.push("--tag", tag);

  const result = await runFactCheckCommand<any>(baseDir, args);
  if (!result.ok) return c.json({ error: result.error }, 500);
  if (shouldUseSearch) return c.json(normalizeSearchResults(result.data));
  return c.json(result.data);
});

projectFactChecksApi.get("/fact-checks/search", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) return c.json({ error: "Project not found" }, 404);

  const q = c.req.query("q")?.trim();
  if (!q) return c.json({ error: "Missing search query" }, 400);

  const args = ["search", q];
  const plan = c.req.query("plan")?.trim();
  const status = c.req.query("status")?.trim();
  const tag = c.req.query("tag")?.trim();

  if (plan) args.push("--plan", plan);
  if (status) args.push("--status", status);
  if (tag) args.push("--tag", tag);

  const result = await runFactCheckCommand<any>(baseDir, args);
  if (!result.ok) return c.json({ error: result.error }, 500);
  return c.json(normalizeSearchResults(result.data));
});

projectFactChecksApi.get("/fact-checks/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) return c.json({ error: "Project not found" }, 404);

  const id = c.req.param("id");
  if (isInvalidPathPart(id)) return c.json({ error: "Invalid fact-check id" }, 400);

  const result = await runFactCheckCommand<any>(baseDir, ["get", id]);
  if (result.ok) return c.json(result.data);
  if (result.error.includes("not found")) return c.json({ error: "Fact-check not found" }, 404);
  return c.json({ error: result.error }, 500);
});

projectFactChecksApi.put("/fact-checks/:fcId/claims/:claimId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) return c.json({ error: "Project not found" }, 404);

  const fcId = c.req.param("fcId");
  const claimId = c.req.param("claimId");
  if (isInvalidPathPart(fcId) || isInvalidPathPart(claimId)) {
    return c.json({ error: "Invalid id" }, 400);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  const status = typeof body.status === "string" ? body.status.trim().toLowerCase() : "";
  if (!status) return c.json({ error: "Missing status" }, 400);
  if (!CLAIM_UPDATE_STATUS_SET.has(status)) {
    return c.json({
      error: "Invalid status",
      allowed: CLAIM_UPDATE_STATUSES,
    }, 400);
  }

  const args = ["claim-update", fcId, claimId, "--status", status];

  const lock = await acquireLock(`${baseDir}/.gran-maestro.fact-check.lock`, 5_000);
  try {
    const result = await runFactCheckCommand<any>(baseDir, args);
    if (result.ok) return c.json(result.data);
    const errorLower = result.error.toLowerCase();
    if (errorLower.includes("not found")) {
      return c.json({ error: "Fact-check or claim not found" }, 404);
    }
    if (errorLower.includes("invalid fact-check id") || errorLower.includes("invalid claim id")) {
      return c.json({ error: "Invalid id" }, 400);
    }
    return c.json({ error: result.error }, 500);
  } finally {
    await releaseLock(lock);
  }
});

export { projectFactChecksApi };
