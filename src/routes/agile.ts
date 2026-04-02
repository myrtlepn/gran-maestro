import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { resolveBaseDir } from "../config.ts";
import { broadcastSse } from "../sse.ts";
import { dirExists, listDirs, readJsonFile, readTextFile, writeJsonFile } from "../utils.ts";

const projectAgileApi = new Hono();

const AGI_ID_RE = /^AGI-\d+$/;
const SPRINT_ID_RE = /^S\d+$/;
const SNAPSHOT_FILE_RE = /^v(\d+)\.md$/;
const IMAGE_EXTENSION_TO_CONTENT_TYPE: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};
const OBJECTIVE_DOD_MARKER_LINE_RE = /^<!--\s*dod:\s*(DOD-[A-Z0-9_-]+)\s+status:\s*([a-z_]+)\s+priority:\s*([a-z_]+)\s*-->$/i;
const MARKER_ANCHOR_HEADING_RE = /^\s{0,3}#{1,6}\s+/;
const MARKER_ANCHOR_CHECKLIST_RE = /^\s*[-*+]\s+\[[ xX]\]\s+/;
const OBJECTIVE_L2_HEADING_RE = /^\s{0,3}##\s+(.+?)\s*$/;

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

type MarkerAnchorType = "heading" | "checklist" | "any";

type ObjectiveMarker = {
  markerLine: string;
  dod: string;
  status: string;
  priority: string;
  anchorType: MarkerAnchorType;
  anchorText: string | null;
  contentText?: string;
};

type ObjectiveParsedSectionKey =
  | "architecture_decisions"
  | "constraints"
  | "moscow"
  | "nfr"
  | "risks"
  | "references";

type ObjectiveParsedSection = {
  key: ObjectiveParsedSectionKey;
  title: string;
  content: string;
};

type ObjectiveParsedDod = {
  dod: string;
  status: string;
  priority: string;
  anchorText: string | null;
  contentText?: string;
};

type ParsedObjective = {
  dods: ObjectiveParsedDod[];
  sections: ObjectiveParsedSection[];
};

const OBJECTIVE_SECTION_DEFINITIONS: Array<{
  key: ObjectiveParsedSectionKey;
  title: string;
  aliases: string[];
}> = [
  {
    key: "architecture_decisions",
    title: "설계 결정",
    aliases: ["설계 결정", "architecture decisions", "architecture decision"],
  },
  {
    key: "constraints",
    title: "제약사항",
    aliases: ["제약사항", "제약 사항", "out-of-scope", "out of scope", "기술적 제약", "비즈니스 제약"],
  },
  {
    key: "moscow",
    title: "MoSCoW",
    aliases: ["moscow", "우선순위"],
  },
  {
    key: "nfr",
    title: "NFR",
    aliases: ["nfr", "프로젝트 nfr", "non-functional", "non functional"],
  },
  {
    key: "risks",
    title: "리스크",
    aliases: ["리스크", "risk register", "리스크 레지스터"],
  },
  {
    key: "references",
    title: "레퍼런스",
    aliases: ["레퍼런스", "참조 레퍼런스", "reference"],
  },
];

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

function imageContentTypeFromPath(filePath: string): string | null {
  const normalized = filePath.replace(/\\/g, "/");
  const lower = normalized.toLowerCase();
  const extensionIndex = lower.lastIndexOf(".");
  if (extensionIndex === -1) return null;
  const extension = lower.slice(extensionIndex);
  return IMAGE_EXTENSION_TO_CONTENT_TYPE[extension] ?? null;
}

function isCommentStatus(value: unknown): value is ObjectiveCommentStatus {
  return value === "open" || value === "resolved";
}

async function toSha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function objectiveRevisionFromContent(content: string): Promise<string> {
  return (await toSha256Hex(content)).slice(0, 12);
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

function normalizeAnchorText(line: string): string {
  return line.trim().replace(/\s+/g, " ");
}

function normalizeHeadingText(line: string): string {
  return line
    .trim()
    .toLowerCase()
    .replace(/[()[\]{}]/g, " ")
    .replace(/[\\/|]+/g, " ")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ");
}

function trimSurroundingEmptyLines(lines: string[]): string[] {
  let start = 0;
  let end = lines.length;
  while (start < end && lines[start].trim().length === 0) start += 1;
  while (end > start && lines[end - 1].trim().length === 0) end -= 1;
  return lines.slice(start, end);
}

function markerAnchorFromOriginalLine(lines: string[], markerLineIndex: number): {
  anchorType: MarkerAnchorType;
  anchorText: string | null;
} {
  let fallbackAnchorText: string | null = null;

  for (let i = markerLineIndex - 1; i >= 0; i -= 1) {
    const currentLine = lines[i];
    if (currentLine.trim().length === 0) continue;
    const normalizedLine = normalizeAnchorText(currentLine);

    if (fallbackAnchorText === null) {
      fallbackAnchorText = normalizedLine;
    }
    if (MARKER_ANCHOR_CHECKLIST_RE.test(currentLine)) {
      return {
        anchorType: "checklist",
        anchorText: normalizedLine,
      };
    }
    if (MARKER_ANCHOR_HEADING_RE.test(currentLine)) {
      return {
        anchorType: "heading",
        anchorText: normalizedLine,
      };
    }
  }

  return {
    anchorType: "any",
    anchorText: fallbackAnchorText,
  };
}

function markerContentFromFollowingLine(lines: string[], markerLineIndex: number): string | null {
  for (let i = markerLineIndex + 1; i < lines.length; i += 1) {
    const currentLine = lines[i];
    const trimmed = currentLine.trim();
    if (trimmed.length === 0) continue;
    if (OBJECTIVE_DOD_MARKER_LINE_RE.test(trimmed)) continue;
    return normalizeAnchorText(currentLine);
  }
  return null;
}

function extractObjectiveMarkers(content: string): ObjectiveMarker[] {
  const lines = content.split("\n");
  const markers: ObjectiveMarker[] = [];

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const match = OBJECTIVE_DOD_MARKER_LINE_RE.exec(lines[lineIndex].trim());
    if (!match) continue;

    const dod = match[1].toUpperCase();
    const status = match[2].toLowerCase();
    const priority = match[3].toLowerCase();
    const { anchorType, anchorText } = markerAnchorFromOriginalLine(lines, lineIndex);
    const contentText = markerContentFromFollowingLine(lines, lineIndex);
    markers.push({
      markerLine: `<!-- dod:${dod} status:${status} priority:${priority} -->`,
      dod,
      status,
      priority,
      anchorType,
      anchorText,
      contentText: contentText ?? undefined,
    });
  }

  return markers;
}

function findMarkerAnchorIndex(lines: string[], marker: ObjectiveMarker): number {
  const dodToken = marker.dod.toLowerCase();
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!MARKER_ANCHOR_CHECKLIST_RE.test(line)) continue;
    if (line.toLowerCase().includes(dodToken)) {
      return i;
    }
  }

  if (marker.anchorText) {
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      if (marker.anchorType === "heading" && !MARKER_ANCHOR_HEADING_RE.test(line)) continue;
      if (marker.anchorType === "checklist" && !MARKER_ANCHOR_CHECKLIST_RE.test(line)) continue;
      if (normalizeAnchorText(line) === marker.anchorText) {
        return i;
      }
    }
  }

  return -1;
}

function reinsertObjectiveMarkers(originalContent: string, editedContent: string): string {
  const markers = extractObjectiveMarkers(originalContent);
  if (markers.length === 0) {
    return editedContent;
  }

  const hasTrailingNewLine = editedContent.endsWith("\n");
  const lines = editedContent
    .split("\n")
    .filter((line) => !OBJECTIVE_DOD_MARKER_LINE_RE.test(line.trim()));
  const insertionCountByAnchor = new Map<number, number>();

  for (const marker of markers) {
    const anchorIndex = findMarkerAnchorIndex(lines, marker);
    if (anchorIndex === -1) {
      lines.push(marker.markerLine);
      continue;
    }

    const insertionOffset = insertionCountByAnchor.get(anchorIndex) ?? 0;
    lines.splice(anchorIndex + 1 + insertionOffset, 0, marker.markerLine);
    insertionCountByAnchor.set(anchorIndex, insertionOffset + 1);
  }

  const merged = lines.join("\n");
  if (hasTrailingNewLine && !merged.endsWith("\n")) {
    return `${merged}\n`;
  }
  return merged;
}

function findObjectiveSectionDefinition(title: string): (typeof OBJECTIVE_SECTION_DEFINITIONS)[number] | null {
  const normalizedTitle = normalizeHeadingText(title);
  for (const definition of OBJECTIVE_SECTION_DEFINITIONS) {
    if (definition.aliases.some((alias) => normalizedTitle.includes(normalizeHeadingText(alias)))) {
      return definition;
    }
  }
  return null;
}

function extractObjectiveSections(content: string): ObjectiveParsedSection[] {
  const lines = content.split("\n");
  const headings: Array<{ title: string; lineIndex: number }> = [];

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const match = OBJECTIVE_L2_HEADING_RE.exec(lines[lineIndex]);
    if (!match) continue;
    headings.push({
      title: match[1].trim(),
      lineIndex,
    });
  }

  const sections: ObjectiveParsedSection[] = [];
  for (let headingIndex = 0; headingIndex < headings.length; headingIndex += 1) {
    const currentHeading = headings[headingIndex];
    const definition = findObjectiveSectionDefinition(currentHeading.title);
    if (!definition) continue;

    const startLine = currentHeading.lineIndex + 1;
    const endLine = headingIndex + 1 < headings.length ? headings[headingIndex + 1].lineIndex : lines.length;
    const sectionLines = trimSurroundingEmptyLines(lines.slice(startLine, endLine));
    if (sectionLines.length === 0) continue;

    sections.push({
      key: definition.key,
      title: currentHeading.title,
      content: sectionLines.join("\n"),
    });
  }

  return sections;
}

function parseObjectiveContent(content: string): ParsedObjective {
  const markers = extractObjectiveMarkers(content);
  return {
    dods: markers.map((marker) => ({
      dod: marker.dod,
      status: marker.status,
      priority: marker.priority,
      anchorText: marker.anchorText,
      contentText: marker.contentText,
    })),
    sections: extractObjectiveSections(content),
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
        ...result,
        sprint_id: sprintId,
      };
    }),
  );

  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectiveVersion = asNumberOrNull(objectiveMeta.version);
  const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
  const objectiveContent = await readTextFile(`${sessionDir}/${objectivePath}`);
  const parsedObjective = objectiveContent === null ? null : parseObjectiveContent(objectiveContent);
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
      parsed: parsedObjective,
    },
    links: links ?? null,
  });
});

projectAgileApi.get("/agile/sessions/:agiId/file", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  if (!isValidAgiId(agiId)) {
    return c.json({ error: "Invalid AGI id" }, 400);
  }

  const relativePath = c.req.query("path");
  if (!relativePath) {
    return c.json({ error: "path query parameter is required" }, 400);
  }
  const normalizedPath = relativePath.replace(/\\/g, "/");
  if (normalizedPath.includes("..")) {
    return c.json({ error: "Invalid path" }, 400);
  }

  const contentType = imageContentTypeFromPath(normalizedPath);
  if (!contentType) {
    return c.json({ error: "Unsupported file extension" }, 400);
  }

  const sessionDir = `${baseDir}/agile/${agiId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Session not found" }, 404);
  }

  const session = await readJsonFile<SessionJson>(`${sessionDir}/session.json`);
  if (!session) {
    return c.json({ error: "Session not found" }, 404);
  }

  const absolutePath = `${sessionDir}/${normalizedPath}`;
  try {
    const fileBytes = await Deno.readFile(absolutePath);
    return new Response(fileBytes, {
      status: 200,
      headers: {
        "Content-Type": contentType,
      },
    });
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) {
      return c.json({ error: "File not found" }, 404);
    }
    throw error;
  }
});

projectAgileApi.get("/agile/sessions/:agiId/objective/files", async (c) => {
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
  const objectivePath = (asStringOrNull(objectiveMeta.path) ?? "objective/objective.md").replace(/\\/g, "/");
  const objectiveDir = objectivePath.includes("/") ? objectivePath.slice(0, objectivePath.lastIndexOf("/")) : "objective";
  const detailsDir = `${sessionDir}/${objectiveDir}/details`;
  const detailFiles: string[] = [];

  try {
    for await (const entry of Deno.readDir(detailsDir)) {
      if (!entry.isFile || !entry.name.endsWith(".md")) continue;
      detailFiles.push(entry.name);
    }
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) {
      return c.json({ files: [] });
    }
    throw error;
  }

  detailFiles.sort((a, b) => a.localeCompare(b));
  return c.json({
    files: [
      { name: objectivePath.split("/").at(-1) ?? "objective.md", path: objectivePath, type: "root" },
      ...detailFiles.map((name) => ({
        name,
        path: `${objectiveDir}/details/${name}`,
        type: "detail",
      })),
    ],
  });
});

projectAgileApi.get("/agile/sessions/:agiId/objective/details/:filename", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  if (!isValidAgiId(agiId)) {
    return c.json({ error: "Invalid AGI id" }, 400);
  }

  const filename = c.req.param("filename");
  if (filename.includes("..") || filename.includes("/") || filename.includes("\\")) {
    return c.json({ error: "Invalid filename" }, 400);
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
  const objectivePath = (asStringOrNull(objectiveMeta.path) ?? "objective/objective.md").replace(/\\/g, "/");
  const objectiveDir = objectivePath.includes("/") ? objectivePath.slice(0, objectivePath.lastIndexOf("/")) : "objective";
  const detailPath = `${objectiveDir}/details/${filename}`;
  const content = await readTextFile(`${sessionDir}/${detailPath}`);
  if (content === null) {
    return c.json({ error: "Objective detail not found" }, 404);
  }

  return c.json({
    content,
    path: detailPath,
  });
});

projectAgileApi.get("/agile/sessions/:agiId/sprints/:sprintId/result-details/files", async (c) => {
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

  const sessionDir = `${baseDir}/agile/${agiId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Session not found" }, 404);
  }

  const session = await readJsonFile<SessionJson>(`${sessionDir}/session.json`);
  if (!session) {
    return c.json({ error: "Session not found" }, 404);
  }

  const resultDetailsDir = `${sessionDir}/sprints/${sprintId}/result-details`;
  const files: string[] = [];

  try {
    for await (const entry of Deno.readDir(resultDetailsDir)) {
      if (!entry.isFile || !entry.name.endsWith(".md")) continue;
      files.push(entry.name);
    }
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) {
      return c.json({ files: [] });
    }
    throw error;
  }

  files.sort((a, b) => a.localeCompare(b));
  return c.json({
    files: files.map((name) => ({
      name,
      path: `sprints/${sprintId}/result-details/${name}`,
    })),
  });
});

projectAgileApi.get("/agile/sessions/:agiId/sprints/:sprintId/result-details/:filename", async (c) => {
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

  const filename = c.req.param("filename");
  if (filename.includes("..") || filename.includes("/") || filename.includes("\\")) {
    return c.json({ error: "Invalid filename" }, 400);
  }

  const sessionDir = `${baseDir}/agile/${agiId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Session not found" }, 404);
  }

  const session = await readJsonFile<SessionJson>(`${sessionDir}/session.json`);
  if (!session) {
    return c.json({ error: "Session not found" }, 404);
  }

  const detailPath = `sprints/${sprintId}/result-details/${filename}`;
  const content = await readTextFile(`${sessionDir}/${detailPath}`);
  if (content === null) {
    return c.json({ error: "Result detail not found" }, 404);
  }

  return c.json({
    content,
    path: detailPath,
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
  const revision = content === null ? null : await objectiveRevisionFromContent(content);
  const parsed = content === null ? null : parseObjectiveContent(content);
  if (etag !== null) {
    c.header("ETag", etag);
  }

  return c.json({
    content,
    path: objectivePath,
    revision,
    parsed,
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

projectAgileApi.patch("/agile/:agiId/objective", async (c) => {
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

  let body: unknown;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  if (!isRecord(body) || typeof body.content !== "string") {
    return c.json({ error: "Content body must be a JSON object with string content" }, 400);
  }

  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
  const objectiveFile = `${sessionDir}/${objectivePath}`;
  const ifMatch = c.req.header("If-Match");
  const currentContent = await readTextFile(objectiveFile);
  if (currentContent === null) {
    return c.json({ error: "Objective not found" }, 404);
  }

  if (ifMatch) {
    const currentEtag = await objectiveEtagFromContent(currentContent);
    if (currentEtag === null || currentEtag !== ifMatch) {
      return c.json({ error: "Objective has been modified" }, 409);
    }
  }

  const mergedContent = reinsertObjectiveMarkers(currentContent, body.content);
  try {
    await Deno.writeTextFile(objectiveFile, mergedContent);
  } catch {
    return c.json({ error: "Failed to write objective" }, 500);
  }

  const revision = await toSha256Hex(mergedContent);
  const mtime = await objectiveMtimeFromFile(objectiveFile);
  const etag = await objectiveEtagFromContent(mergedContent);
  if (etag !== null) {
    c.header("ETag", etag);
  }

  return c.json({
    content: mergedContent,
    path: objectivePath,
    revision,
    mtime,
  });
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

  const revision = await objectiveRevisionFromContent(content);
  const mtime = await objectiveMtimeFromFile(objectiveFile);
  const parsed = parseObjectiveContent(content);
  return c.json({
    content,
    path: objectivePath,
    revision,
    mtime,
    parsed,
  });
});

projectAgileApi.patch("/agile/:agiId/objective", async (c) => {
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

  if (!isRecord(payload) || typeof payload.content !== "string" || typeof payload.baseRevision !== "string") {
    return c.json({ error: "content and baseRevision are required" }, 400);
  }

  const baseRevision = payload.baseRevision.trim();
  if (baseRevision.length === 0) {
    return c.json({ error: "baseRevision is required" }, 400);
  }

  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
  const objectiveFile = `${sessionDir}/${objectivePath}`;
  const currentContent = await readTextFile(objectiveFile);
  if (currentContent === null) {
    return c.json({ error: "Objective not found" }, 404);
  }

  const currentRevision = await objectiveRevisionFromContent(currentContent);
  if (baseRevision !== currentRevision) {
    return c.json({ error: "Objective has been modified", revision: currentRevision }, 409);
  }

  try {
    await Deno.writeTextFile(objectiveFile, payload.content);
  } catch {
    return c.json({ error: "Failed to write objective" }, 500);
  }

  const revision = await objectiveRevisionFromContent(payload.content);
  return c.json({ success: true, revision });
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

  const objectiveMeta = isRecord(session.objective) ? session.objective : {};
  const objectivePath = asStringOrNull(objectiveMeta.path) ?? "objective/objective.md";
  const objectiveContent = await readTextFile(`${sessionDir}/${objectivePath}`);
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
