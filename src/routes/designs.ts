import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { acquireLock, releaseLock } from "../core/concurrency.ts";
import type { DesignScreen, DesignSession } from "../types.ts";
import { dirExists, listDirs, readJsonFile, readTextFile, writeJsonFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

const projectDesignsApi = new Hono();
const SAFE_PATH_SEGMENT_PATTERN = /^[a-z0-9-]+$/;
const SCREEN_MD_FILE_PATTERN = /^screen-\d+\.md$/;
const SCREEN_MD_OR_HTML_FILE_PATTERN = /^screen-\d+\.(md|html)$/;
const NESTED_SCREEN_HTML_FILE_PATTERN = /^[a-z0-9-]+\.html$/;
const NESTED_SCREEN_HTML_PATH_PATTERN = /^screens\/([a-z0-9-]+)\.html$/;
const LOCAL_ORIGIN_PATTERN = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i;
const STITCH_SCREEN_NAME_PATTERN = /\/screens\/([^/]+)$/;
const STITCH_SCRIPT_PATH = new URL("../../scripts/stitch-sdk.mjs", import.meta.url).pathname;
const STITCH_CREATIVE_RANGES = new Set(["REFINE", "EXPLORE", "REIMAGINE"]);
const DEFAULT_SCREEN_HTML = "<html><body></body></html>";

type DesignEditMode = "edit" | "alt";
type DesignEditStatus = "started" | "completed" | "failed";

interface DesignEditVariantOptions {
  count: number;
  creative_range: string;
  aspects?: string[];
}

interface DesignEditPayload {
  prompt: string;
  mode: DesignEditMode;
  screen_id: string;
  variant_options?: DesignEditVariantOptions;
}

interface DesignEditJobContext {
  projectId?: string;
  desId: string;
  desDir: string;
  designPath: string;
  stitchProjectId: string;
  payload: DesignEditPayload;
  notifyUrl: string;
  jobId: string;
}

interface DesignRefreshJobContext {
  projectId?: string;
  desId: string;
  desDir: string;
  designPath: string;
  stitchProjectId: string;
  notifyUrl: string;
  jobId: string;
}

interface DesignRefreshResult {
  added_screen_ids: string[];
  removed_stitch_screen_ids: string[];
  refreshed_screen_ids: string[];
  failed_screen_ids: string[];
}

interface StitchCliEnvelope {
  ok?: boolean;
  data?: unknown;
  error?: {
    message?: string;
  };
}

interface StitchScreenArtifact {
  stitch_screen_id: string;
  title: string | null;
  url: string | null;
  image_url: string | null;
  html: unknown;
}

class RefreshConflictError extends Error {
  editingBy: string;

  constructor(editingBy: string) {
    super("Edit in progress");
    this.name = "RefreshConflictError";
    this.editingBy = editingBy;
  }
}

function isSafePathSegment(value: string): boolean {
  return SAFE_PATH_SEGMENT_PATTERN.test(value);
}

function isAllowedDesignOrigin(origin: string): boolean {
  const normalized = origin.toLowerCase();
  if (normalized.startsWith("chrome-extension://")) {
    return true;
  }

  return LOCAL_ORIGIN_PATTERN.test(normalized);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function normalizePositiveInt(value: unknown, fallback: number): number {
  const parsed = typeof value === "number"
    ? Math.floor(value)
    : Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

function normalizeCreativeRange(value: unknown): string {
  if (typeof value !== "string") {
    return "EXPLORE";
  }
  const normalized = value.trim().toUpperCase();
  return STITCH_CREATIVE_RANGES.has(normalized) ? normalized : "EXPLORE";
}

function normalizeAspects(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const aspects = value
    .filter((entry): entry is string => typeof entry === "string")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);

  return aspects.length > 0 ? aspects : undefined;
}

function normalizeDesignEditPayload(raw: unknown): DesignEditPayload | null {
  const body = asRecord(raw);
  if (!body) {
    return null;
  }

  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (prompt.length === 0) {
    return null;
  }

  const modeRaw = body.mode;
  if (modeRaw !== "edit" && modeRaw !== "alt") {
    return null;
  }

  const screenId = typeof body.screen_id === "string" ? body.screen_id.trim() : "";
  if (screenId.length === 0) {
    return null;
  }

  if (modeRaw === "edit") {
    return {
      prompt,
      mode: modeRaw,
      screen_id: screenId,
    };
  }

  const options = asRecord(body.variant_options) ?? {};
  return {
    prompt,
    mode: modeRaw,
    screen_id: screenId,
    variant_options: {
      count: normalizePositiveInt(options.count, 2),
      creative_range: normalizeCreativeRange(options.creative_range),
      aspects: normalizeAspects(options.aspects),
    },
  };
}

function decodeBytes(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes).trim();
}

function parseCliEnvelope(raw: string): StitchCliEnvelope | null {
  try {
    const parsed = JSON.parse(raw);
    return asRecord(parsed) as StitchCliEnvelope | null;
  } catch {
    return null;
  }
}

function extractCliError(raw: string): string {
  const parsed = parseCliEnvelope(raw);
  if (parsed?.error && typeof parsed.error.message === "string" && parsed.error.message.length > 0) {
    return parsed.error.message;
  }
  return raw || "stitch-sdk command failed";
}

function extractScreenIdFromName(name: string): string | null {
  const match = name.match(STITCH_SCREEN_NAME_PATTERN);
  return match?.[1] ?? null;
}

function extractScreenId(value: unknown): string | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  if (typeof record.name === "string") {
    const fromName = extractScreenIdFromName(record.name);
    if (fromName) {
      return fromName;
    }
  }

  if (typeof record.id === "string") {
    const normalized = record.id.trim();
    if (normalized.length === 0) {
      return null;
    }
    const fromName = extractScreenIdFromName(normalized);
    if (fromName) {
      return fromName;
    }
    if (/^[A-Za-z0-9_-]+$/.test(normalized)) {
      return normalized;
    }
  }

  return null;
}

function collectScreenIdsFromValue(value: unknown, ids: Set<string>): void {
  if (Array.isArray(value)) {
    for (const entry of value) {
      collectScreenIdsFromValue(entry, ids);
    }
    return;
  }

  const record = asRecord(value);
  if (!record) {
    return;
  }

  const maybeId = extractScreenId(record);
  if (maybeId) {
    ids.add(maybeId);
  }

  if (record.screen !== undefined) {
    collectScreenIdsFromValue(record.screen, ids);
  }
  if (record.screens !== undefined) {
    collectScreenIdsFromValue(record.screens, ids);
  }
  if (record.variants !== undefined) {
    collectScreenIdsFromValue(record.variants, ids);
  }
  if (record.result !== undefined) {
    collectScreenIdsFromValue(record.result, ids);
  }
}

function collectGeneratedScreenIds(data: unknown): string[] {
  const ids = new Set<string>();
  collectScreenIdsFromValue(data, ids);
  return [...ids];
}

function normalizeScreensPayload(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }
  const record = asRecord(value);
  if (!record) {
    return [];
  }
  return Array.isArray(record.screens) ? record.screens : [];
}

function toOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function extractDownloadUrl(value: unknown): string | null {
  if (typeof value === "string") {
    const normalized = value.trim();
    if (normalized.length === 0) {
      return null;
    }
    if (/^https?:\/\//i.test(normalized)) {
      return normalized;
    }
    try {
      return extractDownloadUrl(JSON.parse(normalized));
    } catch {
      return null;
    }
  }

  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const downloadUrl = record.downloadUrl;
  if (typeof downloadUrl !== "string") {
    return null;
  }

  const normalized = downloadUrl.trim();
  if (normalized.length === 0 || !/^https?:\/\//i.test(normalized)) {
    return null;
  }

  return normalized;
}

async function resolveArtifactHtmlContent(html: unknown, stitchScreenId: string): Promise<string> {
  const downloadUrl = extractDownloadUrl(html);
  if (!downloadUrl) {
    return typeof html === "string" && html.trim().length > 0 ? html : DEFAULT_SCREEN_HTML;
  }

  try {
    const response = await fetch(downloadUrl);
    if (!response.ok) {
      console.error(
        `[designs] Failed to fetch stitch html (screen: ${stitchScreenId}, status: ${response.status})`,
      );
      return DEFAULT_SCREEN_HTML;
    }

    const content = await response.text();
    return content.trim().length > 0 ? content : DEFAULT_SCREEN_HTML;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[designs] Failed to fetch stitch html (screen: ${stitchScreenId}): ${message}`);
    return DEFAULT_SCREEN_HTML;
  }
}

function buildDesignEditJobId(): string {
  const suffix = crypto.randomUUID().split("-")[0];
  return `job-${Date.now()}-${suffix}`;
}

function formatScreenBaseName(index: number): string {
  return `screen-${String(index).padStart(3, "0")}`;
}

function resolveScreenBaseName(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  if (/^screen-\d+$/.test(normalized)) {
    return normalized;
  }
  if (/^screen-\d+\.(md|html)$/.test(normalized)) {
    return normalized.replace(/\.(md|html)$/, "");
  }
  return null;
}

function resolveScreenHtmlFileName(screen: DesignScreen): string | null {
  if (typeof screen.html_file === "string" && /^screen-\d+\.html$/.test(screen.html_file)) {
    return screen.html_file;
  }
  const baseName = resolveScreenBaseName(screen.id);
  return baseName ? `${baseName}.html` : null;
}

function resolveScreenMarkdownFileName(screen: DesignScreen): string | null {
  const baseName = resolveScreenBaseName(screen.id);
  return baseName ? `${baseName}.md` : null;
}

function normalizeSafeScreenBase(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim().replace(/\.(md|html)$/, "");
  return normalized.length > 0 && isSafePathSegment(normalized) ? normalized : null;
}

function resolveScreenMdFileFromId(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  if (SCREEN_MD_FILE_PATTERN.test(normalized)) {
    return normalized;
  }
  if (/^screen-\d+\.html$/.test(normalized)) {
    return normalized.replace(/\.html$/, ".md");
  }
  if (/^screen-\d+$/.test(normalized)) {
    return `${normalized}.md`;
  }
  return null;
}

function normalizeNestedScreenHtmlPath(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  const match = normalized.match(NESTED_SCREEN_HTML_PATH_PATTERN);
  if (!match || !isSafePathSegment(match[1])) {
    return null;
  }
  return `screens/${match[1]}.html`;
}

function nestedScreenFileFromHtmlPath(htmlPath: string): string {
  return htmlPath.replace(/^screens\//, "");
}

function resolveNestedScreenBase(screen: DesignScreen, htmlPath: string): string | null {
  const record = screen as Record<string, unknown>;
  return normalizeSafeScreenBase(record.slug) ??
    normalizeSafeScreenBase(record.id) ??
    normalizeSafeScreenBase(nestedScreenFileFromHtmlPath(htmlPath));
}

function resolveNestedScreenHtmlPath(screen: DesignScreen): string | null {
  const record = screen as Record<string, unknown>;
  return normalizeNestedScreenHtmlPath(screen.html_file) ??
    normalizeNestedScreenHtmlPath(record.html);
}

function isSupportedScreenRequestFile(screenFile: string): boolean {
  return SCREEN_MD_OR_HTML_FILE_PATTERN.test(screenFile) ||
    NESTED_SCREEN_HTML_FILE_PATTERN.test(screenFile);
}

function resolveScreenHtmlFileFromSession(session: DesignSession, screenFile: string): string | null {
  if (SCREEN_MD_OR_HTML_FILE_PATTERN.test(screenFile)) {
    return screenFile.endsWith(".md") ? screenFile.replace(/\.md$/, ".html") : screenFile;
  }

  if (!NESTED_SCREEN_HTML_FILE_PATTERN.test(screenFile)) {
    return null;
  }

  const requestedBase = normalizeSafeScreenBase(screenFile);
  if (!requestedBase || !Array.isArray(session.screens)) {
    return null;
  }

  for (const screen of session.screens) {
    const htmlPath = resolveNestedScreenHtmlPath(screen);
    if (!htmlPath) {
      continue;
    }

    const base = resolveNestedScreenBase(screen, htmlPath);
    if (base === requestedBase) {
      return htmlPath;
    }
  }

  return null;
}

async function fileExists(path: string): Promise<boolean> {
  try {
    const stat = await Deno.stat(path);
    return stat.isFile;
  } catch {
    return false;
  }
}

function buildScreenMarkdown(
  localScreenId: string,
  stitchScreenId: string,
  parentScreenId: string,
  mode: DesignEditMode,
  prompt: string,
  generatedAt: string,
): string {
  return [
    `## ${localScreenId}`,
    "",
    `- stitch_screen_id: ${stitchScreenId}`,
    `- parent_screen_id: ${parentScreenId}`,
    `- mode: ${mode}`,
    `- generated_at: ${generatedAt}`,
    "",
    "### Prompt",
    "",
    prompt,
    "",
  ].join("\n");
}

function buildRefreshedScreenMarkdown(
  localScreenId: string,
  stitchScreenId: string,
  refreshedAt: string,
  imageUrl?: string | null,
): string {
  const lines = [
    `## ${localScreenId}`,
    "",
    `- stitch_screen_id: ${stitchScreenId}`,
    `- mode: refresh`,
    `- refreshed_at: ${refreshedAt}`,
  ];

  if (typeof imageUrl === "string" && imageUrl.trim().length > 0) {
    lines.push("", `![Screen image](${imageUrl.trim()})`);
  }

  lines.push(
    "",
    "### Note",
    "",
    "Synced from Stitch refresh.",
    "",
  );

  return lines.join("\n");
}

function syncScreenImageInMarkdown(content: string, imageUrl: string | null): string {
  const imagePattern = /!\[[^\]]*\]\(([^)]+)\)/;
  const normalizedImageUrl = typeof imageUrl === "string" ? imageUrl.trim() : "";

  if (normalizedImageUrl.length === 0) {
    if (!imagePattern.test(content)) {
      return content;
    }

    const removed = content
      .replace(imagePattern, "")
      .replace(/\n{3,}/g, "\n\n")
      .trimEnd();

    return removed.length > 0 ? `${removed}\n` : "";
  }

  const imageLine = `![Screen image](${normalizedImageUrl})`;
  if (imagePattern.test(content)) {
    return content.replace(imagePattern, imageLine);
  }

  const trimmed = content.trimEnd();
  if (trimmed.length === 0) {
    return `${imageLine}\n`;
  }

  return `${trimmed}\n\n${imageLine}\n`;
}

async function refreshScreenMarkdownFile(
  desDir: string,
  markdownFile: string,
  localScreenId: string,
  stitchScreenId: string,
  refreshedAt: string,
  imageUrl: string | null,
): Promise<void> {
  const markdownPath = `${desDir}/${markdownFile}`;
  const current = await readTextFile(markdownPath);
  if (current === null) {
    await Deno.writeTextFile(
      markdownPath,
      buildRefreshedScreenMarkdown(localScreenId, stitchScreenId, refreshedAt, imageUrl),
    );
    return;
  }

  const updated = syncScreenImageInMarkdown(current, imageUrl);
  if (updated !== current) {
    await Deno.writeTextFile(markdownPath, updated);
  }
}

async function runStitchCommand(command: string, args: string[]): Promise<unknown> {
  const output = await new Deno.Command("node", {
    args: [STITCH_SCRIPT_PATH, command, ...args],
    stdout: "piped",
    stderr: "piped",
  }).output();

  const stdout = decodeBytes(output.stdout);
  const stderr = decodeBytes(output.stderr);

  if (!output.success) {
    throw new Error(extractCliError(stderr || stdout));
  }

  const envelope = parseCliEnvelope(stdout);
  if (!envelope || envelope.ok !== true) {
    throw new Error(extractCliError(stderr || stdout));
  }

  return envelope.data;
}

async function listStitchScreenIds(projectId: string): Promise<Set<string>> {
  const data = await runStitchCommand("list-screens", ["--project-id", projectId]);
  const record = asRecord(data);
  if (!record) {
    return new Set();
  }

  const screens = normalizeScreensPayload(record.screens);
  const ids = new Set<string>();
  for (const screen of screens) {
    const id = extractScreenId(screen);
    if (id) {
      ids.add(id);
    }
  }
  return ids;
}

async function getStitchScreenArtifact(projectId: string, screenId: string): Promise<StitchScreenArtifact> {
  const data = await runStitchCommand("get-screen", [
    "--project-id",
    projectId,
    "--screen-id",
    screenId,
  ]);

  const root = asRecord(data);
  const screen = asRecord(root?.screen) ?? root ?? {};
  const raw = asRecord(screen.raw);

  return {
    stitch_screen_id: extractScreenId(screen) ?? screenId,
    title: toOptionalString(raw?.title),
    url: toOptionalString(raw?.url),
    image_url: toOptionalString(screen.image) ?? toOptionalString(raw?.image),
    html: screen.html ?? raw?.html ?? null,
  };
}

function asErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function nextScreenNumber(desDir: string): Promise<number> {
  let maxScreenNumber = 0;

  try {
    for await (const entry of Deno.readDir(desDir)) {
      if (!entry.isFile) {
        continue;
      }

      const match = entry.name.match(/^screen-(\d+)\.(md|html)$/);
      if (!match) {
        continue;
      }

      const parsed = Number.parseInt(match[1], 10);
      if (!Number.isNaN(parsed)) {
        maxScreenNumber = Math.max(maxScreenNumber, parsed);
      }
    }
  } catch {
    // ignore
  }

  return maxScreenNumber + 1;
}

async function postDesignEditStatus(
  notifyUrl: string,
  projectId: string | undefined,
  designId: string,
  jobId: string,
  status: DesignEditStatus,
  data: Record<string, unknown>,
): Promise<void> {
  const payload = {
    type: "design_edit_status",
    projectId,
    designId,
    data: {
      status,
      job_id: jobId,
      timestamp: new Date().toISOString(),
      ...data,
    },
  };

  try {
    await fetch(notifyUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch {
    // ignore notify failures
  }
}

async function clearEditingState(designPath: string): Promise<void> {
  const lock = await acquireLock(`${designPath}.lock`, 5_000);
  try {
    const current = await readJsonFile<DesignSession>(designPath);
    if (!current) {
      return;
    }
    await writeJsonFile(designPath, {
      ...current,
      editing_by: null,
      editing_at: new Date().toISOString(),
    });
  } finally {
    await releaseLock(lock);
  }
}

function buildStitchArgs(
  stitchProjectId: string,
  payload: DesignEditPayload,
): { command: "edit" | "variants"; args: string[] } {
  if (payload.mode === "edit") {
    return {
      command: "edit",
      args: [
        "--project-id",
        stitchProjectId,
        "--screen-id",
        payload.screen_id,
        "--prompt",
        payload.prompt,
      ],
    };
  }

  const args = [
    "--project-id",
    stitchProjectId,
    "--screen-id",
    payload.screen_id,
    "--prompt",
    payload.prompt,
    "--variant-count",
    String(payload.variant_options?.count ?? 2),
    "--creative-range",
    payload.variant_options?.creative_range ?? "EXPLORE",
  ];

  if (payload.variant_options?.aspects && payload.variant_options.aspects.length > 0) {
    args.push("--aspects", payload.variant_options.aspects.join(","));
  }

  return {
    command: "variants",
    args,
  };
}

async function runDesignRefreshJob(context: DesignRefreshJobContext): Promise<DesignRefreshResult> {
  const { projectId, desId, desDir, designPath, stitchProjectId, notifyUrl, jobId } = context;
  await postDesignEditStatus(notifyUrl, projectId, desId, jobId, "started", {
    mode: "refresh",
  });

  try {
    const remoteIds = [...await listStitchScreenIds(stitchProjectId)];
    const artifactEntries = await Promise.all(
      remoteIds.map(async (screenId) => {
        try {
          const artifact = await getStitchScreenArtifact(stitchProjectId, screenId);
          return [screenId, artifact, false] as const;
        } catch {
          return [screenId, null, true] as const;
        }
      }),
    );
    const failedScreenIds = artifactEntries
      .filter(([, , failed]) => failed)
      .map(([screenId]) => screenId);
    const failedScreenIdSet = new Set(failedScreenIds);
    const artifactsById = new Map<string, StitchScreenArtifact>(
      artifactEntries.flatMap(([screenId, artifact]) =>
        artifact ? [[screenId, artifact] as const] : []
      ),
    );
    const remoteIdSet = new Set(remoteIds);

    const lock = await acquireLock(`${designPath}.lock`, 5_000);
    let addedScreenIds: string[] = [];
    let removedStitchScreenIds: string[] = [];
    let refreshedScreenIds: string[] = [];
    let failedStitchScreenIds: string[] = [];
    try {
      const current = await readJsonFile<DesignSession>(designPath);
      if (!current) {
        throw new Error("Design not found");
      }
      if (typeof current.editing_by === "string" && current.editing_by.length > 0) {
        throw new RefreshConflictError(current.editing_by);
      }

      const existingScreens: DesignScreen[] = Array.isArray(current.screens) ? current.screens : [];
      const consumedRemoteIds = new Set<string>();
      const nextScreens: DesignScreen[] = [];
      const refreshedAt = new Date().toISOString();

      for (const screen of existingScreens) {
        const stitchId = typeof screen.stitch_screen_id === "string" ? screen.stitch_screen_id.trim() : "";
        if (!stitchId) {
          nextScreens.push(screen);
          continue;
        }
        if (!remoteIdSet.has(stitchId)) {
          removedStitchScreenIds.push(stitchId);
          continue;
        }

        consumedRemoteIds.add(stitchId);
        if (failedScreenIdSet.has(stitchId)) {
          nextScreens.push(screen);
          continue;
        }

        const artifact = artifactsById.get(stitchId);
        if (!artifact) {
          nextScreens.push(screen);
          continue;
        }

        const htmlFile = resolveScreenHtmlFileName(screen);
        const markdownFile = resolveScreenMarkdownFileName(screen);
        if (htmlFile) {
          const htmlContent = await resolveArtifactHtmlContent(artifact?.html, artifact.stitch_screen_id);
          await Deno.writeTextFile(`${desDir}/${htmlFile}`, htmlContent);
        }
        if (markdownFile) {
          await refreshScreenMarkdownFile(
            desDir,
            markdownFile,
            resolveScreenBaseName(screen.id) ?? screen.id,
            artifact.stitch_screen_id,
            refreshedAt,
            artifact.image_url ?? screen.image_url ?? null,
          );
        }

        refreshedScreenIds.push(screen.id);
        nextScreens.push({
          ...screen,
          stitch_screen_id: artifact.stitch_screen_id,
          title: artifact.title ?? screen.title,
          url: artifact.url ?? screen.url,
          image_url: artifact.image_url ?? screen.image_url ?? null,
          html_file: htmlFile ?? screen.html_file ?? null,
        });
      }

      let nextNumber = await nextScreenNumber(desDir);
      for (const stitchId of remoteIds) {
        if (consumedRemoteIds.has(stitchId)) {
          continue;
        }
        if (failedScreenIdSet.has(stitchId)) {
          continue;
        }

        const artifact = artifactsById.get(stitchId);
        if (!artifact) {
          continue;
        }

        const screenBase = formatScreenBaseName(nextNumber);
        nextNumber += 1;
        const mdFile = `${screenBase}.md`;
        const htmlFile = `${screenBase}.html`;
        const htmlContent = await resolveArtifactHtmlContent(artifact.html, artifact.stitch_screen_id);

        await Deno.writeTextFile(
          `${desDir}/${mdFile}`,
          buildRefreshedScreenMarkdown(screenBase, artifact.stitch_screen_id, refreshedAt, artifact.image_url),
        );
        await Deno.writeTextFile(`${desDir}/${htmlFile}`, htmlContent);

        nextScreens.push({
          id: screenBase,
          stitch_screen_id: artifact.stitch_screen_id,
          title: artifact.title ?? screenBase,
          url: artifact.url ?? undefined,
          image_url: artifact.image_url,
          html_file: htmlFile,
          created_at: refreshedAt,
          status: "done",
        });
        addedScreenIds.push(screenBase);
        refreshedScreenIds.push(screenBase);
      }

      const updated: DesignSession = {
        ...current,
        id: current.id || desId,
        screens: nextScreens,
        editing_by: current.editing_by ?? null,
        editing_at: current.editing_at ?? null,
      };
      const saved = await writeJsonFile(designPath, updated);
      if (!saved) {
        throw new Error("Failed to update design.json");
      }

      addedScreenIds = [...new Set(addedScreenIds)];
      removedStitchScreenIds = [...new Set(removedStitchScreenIds)];
      refreshedScreenIds = [...new Set(refreshedScreenIds)];
      failedStitchScreenIds = [...new Set(failedScreenIds)];
    } finally {
      await releaseLock(lock);
    }

    await postDesignEditStatus(notifyUrl, projectId, desId, jobId, "completed", {
      mode: "refresh",
      added_count: addedScreenIds.length,
      removed_count: removedStitchScreenIds.length,
      refreshed_count: refreshedScreenIds.length,
      screen_ids: refreshedScreenIds,
      added_screen_ids: addedScreenIds,
      removed_stitch_screen_ids: removedStitchScreenIds,
      failed_count: failedStitchScreenIds.length,
      failed_screen_ids: failedStitchScreenIds,
    });

    return {
      added_screen_ids: addedScreenIds,
      removed_stitch_screen_ids: removedStitchScreenIds,
      refreshed_screen_ids: refreshedScreenIds,
      failed_screen_ids: failedStitchScreenIds,
    };
  } catch (error) {
    await postDesignEditStatus(notifyUrl, projectId, desId, jobId, "failed", {
      mode: "refresh",
      error: asErrorMessage(error),
    });
    throw error;
  }
}

async function runDesignEditJob(context: DesignEditJobContext): Promise<void> {
  const { projectId, desId, desDir, designPath, stitchProjectId, payload, notifyUrl, jobId } = context;
  await postDesignEditStatus(notifyUrl, projectId, desId, jobId, "started", {
    mode: payload.mode,
    screen_id: payload.screen_id,
  });

  try {
    const beforeIds = await listStitchScreenIds(stitchProjectId);
    const stitchArgs = buildStitchArgs(stitchProjectId, payload);
    const commandData = await runStitchCommand(stitchArgs.command, stitchArgs.args);

    let generatedIds = collectGeneratedScreenIds(commandData);
    if (generatedIds.length === 0) {
      const afterIds = await listStitchScreenIds(stitchProjectId);
      generatedIds = [...afterIds].filter((id) => !beforeIds.has(id));
    }

    generatedIds = [...new Set(generatedIds)];
    if (generatedIds.length === 0) {
      throw new Error("Generated screens were not detected");
    }

    const artifacts = await Promise.all(
      generatedIds.map(async (id) => {
        try {
          return await getStitchScreenArtifact(stitchProjectId, id);
        } catch {
          return {
            stitch_screen_id: id,
            title: null,
            url: null,
            image_url: null,
            html: null,
          } as StitchScreenArtifact;
        }
      }),
    );

    const lock = await acquireLock(`${designPath}.lock`, 5_000);
    let localScreenIds: string[] = [];
    try {
      const current = await readJsonFile<DesignSession>(designPath);
      if (!current) {
        throw new Error("Design not found");
      }

      const existingScreens: DesignScreen[] = Array.isArray(current.screens) ? current.screens : [];
      const appendedScreens: DesignScreen[] = [];
      let nextNumber = await nextScreenNumber(desDir);
      const createdAt = new Date().toISOString();

      for (const artifact of artifacts) {
        const screenBase = formatScreenBaseName(nextNumber);
        nextNumber += 1;

        const mdFile = `${screenBase}.md`;
        const htmlFile = `${screenBase}.html`;
        const htmlContent = await resolveArtifactHtmlContent(artifact.html, artifact.stitch_screen_id);

        await Deno.writeTextFile(`${desDir}/${mdFile}`, buildScreenMarkdown(
          screenBase,
          artifact.stitch_screen_id,
          payload.screen_id,
          payload.mode,
          payload.prompt,
          createdAt,
        ));
        await Deno.writeTextFile(`${desDir}/${htmlFile}`, htmlContent);

        appendedScreens.push({
          id: screenBase,
          stitch_screen_id: artifact.stitch_screen_id,
          title: artifact.title ?? screenBase,
          url: artifact.url ?? undefined,
          image_url: artifact.image_url,
          html_file: htmlFile,
          parent_screen_id: payload.screen_id,
          created_at: createdAt,
          status: "done",
        });
      }

      localScreenIds = appendedScreens.map((screen) => screen.id);
      const updated: DesignSession = {
        ...current,
        id: current.id || desId,
        screens: [...existingScreens, ...appendedScreens],
        editing_by: null,
        editing_at: new Date().toISOString(),
      };

      const saved = await writeJsonFile(designPath, updated);
      if (!saved) {
        throw new Error("Failed to update design.json");
      }
    } finally {
      await releaseLock(lock);
    }

    await postDesignEditStatus(notifyUrl, projectId, desId, jobId, "completed", {
      mode: payload.mode,
      screen_count: localScreenIds.length,
      screen_ids: localScreenIds,
    });
  } catch (error) {
    await clearEditingState(designPath);
    await postDesignEditStatus(notifyUrl, projectId, desId, jobId, "failed", {
      mode: payload.mode,
      error: asErrorMessage(error),
    });
  }
}

async function listScreenMdFiles(dirPath: string): Promise<string[]> {
  const screenFiles: string[] = [];
  try {
    for await (const entry of Deno.readDir(dirPath)) {
      if (entry.isFile && SCREEN_MD_FILE_PATTERN.test(entry.name)) {
        screenFiles.push(entry.name);
      }
    }
  } catch (_error) {
    // ignore
  }
  screenFiles.sort();
  return screenFiles;
}

projectDesignsApi.get("/designs", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const designsDir = `${baseDir}/designs`;
  const plansDir = `${baseDir}/plans`;
  if (!(await dirExists(designsDir)) && !(await dirExists(plansDir))) {
    return c.json([]);
  }

  const desDirs = (await listDirs(designsDir)).filter((d) => /^DES-/.test(d));
  const results = await Promise.all(
    desDirs.map(async (dir) => {
      const json = await readJsonFile<DesignSession>(`${designsDir}/${dir}/design.json`);
      if (!json) {
        return null;
      }
      return { ...json, id: json.id || dir };
    }),
  );

  const sessions = results.filter((s): s is NonNullable<typeof s> => s !== null);
  const planDirs = (await listDirs(plansDir)).filter((d) => /^PLN-/.test(d));
  const legacyPlans = await Promise.all(
    planDirs.map(async (dir) => {
      const json = await readJsonFile<{ title?: string; created_at?: string; linked_designs?: unknown }>(
        `${plansDir}/${dir}/plan.json`,
      );
      if (!json) return null;
      if (Array.isArray(json.linked_designs) && json.linked_designs.length > 0) return null;

      try {
        const stat = await Deno.stat(`${plansDir}/${dir}/design.md`);
        if (!stat.isFile) return null;
      } catch (_error) {
        return null;
      }

      return {
        id: dir,
        title: json.title,
        status: "plan_design",
        created_at: json.created_at,
        linked_plan: dir,
        source: "plan_design",
      };
    }),
  );

  const planSessions = legacyPlans.filter((s): s is NonNullable<typeof s> => s !== null);

  const merged = [...sessions, ...planSessions];
  merged.sort((a, b) => {
    const aTime = a.created_at;
    const bTime = b.created_at;
    if (!aTime && !bTime) return 0;
    if (!aTime) return 1;
    if (!bTime) return -1;
    return bTime.localeCompare(aTime);
  });

  return c.json(merged);
});

projectDesignsApi.get("/designs/design-system", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const content = await readTextFile(`${baseDir}/designs/DESIGN.md`);
  if (content === null) {
    return c.json({ exists: false, content: null });
  }

  return c.json({ exists: true, content });
});

projectDesignsApi.post("/designs/:desId/edit", async (c) => {
  const projectId = c.req.param("projectId");
  const baseDir = resolveBaseDir(projectId);
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const origin = c.req.header("Origin");
  if (origin && !isAllowedDesignOrigin(origin)) {
    return c.json({ error: "Invalid origin" }, 403);
  }

  const desId = c.req.param("desId");
  if (!/^DES-\d+$/.test(desId)) {
    return c.json({ error: "Invalid design ID" }, 400);
  }

  let rawBody: unknown;
  try {
    rawBody = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  const payload = normalizeDesignEditPayload(rawBody);
  if (!payload) {
    return c.json({ error: "Invalid edit payload" }, 400);
  }

  const desDir = `${baseDir}/designs/${desId}`;
  if (!(await dirExists(desDir))) {
    return c.json({ error: "Design not found" }, 404);
  }

  const designPath = `${desDir}/design.json`;
  const lock = await acquireLock(`${designPath}.lock`, 5_000);
  let stitchProjectId = "";
  try {
    const current = await readJsonFile<DesignSession>(designPath);
    if (!current) {
      return c.json({ error: "Design not found" }, 404);
    }

    if (typeof current.editing_by === "string" && current.editing_by.length > 0) {
      return c.json({
        error: "Edit in progress",
        editing_by: current.editing_by,
      }, 409);
    }

    const resolvedStitchProjectId = typeof current.stitch_project_id === "string"
      ? current.stitch_project_id.trim()
      : "";
    if (!resolvedStitchProjectId) {
      return c.json({ error: "stitch_project_id not configured" }, 400);
    }

    const nextRevision = typeof current.revision === "number" && Number.isFinite(current.revision)
      ? current.revision + 1
      : 1;
    const saved = await writeJsonFile(designPath, {
      ...current,
      revision: nextRevision,
      editing_by: "dashboard",
      editing_at: new Date().toISOString(),
    });
    if (!saved) {
      return c.json({ error: "Failed to update design lock" }, 500);
    }

    stitchProjectId = resolvedStitchProjectId;
  } finally {
    await releaseLock(lock);
  }

  if (!stitchProjectId) {
    return c.json({ error: "stitch_project_id not configured" }, 400);
  }

  const notifyUrl = `${new URL(c.req.url).origin}/notify`;
  const jobId = buildDesignEditJobId();

  queueMicrotask(() => {
    void runDesignEditJob({
      projectId,
      desId,
      desDir,
      designPath,
      stitchProjectId,
      payload,
      notifyUrl,
      jobId,
    });
  });

  return c.json({ job_id: jobId, status: "queued" }, 202);
});

projectDesignsApi.get("/designs/:desId/refresh", async (c) => {
  const projectId = c.req.param("projectId");
  const baseDir = resolveBaseDir(projectId);
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const origin = c.req.header("Origin");
  if (origin && !isAllowedDesignOrigin(origin)) {
    return c.json({ error: "Invalid origin" }, 403);
  }

  const desId = c.req.param("desId");
  if (!/^DES-\d+$/.test(desId)) {
    return c.json({ error: "Invalid design ID" }, 400);
  }

  const desDir = `${baseDir}/designs/${desId}`;
  if (!(await dirExists(desDir))) {
    return c.json({ error: "Design not found" }, 404);
  }

  const designPath = `${desDir}/design.json`;
  const lock = await acquireLock(`${designPath}.lock`, 5_000);
  let stitchProjectId = "";
  try {
    const current = await readJsonFile<DesignSession>(designPath);
    if (!current) {
      return c.json({ error: "Design not found" }, 404);
    }

    if (typeof current.editing_by === "string" && current.editing_by.length > 0) {
      return c.json({
        error: "Edit in progress",
        editing_by: current.editing_by,
      }, 409);
    }

    stitchProjectId = typeof current.stitch_project_id === "string"
      ? current.stitch_project_id.trim()
      : "";
  } finally {
    await releaseLock(lock);
  }
  if (!stitchProjectId) {
    return c.json({ error: "Stitch 프로젝트가 연결되지 않았습니다" }, 422);
  }

  const notifyUrl = `${new URL(c.req.url).origin}/notify`;
  const jobId = buildDesignEditJobId();

  try {
    const result = await runDesignRefreshJob({
      projectId,
      desId,
      desDir,
      designPath,
      stitchProjectId,
      notifyUrl,
      jobId,
    });

    return c.json({
      ok: true,
      job_id: jobId,
      ...result,
    });
  } catch (error) {
    if (error instanceof RefreshConflictError) {
      return c.json({
        ok: false,
        job_id: jobId,
        error: error.message,
        editing_by: error.editingBy,
      }, 409);
    }
    return c.json({
      ok: false,
      job_id: jobId,
      error: asErrorMessage(error),
    }, 500);
  }
});

projectDesignsApi.get("/designs/:desId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const desId = c.req.param("desId");
  if (/^PLN-/.test(desId)) {
    const planJson = await readJsonFile<{ title?: string; created_at?: string }>(
      `${baseDir}/plans/${desId}/plan.json`,
    );
    if (!planJson) {
      return c.json({ error: "Design not found" }, 404);
    }

    const content = await readTextFile(`${baseDir}/plans/${desId}/design.md`);
    if (content === null) {
      return c.json({ error: "Design not found" }, 404);
    }

    return c.json({
      id: desId,
      title: planJson.title,
      status: "plan_design",
      plan_design: true,
      design_content: content,
      created_at: planJson.created_at,
    });
  }

  const desDir = `${baseDir}/designs/${desId}`;
  if (!(await dirExists(desDir))) {
    return c.json({ error: "Design not found" }, 404);
  }

  const json = await readJsonFile<DesignSession>(`${desDir}/design.json`);
  if (!json) {
    return c.json({ error: "Design not found" }, 404);
  }

  const screenFiles = await listScreenMdFiles(desDir);
  const screenFilesSet = new Set(screenFiles);

  const screenHtmlFiles: Record<string, string> = {};
  for (const mdFile of screenFiles) {
    const htmlFile = mdFile.replace(/\.md$/, ".html");
    try {
      const stat = await Deno.stat(`${desDir}/${htmlFile}`);
      if (stat.isFile) {
        screenHtmlFiles[mdFile] = htmlFile;
      }
    } catch (_error) {
      // ignore missing .html files
    }
  }

  let screens = json.screens;
  if (Array.isArray(json.screens)) {
    const normalizedScreens: DesignScreen[] = [];
    for (const screen of json.screens) {
      const existingHtmlFile = typeof screen.html_file === "string" && screen.html_file.length > 0
        ? screen.html_file
        : null;
      const screenMdFile = resolveScreenMdFileFromId((screen as Record<string, unknown>).id);

      if (existingHtmlFile && screenMdFile && screenFilesSet.has(screenMdFile)) {
        screenHtmlFiles[screenMdFile] = existingHtmlFile;
        normalizedScreens.push(screen);
        continue;
      }

      if (screenMdFile) {
        const detectedHtmlFile = screenHtmlFiles[screenMdFile];
        if (detectedHtmlFile) {
          normalizedScreens.push({ ...screen, html_file: detectedHtmlFile });
          continue;
        }
      }

      const nestedHtmlPath = resolveNestedScreenHtmlPath(screen);
      if (nestedHtmlPath && await fileExists(`${desDir}/${nestedHtmlPath}`)) {
        const nestedBase = resolveNestedScreenBase(screen, nestedHtmlPath);
        if (nestedBase) {
          const nestedScreenFile = `${nestedBase}.html`;
          if (!screenFilesSet.has(nestedScreenFile)) {
            screenFilesSet.add(nestedScreenFile);
            screenFiles.push(nestedScreenFile);
          }
          screenHtmlFiles[nestedScreenFile] = nestedHtmlPath;
          normalizedScreens.push({
            ...screen,
            id: normalizeSafeScreenBase((screen as Record<string, unknown>).id) ?? nestedBase,
            html_file: nestedHtmlPath,
          });
          continue;
        }
      }

      normalizedScreens.push(screen);
    }
    screens = normalizedScreens;
  }

  const response = {
    ...json,
    id: json.id || desId,
    screens,
    screen_files: screenFiles,
    screen_html_files: screenHtmlFiles,
  };

  const stylesDir = `${desDir}/styles`;
  const hasStyles = await dirExists(stylesDir);
  if (hasStyles) {
    const styleDirs = (await listDirs(stylesDir)).filter((dir) => isSafePathSegment(dir));
    const normalizedScreens = Array.isArray(response.screens)
      ? await Promise.all(response.screens.map(async (screen) => {
        const currentStyle = typeof screen.style === "string" ? screen.style : null;
        const htmlFile = typeof screen.html_file === "string" ? screen.html_file : null;

        if (!htmlFile && typeof currentStyle === "string" && isSafePathSegment(currentStyle)) {
          const screenId = (screen.id as string).replace(/\.md$/, "");
          if (isSafePathSegment(screenId)) {
            const candidatePath = `${stylesDir}/${currentStyle}/${screenId}.html`;
            try {
              const stat = await Deno.stat(candidatePath);
              if (stat.isFile) {
                return { ...screen, html_file: `styles/${currentStyle}/${screenId}.html` };
              }
            } catch (_error) {
              // ignore missing fallback html file
            }
          }
        }

        if (!currentStyle || isSafePathSegment(currentStyle)) {
          return screen;
        }

        if (!htmlFile) {
          return screen;
        }

        const styleMatch = `/${htmlFile}`.match(/\/styles\/([^/]+)\//);
        const extractedStyle = styleMatch?.[1];
        if (!extractedStyle || !isSafePathSegment(extractedStyle)) {
          return screen;
        }

        return {
          ...screen,
          style: extractedStyle,
        };
      }))
      : response.screens;

    return c.json({
      ...response,
      screens: normalizedScreens,
      has_styles: true,
      style_dirs: styleDirs,
    });
  }

  return c.json(response);
});

projectDesignsApi.get("/designs/:desId/styles/:styleName/screens", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const desId = c.req.param("desId");
  if (!/^(DES-\d+|PLN-\d+)$/.test(desId)) {
    return c.json({ error: "Invalid design ID" }, 400);
  }

  const styleName = c.req.param("styleName");
  if (!isSafePathSegment(styleName)) {
    return c.json({ error: "Invalid style name" }, 400);
  }

  const styleDir = `${baseDir}/designs/${desId}/styles/${styleName}`;
  if (!(await dirExists(styleDir))) {
    return c.json({ error: "Style not found" }, 404);
  }

  const screenFiles = await listScreenMdFiles(styleDir);
  return c.json({ screen_files: screenFiles });
});

projectDesignsApi.get("/designs/:desId/styles/:styleName/screens/:screenFile", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const desId = c.req.param("desId");
  if (!/^(DES-\d+|PLN-\d+)$/.test(desId)) {
    return c.json({ error: "Invalid design ID" }, 400);
  }

  const styleName = c.req.param("styleName");
  if (!isSafePathSegment(styleName)) {
    return c.json({ error: "Invalid style name" }, 400);
  }

  const screenFile = c.req.param("screenFile");
  if (!SCREEN_MD_FILE_PATTERN.test(screenFile)) {
    return c.json({ error: "Invalid screen file" }, 400);
  }

  const content = await readTextFile(`${baseDir}/designs/${desId}/styles/${styleName}/${screenFile}`);
  if (content === null) {
    return c.json({ exists: false, content: null });
  }
  return c.json({ exists: true, content });
});

projectDesignsApi.get("/designs/:desId/styles/:styleName/screens/:screenFile/html", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const desId = c.req.param("desId");
  if (!/^(DES-\d+|PLN-\d+)$/.test(desId)) {
    return c.json({ error: "Invalid design ID" }, 400);
  }

  const styleName = c.req.param("styleName");
  if (!isSafePathSegment(styleName)) {
    return c.json({ error: "Invalid style name" }, 400);
  }

  const screenFile = c.req.param("screenFile");
  if (!SCREEN_MD_OR_HTML_FILE_PATTERN.test(screenFile)) {
    return c.json({ error: "Invalid screen file" }, 400);
  }

  const htmlFile = screenFile.endsWith(".md")
    ? screenFile.replace(/\.md$/, ".html")
    : screenFile;
  const content = await readTextFile(`${baseDir}/designs/${desId}/styles/${styleName}/${htmlFile}`);
  if (content === null) {
    return c.html("<html><body></body></html>", 404);
  }
  const htmlContent = extractDownloadUrl(content)
    ? await resolveArtifactHtmlContent(content, htmlFile)
    : content;
  return c.html(htmlContent);
});

projectDesignsApi.get("/designs/:desId/screens/:screenFile", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const desId = c.req.param("desId");
  if (!/^(DES-\d+|PLN-\d+)$/.test(desId)) {
    return c.json({ error: "Invalid design ID" }, 400);
  }

  const screenFile = c.req.param("screenFile");
  if (!SCREEN_MD_FILE_PATTERN.test(screenFile)) {
    if (NESTED_SCREEN_HTML_FILE_PATTERN.test(screenFile)) {
      return c.json({ exists: false, content: null });
    }
    return c.json({ error: "Invalid screen file" }, 400);
  }

  const content = await readTextFile(`${baseDir}/designs/${desId}/${screenFile}`);
  if (content === null) {
    return c.json({ exists: false, content: null });
  }
  return c.json({ exists: true, content });
});

projectDesignsApi.get("/designs/:desId/screens/:screenFile/html", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const desId = c.req.param("desId");
  if (!/^(DES-\d+|PLN-\d+)$/.test(desId)) {
    return c.json({ error: "Invalid design ID" }, 400);
  }

  const screenFile = c.req.param("screenFile");
  if (!isSupportedScreenRequestFile(screenFile)) {
    return c.json({ error: "Invalid screen file" }, 400);
  }

  let htmlFile: string | null = null;
  if (SCREEN_MD_OR_HTML_FILE_PATTERN.test(screenFile)) {
    htmlFile = screenFile.endsWith(".md")
      ? screenFile.replace(/\.md$/, ".html")
      : screenFile;
  } else {
    const session = await readJsonFile<DesignSession>(`${baseDir}/designs/${desId}/design.json`);
    htmlFile = session ? resolveScreenHtmlFileFromSession(session, screenFile) : null;
  }

  if (!htmlFile) {
    return c.html("<html><body></body></html>", 404);
  }

  const content = await readTextFile(`${baseDir}/designs/${desId}/${htmlFile}`);
  if (content === null) {
    return c.html("<html><body></body></html>", 404);
  }
  const htmlContent = extractDownloadUrl(content)
    ? await resolveArtifactHtmlContent(content, htmlFile)
    : content;
  return c.html(htmlContent);
});

export { projectDesignsApi };
