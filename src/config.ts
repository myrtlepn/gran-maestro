/**
 * Gran Maestro Dashboard Configuration and mutable server state.
 */

import {
  dirname,
  fromFileUrl,
  join,
} from "https://deno.land/std@0.224.0/path/mod.ts";
import { deepMerge, readJsonFile, writeJsonFile } from "./utils.ts";
import type { GranMaestroConfig, Project, Registry } from "./types.ts";

export const BASE_DIR = ".gran-maestro";
export const DEFAULT_PORT = 3847;
export const HOST = "127.0.0.1";
export const SSE_DEBOUNCE_MS = 300;
export const HUB_MODE = true; // Always hub mode — multi-project by default
export const PLUGIN_ROOT = join(dirname(fromFileUrl(import.meta.url)), "..");
export const DEFAULTS_PATH = join(
  PLUGIN_ROOT,
  "templates",
  "defaults",
  "config.json",
);

function safeEnvGet(name: string): string | undefined {
  try {
    return Deno.env.get(name) ?? undefined;
  } catch {
    return undefined;
  }
}

const _homeDir = safeEnvGet("HOME") ??
  safeEnvGet("USERPROFILE") ??
  ".";
export const HUB_DIR = `${_homeDir}/.gran-maestro-hub`;

export let registry: Registry = { projects: [] };

export function setRegistry(nextRegistry: Registry): void {
  registry = nextRegistry;
}

/**
 * Returns the effective runtime config: deepMerge(defaults, userConfig).
 * This includes all default values filled in. To check if a user explicitly
 * configured a key, read config.json directly instead.
 */
export async function loadConfig(
  baseDir = BASE_DIR,
): Promise<GranMaestroConfig> {
  const defaults = await readJsonFile<GranMaestroConfig>(DEFAULTS_PATH) ?? {};
  const userConfig =
    await readJsonFile<GranMaestroConfig>(`${baseDir}/config.json`) ?? {};
  return deepMerge(defaults, userConfig) as GranMaestroConfig;
}

export function stripBasePath(path: string, baseDir: string): string {
  const normPath = path.replace(/\\/g, "/");
  const normBase = baseDir.replace(/\\/g, "/");
  const normalizedBase = normBase.endsWith("/")
    ? normBase.slice(0, -1)
    : normBase;
  if (
    path.startsWith(`${normalizedBase}/`) ||
    normPath.startsWith(`${normalizedBase}/`)
  ) {
    return normPath.replace(`${normalizedBase}/`, "");
  }
  const normCwd = Deno.cwd().replace(/\\/g, "/");
  return normPath.replace(`${normCwd}/`, "");
}

export async function generateProjectId(path: string): Promise<string> {
  const data = new TextEncoder().encode(path);
  const hash = await crypto.subtle.digest("SHA-256", data);
  const hex = [...new Uint8Array(hash)].map((byte) =>
    byte.toString(16).padStart(2, "0")
  ).join("");
  return hex.slice(0, 6);
}

export async function loadRegistry(): Promise<Registry> {
  const loaded = await readJsonFile<Registry>(`${HUB_DIR}/registry.json`);
  if (!loaded || !Array.isArray(loaded.projects)) {
    return { projects: [] };
  }
  return {
    projects: loaded.projects.filter((project): project is Project =>
      typeof project?.id === "string" &&
      typeof project?.name === "string" &&
      typeof project?.path === "string" &&
      typeof project?.registered_at === "string"
    ),
  };
}

export async function saveRegistry(): Promise<boolean> {
  return await writeJsonFile(`${HUB_DIR}/registry.json`, registry);
}

export function resolveBaseDir(projectId?: string): string | null {
  if (!HUB_MODE) return BASE_DIR;

  if (!projectId) {
    return registry.projects.length === 1
      ? registry.projects[0]?.path ?? null
      : null;
  }

  return registry.projects.find((project) => project.id === projectId)?.path ??
    null;
}
