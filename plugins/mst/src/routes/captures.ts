import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { atomicWriteJSON, acquireLock, releaseLock } from "../core/concurrency.ts";
import type { CaptureCreatePayload, CaptureMeta, CaptureUpdatePayload } from "../types.ts";
import { dirExists, listDirs, readJsonFile, writeJsonFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

type CaptureStatus = CaptureMeta["status"];
type CaptureStatusUpdate = CaptureUpdatePayload["status"];

type StatusFilterParseResult = { type: "none" } | {
  type: "value";
  value: CaptureStatus;
} | { type: "invalid" };

const projectCapturesApi = new Hono();

function isInvalidPathPart(value: string): boolean {
  return !value || value.includes("..") || value.includes("/") || value.includes("\\");
}

function isAllowedCaptureOrigin(origin: string): boolean {
  const normalized = origin.toLowerCase();
  if (normalized.startsWith("chrome-extension://")) {
    return true;
  }

  return /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(normalized);
}

function isSupportedStatus(value: unknown): value is CaptureStatus {
  return value === "pending" || value === "selected" || value === "consumed" || value === "done" ||
    value === "cancelled" || value === "archived";
}

function isSupportedStatusForUpdate(value: unknown): value is CaptureStatusUpdate {
  return value === "pending" || value === "selected" || value === "consumed" || value === "done" ||
    value === "cancelled";
}

function canTransitionStatus(from: CaptureStatus, to: CaptureStatus): boolean {
  if (from === to) return true;

  return (
    (from === "pending" && to === "selected") ||
    (from === "pending" && to === "cancelled") ||
    (from === "selected" && to === "consumed") ||
    (from === "consumed" && to === "done") ||
    (from === "consumed" && to === "cancelled")
  );
}

function normalizeCaptureCreatePayload(raw: unknown): CaptureCreatePayload | null {
  if (!raw || typeof raw !== "object") return null;

  const body = raw as Record<string, unknown>;

  const url = typeof body.url === "string" ? body.url.trim() : "";
  if (url.length === 0) return null;

  const selector = typeof body.selector === "string" ? body.selector : "";
  const cssPath = typeof body.css_path === "string" ? body.css_path : "";
  const memo = typeof body.memo === "string" ? body.memo : "";
  const rect = normalizeRect(body.rect);
  const htmlSnapshot = typeof body.html_snapshot === "string" ? body.html_snapshot : null;
  const componentName = typeof body.component_name === "string" ? body.component_name : null;
  const sourcePath = typeof body.source_path === "string" ? body.source_path : null;
  const screenshotData = typeof body.screenshot_data === "string" ? body.screenshot_data : null;
  const mode = body.mode === "batch" ? "batch" : "immediate";
  const tags = normalizeTags(body.tags);

  return {
    url,
    selector,
    css_path: cssPath,
    rect,
    html_snapshot: htmlSnapshot,
    screenshot_data: screenshotData,
    memo,
    tags,
    mode,
    component_name: componentName,
    source_path: sourcePath,
  };
}

function normalizeTags(raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    return [];
  }

  return raw
    .filter((tag): tag is string => typeof tag === "string")
    .map((tag) => tag.trim())
    .filter((tag) => tag.length > 0);
}

function normalizeRect(raw: unknown): CaptureCreatePayload["rect"] {
  if (!raw || typeof raw !== "object") return null;

  const rect = raw as Record<string, unknown>;
  const x = Number(rect.x);
  const y = Number(rect.y);
  const width = Number(rect.width);
  const height = Number(rect.height);

  if ([x, y, width, height].some((value) => Number.isNaN(value))) {
    return null;
  }

  return {
    x,
    y,
    width,
    height,
  };
}

function normalizeScreenshotData(raw: string | null): string | null {
  if (typeof raw !== "string") {
    return null;
  }

  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function extractBase64Payload(raw: string): string {
  if (!raw.startsWith("data:")) {
    return raw;
  }

  const commaIndex = raw.indexOf(",");
  if (commaIndex < 0) {
    return "";
  }

  return raw.slice(commaIndex + 1);
}

function decodeBase64ToBytes(raw: string): Uint8Array {
  const normalized = raw.replace(/\s+/g, "");
  if (normalized.length === 0) {
    throw new Error("Empty screenshot data");
  }
  const binary = atob(normalized);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function parseStatusFilter(raw: string | undefined): StatusFilterParseResult {
  if (raw === undefined) {
    return { type: "none" };
  }

  const normalized = raw.trim();
  if (normalized.length === 0) {
    return { type: "none" };
  }

  if (!isSupportedStatus(normalized)) {
    return { type: "invalid" };
  }

  return { type: "value", value: normalized };
}

function formatCaptureId(nextId: number): string {
  return nextId < 1000 ? `CAP-${String(nextId).padStart(3, "0")}` : `CAP-${nextId}`;
}

async function scanMaxCaptureId(capturesDir: string): Promise<number> {
  let maxId = 0;
  try {
    const dirs = await listDirs(capturesDir);
    for (const dir of dirs) {
      const match = dir.match(/^CAP-(\d+)$/);
      if (!match) {
        continue;
      }
      const parsed = Number.parseInt(match[1], 10);
      if (!Number.isNaN(parsed)) {
        maxId = Math.max(maxId, parsed);
      }
    }
  } catch {
    // ignore
  }
  return maxId;
}

async function nextCaptureId(capturesDir: string): Promise<string> {
  const counterPath = `${capturesDir}/counter.json`;
  const lockPath = `${counterPath}.lock`;

  const lock = await acquireLock(lockPath, 5_000);
  try {
    let lastId = 0;
    const counter = await readJsonFile<{ last_id?: unknown }>(counterPath);
    if (typeof counter?.last_id === "number" && Number.isFinite(counter.last_id)) {
      lastId = counter.last_id;
    } else {
      lastId = await scanMaxCaptureId(capturesDir);
    }

    const nextId = lastId + 1;
    await atomicWriteJSON(counterPath, { last_id: nextId });
    return formatCaptureId(nextId);
  } finally {
    await releaseLock(lock);
  }
}

projectCapturesApi.use(async (c, next) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const origin = c.req.header("Origin");
  if (origin && !isAllowedCaptureOrigin(origin)) {
    return c.json({ error: "Invalid origin" }, 403);
  }

  return next();
});

projectCapturesApi.get("/captures", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  const capturesDir = `${baseDir}/captures`;

  const rawStatus = c.req.query("status");
  const parsedStatus = parseStatusFilter(rawStatus);
  if (parsedStatus.type === "invalid") {
    return c.json({ error: "Invalid status query" }, 400);
  }

  if (!(await dirExists(capturesDir))) {
    return c.json([]);
  }

  const dirs = await listDirs(capturesDir);
  const captures = (await Promise.all(
    dirs
      .filter((dir) => /^CAP-\d+/.test(dir))
      .map(async (dir) => {
        const capture = await readJsonFile<CaptureMeta>(`${capturesDir}/${dir}/capture.json`);
        if (!capture) {
          return null;
        }

        if (!isSupportedStatus(capture.status)) {
          return null;
        }

        if (parsedStatus.type === "value" && capture.status !== parsedStatus.value) {
          return null;
        }

        return {
          ...capture,
          id: capture.id || dir,
        };
      }),
  )).filter((capture): capture is CaptureMeta => capture !== null);

  captures.sort((a, b) => {
    const aTime = a.created_at ?? "";
    const bTime = b.created_at ?? "";
    return bTime.localeCompare(aTime);
  });

  return c.json(captures);
});

projectCapturesApi.get("/captures/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  const id = c.req.param("id");

  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid capture id" }, 400);
  }

  const captureDir = `${baseDir}/captures/${id}`;
  if (!(await dirExists(captureDir))) {
    return c.json({ error: "Capture not found" }, 404);
  }

  const capture = await readJsonFile<CaptureMeta>(`${captureDir}/capture.json`);
  if (!capture) {
    return c.json({ error: "Capture not found" }, 404);
  }

  return c.json({ ...capture, id: capture.id || id });
});

projectCapturesApi.get("/captures/:id/screenshot", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  const id = c.req.param("id");

  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid capture id" }, 400);
  }

  const screenshotFile = `${baseDir}/captures/${id}/screenshot.webp`;

  try {
    const fileContent = await Deno.readFile(screenshotFile);
    return new Response(fileContent, {
      status: 200,
      headers: {
        "Content-Type": "image/webp",
        "Cache-Control": "no-cache",
      },
    });
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) {
      return c.json({ error: "Screenshot not found" }, 404);
    }

    return c.json({ error: "Failed to read screenshot" }, 500);
  }
});

projectCapturesApi.post("/captures", async (c) => {
  const projectId = c.req.param("projectId");
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  const capturesDir = `${baseDir}/captures`;

  let body: unknown;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  const payload = normalizeCaptureCreatePayload(body);
  if (!payload) {
    return c.json({ error: "Invalid capture payload" }, 400);
  }

  let captureId: string;
  let captureDir: string;
  try {
    await Deno.mkdir(capturesDir, { recursive: true });
    captureId = await nextCaptureId(capturesDir);
    captureDir = `${capturesDir}/${captureId}`;
    await Deno.mkdir(captureDir, { recursive: true });
  } catch {
    return c.json({ error: "Failed to allocate capture id" }, 500);
  }

  let screenshotPath: string | null = null;
  const screenshotData = normalizeScreenshotData(payload.screenshot_data);
  if (screenshotData) {
    try {
      const base64Payload = extractBase64Payload(screenshotData);
      const screenshotBytes = decodeBase64ToBytes(base64Payload);
      await Deno.writeFile(`${captureDir}/screenshot.webp`, screenshotBytes);
      const prefix = projectId ? `/api/projects/${projectId}` : "/api";
      screenshotPath = `${prefix}/captures/${captureId}/screenshot`;
    } catch (err) {
      console.warn(
        `[GM] Screenshot save failed for ${captureId}:`,
        err instanceof Error ? err.message : err
      );
      screenshotPath = null;
    }
  }

  const createdAt = new Date().toISOString();
  const capture: CaptureMeta = {
    id: captureId,
    status: "pending",
    created_at: createdAt,
    url: payload.url,
    selector: payload.selector,
    rect: payload.rect,
    screenshot_path: screenshotPath,
    memo: payload.memo,
    tags: payload.tags,
    html_snapshot: payload.html_snapshot,
    css_path: payload.css_path,
    component_name: payload.component_name,
    source_path: payload.source_path,
    linked_plan: null,
    linked_request: null,
    ttl_expires_at: null,
    ttl_warned_at: null,
    consumed_at: null,
    mode: payload.mode,
  };

  const saved = await writeJsonFile(`${capturesDir}/${captureId}/capture.json`, capture);
  if (!saved) {
    return c.json({ error: "Failed to save capture" }, 500);
  }

  return c.json(capture, 201);
});

projectCapturesApi.patch("/captures/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  const id = c.req.param("id");

  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid capture id" }, 400);
  }

  const captureDir = `${baseDir}/captures/${id}`;
  if (!(await dirExists(captureDir))) {
    return c.json({ error: "Capture not found" }, 404);
  }

  let body: CaptureUpdatePayload | null = null;
  try {
    const raw = await c.req.json();
    if (!raw || typeof raw !== "object") {
      return c.json({ error: "Invalid JSON body" }, 400);
    }

    const statusRaw = (raw as { status?: unknown }).status;
    if (!isSupportedStatusForUpdate(statusRaw)) {
      return c.json({ error: "Invalid status" }, 400);
    }

    body = { status: statusRaw };
  } catch {
    return c.json({ error: "Invalid JSON body" }, 400);
  }

  const current = await readJsonFile<CaptureMeta>(`${captureDir}/capture.json`);
  if (!current) {
    return c.json({ error: "Capture not found" }, 404);
  }

  if (!isSupportedStatus(current.status)) {
    return c.json({ error: "Invalid current capture status" }, 400);
  }

  const nextStatus = body?.status;
  if (!nextStatus) {
    return c.json({ error: "Invalid status" }, 400);
  }
  if (!canTransitionStatus(current.status, nextStatus)) {
    return c.json({ error: "Invalid status transition" }, 400);
  }

  const updatedCapture: CaptureMeta = {
    ...current,
    id,
    status: nextStatus,
    consumed_at:
      nextStatus === "consumed" && current.status !== "consumed"
        ? new Date().toISOString()
        : current.consumed_at ?? null,
  };

  const saved = await writeJsonFile(`${captureDir}/capture.json`, updatedCapture);
  if (!saved) {
    return c.json({ error: "Failed to update capture" }, 500);
  }

  return c.json(updatedCapture);
});

export { projectCapturesApi };
