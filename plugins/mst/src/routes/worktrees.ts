import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";

import { resolveBaseDir } from "../config.ts";
import { listDirs, readJsonFile } from "../utils.ts";

const projectWorktreesApi = new Hono();

interface WorktreeMeta {
  path?: string | null;
  branch?: string | null;
  state?: string | null;
  taskId?: string | null;
  last_activity_at?: string | null;
}

interface WorktreeEntry {
  id: string;
  path: string | null;
  branch: string | null;
  state: string;
  taskId: string | null;
  requestId: string | null;
  last_activity_at: string | null;
  has_meta: boolean;
}

interface WorktreeSummary {
  total: number;
  by_state: Record<string, number>;
  orphaned: number;
}

projectWorktreesApi.get("/worktrees", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }
  const worktreesDir = `${baseDir}/worktrees`;
  const entries = await listDirs(worktreesDir);

  const worktrees: WorktreeEntry[] = [];
  const byState: Record<string, number> = {};

  for (const dirName of entries) {
    try {
      const match = dirName.match(/^(REQ-\d+)-(\d+)$/);
      const requestId = match?.[1] ?? null;
      const taskId = match?.[2] ?? null;

      const metaPath = `${worktreesDir}/${dirName}.meta.json`;
      let hasMeta = false;
      let state = "orphaned";
      let path: string | null = null;
      let branch: string | null = null;
      let last_activity_at: string | null = null;

      let metaExists = false;
      try {
        const stat = await Deno.stat(metaPath);
        metaExists = stat.isFile;
      } catch {
        metaExists = false;
      }

      if (metaExists) {
        const meta = await readJsonFile<WorktreeMeta>(metaPath);
        if (meta) {
          hasMeta = true;
          state = typeof meta.state === "string" ? meta.state : "unknown";
          path = typeof meta.path === "string" ? meta.path : null;
          branch = typeof meta.branch === "string" ? meta.branch : null;
          last_activity_at = typeof meta.last_activity_at === "string"
            ? meta.last_activity_at
            : null;
        } else {
          state = "unknown";
        }
      }

      worktrees.push({
        id: dirName,
        path,
        branch,
        state,
        taskId,
        requestId,
        last_activity_at,
        has_meta: hasMeta,
      });
      byState[state] = (byState[state] ?? 0) + 1;
    } catch {
      continue;
    }
  }

  const summary: WorktreeSummary = {
    total: worktrees.length,
    by_state: byState,
    orphaned: byState.orphaned ?? 0,
  };

  return c.json({ worktrees, summary });
});

export { projectWorktreesApi };
