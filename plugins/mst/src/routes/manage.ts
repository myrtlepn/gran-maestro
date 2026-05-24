import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { dirExists } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

const projectManageApi = new Hono();

const decoder = new TextDecoder();
const PROJECT_ROOT = new URL("../../", import.meta.url).pathname;

const ALLOWED_STATUS = {
  request: ["completed", "cancelled"],
  plan: ["completed"],
  session: ["completed"],
  explore: ["completed", "cancelled"],
} as const;

type ManagedStatus = (typeof ALLOWED_STATUS)[keyof typeof ALLOWED_STATUS][number];
type TargetType = keyof typeof ALLOWED_STATUS;

function isInvalidPathPart(value: string): boolean {
  return !value || value.includes("..") || value.includes("/") || value.includes("\\");
}

function getTargetType(id: string): TargetType | null {
  if (id.startsWith("REQ-")) return "request";
  if (id.startsWith("PLN-")) return "plan";
  if (id.startsWith("DBG-") || id.startsWith("IDN-") || id.startsWith("DSC-")) return "session";
  if (id.startsWith("EXP-")) return "explore";
  return null;
}

function isAllowedStatus(targetStatus: string): targetStatus is ManagedStatus {
  return (Object.values(ALLOWED_STATUS) as ReadonlyArray<ReadonlyArray<string>>).flat().includes(targetStatus);
}

async function setState(
  baseDir: string,
  id: string,
  targetStatus: ManagedStatus,
): Promise<{ success: boolean; error?: string }> {
  const action = targetStatus === "completed" ? "complete" : targetStatus === "cancelled" ? "cancel" : "set-status";
  const command = new Deno.Command("python3", {
    args: [
      "-c",
      `
import sys
from pathlib import Path
sys.path.insert(0, "scripts")
from _state_manager import set_status, complete, cancel

base_dir = Path(sys.argv[1])
item_id = sys.argv[2]
status = sys.argv[3]
action = sys.argv[4]

if action == "complete":
    complete(base_dir, item_id)
elif action == "cancel":
    cancel(base_dir, item_id)
elif action == "set-status":
    set_status(base_dir, item_id, status)
else:
    raise ValueError(f"Unknown action: {action}")
      `,
      baseDir,
      id,
      targetStatus,
      action,
    ],
    cwd: PROJECT_ROOT,
    stdout: "piped",
    stderr: "piped",
  });

  const output = await command.output();
  if (output.code === 0) {
    return { success: true };
  }
  return {
    success: false,
    error: `${decoder.decode(output.stderr)}${decoder.decode(output.stdout)}`.trim(),
  };
}

async function resolveItemDir(baseDir: string, id: string): Promise<string | null> {
  const targetType = getTargetType(id);
  let candidates: string[];
  if (targetType === "request") {
    candidates = [`requests/${id}`, `requests/completed/${id}`];
  } else if (targetType === "plan") {
    candidates = [`plans/${id}`, `plans/completed/${id}`];
  } else if (targetType === "session") {
    if (id.startsWith("DBG-")) {
      candidates = [`debug/${id}`, `debug/completed/${id}`];
    } else if (id.startsWith("IDN-")) {
      candidates = [`ideation/${id}`, `ideation/completed/${id}`];
    } else {
      candidates = [`discussion/${id}`, `discussion/completed/${id}`];
    }
  } else if (targetType === "explore") {
    candidates = [`explore/${id}`, `explore/completed/${id}`];
  } else {
    candidates = [
      `requests/${id}`,
      `requests/completed/${id}`,
      `plans/${id}`,
      `plans/completed/${id}`,
      `debug/${id}`,
      `debug/completed/${id}`,
      `ideation/${id}`,
      `ideation/completed/${id}`,
      `discussion/${id}`,
      `discussion/completed/${id}`,
      `explore/${id}`,
      `explore/completed/${id}`,
    ];
  }

  for (const candidate of candidates) {
    if (await dirExists(`${baseDir}/${candidate}`)) {
      return candidate;
    }
  }

  return null;
}

projectManageApi.patch("/manage/status", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  type Body = { ids: unknown; targetStatus: unknown };
  let body: Body;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  if (!Array.isArray(body?.ids) || typeof body.targetStatus !== "string") {
    return c.json({ error: "Invalid request body" }, 400);
  }

  const targetStatus = body.targetStatus.trim();
  if (!isAllowedStatus(targetStatus)) {
    return c.json({ error: "Invalid targetStatus" }, 400);
  }

  const succeeded: string[] = [];
  const skipped: string[] = [];
  const errors: string[] = [];

  for (const rawId of body.ids) {
    if (typeof rawId !== "string" || isInvalidPathPart(rawId)) {
      skipped.push(String(rawId));
      continue;
    }

    const targetType = getTargetType(rawId);
    if (!targetType || !(ALLOWED_STATUS[targetType] as readonly string[]).includes(targetStatus)) {
      errors.push(rawId);
      continue;
    }

    try {
      const result = await setState(baseDir, rawId, targetStatus);
      if (result.success) {
        succeeded.push(rawId);
        continue;
      }

      const errorMessage = result.error ?? "";
      if (errorMessage.includes("JSON not found for ID")) {
        skipped.push(rawId);
      } else {
        errors.push(rawId);
      }
    } catch (_e) {
      errors.push(rawId);
    }
  }

  const allFailed = body.ids.length > 0 && succeeded.length === 0 && errors.length > 0;
  return c.json({ succeeded, skipped, errors }, allFailed ? 207 : 200);
});

projectManageApi.post("/manage/backup", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  type Body = { ids: unknown };
  let body: Body;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  if (!Array.isArray(body?.ids)) {
    return c.json({ error: "Invalid request body" }, 400);
  }

  const skipped: string[] = [];
  const unsupported: string[] = [];
  const itemDirs: string[] = [];

  for (const rawId of body.ids) {
    if (typeof rawId !== "string" || isInvalidPathPart(rawId)) {
      skipped.push(String(rawId));
      continue;
    }

    if (!getTargetType(rawId)) {
      unsupported.push(rawId);
      continue;
    }

    const dir = await resolveItemDir(baseDir, rawId);
    if (!dir) {
      skipped.push(rawId);
      continue;
    }
    itemDirs.push(dir);
  }

  if (itemDirs.length === 0) {
    return c.json({ error: "No valid ids", skipped, unsupported }, 400);
  }

  const zipName = `gran-maestro-backup-${new Date().toISOString().replace(/[:.]/g, "-")}.zip`;
  const zipPath = await Deno.makeTempFile({
    dir: "/tmp",
    prefix: "gran-maestro-backup-",
    suffix: ".zip",
  });

  try {
    const zipCommand = new Deno.Command("zip", {
      args: ["-r", zipPath, ...itemDirs],
      cwd: baseDir,
      stdout: "piped",
      stderr: "piped",
    });
    const output = await zipCommand.output();
    if (output.code !== 0) {
      const err = `${decoder.decode(output.stderr)}${decoder.decode(output.stdout)}`.trim();
      return c.json({ error: "Failed to create backup", detail: err }, 500);
    }

    const zipBytes = await Deno.readFile(zipPath);
    const headers = new Headers({
      "Content-Type": "application/zip",
      "Content-Disposition": `attachment; filename=${JSON.stringify(zipName)}`,
    });
    if (skipped.length > 0) {
      headers.set("X-Manage-Backup-Skipped", skipped.join(","));
    }
    return new Response(zipBytes, { headers });
  } finally {
    try {
      await Deno.remove(zipPath);
    } catch {
      // best-effort cleanup
    }
  }
});

projectManageApi.post("/manage/archive-all", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const command = new Deno.Command("python3", {
    args: [
      `${PROJECT_ROOT}/scripts/mst.py`,
      "archive",
      "run-all",
      "--dir",
      baseDir,
    ],
    cwd: PROJECT_ROOT,
    stdout: "piped",
    stderr: "piped",
  });

  const output = await command.output();
  const stdout = decoder.decode(output.stdout).trim();
  const stderr = decoder.decode(output.stderr).trim();

  if (output.code === 0) {
    return c.json({ success: true, message: stdout || "[Archive] 정리 대상 없음" });
  }

  return c.json(
    { success: false, error: stderr || stdout || "archive run-all failed" },
    500,
  );
});

export { projectManageApi };
