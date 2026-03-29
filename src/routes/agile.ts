import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { resolveBaseDir } from "../config.ts";
import { dirExists, listDirs, readJsonFile, readTextFile } from "../utils.ts";

const projectAgileApi = new Hono();

const AGI_ID_RE = /^AGI-\d+$/;
const SPRINT_ID_RE = /^S\d+$/;
const SNAPSHOT_FILE_RE = /^v(\d+)\.md$/;

type SessionJson = Record<string, unknown> & {
  id?: string;
  status?: string;
  current_sprint?: number;
  created_at?: string;
  updated_at?: string;
  steering_every?: unknown;
  queue?: unknown;
  refs?: unknown;
  objective?: unknown;
};

function isValidAgiId(value: string): boolean {
  return AGI_ID_RE.test(value);
}

function isValidSprintId(value: string): boolean {
  return SPRINT_ID_RE.test(value);
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNumberOrNull(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

async function toSha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function objectiveEtagFromContent(content: string | null): Promise<string | null> {
  if (content === null) return null;
  return `"${await toSha256Hex(content)}"`;
}

async function listObjectiveSnapshotVersions(historyDir: string): Promise<number[]> {
  const versions: number[] = [];

  try {
    for await (const entry of Deno.readDir(historyDir)) {
      if (!entry.isFile) continue;
      const match = SNAPSHOT_FILE_RE.exec(entry.name);
      if (!match) continue;
      const version = Number.parseInt(match[1], 10);
      if (Number.isFinite(version)) {
        versions.push(version);
      }
    }
  } catch {
    // history directory may not exist
  }

  versions.sort((a, b) => a - b);
  return versions;
}

projectAgileApi.get("/agile/sessions", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agileDir = `${baseDir}/agile`;
  if (!(await dirExists(agileDir))) {
    return c.json([]);
  }

  const sessionDirs = (await listDirs(agileDir)).filter((dir) => AGI_ID_RE.test(dir));
  const sessions = await Promise.all(
    sessionDirs.map(async (dir) => {
      const session = await readJsonFile<SessionJson>(`${agileDir}/${dir}/session.json`);
      if (!session) return null;
      const queue = asArray(session.queue);
      const refs = asArray(session.refs);
      return {
        id: asStringOrNull(session.id) ?? dir,
        status: asStringOrNull(session.status) ?? "unknown",
        current_sprint: asNumberOrNull(session.current_sprint) ?? 0,
        steering_every: asNumberOrNull(session.steering_every) ?? 0,
        queue_size: queue.length,
        refs_count: refs.length,
        created_at: asStringOrNull(session.created_at),
        updated_at: asStringOrNull(session.updated_at),
      };
    }),
  );

  const filtered = sessions.filter((session): session is NonNullable<typeof session> => session !== null);
  filtered.sort((a, b) => {
    const aKey = a.updated_at ?? a.created_at ?? "";
    const bKey = b.updated_at ?? b.created_at ?? "";
    return bKey.localeCompare(aKey);
  });

  return c.json(filtered);
});

projectAgileApi.get("/agile/sessions/:agiId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  if (!isValidAgiId(agiId)) {
    return c.json({ error: "Invalid AGI id" }, 400);
  }

  const sessionDir = `${baseDir}/agile/${agiId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Session not found" }, 404);
  }

  const session = await readJsonFile<SessionJson>(`${sessionDir}/session.json`);
  if (!session) {
    return c.json({ error: "Session not found" }, 404);
  }

  const sprintsDir = `${sessionDir}/sprints`;
  const sprintDirs = (await listDirs(sprintsDir)).filter((dir) => SPRINT_ID_RE.test(dir));
  sprintDirs.sort((a, b) => a.localeCompare(b));

  const sprints = await Promise.all(
    sprintDirs.map(async (sprintId) => {
      const result = await readJsonFile<Record<string, unknown>>(`${sprintsDir}/${sprintId}/result.json`);
      if (!result) return null;
      return {
        sprint_id: sprintId,
        ...result,
      };
    }),
  );

  const objectiveContent = await readTextFile(`${sessionDir}/objective/objective.md`);
  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectiveVersion = asNumberOrNull(objectiveMeta.version);
  const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
  const links = await readJsonFile<Record<string, unknown>>(`${sessionDir}/index/links.json`);
  const sessionResponse = {
    ...session,
    steering_every: asNumberOrNull(session.steering_every) ?? 0,
    queue: asArray(session.queue),
    refs: asArray(session.refs),
  };

  return c.json({
    session: sessionResponse,
    sprints: sprints.filter((item): item is NonNullable<typeof item> => item !== null),
    objective: {
      version: objectiveVersion,
      path: objectivePath,
      content: objectiveContent,
    },
    links: links ?? null,
  });
});

projectAgileApi.get("/agile/sessions/:agiId/objective", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  if (!isValidAgiId(agiId)) {
    return c.json({ error: "Invalid AGI id" }, 400);
  }

  const sessionDir = `${baseDir}/agile/${agiId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Session not found" }, 404);
  }

  const session = await readJsonFile<SessionJson>(`${sessionDir}/session.json`);
  if (!session) {
    return c.json({ error: "Session not found" }, 404);
  }

  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
  const content = await readTextFile(`${sessionDir}/${objectivePath}`);
  const etag = await objectiveEtagFromContent(content);
  if (etag !== null) {
    c.header("ETag", etag);
  }

  return c.json({
    content,
    path: objectivePath,
  });
});

projectAgileApi.put("/agile/sessions/:agiId/objective", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  if (!isValidAgiId(agiId)) {
    return c.json({ error: "Invalid AGI id" }, 400);
  }

  const sessionDir = `${baseDir}/agile/${agiId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Session not found" }, 404);
  }

  const session = await readJsonFile<SessionJson>(`${sessionDir}/session.json`);
  if (!session) {
    return c.json({ error: "Session not found" }, 404);
  }

  try {
    const body = await c.req.json();
    if (!isRecord(body) || typeof body.content !== "string") {
      return c.json({ error: "Content body must be a JSON object with string content" }, 400);
    }

    const objectiveMeta = isRecord(session.objective) ? session.objective : {};
    const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
    const objectiveFile = `${sessionDir}/${objectivePath}`;
    const ifMatch = c.req.header("If-Match");

    if (ifMatch) {
      const currentContent = await readTextFile(objectiveFile);
      const currentEtag = await objectiveEtagFromContent(currentContent);
      if (currentEtag === null || currentEtag !== ifMatch) {
        return c.json({ error: "Objective has been modified" }, 409);
      }
    }

    try {
      if (ifMatch) {
        const latestContent = await readTextFile(objectiveFile);
        const latestEtag = await objectiveEtagFromContent(latestContent);
        if (latestEtag === null || latestEtag !== ifMatch) {
          return c.json({ error: "Objective has been modified" }, 409);
        }
      }

      await Deno.writeTextFile(objectiveFile, body.content);
      const newEtag = await objectiveEtagFromContent(body.content);
      if (newEtag !== null) {
        c.header("ETag", newEtag);
      }
      return c.json({ success: true });
    } catch {
      return c.json({ error: "Failed to write objective" }, 500);
    }
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }
});

projectAgileApi.get("/agile/sessions/:agiId/sprints/:sprintId/retrospective", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  if (!isValidAgiId(agiId)) {
    return c.json({ error: "Invalid AGI id" }, 400);
  }

  const sprintId = c.req.param("sprintId").toUpperCase();
  if (!isValidSprintId(sprintId)) {
    return c.json({ error: "Invalid sprint id" }, 400);
  }

  const retrospective = await readJsonFile<Record<string, unknown>>(
    `${baseDir}/agile/${agiId}/sprints/${sprintId}/retrospective.json`,
  );
  if (!retrospective) {
    return c.json({ error: "Retrospective not found" }, 404);
  }
  return c.json(retrospective);
});

projectAgileApi.get("/agile/sessions/:agiId/objective/diff", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  if (!isValidAgiId(agiId)) {
    return c.json({ error: "Invalid AGI id" }, 400);
  }

  const sessionDir = `${baseDir}/agile/${agiId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Session not found" }, 404);
  }

  const session = await readJsonFile<SessionJson>(`${sessionDir}/session.json`);
  if (!session) {
    return c.json({ error: "Session not found" }, 404);
  }

  const objectiveContent = await readTextFile(`${sessionDir}/objective/objective.md`);
  if (objectiveContent === null) {
    return c.json({ error: "Objective not found" }, 404);
  }

  const historyDir = `${sessionDir}/objective/history`;
  const versions = await listObjectiveSnapshotVersions(historyDir);
  const snapshotVersion = versions.length > 0 ? versions[versions.length - 1] : null;
  const previousSnapshotVersion = versions.length > 1 ? versions[versions.length - 2] : null;

  let changed = false;
  if (snapshotVersion !== null && previousSnapshotVersion !== null) {
    const latest = await readTextFile(`${historyDir}/v${snapshotVersion}.md`);
    const previous = await readTextFile(`${historyDir}/v${previousSnapshotVersion}.md`);
    changed = latest !== null && previous !== null && latest !== previous;
  } else if (snapshotVersion !== null) {
    const snapshot = await readTextFile(`${historyDir}/v${snapshotVersion}.md`);
    changed = snapshot !== null && snapshot !== objectiveContent;
  }

  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectiveVersion = asNumberOrNull(objectiveMeta.version) ?? snapshotVersion ?? 0;

  return c.json({
    agi_id: agiId,
    version: objectiveVersion,
    changed,
    snapshot_version: snapshotVersion,
    previous_snapshot_version: previousSnapshotVersion,
  });
});

export { projectAgileApi };
