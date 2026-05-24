import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { dirExists, listDirs, readJsonFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

type OverviewItemType = "request" | "plan";

type CursorPayload = {
  last_event_at: string;
  id: string;
};

type OverviewItem = {
  id: string;
  type: OverviewItemType;
  title: string;
  status: string;
  last_event_at: string;
  blocked?: boolean;
};

type RequestOverviewJson = {
  id?: unknown;
  title?: unknown;
  status?: unknown;
  updated_at?: unknown;
  created_at?: unknown;
  dependencies?: {
    blockedBy?: unknown;
  };
};

type PlanOverviewJson = {
  id?: unknown;
  title?: unknown;
  status?: unknown;
  updated_at?: unknown;
  created_at?: unknown;
  linked_requests?: unknown;
};

type NextStepItem = {
  label: string;
  command: string;
  reason: string;
};

type PulseResponse = {
  active: number;
  blocked: number;
  done_7d: number;
  stale_7d: number;
};

const DEFAULT_LIMIT = 10;
const MAX_LIMIT = 20;
const REQUEST_PREFIX = /^REQ-/;
const PLAN_PREFIX = /^PLN-/;
const INACTIVE_REQUEST_STATUSES = new Set(["done", "committed", "cancelled", "archived"]);
const ACTIVE_PLAN_STATUSES = new Set(["active", "in_progress"]);

const projectOverviewApi = new Hono();

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

function asIsoTimestamp(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

function parseLimit(raw: string | undefined): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_LIMIT;
  }
  return Math.min(parsed, MAX_LIMIT);
}

function decodeCursor(raw: string | undefined): CursorPayload | null {
  if (!raw) return null;

  try {
    const parsed = JSON.parse(atob(raw)) as CursorPayload;
    if (typeof parsed?.last_event_at !== "string" || typeof parsed?.id !== "string") {
      return null;
    }
    if (parsed.last_event_at.length === 0 || parsed.id.length === 0) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function encodeCursor(payload: CursorPayload): string {
  return btoa(JSON.stringify(payload));
}

function compareOverviewItemsDesc(a: OverviewItem, b: OverviewItem): number {
  const byTime = b.last_event_at.localeCompare(a.last_event_at);
  if (byTime !== 0) return byTime;
  return b.id.localeCompare(a.id);
}

function isBlockedRequest(dependencies: RequestOverviewJson["dependencies"]): boolean {
  return Array.isArray(dependencies?.blockedBy) && dependencies.blockedBy.length > 0;
}

function isDoneRequestStatus(status: string): boolean {
  return status === "done" || status === "committed";
}

function isPlanOnlyStatus(status: string): boolean {
  return ACTIVE_PLAN_STATUSES.has(status);
}

function hasNoLinkedRequests(linkedRequests: unknown): boolean {
  return Array.isArray(linkedRequests) && linkedRequests.length === 0;
}

function timestampToMs(value: unknown): number | null {
  if (typeof value !== "string" || value.trim().length === 0) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function isWithin7Days(value: unknown, thresholdMs: number): boolean {
  const timestampMs = timestampToMs(value);
  return timestampMs !== null && timestampMs >= thresholdMs;
}

function isStaleBy7Days(updatedAt: unknown, createdAt: unknown, thresholdMs: number): boolean {
  const updatedAtMs = timestampToMs(updatedAt);
  if (updatedAtMs !== null) {
    return updatedAtMs < thresholdMs;
  }

  const createdAtMs = timestampToMs(createdAt);
  if (createdAtMs !== null) {
    return createdAtMs < thresholdMs;
  }

  return false;
}

async function listRequestDirs(baseDir: string): Promise<string[]> {
  const requestsDir = `${baseDir}/requests`;
  if (!(await dirExists(requestsDir))) {
    return [];
  }
  return (await listDirs(requestsDir)).filter((dir) => REQUEST_PREFIX.test(dir));
}

async function listPlanDirs(baseDir: string): Promise<string[]> {
  const plansDir = `${baseDir}/plans`;
  if (!(await dirExists(plansDir))) {
    return [];
  }
  return (await listDirs(plansDir)).filter((dir) => PLAN_PREFIX.test(dir));
}

async function collectActiveRequests(baseDir: string): Promise<OverviewItem[]> {
  const requestDirs = await listRequestDirs(baseDir);
  const results = await Promise.all(
    requestDirs.map(async (dir): Promise<OverviewItem | null> => {
      const requestJson = await readJsonFile<RequestOverviewJson>(`${baseDir}/requests/${dir}/request.json`);
      if (!requestJson) return null;

      const id = asString(requestJson.id, dir);
      const status = asString(requestJson.status, "unknown");
      if (INACTIVE_REQUEST_STATUSES.has(status.toLowerCase())) {
        return null;
      }

      return {
        id,
        type: "request",
        title: asString(requestJson.title, id),
        status,
        last_event_at: asIsoTimestamp(requestJson.updated_at, asIsoTimestamp(requestJson.created_at, "")),
        blocked: isBlockedRequest(requestJson.dependencies),
      };
    }),
  );

  return results.filter((item): item is OverviewItem => item !== null);
}

async function collectActivePlans(baseDir: string): Promise<OverviewItem[]> {
  const planDirs = await listPlanDirs(baseDir);
  const results = await Promise.all(
    planDirs.map(async (dir): Promise<OverviewItem | null> => {
      const planJson = await readJsonFile<PlanOverviewJson>(`${baseDir}/plans/${dir}/plan.json`);
      if (!planJson) return null;

      const id = asString(planJson.id, dir);
      const status = asString(planJson.status, "unknown");
      if (!ACTIVE_PLAN_STATUSES.has(status.toLowerCase())) {
        return null;
      }

      return {
        id,
        type: "plan",
        title: asString(planJson.title, id),
        status,
        last_event_at: asIsoTimestamp(planJson.updated_at, asIsoTimestamp(planJson.created_at, "")),
      };
    }),
  );

  return results.filter((item): item is OverviewItem => item !== null);
}

function compareByIdAsc<T extends { id: string }>(a: T, b: T): number {
  return a.id.localeCompare(b.id);
}

async function collectNextSteps(baseDir: string): Promise<NextStepItem[]> {
  const [requestDirs, planDirs] = await Promise.all([
    listRequestDirs(baseDir),
    listPlanDirs(baseDir),
  ]);

  const [requests, plans] = await Promise.all([
    Promise.all(
      requestDirs.map(async (dir) => {
        const requestJson = await readJsonFile<RequestOverviewJson>(`${baseDir}/requests/${dir}/request.json`);
        if (!requestJson) return null;
        return {
          id: asString(requestJson.id, dir),
          status: asString(requestJson.status, "unknown").toLowerCase(),
          dependencies: requestJson.dependencies,
        };
      }),
    ),
    Promise.all(
      planDirs.map(async (dir) => {
        const planJson = await readJsonFile<PlanOverviewJson>(`${baseDir}/plans/${dir}/plan.json`);
        if (!planJson) return null;
        return {
          id: asString(planJson.id, dir),
          status: asString(planJson.status, "unknown").toLowerCase(),
          linked_requests: planJson.linked_requests,
        };
      }),
    ),
  ]);

  const requestItems = requests.filter((item): item is NonNullable<typeof item> => item !== null);
  const planItems = plans.filter((item): item is NonNullable<typeof item> => item !== null);

  const blockedSteps = requestItems
    .filter((item) => !INACTIVE_REQUEST_STATUSES.has(item.status) && isBlockedRequest(item.dependencies))
    .sort(compareByIdAsc)
    .map((item) => ({
      label: `${item.id} 차단됨`,
      command: `/mst:recover ${item.id}`,
      reason: "차단된 요청 복구",
    }));

  const planOnlySteps = planItems
    .filter((item) => isPlanOnlyStatus(item.status) && hasNoLinkedRequests(item.linked_requests))
    .sort(compareByIdAsc)
    .map((item) => ({
      label: `${item.id} spec 미생성`,
      command: `/mst:request --plan ${item.id}`,
      reason: "구현 사양 작성",
    }));

  const specReadySteps = requestItems
    .filter((item) => item.status === "spec_ready" && !isBlockedRequest(item.dependencies))
    .sort(compareByIdAsc)
    .map((item) => ({
      label: `${item.id} 승인 대기`,
      command: `/mst:approve ${item.id}`,
      reason: "스펙 승인 및 실행",
    }));

  return [...blockedSteps, ...planOnlySteps, ...specReadySteps].slice(0, 3);
}

async function collectPulse(baseDir: string): Promise<PulseResponse> {
  const requestDirs = await listRequestDirs(baseDir);
  const requests = await Promise.all(
    requestDirs.map(async (dir) => {
      const requestJson = await readJsonFile<RequestOverviewJson>(`${baseDir}/requests/${dir}/request.json`);
      if (!requestJson) return null;
      return {
        status: asString(requestJson.status, "unknown").toLowerCase(),
        updated_at: requestJson.updated_at,
        created_at: requestJson.created_at,
        dependencies: requestJson.dependencies,
      };
    }),
  );

  const nowMs = Date.now();
  const sevenDaysMs = 7 * 24 * 60 * 60 * 1000;
  const thresholdMs = nowMs - sevenDaysMs;

  let active = 0;
  let blocked = 0;
  let done_7d = 0;
  let stale_7d = 0;

  for (const request of requests) {
    if (!request) continue;

    const isActive = !INACTIVE_REQUEST_STATUSES.has(request.status);
    if (isActive) {
      active += 1;
      if (isBlockedRequest(request.dependencies)) {
        blocked += 1;
      }
      if (isStaleBy7Days(request.updated_at, request.created_at, thresholdMs)) {
        stale_7d += 1;
      }
    }

    if (isDoneRequestStatus(request.status) && isWithin7Days(request.updated_at, thresholdMs)) {
      done_7d += 1;
    }
  }

  return { active, blocked, done_7d, stale_7d };
}

projectOverviewApi.get("/overview/active-items", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const [requests, plans] = await Promise.all([
    collectActiveRequests(baseDir),
    collectActivePlans(baseDir),
  ]);

  const allItems = [...requests, ...plans].sort(compareOverviewItemsDesc);

  const limit = parseLimit(c.req.query("limit"));
  const cursor = decodeCursor(c.req.query("cursor"));
  const startIndex = cursor
    ? (() => {
      const cursorIndex = allItems.findIndex((item) => {
        return item.last_event_at === cursor.last_event_at && item.id === cursor.id;
      });
      return cursorIndex >= 0 ? cursorIndex + 1 : 0;
    })()
    : 0;

  const items = allItems.slice(startIndex, startIndex + limit);
  const has_more = startIndex + limit < allItems.length;
  const next_cursor = has_more && items.length > 0
    ? encodeCursor({
      last_event_at: items[items.length - 1].last_event_at,
      id: items[items.length - 1].id,
    })
    : null;

  return c.json({
    items,
    next_cursor,
    has_more,
    as_of: new Date().toISOString(),
  });
});

projectOverviewApi.get("/overview/next-steps", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const items = await collectNextSteps(baseDir);
  return c.json({
    items,
    as_of: new Date().toISOString(),
  });
});

projectOverviewApi.get("/overview/pulse", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const pulse = await collectPulse(baseDir);
  return c.json({
    ...pulse,
    as_of: new Date().toISOString(),
  });
});

export { projectOverviewApi };
