import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import type { PlanMeta } from "../types.ts";
import { dirExists, listDirs, readJsonFile, readTextFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

const projectPlansApi = new Hono();

type GraphNodeType =
  | "plan"
  | "request"
  | "debug"
  | "ideation"
  | "discussion"
  | "task"
  | "commit";

type GraphNode = {
  id: string;
  type: GraphNodeType;
  data: {
    label: string;
    status?: string;
    title?: string;
    commit_hash?: string;
    commit_message?: string;
    [key: string]: unknown;
  };
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
};

interface GraphPlanMeta extends PlanMeta {
  linked_debug?: string;
  linked_ideation?: string;
  linked_discussion?: string;
}

interface SessionMeta {
  id?: string;
  status?: string;
  issue?: string;
  focus?: string;
  topic?: string;
  [key: string]: unknown;
}

interface RequestTaskMeta {
  id?: string;
  title?: string;
  name?: string;
  status?: string;
  commit_hash?: string;
  commit_message?: string;
}

interface GraphRequestMeta {
  id?: string;
  title?: string;
  status?: string;
  tasks?: RequestTaskMeta[];
}

async function resolveReqPath(
  baseDir: string,
  reqId: string,
): Promise<string | null> {
  const requestJsonPath = `${baseDir}/requests/${reqId}/request.json`;
  const completedRequestJsonPath = `${baseDir}/requests/completed/${reqId}/request.json`;
  for (const path of [requestJsonPath, completedRequestJsonPath]) {
    try {
      await Deno.stat(path);
      return path;
    } catch (_error) {
      // try next path
    }
  }
  return null;
}

function pickRequestNodeLabel(req: GraphRequestMeta, requestId: string): string {
  return req.title && req.title.trim().length > 0 ? req.title : requestId;
}

function pickTaskNodeLabel(task: RequestTaskMeta): string {
  if (task.title?.trim().length) return task.title;
  if (task.name?.trim().length) return task.name;
  return task.id || "";
}

function pickSessionNodeLabel(
  type: GraphNodeType,
  session: SessionMeta,
  sessionId: string,
): string {
  const title = session.topic || session.issue || session.focus;
  return title ? `${type}: ${title}` : sessionId;
}

// ─── API: Plans ────────────────────────────────────────────────────────────

projectPlansApi.get("/plans", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const plansDir = `${baseDir}/plans`;
  if (!(await dirExists(plansDir))) {
    return c.json([]);
  }

  const planDirs = (await listDirs(plansDir)).filter((dir) => /^PLN-/.test(dir));
  const planResults = await Promise.all(
    planDirs.map(async (dir) => {
      const planJson = await readJsonFile<PlanMeta>(`${plansDir}/${dir}/plan.json`);
      if (!planJson) {
        return null;
      }

      let createdAt = planJson.created_at;
      let hasDesign = false;
      try {
        await Deno.stat(`${plansDir}/${dir}/design.md`);
        hasDesign = true;
      } catch (_error) {
        hasDesign = false;
      }
      if (!createdAt || createdAt.includes("T00:00:00")) {
        try {
          const stat = await Deno.stat(`${plansDir}/${dir}/plan.json`);
          if (stat.mtime) {
            createdAt = stat.mtime.toISOString();
          }
        } catch (_error) {
          // ignore fallback failure
        }
      }
      return {
        ...planJson,
        id: planJson.id || dir,
        created_at: createdAt,
        has_design: hasDesign,
      };
    })
  );

  const plans = planResults.filter((plan): plan is NonNullable<typeof plan> =>
    plan !== null
  ) as (PlanMeta & { has_design: boolean })[];

  plans.sort((a, b) => {
    const aTime = a.created_at;
    const bTime = b.created_at;
    if (!aTime && !bTime) return 0;
    if (!aTime) return 1;
    if (!bTime) return -1;
    return bTime.localeCompare(aTime);
  });

  return c.json(plans);
});

projectPlansApi.get("/plans/:planId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const planId = c.req.param("planId");
  const planDir = `${baseDir}/plans/${planId}`;
  if (!(await dirExists(planDir))) {
    return c.json({ error: "Plan not found" }, 404);
  }

  const planJson = await readJsonFile<PlanMeta>(`${planDir}/plan.json`);
  if (!planJson) {
    return c.json({ error: "Plan not found" }, 404);
  }
  const content = await readTextFile(`${planDir}/plan.md`);
  return c.json({ ...planJson, id: planJson.id || planId, content: content ?? null });
});

projectPlansApi.get("/plans/:planId/design", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const planId = c.req.param("planId");
  const designPath = `${baseDir}/plans/${planId}/design.md`;
  const content = await readTextFile(designPath);
  if (content !== null) {
    return c.json({ exists: true, content });
  }
  return c.json({ exists: false, content: null });
});

interface ReviewIssue {
  severity: "CRITICAL" | "MAJOR" | "MINOR";
  title: string;
  description: string;
}

interface RoleReviewResult {
  role: string;
  no_issues: boolean;
  issues: ReviewIssue[];
}

const REVIEW_ROLES = ["architect", "devils_advocate", "completeness", "ux_reviewer"] as const;
const REVIEW_LINE_RE = /^(CRITICAL|MAJOR|MINOR):\s+(.+?)\s+\u2014\s+(.+)$/;

function parseReviewLog(content: string): { no_issues: boolean; issues: ReviewIssue[] } {
  const lines = content.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  if (lines.length > 0 && lines[0] === "NO_ISSUES") {
    return { no_issues: true, issues: [] };
  }
  const issues: ReviewIssue[] = [];
  for (const line of lines) {
    const match = REVIEW_LINE_RE.exec(line);
    if (!match) continue;
    issues.push({
      severity: match[1] as "CRITICAL" | "MAJOR" | "MINOR",
      title: match[2],
      description: match[3],
    });
  }
  return { no_issues: false, issues };
}

projectPlansApi.get("/plans/:planId/review", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const planId = c.req.param("planId");
  const promptsDir = `${baseDir}/plans/${planId}/prompts`;
  if (!(await dirExists(promptsDir))) {
    return c.json({ roles: [] });
  }

  const roleResults = await Promise.all(
    REVIEW_ROLES.map(async (role): Promise<RoleReviewResult | null> => {
      const logPath = `${promptsDir}/review-${role}.log`;
      const content = await readTextFile(logPath);
      if (content === null) return null;
      const parsed = parseReviewLog(content);
      return { role, ...parsed };
    })
  );

  const roles = roleResults.filter((r): r is RoleReviewResult => r !== null);
  return c.json({ roles });
});

projectPlansApi.get("/plans/:planId/graph", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const planId = c.req.param("planId");
  const planDir = `${baseDir}/plans/${planId}`;
  if (!(await dirExists(planDir))) {
    return c.json({ error: "Plan not found" }, 404);
  }

  const planJson = await readJsonFile<GraphPlanMeta>(`${planDir}/plan.json`);
  if (!planJson) {
    return c.json({ error: "Plan not found" }, 404);
  }

  const nodes: GraphNode[] = [];
  const nodeIds = new Set<string>();
  const edges: GraphEdge[] = [];
  const edgeIds = new Set<string>();
  const addNode = (node: GraphNode) => {
    if (nodeIds.has(node.id)) return;
    nodeIds.add(node.id);
    nodes.push(node);
  };
  const addEdge = (source: string, target: string) => {
    const edgeId = `${source}->${target}`;
    if (edgeIds.has(edgeId)) return;
    edgeIds.add(edgeId);
    edges.push({ id: edgeId, source, target });
  };

  addNode({
    id: planId,
    type: "plan",
    data: {
      label: planJson.title || planId,
      status: planJson.status,
      title: planJson.title,
    },
  });

  const sessionDefs: Array<{ type: "debug" | "ideation" | "discussion"; sessionId?: string; dir: string }> = [
    { type: "debug", sessionId: planJson.linked_debug, dir: `${baseDir}/debug` },
    { type: "ideation", sessionId: planJson.linked_ideation, dir: `${baseDir}/ideation` },
    { type: "discussion", sessionId: planJson.linked_discussion, dir: `${baseDir}/discussion` },
  ];

  await Promise.all(sessionDefs.map(async ({ type, sessionId, dir }) => {
    if (!sessionId?.trim()) return;
    const resolvedSessionId = sessionId.trim();
    const sessionJson = await readJsonFile<SessionMeta>(
      `${dir}/${resolvedSessionId}/session.json`
    );
    if (!sessionJson) return;

    addNode({
      id: resolvedSessionId,
      type,
      data: {
        label: pickSessionNodeLabel(type, sessionJson, resolvedSessionId),
        status: sessionJson.status,
        title: sessionJson.id ? resolvedSessionId : undefined,
        issue: sessionJson.issue,
        topic: sessionJson.topic,
      },
    });
    addEdge(planId, resolvedSessionId);
  }));

  const linkedRequests = Array.isArray(planJson.linked_requests)
    ? planJson.linked_requests
    : [];
  for (const reqId of linkedRequests) {
    if (typeof reqId !== "string" || !reqId.trim()) continue;
    const targetReqId = reqId.trim();
    const requestPath = await resolveReqPath(baseDir, targetReqId);
    if (!requestPath) continue;

    const requestJson = await readJsonFile<GraphRequestMeta>(requestPath);
    if (!requestJson) continue;
    const requestId = requestJson.id || targetReqId;

    addNode({
      id: requestId,
      type: "request",
      data: {
        label: pickRequestNodeLabel(requestJson, requestId),
        status: requestJson.status,
        title: requestJson.title,
      },
    });
    addEdge(planId, requestId);

    const tasks = Array.isArray(requestJson.tasks) ? requestJson.tasks : [];
    for (const task of tasks) {
      if (!task || typeof task !== "object") continue;
      const taskLabel = pickTaskNodeLabel(task);
      if (!task.id?.trim()) continue;
      const taskId = task.id.trim();
      addNode({
        id: taskId,
        type: "task",
        data: {
          label: taskLabel,
          status: task.status,
          title: task.title || taskLabel,
          commit_hash: task.commit_hash,
          commit_message: task.commit_message,
        },
      });
      addEdge(requestId, taskId);

      if (task.commit_hash?.trim()) {
        const commitId = `commit-${task.commit_hash.slice(0, 7)}`;
        addNode({
          id: commitId,
          type: "commit",
          data: {
            label: task.commit_message?.trim()
              ? `${task.commit_hash.slice(0, 7)}: ${task.commit_message}`
              : task.commit_hash,
            commit_hash: task.commit_hash,
            commit_message: task.commit_message,
          },
        });
        addEdge(taskId, commitId);
      }
    }
  }

  return c.json({ nodes, edges });
});

export { projectPlansApi };
