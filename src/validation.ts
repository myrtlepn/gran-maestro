import { readJsonFile } from "./utils.ts";

export interface ValidationWarning {
  path: string;
  value: unknown;
  allowed: string[];
}

interface FlatConfig {
  [path: string]: unknown;
}

export interface ValidationResult {
  warnings: ValidationWarning[];
}

export type SettingOptions = Record<string, string[]>;

function optionPatternMatches(pattern: string, path: string): boolean {
  const expression = pattern
    .split(".")
    .map((segment) => {
      if (segment === "**") return ".+";
      if (segment === "*") return "[^.]+";
      return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("\\.");
  return new RegExp(`^${expression}$`).test(path);
}

function allowedValuesForPath(options: SettingOptions, path: string): string[] | undefined {
  if (options[path]) return options[path];
  for (const [pattern, values] of Object.entries(options)) {
    if (pattern.includes("*") && optionPatternMatches(pattern, path)) {
      return values;
    }
  }
  return undefined;
}

function joinPath(...segments: string[]): string {
  return segments
    .map((segment, index) => {
      if (index === 0) {
        return segment.replace(/[\\/]+$/, "");
      }
      return segment.replace(/^[/\\]+|[/\\]+$/g, "");
    })
    .join("/");
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function flattenInto(value: unknown, out: FlatConfig, prefix = ""): void {
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) {
      const path = prefix ? `${prefix}.${i}` : String(i);
      flattenInto(value[i], out, path);
    }
    return;
  }

  if (isPlainObject(value)) {
    for (const [key, next] of Object.entries(value)) {
      const path = prefix ? `${prefix}.${key}` : key;
      flattenInto(next, out, path);
    }
    return;
  }

  if (prefix) {
    out[prefix] = value;
  }
}

function flattenConfig(config: Record<string, unknown>): FlatConfig {
  const out: FlatConfig = {};
  flattenInto(config, out);
  return out;
}

export async function loadSettingOptions(pluginRoot: string): Promise<SettingOptions | null> {
  const filePath = joinPath(pluginRoot, "templates", "defaults", "setting-options.json");
  const loaded = await readJsonFile<unknown>(filePath);
  if (!loaded || !isPlainObject(loaded)) {
    return null;
  }

  const options: SettingOptions = {};
  for (const [path, allowed] of Object.entries(loaded)) {
    if (Array.isArray(allowed) && allowed.every((v) => typeof v === "string")) {
      options[path] = [...allowed];
    }
  }
  return options;
}

export function validateConfigValues(
  config: Record<string, unknown>,
  options: SettingOptions,
): ValidationResult {
  const flattened = flattenConfig(config);
  const warnings: ValidationWarning[] = [];

  for (const [path, value] of Object.entries(flattened)) {
    const allowed = allowedValuesForPath(options, path);
    if (!allowed) {
      continue;
    }

    const isAllowed = allowed.some((candidate) => candidate === value);
    if (!isAllowed) {
      warnings.push({ path, value, allowed });
    }
  }

  return { warnings };
}
