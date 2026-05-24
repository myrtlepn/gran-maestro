import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { resolveBaseDir } from "../config.ts";

const projectArchivesApi = new Hono();
const decoder = new TextDecoder();
const ARCHIVE_SUFFIX = ".tar.gz";

type ArchiveType = "requests" | "plans" | "designs" | "ideation" | "discussion" | "debug" | "explore" | "unknown";

type ArchiveEntry = {
  id: string;
  filename: string;
  source: string;
  type: ArchiveType;
  size_bytes: number;
  archived_at: string;
};

type ArchiveSource = {
  type: ArchiveType | "archive_root";
  dir: string;
};

function isInvalidPathPart(value: string): boolean {
  return !value || value.includes("..") || value.includes("/") || value.includes("\\");
}

function stripArchiveSuffix(fileName: string): string {
  return fileName.toLowerCase().endsWith(ARCHIVE_SUFFIX)
    ? fileName.slice(0, -ARCHIVE_SUFFIX.length)
    : fileName;
}

function buildArchiveSources(baseDir: string): ArchiveSource[] {
  return [
    { type: "requests", dir: `${baseDir}/requests/archived` },
    { type: "plans", dir: `${baseDir}/plans/archived` },
    { type: "designs", dir: `${baseDir}/designs/archived` },
    { type: "ideation", dir: `${baseDir}/ideation/archived` },
    { type: "discussion", dir: `${baseDir}/discussion/archived` },
    { type: "debug", dir: `${baseDir}/debug/archived` },
    { type: "explore", dir: `${baseDir}/explore/archived` },
    { type: "archive_root", dir: `${baseDir}/archive` },
  ];
}

function inferArchiveTypeFromStem(stem: string): ArchiveType {
  const prefix = stem.slice(0, 3).toUpperCase();
  if (prefix === "REQ") return "requests";
  if (prefix === "PLN") return "plans";
  if (prefix === "DES") return "designs";
  if (prefix === "IDN") return "ideation";
  if (prefix === "DSC") return "discussion";
  if (prefix === "DBG") return "debug";
  if (prefix === "EXP") return "explore";
  return "unknown";
}

function fileExists(filePath: string): Promise<boolean> {
  return Deno.stat(filePath).then(
    () => true,
    () => false,
  );
}

function isPathReadableDirectory(path: string): Promise<boolean> {
  return Deno.stat(path).then(
    (info) => info.isDirectory,
    () => false,
  );
}

async function listArchivesInDirectory(
  sourceDir: string,
  sourceType: ArchiveType | "archive_root",
): Promise<ArchiveEntry[]> {
  const result: ArchiveEntry[] = [];
  try {
    for await (const entry of Deno.readDir(sourceDir)) {
      if (!entry.isFile || !entry.name.endsWith(ARCHIVE_SUFFIX)) {
        continue;
      }
      const fullPath = `${sourceDir}/${entry.name}`;
      const stem = stripArchiveSuffix(entry.name);
      try {
        const stat = await Deno.stat(fullPath);
        const type: ArchiveType = sourceType === "archive_root"
          ? inferArchiveTypeFromStem(stem)
          : sourceType;
        const source = sourceType === "archive_root"
          ? "archive"
          : `${sourceType}/archived`;

        result.push({
          id: stem,
          filename: fullPath,
          source,
          type,
          size_bytes: stat.size,
          archived_at: stat.mtime?.toISOString() ?? new Date().toISOString(),
        });
      } catch {
        continue;
      }
    }
  } catch {
    // ignore missing or unreadable directories
  }
  return result;
}

function isUnsafeArchiveMember(name: string): boolean {
  return name.includes("\\") ||
    name === "" ||
    name === ".." ||
    name.startsWith("../") ||
    name.includes("/../") ||
    name.endsWith("/..") ||
    name.startsWith("/") ;
}

async function findArchive(baseDir: string, archiveId: string): Promise<{ path: string; type: ArchiveType; source: ArchiveSource } | null> {
  const archiveFileName = `${archiveId}${ARCHIVE_SUFFIX}`;
  for (const source of buildArchiveSources(baseDir)) {
    const path = `${source.dir}/${archiveFileName}`;
    if (await fileExists(path)) {
      if (source.type === "archive_root") {
        return { path, type: inferArchiveTypeFromStem(archiveId), source };
      }
      return { path, type: source.type, source };
    }
  }
  return null;
}

async function readArchiveMembers(archivePath: string): Promise<string[]> {
  const output = await new Deno.Command("tar", {
    args: ["-tzf", archivePath],
    stdout: "piped",
    stderr: "piped",
  }).output();
  if (output.code !== 0) {
    throw new Error(`${decoder.decode(output.stderr)}${decoder.decode(output.stdout)}`.trim() || "Failed to read archive");
  }

  const list = decoder.decode(output.stdout).trim();
  if (!list) {
    return [];
  }
  return list.split(/\r?\n/);
}

function isSafeDestinationType(archiveType: ArchiveType): archiveType is Exclude<ArchiveType, "unknown"> {
  return archiveType !== "unknown";
}

async function restoreArchiveAtomically(
  baseDir: string,
  archivePath: string,
  archiveType: ArchiveType,
) {
  const tempDir = await Deno.makeTempDir({ prefix: "gran-maestro-archive-" });
  const movedItems: string[] = [];

  try {
    const members = await readArchiveMembers(archivePath);
    for (const member of members) {
      if (isUnsafeArchiveMember(member)) {
        throw new Error("Archive contains invalid member path");
      }
    }

    const extract = await new Deno.Command("tar", {
      args: ["-xzf", archivePath, "-C", tempDir],
      stdout: "piped",
      stderr: "piped",
    }).output();
    if (extract.code !== 0) {
      throw new Error(
        `${decoder.decode(extract.stderr)}${decoder.decode(extract.stdout)}`.trim() || "Failed to extract archive",
      );
    }

    const restoreDir = `${baseDir}/${archiveType}`;
    await Deno.mkdir(restoreDir, { recursive: true });

    const entries = [];
    for await (const entry of Deno.readDir(tempDir)) {
      entries.push(entry.name);
      if (isInvalidPathPart(entry.name)) {
        throw new Error(`Invalid extracted entry name: ${entry.name}`);
      }
      const destination = `${restoreDir}/${entry.name}`;
      if (await fileExists(destination)) {
        throw new Error(`Target already exists: ${entry.name}`);
      }
    }

    for (const entryName of entries) {
      const source = `${tempDir}/${entryName}`;
      const destination = `${restoreDir}/${entryName}`;
      await Deno.rename(source, destination);
      movedItems.push(destination);
    }

    return { restored: entries, type: archiveType };
  } catch (error) {
    for (let i = movedItems.length - 1; i >= 0; i--) {
      try {
        await Deno.remove(movedItems[i], { recursive: true });
      } catch {
        // best-effort rollback
      }
    }
    throw error;
  } finally {
    try {
      await Deno.remove(tempDir, { recursive: true });
    } catch {
      // best-effort cleanup
    }
  }
}

projectArchivesApi.get("/archives", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const byType: Record<ArchiveType, number> = {
    requests: 0,
    plans: 0,
    designs: 0,
    ideation: 0,
    discussion: 0,
    debug: 0,
    explore: 0,
    unknown: 0,
  };

  const sources = buildArchiveSources(baseDir);
  const archiveRecords = (
    await Promise.all(
      sources.map((source) =>
        isPathReadableDirectory(source.dir).then((exists) =>
          exists ? listArchivesInDirectory(source.dir, source.type) : []
        )
      )
    )
  ).flat();

  let totalSizeBytes = 0;
  for (const archive of archiveRecords) {
    byType[archive.type] += 1;
    totalSizeBytes += archive.size_bytes;
  }

  archiveRecords.sort((a, b) => b.archived_at.localeCompare(a.archived_at));

  const summary = {
    total_count: archiveRecords.length,
    total_size_bytes: totalSizeBytes,
    by_type: byType,
  };

  return c.json({
    archives: archiveRecords,
    summary,
    by_type: byType,
  });
});

projectArchivesApi.post("/archives/:id/restore", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const rawId = c.req.param("id");
  if (isInvalidPathPart(rawId)) {
    return c.json({ error: "Invalid archive id" }, 400);
  }
  const archiveId = stripArchiveSuffix(rawId);
  if (!archiveId) {
    return c.json({ error: "Invalid archive id" }, 400);
  }

  const archive = await findArchive(baseDir, archiveId);
  if (!archive) {
    return c.json({ error: "Archive not found" }, 404);
  }
  if (!isSafeDestinationType(archive.type)) {
    return c.json({ error: "Cannot infer restore type" }, 409);
  }

  try {
    const result = await restoreArchiveAtomically(baseDir, archive.path, archive.type);
    await Deno.remove(archive.path);
    return c.json({ success: true, archive_id: archiveId, ...result });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to restore archive";
    if (message.startsWith("Target already exists")) {
      return c.json({ error: "Restore target already exists", detail: message }, 409);
    }
    if (message.startsWith("Archive contains invalid member path") || message.startsWith("Invalid extracted entry name")) {
      return c.json({ error: message }, 400);
    }
    return c.json({ error: "Failed to restore archive", detail: message }, 500);
  }
});

export { projectArchivesApi };
