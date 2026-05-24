import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { HUB_MODE, registry, generateProjectId, saveRegistry } from "../config.ts";
import { isGranMaestroRoot, normalizeGranMaestroBasePath } from "../core/paths.ts";
import { dirExists } from "../utils.ts";

const projectRegistryApi = new Hono();
projectRegistryApi.get("/", async (c) => {
  return c.json(registry.projects);
});

projectRegistryApi.post("/", async (c) => {
  if (!HUB_MODE) {
    return c.json({ error: "Hub mode is disabled" }, 400);
  }

  let body: { name?: string; path?: string };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  if (!body?.path || typeof body.path !== "string") {
    return c.json({ error: "Missing required field: path" }, 400);
  }

  const projectPath = body.path.trim();
  if (!projectPath) {
    return c.json({ error: "Invalid path" }, 400);
  }

  const name = body.name && body.name.trim() ? body.name.trim() : projectPath;
  let resolvedPath = projectPath;
  try {
    resolvedPath = await Deno.realPath(projectPath);
  } catch {
    return c.json({ error: "Invalid project path" }, 400);
  }

  if (!isGranMaestroRoot(resolvedPath)) {
    const grandMaestroPath = normalizeGranMaestroBasePath(resolvedPath);
    if (await dirExists(grandMaestroPath)) {
      resolvedPath = grandMaestroPath;
    }
  }

  if (!(await dirExists(resolvedPath))) {
    return c.json({ error: "Project path not found" }, 404);
  }

  const existing = registry.projects.find((project) => project.path === resolvedPath);
  const now = new Date().toISOString();

  if (existing) {
    existing.name = name;
    existing.path = resolvedPath;
    existing.registered_at = now;

    await saveRegistry();
    return c.json({
      id: existing.id,
      name,
      path: resolvedPath,
      registered_at: existing.registered_at,
    });
  }

  const projectId = await generateProjectId(resolvedPath);

  registry.projects.push({
    id: projectId,
    name,
    path: resolvedPath,
    registered_at: now,
  });

  await saveRegistry();
  return c.json({
    id: projectId,
    name,
    path: resolvedPath,
    registered_at: now,
  });
});

projectRegistryApi.delete("/:projectId", async (c) => {
  if (!HUB_MODE) {
    return c.json({ error: "Hub mode is disabled" }, 400);
  }

  const projectId = c.req.param("projectId");
  const previous = registry.projects.length;
  registry.projects = registry.projects.filter((project) => project.id !== projectId);

  if (registry.projects.length === previous) {
    return c.json({ error: "Project not found" }, 404);
  }

  await saveRegistry();
  return c.json({ ok: true });
});

export { projectRegistryApi };
