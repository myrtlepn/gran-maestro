import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { join } from "https://deno.land/std@0.224.0/path/mod.ts";
import { readJsonFile, writeJsonFile, deepMerge, diffFromBase } from "../utils.ts";
import { DEFAULTS_PATH, PLUGIN_ROOT, resolveBaseDir } from "../config.ts";
import type { PresetMeta, PresetListResponse, PresetDiffChange, GranMaestroConfig } from "../types.ts";
import { loadSettingOptions, validateConfigValues } from "../validation.ts";

const PRESETS_DIR = join(PLUGIN_ROOT, "templates", "defaults", "presets");
const MANIFEST_PATH = join(PRESETS_DIR, "manifest.json");

const projectPresetsApi = new Hono();

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    !(value instanceof Date) &&
    !(value instanceof RegExp) &&
    !(value instanceof Map) &&
    !(value instanceof Set)
  );
}

function flatDiff(before: Record<string, unknown>, after: Record<string, unknown>, prefix = ""): PresetDiffChange[] {
  const changes: PresetDiffChange[] = [];
  const allKeys = new Set([...Object.keys(before), ...Object.keys(after)]);
  
  for (const key of allKeys) {
    const path = prefix ? `${prefix}.${key}` : key;
    const fromVal = before[key];
    const toVal = after[key];
    
    if (isPlainObject(fromVal) && isPlainObject(toVal)) {
      changes.push(...flatDiff(fromVal, toVal, path));
    } else if (JSON.stringify(fromVal) !== JSON.stringify(toVal)) {
      changes.push({ path, from: fromVal, to: toVal });
    }
  }
  return changes;
}

interface ManifestType {
  presets?: PresetMeta[];
  categories?: Record<string, { label: string; description: string }>;
  tiers?: Record<string, { label: string; description: string }>;
}

const PRESET_ID_RE = /^[a-z0-9-]+$/;

async function loadPreset(presetId: string, baseDir: string): Promise<{ data: object; source: "builtin" | "user" } | null> {
  if (!PRESET_ID_RE.test(presetId)) {
    return null;
  }
  const manifest = await readJsonFile<ManifestType>(MANIFEST_PATH);
  if (manifest && Array.isArray(manifest.presets)) {
    const builtinPreset = manifest.presets.find((p) => p.id === presetId);
    if (builtinPreset && builtinPreset.file) {
      const filePath = join(PRESETS_DIR, builtinPreset.file);
      const data = await readJsonFile<object>(filePath);
      if (data) {
        return { data, source: "builtin" };
      }
    }
  }

  const userPresetPath = join(baseDir, "presets", `${presetId}.json`);
  const userData = await readJsonFile<Record<string, unknown>>(userPresetPath);
  if (userData && isPlainObject(userData.config)) {
    return { data: userData.config, source: "user" };
  }

  return null;
}

async function isBuiltinPreset(presetId: string): Promise<boolean> {
  const manifest = await readJsonFile<ManifestType>(MANIFEST_PATH);
  return Array.isArray(manifest?.presets) && manifest.presets.some((preset) => preset.id === presetId);
}

projectPresetsApi.get("/presets", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const manifest = await readJsonFile<ManifestType>(MANIFEST_PATH) ?? { presets: [], categories: {}, tiers: {} };
  const builtin: PresetMeta[] = Array.isArray(manifest.presets) ? manifest.presets : [];
  const user: PresetMeta[] = [];

  const userPresetsDir = join(baseDir, "presets");
  const userFiles: string[] = [];
  try {
    for await (const entry of Deno.readDir(userPresetsDir)) {
      if (entry.isFile && entry.name.endsWith(".json")) {
        userFiles.push(entry.name);
      }
    }
  } catch {
    // Directory might not exist yet
  }

  for (const file of userFiles) {
    const presetId = file.replace(/\.json$/, "");
    const presetData = await readJsonFile<Record<string, unknown>>(join(userPresetsDir, file));
    if (presetData) {
      user.push({
        id: presetId,
        name: (presetData.name as string) || presetId,
        description: (presetData.description as string) || "",
      });
    }
  }

  const response: PresetListResponse = {
    builtin,
    user,
    categories: manifest.categories || {},
    tiers: manifest.tiers || {},
  };

  return c.json(response);
});

projectPresetsApi.post("/presets/:presetId/diff", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const presetId = c.req.param("presetId");
  const preset = await loadPreset(presetId, baseDir);
  
  if (!preset) {
    return c.json({ error: "Preset not found" }, 404);
  }

  const defaults = await readJsonFile<GranMaestroConfig>(DEFAULTS_PATH) ?? {};
  const overrides = await readJsonFile<GranMaestroConfig>(join(baseDir, "config.json")) ?? {};
  const merged = deepMerge(defaults, overrides) as Record<string, unknown>;
  const nextMerged = deepMerge(merged, preset.data) as Record<string, unknown>;

  const changes = flatDiff(merged, nextMerged);
  return c.json({ changes });
});

projectPresetsApi.post("/presets/:presetId/apply", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const presetId = c.req.param("presetId");
  const preset = await loadPreset(presetId, baseDir);
  
  if (!preset) {
    return c.json({ error: "Preset not found" }, 404);
  }

  const defaults = await readJsonFile<GranMaestroConfig>(DEFAULTS_PATH) ?? {};
  const overrides = await readJsonFile<GranMaestroConfig>(join(baseDir, "config.json")) ?? {};
  const merged = deepMerge(defaults, overrides) as Record<string, unknown>;
  const nextMerged = deepMerge(merged, preset.data) as Record<string, unknown>;

  const changes = flatDiff(merged, nextMerged);

  const settingOptions = await loadSettingOptions(PLUGIN_ROOT);
  if (!settingOptions) {
    console.warn("[presets] Failed to load setting-options.json; skipping validation");
  } else {
    const { warnings } = validateConfigValues(nextMerged, settingOptions);
    if (warnings.length > 0) {
      console.warn("[presets] Invalid values:", warnings);
    }
  }
  
  const nextOverrides = diffFromBase(defaults, nextMerged);
  const writeConfigOk = await writeJsonFile(join(baseDir, "config.json"), nextOverrides);
  if (!writeConfigOk) {
    return c.json({ error: "Failed to write config.json" }, 500);
  }
  
  const writeResolvedOk = await writeJsonFile(join(baseDir, "config.resolved.json"), nextMerged);
  if (!writeResolvedOk) {
    console.warn("Warning: Failed to write config.resolved.json");
  }

  return c.json({ ok: true, changes });
});

projectPresetsApi.delete("/presets/:presetId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const presetId = c.req.param("presetId");
  if (!PRESET_ID_RE.test(presetId)) {
    return c.json({ error: "Preset not found" }, 404);
  }

  if (await isBuiltinPreset(presetId)) {
    return c.json({ error: "Cannot delete built-in preset" }, 403);
  }

  const userPresetPath = join(baseDir, "presets", `${presetId}.json`);
  try {
    await Deno.remove(userPresetPath);
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) {
      return c.json({ error: "Preset not found" }, 404);
    }
    return c.json({ error: "Failed to delete preset" }, 500);
  }

  return c.json({ ok: true });
});

projectPresetsApi.patch("/presets/:presetId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const presetId = c.req.param("presetId");
  if (!PRESET_ID_RE.test(presetId)) {
    return c.json({ error: "Preset not found" }, 404);
  }

  if (await isBuiltinPreset(presetId)) {
    return c.json({ error: "Cannot edit built-in preset" }, 403);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  const { name, description } = body;
  if (name !== undefined && typeof name !== "string") {
    return c.json({ error: "Invalid name. Must be a string." }, 400);
  }
  if (description !== undefined && typeof description !== "string") {
    return c.json({ error: "Invalid description. Must be a string." }, 400);
  }
  if (name === undefined && description === undefined) {
    return c.json({ error: "No fields to update" }, 400);
  }

  const userPresetPath = join(baseDir, "presets", `${presetId}.json`);
  const presetData = await readJsonFile<Record<string, unknown>>(userPresetPath);
  if (!presetData) {
    return c.json({ error: "Preset not found" }, 404);
  }

  const nextPresetData: Record<string, unknown> = { ...presetData };
  if (name !== undefined) {
    nextPresetData.name = name;
  }
  if (description !== undefined) {
    nextPresetData.description = description;
  }

  const writeOk = await writeJsonFile(userPresetPath, nextPresetData);
  if (!writeOk) {
    return c.json({ error: "Failed to update preset" }, 500);
  }

  return c.json({ ok: true });
});

projectPresetsApi.post("/presets", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  try {
    const body = await c.req.json();
    const { id, name, description, force } = body as Record<string, unknown>;

    if (!id || typeof id !== "string" || !PRESET_ID_RE.test(id)) {
      return c.json({ error: "Invalid preset ID. Must be lowercase alphanumeric and hyphens only." }, 400);
    }
    if (await isBuiltinPreset(id)) {
      return c.json({ error: "Cannot overwrite built-in preset" }, 403);
    }
    if (force !== undefined && typeof force !== "boolean") {
      return c.json({ error: "Invalid force option. Must be a boolean." }, 400);
    }

    const overrides = await readJsonFile<GranMaestroConfig>(join(baseDir, "config.json")) ?? {};
    const userPresetsDir = join(baseDir, "presets");
    
    try {
      await Deno.mkdir(userPresetsDir, { recursive: true });
    } catch {
      // ignore
    }

    const presetPath = join(userPresetsDir, `${id}.json`);
    if (!force) {
      try {
        await Deno.stat(presetPath);
        return c.json({ exists: true, id }, 409);
      } catch (error) {
        if (!(error instanceof Deno.errors.NotFound)) {
          return c.json({ error: "Failed to check existing preset" }, 500);
        }
      }
    }

    const presetData = {
      name: typeof name === "string" ? name : id,
      description: typeof description === "string" ? description : "",
      config: overrides,
    };

    const writeOk = await writeJsonFile(presetPath, presetData);
    if (!writeOk) {
      return c.json({ error: "Failed to save preset" }, 500);
    }

    return c.json({ ok: true, id });
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }
});

export { projectPresetsApi };
