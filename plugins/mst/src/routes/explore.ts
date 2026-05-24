import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import type { ExploreMeta } from "../types.ts";
import { dirExists, listDirs, readJsonFile, readTextFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

const projectExploreApi = new Hono();

// ─── API: Explore ────────────────────────────────────────────────────────────

projectExploreApi.get("/explore", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const exploreDir = `${baseDir}/explore`;
  if (!(await dirExists(exploreDir))) {
    return c.json([]);
  }

  const sessions: ExploreMeta[] = [];
  const exploreDirs = (await listDirs(exploreDir)).filter((dir) => /^EXP-/.test(dir));
  for (const dir of exploreDirs) {
    const sessionJsonPath = `${exploreDir}/${dir}/session.json`;
    const sessionJson = await readJsonFile<ExploreMeta>(sessionJsonPath);
    if (sessionJson) {
      let createdAt = sessionJson.created_at;
      if (!createdAt || createdAt.includes("T00:00:00")) {
        try {
          const stat = await Deno.stat(sessionJsonPath);
          if (stat.mtime) {
            createdAt = stat.mtime.toISOString();
          }
        } catch (_error) {
          // ignore fallback failure
        }
      }
      sessions.push({ ...sessionJson, id: sessionJson.id || dir, created_at: createdAt });
    }
  }
  sessions.sort((a, b) => {
    const aTime = a.created_at ?? "";
    const bTime = b.created_at ?? "";
    return bTime.localeCompare(aTime);
  });

  return c.json(sessions);
});

projectExploreApi.get("/explore/:exploreId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const exploreId = c.req.param("exploreId");
  const sessionDir = `${baseDir}/explore/${exploreId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Explore session not found" }, 404);
  }

  const sessionJson = await readJsonFile<ExploreMeta>(`${sessionDir}/session.json`);
  if (!sessionJson) {
    return c.json({ error: "Explore session not found" }, 404);
  }
  const content = await readTextFile(`${sessionDir}/explore-report.md`);
  return c.json({ ...sessionJson, id: sessionJson.id || exploreId, content: content ?? null });
});

projectExploreApi.get("/explore/:exploreId/files", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const exploreId = c.req.param("exploreId");
  const sessionDir = `${baseDir}/explore/${exploreId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Explore session not found" }, 404);
  }

  const files: string[] = [];
  for await (const entry of Deno.readDir(sessionDir)) {
    if (
      entry.isFile &&
      entry.name.startsWith("explore-") &&
      entry.name.endsWith(".md") &&
      entry.name !== "explore-report.md"
    ) {
      files.push(entry.name);
    }
  }
  files.sort();
  return c.json(files);
});

projectExploreApi.delete("/explore/:exploreId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const exploreId = c.req.param("exploreId");
  const sessionDir = `${baseDir}/explore/${exploreId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Explore session not found" }, 404);
  }

  try {
    await Deno.remove(sessionDir, { recursive: true });
    return c.json({ ok: true });
  } catch {
    return c.json({ error: "Failed to delete explore session" }, 500);
  }
});

export { projectExploreApi };
