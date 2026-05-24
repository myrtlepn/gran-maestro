import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { dirExists, listDirs, readJsonFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

type CounterType = "requests" | "plans" | "debug" | "ideation" | "discussion" | "explore" | "designs";

interface CounterStats {
  total: number;
  active: number;
  archived: number;
}

const projectStatsApi = new Hono();

const TYPE_PREFIXES: Record<CounterType, RegExp> = {
  requests: /^REQ-/,
  plans: /^PLN-/,
  debug: /^DBG-/,
  ideation: /^IDN-/,
  discussion: /^DSC-/,
  explore: /^EXP-/,
  designs: /^DES-/,
};

function normalizeAgent(value: unknown): string {
  return typeof value === "string" && value.trim().length > 0 ? value : "unknown";
}

function normalizeStatus(value: unknown): string {
  return typeof value === "string" ? value : "unknown";
}

function normalizeRetry(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;
}

function isCompletedRequestStatus(status: string): boolean {
  return status === "done" || status === "committed";
}

function isCompletedTaskStatus(status: string): boolean {
  return status === "done" || status === "committed";
}

async function readCounterTotal(baseDir: string, type: CounterType): Promise<number> {
  const counterJson = await readJsonFile<{ last_id?: unknown }>(
    `${baseDir}/${type}/counter.json`
  );
  if (typeof counterJson?.last_id === "number" && Number.isFinite(counterJson.last_id)) {
    return counterJson.last_id;
  }
  return 0;
}

async function countActive(baseDir: string, type: CounterType): Promise<number> {
  const dirs = await listDirs(`${baseDir}/${type}`);
  return dirs.filter((dir) => TYPE_PREFIXES[type].test(dir)).length;
}

async function countArchived(baseDir: string, type: CounterType): Promise<number> {
  const archivedDir = `${baseDir}/${type}/archived`;
  if (!(await dirExists(archivedDir))) return 0;

  let count = 0;
  try {
    for await (const entry of Deno.readDir(archivedDir)) {
      if (entry.isFile && entry.name.endsWith(".tar.gz")) {
        count += 1;
      }
    }
  } catch (_error) {
    return 0;
  }
  return count;
}

projectStatsApi.get("/stats", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const counterTypes = Object.keys(TYPE_PREFIXES) as CounterType[];
  const counters = {} as Record<CounterType, CounterStats>;

  await Promise.all(
    counterTypes.map(async (type) => {
      const [total, active, archived] = await Promise.all([
        readCounterTotal(baseDir, type),
        countActive(baseDir, type),
        countArchived(baseDir, type),
      ]);
      counters[type] = { total, active, archived };
    }),
  );

  const requestDirs = (await listDirs(`${baseDir}/requests`)).filter(
    (dir) => TYPE_PREFIXES.requests.test(dir),
  );

  const statusDistribution: Record<string, number> = {};
  let completedRequests = 0;

  for (const dir of requestDirs) {
    const requestJson = await readJsonFile<{ status?: unknown }>(
      `${baseDir}/requests/${dir}/request.json`
    );
    if (!requestJson?.status) {
      continue;
    }

    const status = normalizeStatus(requestJson.status);
    statusDistribution[status] = (statusDistribution[status] ?? 0) + 1;
    if (isCompletedRequestStatus(status)) {
      completedRequests += 1;
    }
  }

  const completionRate = requestDirs.length > 0
    ? completedRequests / requestDirs.length
    : 0;

  return c.json({
    counters,
    status_distribution: statusDistribution,
    completion_rate: completionRate,
  });
});

projectStatsApi.get("/stats/agents", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  interface AgentAggregate {
    agent: string;
    tasks_assigned: number;
    tasks_completed: number;
    tasks_failed: number;
    retry_total: number;
  }

  const requestDirs = (await listDirs(`${baseDir}/requests`)).filter(
    (dir) => TYPE_PREFIXES.requests.test(dir),
  );
  const agentMap = new Map<string, AgentAggregate>();

  for (const requestDir of requestDirs) {
    const tasksDir = `${baseDir}/requests/${requestDir}/tasks`;
    if (!(await dirExists(tasksDir))) continue;

    const taskDirs = await listDirs(tasksDir);
    for (const taskDir of taskDirs) {
      const taskStatus = await readJsonFile<{ agent?: unknown; status?: unknown; retry_count?: unknown }>(
        `${tasksDir}/${taskDir}/status.json`
      );
      if (!taskStatus) continue;

      const agent = normalizeAgent(taskStatus.agent);
      const status = normalizeStatus(taskStatus.status);
      const retryCount = normalizeRetry(taskStatus.retry_count);

      const aggregate = agentMap.get(agent) ?? {
        agent,
        tasks_assigned: 0,
        tasks_completed: 0,
        tasks_failed: 0,
        retry_total: 0,
      };

      aggregate.tasks_assigned += 1;
      if (isCompletedTaskStatus(status)) aggregate.tasks_completed += 1;
      if (status === "failed") aggregate.tasks_failed += 1;
      aggregate.retry_total += retryCount;

      agentMap.set(agent, aggregate);
    }
  }

  const agents = Array.from(agentMap.values()).sort((a, b) => a.agent.localeCompare(b.agent));
  return c.json(agents);
});

export { projectStatsApi };
