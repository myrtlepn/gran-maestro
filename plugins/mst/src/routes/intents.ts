import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { dirname } from "https://deno.land/std@0.224.0/path/mod.ts";
import { acquireLock, releaseLock } from "../core/concurrency.ts";
import { PLUGIN_ROOT, resolveBaseDir } from "../config.ts";
import type { IntentMeta } from "../types.ts";

const projectIntentsApi = new Hono();

const decoder = new TextDecoder();

function isInvalidPathPart(value: string): boolean {
  return !value || value.includes("..") || value.includes("/") || value.includes("\\");
}

function extractCommandError(output: Deno.CommandOutput): string {
  const stderr = decoder.decode(output.stderr).trim();
  const stdout = decoder.decode(output.stdout).trim();
  return stderr || stdout || "Intent command failed";
}

async function runIntentCommand<T>(
  baseDir: string,
  args: string[],
  json = true,
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  const commandArgs = [`${PLUGIN_ROOT}/scripts/mst.py`, "intent", ...args];
  if (json) {
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
      return { ok: false, error: "Invalid intent command JSON output" };
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return { ok: false, error: "Intent command timed out" };
    }
    return { ok: false, error: error instanceof Error ? error.message : "Intent command failed" };
  }
}

function normalizeStringList(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) {
    return null;
  }

  const values = raw
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim())
    .filter((value) => value.length > 0);

  return values;
}

function appendRepeatedArg(args: string[], flag: string, values: string[] | undefined): void {
  if (!values) {
    return;
  }

  for (const value of values) {
    args.push(flag, value);
  }
}

function getOptionalString(
  body: Record<string, unknown>,
  primaryKey: string,
  fallbackKey?: string,
): string | null {
  const primary = body[primaryKey];
  if (primary !== undefined) {
    return typeof primary === "string" ? primary.trim() : null;
  }
  if (!fallbackKey) {
    return "";
  }
  const fallback = body[fallbackKey];
  if (fallback !== undefined) {
    return typeof fallback === "string" ? fallback.trim() : null;
  }
  return "";
}

projectIntentsApi.get("/intents", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const args = ["list"];
  const req = c.req.query("req")?.trim();
  const plan = c.req.query("plan")?.trim();

  if (req) {
    args.push("--req", req);
  }
  if (plan) {
    args.push("--plan", plan);
  }

  const result = await runIntentCommand<IntentMeta[]>(baseDir, args);
  return result.ok ? c.json(result.data) : c.json({ error: result.error }, 500);
});

projectIntentsApi.get("/intents/search", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const query = c.req.query("q")?.trim();
  if (!query) {
    return c.json({ error: "Missing search query" }, 400);
  }

  const result = await runIntentCommand<Array<Record<string, unknown>>>(baseDir, ["search", query]);
  return result.ok ? c.json(result.data) : c.json({ error: result.error }, 500);
});

projectIntentsApi.get("/intents/:id/related", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid intent id" }, 400);
  }

  const rawDepth = c.req.query("depth");
  const depth = rawDepth ? Number.parseInt(rawDepth, 10) : 1;
  if (!Number.isInteger(depth) || depth < 1) {
    return c.json({ error: "Invalid depth query" }, 400);
  }

  const result = await runIntentCommand<Record<string, unknown>>(baseDir, [
    "related",
    id,
    "--depth",
    String(depth),
  ]);
  if (result.ok) {
    return c.json(result.data);
  }
  if (result.error.toLowerCase().includes("not found")) {
    return c.json({ error: "Intent not found" }, 404);
  }
  return c.json({ error: result.error }, 500);
});

projectIntentsApi.get("/intents/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid intent id" }, 400);
  }

  const result = await runIntentCommand<IntentMeta>(baseDir, ["get", id]);
  if (result.ok) {
    return c.json(result.data);
  }

  if (result.error.includes("not found")) {
    return c.json({ error: "Intent not found" }, 404);
  }

  return c.json({ error: result.error }, 500);
});

projectIntentsApi.post("/intents", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  const feature = typeof body.feature === "string" ? body.feature.trim() : "";
  const situation = typeof body.situation === "string" ? body.situation.trim() : "";
  const goal = typeof body.goal === "string" ? body.goal.trim() : "";
  const motivation = typeof body.motivation === "string" ? body.motivation.trim() : "";
  const req = getOptionalString(body, "linked_req", "req");
  const plan = getOptionalString(body, "linked_plan", "plan");
  const relatedIntent = body.related_intent === undefined ? undefined : normalizeStringList(body.related_intent);
  const tags = body.tags === undefined ? undefined : normalizeStringList(body.tags);
  const files = body.files === undefined ? undefined : normalizeStringList(body.files);

  if (!feature || !situation || !motivation || !goal) {
    return c.json({ error: "Missing required intent fields" }, 400);
  }
  if (req === null || plan === null || relatedIntent === null || tags === null || files === null) {
    return c.json({ error: "Invalid request body" }, 400);
  }

  const args = ["add", "--feature", feature, "--situation", situation, "--goal", goal];
  if (motivation) {
    args.push("--motivation", motivation);
  }
  if (req) {
    args.push("--req", req);
  }
  if (plan) {
    args.push("--plan", plan);
  }
  appendRepeatedArg(args, "--related-intent", relatedIntent);
  appendRepeatedArg(args, "--tag", tags);
  appendRepeatedArg(args, "--file", files);

  const lock = await acquireLock(`${baseDir}/.gran-maestro.intent.lock`, 5_000);
  try {
    const result = await runIntentCommand<IntentMeta>(baseDir, args);
    return result.ok ? c.json(result.data, 201) : c.json({ error: result.error }, 500);
  } finally {
    await releaseLock(lock);
  }
});

projectIntentsApi.post("/intents/lookup", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  const files = normalizeStringList(body.files);
  if (!files || files.length === 0) {
    return c.json({ error: "Missing files" }, 400);
  }

  const result = await runIntentCommand<IntentMeta[]>(baseDir, ["lookup", "--files", ...files]);
  return result.ok ? c.json(result.data) : c.json({ error: result.error }, 500);
});

projectIntentsApi.patch("/intents/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid intent id" }, 400);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  const args = ["update", id];
  const stringFields = [
    ["feature", "--feature"],
    ["situation", "--situation"],
    ["motivation", "--motivation"],
    ["goal", "--goal"],
    ["created_at", "--created-at"],
  ] as const;

  for (const [key, flag] of stringFields) {
    const value = body[key];
    if (value === undefined) {
      continue;
    }
    if (typeof value !== "string" || value.trim().length === 0) {
      return c.json({ error: "Invalid request body" }, 400);
    }
    args.push(flag, value.trim());
  }

  const req = getOptionalString(body, "linked_req", "req");
  const plan = getOptionalString(body, "linked_plan", "plan");
  if (req === null || plan === null) {
    return c.json({ error: "Invalid request body" }, 400);
  }
  if (req !== "") {
    args.push("--req", req);
  }
  if (plan !== "") {
    args.push("--plan", plan);
  }

  const relatedIntent = body.related_intent === undefined ? undefined : normalizeStringList(body.related_intent);
  const tags = body.tags === undefined ? undefined : normalizeStringList(body.tags);
  const files = body.files === undefined ? undefined : normalizeStringList(body.files);

  if (
    (body.related_intent !== undefined && relatedIntent === null) ||
    (body.tags !== undefined && tags === null) ||
    (body.files !== undefined && files === null)
  ) {
    return c.json({ error: "Invalid request body" }, 400);
  }

  appendRepeatedArg(args, "--related-intent", relatedIntent ?? undefined);
  appendRepeatedArg(args, "--tag", tags ?? undefined);
  appendRepeatedArg(args, "--file", files ?? undefined);

  if (args.length === 2) {
    return c.json({ error: "No fields to update" }, 400);
  }

  const lock = await acquireLock(`${baseDir}/.gran-maestro.intent.lock`, 5_000);
  try {
    const result = await runIntentCommand<IntentMeta>(baseDir, args);
    if (result.ok) {
      return c.json(result.data);
    }
    if (result.error.toLowerCase().includes("not found")) {
      return c.json({ error: "Intent not found" }, 404);
    }
    return c.json({ error: result.error }, 500);
  } finally {
    await releaseLock(lock);
  }
});

projectIntentsApi.delete("/intents/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid intent id" }, 400);
  }

  const lock = await acquireLock(`${baseDir}/.gran-maestro.intent.lock`, 5_000);
  try {
    const result = await runIntentCommand<string>(baseDir, ["delete", id], false);
    if (result.ok) {
      return c.json({ success: true, message: result.data || `Deleted ${id}` });
    }
    if (result.error.toLowerCase().includes("not found")) {
      return c.json({ error: "Intent not found" }, 404);
    }
    return c.json({ error: result.error }, 500);
  } finally {
    await releaseLock(lock);
  }
});

export { projectIntentsApi };
