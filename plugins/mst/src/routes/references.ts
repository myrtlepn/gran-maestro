import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { dirname } from "https://deno.land/std@0.224.0/path/mod.ts";
import { PLUGIN_ROOT, resolveBaseDir } from "../config.ts";

const projectReferencesApi = new Hono();
const decoder = new TextDecoder();

function isInvalidPathPart(value: string): boolean {
  return !value || value.includes("..") || value.includes("/") || value.includes("\\");
}

function extractCommandError(output: Deno.CommandOutput): string {
  const stderr = decoder.decode(output.stderr).trim();
  const stdout = decoder.decode(output.stdout).trim();
  return stderr || stdout || "Reference command failed";
}

async function runReferenceCommand<T>(
  baseDir: string,
  args: string[],
  json = true,
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  const commandArgs = [`${PLUGIN_ROOT}/scripts/mst.py`, "reference", ...args];
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
      return { ok: false, error: "Invalid reference command JSON output" };
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return { ok: false, error: "Reference command timed out" };
    }
    return { ok: false, error: error instanceof Error ? error.message : "Reference command failed" };
  }
}

projectReferencesApi.get("/references", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) return c.json({ error: "Project not found" }, 404);

  const result = await runReferenceCommand<Array<Record<string, unknown>>>(baseDir, ["list"]);
  return result.ok ? c.json(result.data) : c.json({ error: result.error }, 500);
});

projectReferencesApi.get("/references/search", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) return c.json({ error: "Project not found" }, 404);

  const q = c.req.query("q")?.trim();
  if (!q) return c.json({ error: "Missing search query" }, 400);

  const result = await runReferenceCommand<Array<Record<string, unknown>>>(baseDir, [
    "search",
    "--keyword",
    q,
  ]);
  return result.ok ? c.json(result.data) : c.json({ error: result.error }, 500);
});

projectReferencesApi.get("/references/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) return c.json({ error: "Project not found" }, 404);

  const id = c.req.param("id");
  if (isInvalidPathPart(id)) return c.json({ error: "Invalid reference id" }, 400);

  const result = await runReferenceCommand<Record<string, unknown>>(baseDir, ["get", id]);
  if (result.ok) return c.json(result.data);
  if (result.error.toLowerCase().includes("not found")) return c.json({ error: "Reference not found" }, 404);
  return c.json({ error: result.error }, 500);
});

export { projectReferencesApi };
