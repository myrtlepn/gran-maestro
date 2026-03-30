import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { resolveBaseDir } from "../config.ts";
import { broadcastSse } from "../sse.ts";
import { dirExists, listDirs, readJsonFile, readTextFile, writeJsonFile } from "../utils.ts";

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

type ObjectiveCommentStatus = "open" | "resolved";

type ObjectiveComment = {
  id: string;
  author: string;
  body: string;
  createdAt: string;
  status: ObjectiveCommentStatus;
  tags: string[];
};

type ObjectiveCommentsFile = {
  docPath: string;
  docRevision: string | null;
  updatedAt: string;
  comments: ObjectiveComment[];
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

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string");
}

function isCommentStatus(value: unknown): value is ObjectiveCommentStatus {
  return value === "open" || value === "resolved";
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

function objectiveCommentsPathFromObjectivePath(objectivePath: string): string {
  const normalized = objectivePath.replace(/\\/g, "/");
  const slashIndex = normalized.lastIndexOf("/");
  if (slashIndex === -1) {
    return "objective.comments.json";
  }
  const directory = normalized.slice(0, slashIndex);
  return `${directory}/objective.comments.json`;
}

function normalizeObjectiveComment(entry: unknown): ObjectiveComment | null {
  if (!isRecord(entry)) return null;
  const id = asStringOrNull(entry.id);
  const author = asStringOrNull(entry.author);
  const body = asStringOrNull(entry.body);
  const createdAt = asStringOrNull(entry.createdAt);
  const status = entry.status;
  if (!id || !author || !body || !createdAt || !isCommentStatus(status)) {
    return null;
  }
  return {
    id,
    author,
    body,
    createdAt,
    status,
    tags: asStringArray(entry.tags),
  };
}

async function objectiveRevisionFromFile(objectiveFile: string): Promise<string | null> {
  const content = await readTextFile(objectiveFile);
  if (content === null) return null;
  return await toSha256Hex(content);
}

async function objectiveMtimeFromFile(objectiveFile: string): Promise<string | null> {
  try {
    const stat = await Deno.stat(objectiveFile);
    return stat.mtime ? stat.mtime.toISOString() : null;
  } catch {
    return null;
  }
}

async function loadObjectiveComments(
  commentsFile: string,
  objectivePath: string,
  objectiveRevision: string | null,
): Promise<ObjectiveCommentsFile> {
  const initialState: ObjectiveCommentsFile = {
    docPath: objectivePath,
    docRevision: objectiveRevision,
    updatedAt: new Date().toISOString(),
    comments: [],
  };

  const loaded = await readJsonFile<Record<string, unknown>>(commentsFile);
  if (!loaded) {
    return initialState;
  }

  const comments = Array.isArray(loaded.comments)
    ? loaded.comments.map(normalizeObjectiveComment).filter((item): item is ObjectiveComment => item !== null)
    : [];

  return {
    docPath: asStringOrNull(loaded.docPath) ?? objectivePath,
    docRevision: asStringOrNull(loaded.docRevision) ?? objectiveRevision,
    updatedAt: asStringOrNull(loaded.updatedAt) ?? initialState.updatedAt,
    comments,
  };
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

projectAgileApi.get("/agile/:agiId/objective", async (c) => {
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
  const objectiveFile = `${sessionDir}/${objectivePath}`;
  const content = await readTextFile(objectiveFile);
  if (content === null) {
    return c.json({ error: "Objective not found" }, 404);
  }

  const revision = await toSha256Hex(content);
  const mtime = await objectiveMtimeFromFile(objectiveFile);
  return c.json({
    content,
    path: objectivePath,
    revision,
    mtime,
  });
});

projectAgileApi.get("/agile/:agiId/objective/comments", async (c) => {
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
  const objectiveFile = `${sessionDir}/${objectivePath}`;
  const commentsFile = `${sessionDir}/${objectiveCommentsPathFromObjectivePath(objectivePath)}`;
  const objectiveRevision = await objectiveRevisionFromFile(objectiveFile);
  const commentsState = await loadObjectiveComments(commentsFile, objectivePath, objectiveRevision);
  return c.json(commentsState);
});

projectAgileApi.post("/agile/:agiId/objective/comments", async (c) => {
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

  let payload: unknown;
  try {
    payload = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  if (!isRecord(payload)) {
    return c.json({ error: "Request body must be an object" }, 400);
  }

  const commentBody = asStringOrNull(payload.body)?.trim();
  if (!commentBody) {
    return c.json({ error: "body is required" }, 400);
  }

  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
  const objectiveFile = `${sessionDir}/${objectivePath}`;
  const commentsPath = objectiveCommentsPathFromObjectivePath(objectivePath);
  const commentsFile = `${sessionDir}/${commentsPath}`;
  const objectiveRevision = await objectiveRevisionFromFile(objectiveFile);
  const commentsState = await loadObjectiveComments(commentsFile, objectivePath, objectiveRevision);

  const now = new Date().toISOString();
  const comment: ObjectiveComment = {
    id: crypto.randomUUID(),
    author: asStringOrNull(payload.author)?.trim() || "anonymous",
    body: commentBody,
    createdAt: now,
    status: "open",
    tags: asStringArray(payload.tags),
  };

  const nextState: ObjectiveCommentsFile = {
    docPath: objectivePath,
    docRevision: objectiveRevision,
    updatedAt: now,
    comments: [...commentsState.comments, comment],
  };

  const commentsDir = commentsFile.slice(0, commentsFile.lastIndexOf("/"));
  try {
    await Deno.mkdir(commentsDir, { recursive: true });
  } catch {
    // directory may already exist
  }
  const saved = await writeJsonFile(commentsFile, nextState);
  if (!saved) {
    return c.json({ error: "Failed to persist objective comments" }, 500);
  }

  broadcastSse({
    type: "objective_comment_added",
    projectId: c.req.param("projectId"),
    sessionId: agiId,
    data: {
      agiId,
      docPath: objectivePath,
      docRevision: objectiveRevision,
      comment,
      timestamp: now,
    },
  });

  return c.json({ id: comment.id, comment }, 201);
});

projectAgileApi.patch("/agile/:agiId/objective/comments/:commentId", async (c) => {
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

  let payload: unknown;
  try {
    payload = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  if (!isRecord(payload) || !isCommentStatus(payload.status)) {
    return c.json({ error: "status must be either open or resolved" }, 400);
  }

  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
  const objectiveFile = `${sessionDir}/${objectivePath}`;
  const commentsFile = `${sessionDir}/${objectiveCommentsPathFromObjectivePath(objectivePath)}`;
  const objectiveRevision = await objectiveRevisionFromFile(objectiveFile);
  const commentsState = await loadObjectiveComments(commentsFile, objectivePath, objectiveRevision);
  const commentId = c.req.param("commentId");
  const index = commentsState.comments.findIndex((item) => item.id === commentId);
  if (index === -1) {
    return c.json({ error: "Comment not found" }, 404);
  }

  const now = new Date().toISOString();
  const updatedComment: ObjectiveComment = {
    ...commentsState.comments[index],
    status: payload.status,
  };

  const nextComments = [...commentsState.comments];
  nextComments[index] = updatedComment;

  const saved = await writeJsonFile(commentsFile, {
    docPath: objectivePath,
    docRevision: objectiveRevision,
    updatedAt: now,
    comments: nextComments,
  } satisfies ObjectiveCommentsFile);
  if (!saved) {
    return c.json({ error: "Failed to persist objective comments" }, 500);
  }

  return c.json({ ok: true, comment: updatedComment });
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

projectAgileApi.get("/agile/sessions/:agiId/sprints/:sprintId/retrospective-md", async (c) => {
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

  const content = await readTextFile(
    `${baseDir}/agile/${agiId}/sprints/${sprintId}/retrospective.md`
  );

  if (content === null) {
    return c.json({ error: "Retrospective not found" }, 404);
  }
  return c.text(content);
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
