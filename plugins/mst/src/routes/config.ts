import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { readJsonFile, writeJsonFile, diffFromBase, deepMerge } from "../utils.ts";
import { DEFAULTS_PATH, PLUGIN_ROOT, resolveBaseDir, registry } from "../config.ts";
import type { ConfigResponse, GranMaestroConfig } from "../types.ts";
import { loadSettingOptions, validateConfigValues } from "../validation.ts";

const projectConfigApi = new Hono();

projectConfigApi.get("/config", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const defaults = await readJsonFile<GranMaestroConfig>(DEFAULTS_PATH) ?? {};
  const overrides = await readJsonFile<GranMaestroConfig>(`${baseDir}/config.json`) ?? {};
  const merged = deepMerge(defaults, overrides) as GranMaestroConfig;
  const response: ConfigResponse = {
    merged,
    overrides,
    defaults,
  };
  return c.json(response);
});

projectConfigApi.put("/config", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  try {
    const body = await c.req.json();
    if (typeof body !== "object" || body === null || Array.isArray(body)) {
      return c.json({ error: "Config body must be a JSON object" }, 400);
    }

    const settingOptions = await loadSettingOptions(PLUGIN_ROOT);
    if (!settingOptions) {
      console.warn("[config] Failed to load setting-options.json; skipping validation");
    } else {
      const { warnings } = validateConfigValues(body as Record<string, unknown>, settingOptions);
      if (warnings.length > 0) {
        console.warn("[config] Invalid values:", warnings);
      }
    }

    const defaults = await readJsonFile<GranMaestroConfig>(DEFAULTS_PATH) ?? {};
    const overrides = diffFromBase(defaults, body);
    const success = await writeJsonFile(`${baseDir}/config.json`, overrides);
    if (!success) {
      return c.json({ error: "Failed to write config" }, 500);
    }

    const resolved = deepMerge(defaults, overrides) as GranMaestroConfig;
    const resolvedOk = await writeJsonFile(`${baseDir}/config.resolved.json`, resolved);
    if (!resolvedOk) {
      console.warn("Warning: Failed to update config.resolved.json");
    }

    return c.json({ ok: true });
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }
});

projectConfigApi.put("/config/apply-all", async (c) => {
  if (!resolveBaseDir(c.req.param("projectId"))) {
    return c.json({ error: "Project not found" }, 404);
  }

  try {
    const body = await c.req.json();
    if (typeof body !== "object" || body === null || Array.isArray(body)) {
      return c.json({ error: "Config body must be a JSON object" }, 400);
    }

    const settingOptions = await loadSettingOptions(PLUGIN_ROOT);
    if (!settingOptions) {
      console.warn("[config] Failed to load setting-options.json; skipping validation");
    } else {
      const { warnings } = validateConfigValues(body as Record<string, unknown>, settingOptions);
      if (warnings.length > 0) {
        console.warn("[config] Invalid values:", warnings);
      }
    }

    const defaults = await readJsonFile<GranMaestroConfig>(DEFAULTS_PATH) ?? {};
    const overrides = diffFromBase(defaults, body);
    const resolved = deepMerge(defaults, overrides) as GranMaestroConfig;

    const failed: Array<{ id: string; name: string; error: string }> = [];
    let applied = 0;

    for (const project of registry.projects) {
      try {
        const configOk = await writeJsonFile(`${project.path}/config.json`, overrides);
        if (!configOk) {
          failed.push({ id: project.id, name: project.name, error: "Failed to write config.json" });
          continue;
        }

        const resolvedOk = await writeJsonFile(`${project.path}/config.resolved.json`, resolved);
        if (!resolvedOk) {
          failed.push({ id: project.id, name: project.name, error: "Failed to write config.resolved.json" });
          continue;
        }

        applied += 1;
      } catch (err) {
        failed.push({
          id: project.id,
          name: project.name,
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }

    return c.json({ ok: true, applied, failed });
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }
});

projectConfigApi.get("/config/defaults", async (c) => {
  const defaults = await readJsonFile(DEFAULTS_PATH);
  if (!defaults) {
    return c.json({ error: "Defaults not found" }, 404);
  }
  return c.json(defaults);
});

// ─── API: Mode ──────────────────────────────────────────────────────────────

projectConfigApi.get("/mode", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const mode = await readJsonFile(`${baseDir}/mode.json`);
  if (!mode) {
    return c.json({ active: false });
  }
  return c.json(mode);
});

export { projectConfigApi };
