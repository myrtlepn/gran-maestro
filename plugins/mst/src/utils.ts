/**
 * Gran Maestro Dashboard File Utilities
 */

export async function readJsonFile<T>(path: string): Promise<T | null> {
  try {
    const text = await Deno.readTextFile(path);
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

export async function readTextFile(path: string): Promise<string | null> {
  try {
    return await Deno.readTextFile(path);
  } catch {
    return null;
  }
}

export async function writeJsonFile(path: string, data: unknown): Promise<boolean> {
  try {
    await Deno.writeTextFile(path, JSON.stringify(data, null, 2) + "\n");
    return true;
  } catch {
    return false;
  }
}

export async function dirExists(path: string): Promise<boolean> {
  try {
    const stat = await Deno.stat(path);
    return stat.isDirectory;
  } catch {
    return false;
  }
}

export async function listDirs(path: string): Promise<string[]> {
  const dirs: string[] = [];
  try {
    for await (const entry of Deno.readDir(path)) {
      if (entry.isDirectory) {
        dirs.push(entry.name);
      }
    }
  } catch {
    // directory may not exist
  }
  return dirs.sort();
}

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

export function deepMerge(base: unknown, override: unknown, depth = 0): unknown {
  if (depth > 20) return override;
  if (!isPlainObject(base) || !isPlainObject(override)) {
    return override;
  }

  const result: Record<string, unknown> = { ...base };

  for (const [key, overrideValue] of Object.entries(override)) {
    const baseValue = base[key];

    if (isPlainObject(baseValue) && isPlainObject(overrideValue)) {
      result[key] = deepMerge(baseValue, overrideValue, depth + 1);
      continue;
    }

    result[key] = overrideValue;
  }

  return result;
}

function shouldReplaceArray(baseValue: unknown, currentValue: unknown): boolean {
  if (Array.isArray(baseValue) && Array.isArray(currentValue)) {
    return JSON.stringify(baseValue) !== JSON.stringify(currentValue);
  }
  return baseValue !== currentValue;
}

/**
 * Extracts overrides from `current` that differ from `base`.
 * Keys present in `base` but absent in `current` are treated as
 * "keep default" — they are NOT included in the diff.
 * To reset a key to its default, simply omit it from `current`.
 */
export function diffFromBase(base: unknown, current: unknown): Record<string, unknown> {
  if (!isPlainObject(base) || !isPlainObject(current)) {
    throw new Error("diffFromBase requires plain objects");
  }

  const diff: Record<string, unknown> = {};

  for (const [key, currentValue] of Object.entries(current)) {
    const baseValue = base[key];
    const baseHasKey = Object.prototype.hasOwnProperty.call(base, key);

    if (!baseHasKey) {
      diff[key] = currentValue;
      continue;
    }

    if (isPlainObject(baseValue) && isPlainObject(currentValue)) {
      const childDiff = diffFromBase(baseValue, currentValue);
      if (Object.keys(childDiff).length > 0) {
        diff[key] = childDiff;
      }
      continue;
    }

    if (shouldReplaceArray(baseValue, currentValue)) {
      diff[key] = currentValue;
    }
  }

  return diff;
}
