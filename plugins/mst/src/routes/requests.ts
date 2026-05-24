import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import type { RequestMeta, TaskMeta } from "../types.ts";
import { dirExists, listDirs, readJsonFile, readTextFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

const projectRequestsApi = new Hono();

function isInvalidPathPart(value: string): boolean {
  return !value || value.includes("..") || value.includes("/") ||
    value.includes("\\");
}

async function resolveRequestDir(
  baseDir: string,
  id: string,
): Promise<string | null> {
  const primary = `${baseDir}/requests/${id}`;
  if (await dirExists(primary)) return primary;
  const completed = `${baseDir}/requests/completed/${id}`;
  if (await dirExists(completed)) return completed;
  return null;
}

function splitLogLines(text: string): string[] {
  const lines = text.split(/\r?\n/);
  if (lines.length > 0 && lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
}

async function buildReqToPlanMap(
  baseDir: string,
): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  const plansDir = `${baseDir}/plans`;
  if (!(await dirExists(plansDir))) return map;

  const planDirs = (await listDirs(plansDir)).filter((dir) =>
    /^PLN-/.test(dir)
  );
  const planJsons = await Promise.all(
    planDirs.map((dir) =>
      readJsonFile<{ id?: string; linked_requests?: string[] }>(
        `${plansDir}/${dir}/plan.json`,
      )
    ),
  );
  for (let i = 0; i < planDirs.length; i++) {
    const planJson = planJsons[i];
    if (!planJson?.linked_requests) continue;

    const planId = planJson.id || planDirs[i];
    for (const reqId of planJson.linked_requests) {
      if (!map.has(reqId)) {
        map.set(reqId, planId);
      }
    }
  }

  return map;
}

async function findLinkedPlan(
  baseDir: string,
  reqId: string,
): Promise<string | null> {
  const plansDir = `${baseDir}/plans`;
  if (!(await dirExists(plansDir))) return null;

  const planDirs = (await listDirs(plansDir)).filter((dir) =>
    /^PLN-/.test(dir)
  );
  const planJsons = await Promise.all(
    planDirs.map((dir) =>
      readJsonFile<{ id?: string; linked_requests?: string[] }>(
        `${plansDir}/${dir}/plan.json`,
      )
    ),
  );
  for (let i = 0; i < planDirs.length; i++) {
    const planJson = planJsons[i];
    if (planJson?.linked_requests?.includes(reqId)) {
      return planJson.id || planDirs[i];
    }
  }
  return null;
}

async function buildReqToDesMap(baseDir: string): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  const designsDir = `${baseDir}/designs`;
  if (!(await dirExists(designsDir))) return map;

  const desDirs = (await listDirs(designsDir)).filter((dir) =>
    /^DES-/.test(dir)
  );
  await Promise.all(
    desDirs.map(async (dir) => {
      const desJson = await readJsonFile<{ id?: string; linked_req?: string }>(
        `${designsDir}/${dir}/design.json`,
      );
      if (!desJson?.linked_req) return;
      const desId = desJson.id || dir;
      if (!map.has(desJson.linked_req)) {
        map.set(desJson.linked_req, desId);
      }
    }),
  );
  return map;
}

async function findLinkedDesign(
  baseDir: string,
  reqId: string,
): Promise<string | null> {
  const designsDir = `${baseDir}/designs`;
  if (!(await dirExists(designsDir))) return null;

  const desDirs = (await listDirs(designsDir)).filter((dir) =>
    /^DES-/.test(dir)
  );
  const desJsons = await Promise.all(
    desDirs.map((dir) =>
      readJsonFile<{ id?: string; linked_req?: string }>(
        `${designsDir}/${dir}/design.json`,
      )
    ),
  );
  for (let i = 0; i < desDirs.length; i++) {
    const desJson = desJsons[i];
    if (desJson?.linked_req === reqId) {
      return desJson.id || desDirs[i];
    }
  }
  return null;
}

function toImageContentType(fileName: string): string {
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".webp")) return "image/webp";
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".gif")) return "image/gif";
  return "application/octet-stream";
}

type BrowserTestApiItem = Record<string, unknown> & {
  id: string;
  rv_id: string;
  created_at: string | null;
  screenshots: string[];
  screenshot_urls: string[];
};

projectRequestsApi.get("/requests", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const requestsDir = `${baseDir}/requests`;
  if (!(await dirExists(requestsDir))) {
    return c.json([]);
  }

  const [reqToPlanMap, reqToDesMap] = await Promise.all([
    buildReqToPlanMap(baseDir),
    buildReqToDesMap(baseDir),
  ]);

  const requests: RequestMeta[] = [];
  const requestDirs = (await listDirs(requestsDir)).filter((dir) =>
    /^REQ-/.test(dir)
  );
  const completedRequestDirs = (await listDirs(`${requestsDir}/completed`))
    .filter((dir) => /^REQ-/.test(dir));

  for (const dir of requestDirs) {
    const reqJson = await readJsonFile<RequestMeta>(
      `${requestsDir}/${dir}/request.json`,
    );
    if (reqJson) {
      const requestId = reqJson.id || dir;
      let createdAt = reqJson.created_at as string | undefined;
      if (!createdAt || createdAt.includes("T00:00:00")) {
        try {
          const stat = await Deno.stat(`${requestsDir}/${dir}/request.json`);
          if (stat.mtime) {
            createdAt = stat.mtime.toISOString();
          }
        } catch (_error) {
          // ignore fallback failure
        }
      }
      const { review_iterations: _ri1, ...reqJsonRest1 } = reqJson as
        & RequestMeta
        & { review_iterations?: unknown };
      requests.push({
        ...reqJsonRest1,
        id: requestId,
        created_at: createdAt,
        linked_plan: reqToPlanMap.get(requestId) ?? null,
        linked_design: reqToDesMap.get(requestId) ?? null,
        review_summary: reqJson.review_summary ?? null,
      });
    }
  }

  for (const dir of completedRequestDirs) {
    const reqJson = await readJsonFile<RequestMeta>(
      `${requestsDir}/completed/${dir}/request.json`,
    );
    if (reqJson) {
      const requestId = reqJson.id || dir;
      let createdAt = reqJson.created_at as string | undefined;
      if (!createdAt || createdAt.includes("T00:00:00")) {
        try {
          const stat = await Deno.stat(
            `${requestsDir}/completed/${dir}/request.json`,
          );
          if (stat.mtime) {
            createdAt = stat.mtime.toISOString();
          }
        } catch (_error) {
          // ignore fallback failure
        }
      }
      const { review_iterations: _ri2, ...reqJsonRest2 } = reqJson as
        & RequestMeta
        & { review_iterations?: unknown };
      requests.push({
        ...reqJsonRest2,
        id: requestId,
        created_at: createdAt,
        _location: "completed",
        linked_plan: reqToPlanMap.get(requestId) ?? null,
        linked_design: reqToDesMap.get(requestId) ?? null,
        review_summary: reqJson.review_summary ?? null,
      });
    }
  }

  requests.sort((a, b) => {
    const aTime = String(a["created_at"] ?? "");
    const bTime = String(b["created_at"] ?? "");
    return bTime.localeCompare(aTime);
  });

  return c.json(requests);
});

projectRequestsApi.get("/requests/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  const requestDir = await resolveRequestDir(baseDir, id);
  if (!requestDir) {
    return c.json({ error: "Request not found" }, 404);
  }

  const reqJson = await readJsonFile<RequestMeta>(
    `${requestDir}/request.json`,
  );
  if (!reqJson) {
    return c.json({ error: "Request not found" }, 404);
  }
  const requestId = reqJson.id || id;
  const [linkedPlan, linkedDesign] = await Promise.all([
    findLinkedPlan(baseDir, requestId),
    findLinkedDesign(baseDir, requestId),
  ]);
  let createdAt = reqJson.created_at as string | undefined;
  if (!createdAt || createdAt.includes("T00:00:00")) {
    try {
      const stat = await Deno.stat(`${requestDir}/request.json`);
      if (stat.mtime) {
        createdAt = stat.mtime.toISOString();
      }
    } catch (_error) {
      // ignore fallback failure
    }
  }
  return c.json({
    ...reqJson,
    id: requestId,
    created_at: createdAt,
    linked_plan: linkedPlan ?? null,
    linked_design: linkedDesign ?? null,
    review_summary: reqJson.review_summary ?? null,
  });
});

// ─── API: Browser Tests ─────────────────────────────────────────────────────

projectRequestsApi.get("/requests/:id/browser-tests", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid request id" }, 400);
  }

  const requestDir = await resolveRequestDir(baseDir, id);
  if (!requestDir) {
    return c.json([]);
  }

  const browserTestsDir = `${requestDir}/browser-tests`;
  if (!(await dirExists(browserTestsDir))) {
    return c.json([]);
  }

  const projectId = c.req.param("projectId");
  const prefix = projectId ? `/api/projects/${projectId}` : "/api";
  const dirs = (await listDirs(browserTestsDir)).filter((dir) =>
    /^BT-/.test(dir)
  );

  const browserTests = (await Promise.all(
    dirs.map(async (dir) => {
      const result = await readJsonFile<Record<string, unknown>>(
        `${browserTestsDir}/${dir}/results.json`,
      );
      if (!result) {
        return null;
      }

      const screenshotsDir = `${browserTestsDir}/${dir}/screenshots`;
      const screenshots: string[] = [];
      try {
        for await (const entry of Deno.readDir(screenshotsDir)) {
          if (entry.isFile) {
            screenshots.push(entry.name);
          }
        }
      } catch {
        // screenshots directory may not exist
      }
      screenshots.sort();

      const resultId = typeof result.id === "string" && result.id.length > 0
        ? result.id
        : dir;
      const rvId = typeof result.rv_id === "string" && result.rv_id.length > 0
        ? result.rv_id
        : dir.replace(/^BT-/, "");
      const createdAt = typeof result.created_at === "string"
        ? result.created_at
        : null;

      return {
        ...result,
        id: resultId,
        rv_id: rvId,
        created_at: createdAt,
        screenshots,
        screenshot_urls: screenshots.map(
          (file) =>
            `${prefix}/requests/${id}/browser-tests/${dir}/screenshots/${
              encodeURIComponent(file)
            }`,
        ),
      };
    }),
  )).filter((item): item is BrowserTestApiItem => item !== null);

  browserTests.sort((a, b) => {
    const aTime = typeof a.created_at === "string" ? a.created_at : "";
    const bTime = typeof b.created_at === "string" ? b.created_at : "";
    return bTime.localeCompare(aTime);
  });

  return c.json(browserTests);
});

projectRequestsApi.get(
  "/requests/:id/browser-tests/:btId/screenshots/:file",
  async (c) => {
    const baseDir = resolveBaseDir(c.req.param("projectId"));
    if (!baseDir) {
      return c.json({ error: "Project not found" }, 404);
    }

    const id = c.req.param("id");
    const btId = c.req.param("btId");
    const file = c.req.param("file");
    if (
      isInvalidPathPart(id) || isInvalidPathPart(btId) ||
      isInvalidPathPart(file)
    ) {
      return c.json({ error: "Invalid browser-test path" }, 400);
    }

    const requestDir = await resolveRequestDir(baseDir, id);
    if (!requestDir) {
      return c.json({ error: "Request not found" }, 404);
    }

    const screenshotFile =
      `${requestDir}/browser-tests/${btId}/screenshots/${file}`;
    try {
      const fileContent = await Deno.readFile(screenshotFile);
      return new Response(fileContent, {
        status: 200,
        headers: {
          "Content-Type": toImageContentType(file),
          "Cache-Control": "no-cache",
        },
      });
    } catch (error) {
      if (error instanceof Deno.errors.NotFound) {
        return c.json({ error: "Screenshot not found" }, 404);
      }
      return c.json({ error: "Failed to read screenshot" }, 500);
    }
  },
);

// ─── API: Tasks ─────────────────────────────────────────────────────────────

projectRequestsApi.get("/requests/:id/tasks", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  if (isInvalidPathPart(id)) {
    return c.json({ error: "Invalid request/task id" }, 400);
  }
  const requestDir = await resolveRequestDir(baseDir, id);
  if (!requestDir) {
    return c.json([]);
  }

  const tasksDir = `${requestDir}/tasks`;
  if (!(await dirExists(tasksDir))) {
    return c.json([]);
  }

  const dirs = await listDirs(tasksDir);
  const tasks: TaskMeta[] = [];

  for (const dir of dirs) {
    const statusJson = await readJsonFile<TaskMeta>(
      `${tasksDir}/${dir}/status.json`,
    );
    if (statusJson) {
      tasks.push({ ...statusJson, id: statusJson.id || dir, requestId: id });
    } else {
      const reqJson = await readJsonFile<
        { tasks?: Array<{ id: string; status?: string; title?: string }> }
      >(
        `${requestDir}/request.json`,
      );
      const taskFromReq = reqJson?.tasks?.find(
        (t) =>
          t.id === dir || t.id.endsWith(`-${dir}`) || t.id.endsWith(`/${dir}`),
      );
      tasks.push({
        id: dir,
        requestId: id,
        status: taskFromReq?.status ?? "unknown",
        name: taskFromReq?.title,
      });
    }
  }

  return c.json(tasks);
});

projectRequestsApi.get("/requests/:id/tasks/:taskId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  const taskId = c.req.param("taskId");
  if (isInvalidPathPart(id) || isInvalidPathPart(taskId)) {
    return c.json({ error: "Invalid request/task id" }, 400);
  }
  const requestDir = await resolveRequestDir(baseDir, id);
  if (!requestDir) {
    return c.json({ error: "Task not found" }, 404);
  }

  const taskDir = `${requestDir}/tasks/${taskId}`;

  const statusPath = `${taskDir}/status.json`;
  const status = await readJsonFile<TaskMeta>(statusPath);
  const spec = await readTextFile(`${taskDir}/spec.md`);
  const feedback = await readTextFile(`${taskDir}/feedback.md`);

  const parseTimestamp = (value: unknown): number | null => {
    if (typeof value !== "string") return null;
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const isTerminalStatus = (value?: string): boolean =>
    value === "done" || value === "completed";

  let duration: number | null = null;
  if (status) {
    const startedAtMs = parseTimestamp(status.started_at);
    if (startedAtMs !== null) {
      let completedAtMs = parseTimestamp(status.completed_at);

      if (completedAtMs === null && isTerminalStatus(status.status)) {
        try {
          const statusStat = await Deno.stat(statusPath);
          if (statusStat.mtime) {
            completedAtMs = statusStat.mtime.getTime();
          }
        } catch {
          /* ignore */
        }
      }

      if (completedAtMs !== null) {
        duration = completedAtMs - startedAtMs;
      }
    }
  }

  // Find review: try review.md first, then latest review-*.md
  let review = await readTextFile(`${taskDir}/review.md`);
  if (!review) {
    const reviewFiles: string[] = [];
    try {
      for await (const entry of Deno.readDir(taskDir)) {
        if (
          entry.isFile && entry.name.startsWith("review-") &&
          entry.name.endsWith(".md")
        ) {
          reviewFiles.push(entry.name);
        }
      }
    } catch { /* ignore */ }
    reviewFiles.sort();
    if (reviewFiles.length > 0) {
      review = await readTextFile(
        `${taskDir}/${reviewFiles[reviewFiles.length - 1]}`,
      );
    }
  }

  // Collect trace files
  const tracesDir = `${taskDir}/traces`;
  const traceFiles: string[] = [];
  try {
    for await (const entry of Deno.readDir(tracesDir)) {
      if (entry.isFile && entry.name.endsWith(".md")) {
        traceFiles.push(entry.name);
      }
    }
  } catch {
    // traces directory may not exist
  }
  traceFiles.sort();

  if (!status && !spec) {
    if (!(await dirExists(taskDir))) {
      return c.json({ error: "Task not found" }, 404);
    }
    // Task directory exists but files not ready yet — return partial data
  }

  const worktreeMetaPath = `${baseDir}/worktrees/${id}-${taskId}.meta.json`;
  const worktreeMeta = await readJsonFile<{
    path?: string;
    branch?: string;
    state?: string;
    last_activity_at?: string;
  }>(worktreeMetaPath);

  return c.json({
    id: taskId,
    requestId: id,
    duration,
    status: status ?? { id: taskId, status: "unknown" },
    spec: spec ?? null,
    review: review ?? null,
    feedback: feedback ?? null,
    traces: traceFiles,
    worktree: worktreeMeta
      ? {
        path: worktreeMeta.path ?? null,
        branch: worktreeMeta.branch ?? null,
        state: worktreeMeta.state ?? null,
        last_activity_at: worktreeMeta.last_activity_at ?? null,
      }
      : null,
  });
});

projectRequestsApi.get("/requests/:id/tasks/:taskId/log-stream", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const requestId = c.req.param("id");
  const taskId = c.req.param("taskId");
  if (isInvalidPathPart(requestId) || isInvalidPathPart(taskId)) {
    return c.json({ error: "Invalid request/task id" }, 400);
  }

  const requestDir = await resolveRequestDir(baseDir, requestId);
  if (!requestDir) {
    return c.json({ error: "Task not found" }, 404);
  }

  const taskDir = `${requestDir}/tasks/${taskId}`;
  const lastEventIdHeader = c.req.header("Last-Event-ID");
  const resumeOffset = lastEventIdHeader
    ? parseInt(lastEventIdHeader, 10) || null
    : null;
  try {
    const taskStat = await Deno.stat(taskDir);
    if (!taskStat.isDirectory) {
      return c.json({ error: "Task not found" }, 404);
    }
  } catch {
    return c.json({ error: "Task not found" }, 404);
  }

  const runningLog = `${taskDir}/running.log`;
  const decoder = new TextDecoder();

  const stream = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder();
      const CHECK_INTERVAL_MS = 30000;
      let closed = false;
      let watcher: Deno.FsWatcher | null = null;
      let offset = 0;
      let keepAliveInterval: number | null = null;

      const cleanup = () => {
        closed = true;
        if (keepAliveInterval !== null) {
          clearInterval(keepAliveInterval);
          keepAliveInterval = null;
        }
        if (watcher) {
          try {
            watcher.close();
          } catch { /* ignore */ }
          watcher = null;
        }
      };

      const send = async (lines: string[], currentOffset: number) => {
        if (closed || lines.length === 0) return;
        const payload = JSON.stringify({
          type: "log_line",
          requestId,
          taskId,
          data: {
            lines,
            timestamp: new Date().toISOString(),
          },
        });
        controller.enqueue(
          encoder.encode(
            `id: ${currentOffset}\nevent: log_line\ndata: ${payload}\n\n`,
          ),
        );
      };

      const sendInitialContent = async () => {
        try {
          const bytes = await Deno.readFile(runningLog);
          if (resumeOffset !== null && resumeOffset <= bytes.length) {
            const added = bytes.slice(resumeOffset);
            offset = resumeOffset;
            if (added.length > 0) {
              await send(splitLogLines(decoder.decode(added)), bytes.length);
            } else {
              offset = bytes.length;
            }
          } else if (resumeOffset === null) {
            offset = bytes.length;
            await send(splitLogLines(decoder.decode(bytes)), offset);
          } else {
            offset = bytes.length;
          }
        } catch {
          offset = 0;
        }
      };

      const sendNewContent = async () => {
        try {
          const bytes = await Deno.readFile(runningLog);
          if (bytes.length < offset) {
            offset = 0;
          }
          const added = bytes.slice(offset);
          offset = bytes.length;
          if (added.length === 0) return;
          await send(splitLogLines(decoder.decode(added)), offset);
        } catch {
          // ignore read errors
        }
      };

      const isRequestFinished = async (): Promise<boolean> => {
        try {
          const requestJson = await readJsonFile<{ status?: string }>(
            `${requestDir}/request.json`,
          );
          return ["completed", "done", "failed"].includes(
            requestJson?.status ?? "",
          );
        } catch {
          return false;
        }
      };

      const waitForFile = async () => {
        while (!closed) {
          try {
            await Deno.stat(runningLog);
            return;
          } catch {
            if (await isRequestFinished()) {
              const noLogPayload = JSON.stringify({
                type: "no_log",
                requestId,
                taskId,
              });
              controller.enqueue(
                encoder.encode(`event: no_log\ndata: ${noLogPayload}\n\n`),
              );
              closed = true;
              return;
            }
            watcher = Deno.watchFs(taskDir);
            if (closed) {
              try {
                watcher.close();
              } catch { /* ignore */ }
              watcher = null;
              return;
            }
            try {
              for await (const event of watcher) {
                if (closed) break;
                const matched = event.paths.some((path) =>
                  path.endsWith("/running.log") ||
                  path.endsWith("\\running.log")
                );
                if (matched) {
                  break;
                }
              }
            } finally {
              watcher?.close();
              watcher = null;
            }
            if (closed) break;
          }
        }
      };

      const waitForRunningLogEvent = async (): Promise<"event"> => {
        const watched = watcher;
        if (!watched) return "event";
        return new Promise<"event">((resolve) => {
          (async () => {
            try {
              for await (const event of watched) {
                const isRunningLog = event.paths.some((path: string) =>
                  path.endsWith("/running.log") ||
                  path.endsWith("\\running.log")
                );
                if (isRunningLog) {
                  resolve("event");
                  return;
                }
              }
            } catch {
              // ignore
            }
            resolve("event");
          })();
        });
      };

      c.req.raw.signal?.addEventListener("abort", () => {
        cleanup();
        try {
          controller.close();
        } catch { /* ignore */ }
      }, { once: true });

      try {
        await waitForFile();
        if (closed) return;
        await sendInitialContent();

        keepAliveInterval = setInterval(() => {
          if (closed) {
            clearInterval(keepAliveInterval!);
            keepAliveInterval = null;
            return;
          }
          try {
            controller.enqueue(encoder.encode(": ping\n\n"));
          } catch {
            clearInterval(keepAliveInterval!);
            keepAliveInterval = null;
          }
        }, CHECK_INTERVAL_MS);

        watcher = Deno.watchFs(taskDir);
        let waitingForRunningLog = waitForRunningLogEvent();

        while (!closed) {
          const result = await Promise.race([
            waitingForRunningLog,
            new Promise<"timer">((resolve) =>
              setTimeout(() => resolve("timer"), CHECK_INTERVAL_MS)
            ),
          ]);

          if (closed) break;
          if (result === "timer") {
            if (await isRequestFinished()) {
              cleanup();
              break;
            }
            continue;
          }

          await sendNewContent();
          waitingForRunningLog = waitForRunningLogEvent();
        }
      } finally {
        cleanup();
        try {
          controller.close();
        } catch { /* ignore */ }
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
});

// ─── API: Task Traces ──────────────────────────────────────────────────────

projectRequestsApi.get("/requests/:id/tasks/:taskId/traces", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  const taskId = c.req.param("taskId");
  if (isInvalidPathPart(id) || isInvalidPathPart(taskId)) {
    return c.json({ error: "Invalid request/task id" }, 400);
  }
  const requestDir = await resolveRequestDir(baseDir, id);
  if (!requestDir) {
    return c.json([]);
  }

  const tracesDir = `${requestDir}/tasks/${taskId}/traces`;

  if (!(await dirExists(tracesDir))) {
    return c.json([]);
  }

  const traceFiles: {
    name: string;
    agent: string;
    label: string;
    timestamp: string;
  }[] = [];
  try {
    for await (const entry of Deno.readDir(tracesDir)) {
      if (entry.isFile && entry.name.endsWith(".md")) {
        // Parse filename: {agent}-{label}-{YYYYMMDD-HHmmss}.md
        const match = entry.name.match(
          /^(codex|gemini|claude)-(.+)-(\d{8}-\d{6})\.md$/,
        );
        if (match) {
          traceFiles.push({
            name: entry.name,
            agent: match[1],
            label: match[2],
            timestamp: match[3],
          });
        } else {
          traceFiles.push({
            name: entry.name,
            agent: "unknown",
            label: entry.name.replace(/\.md$/, ""),
            timestamp: "",
          });
        }
      }
    }
  } catch {
    // directory read error
  }

  traceFiles.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  return c.json(traceFiles);
});

projectRequestsApi.get(
  "/requests/:id/tasks/:taskId/traces/:traceFile",
  async (c) => {
    const baseDir = resolveBaseDir(c.req.param("projectId"));
    if (!baseDir) {
      return c.json({ error: "Project not found" }, 404);
    }

    const id = c.req.param("id");
    const taskId = c.req.param("taskId");
    const traceFile = c.req.param("traceFile");
    const requestDir = await resolveRequestDir(baseDir, id);
    if (!requestDir) {
      return c.json({ error: "Trace file not found" }, 404);
    }

    // Prevent directory traversal
    if (traceFile.includes("..") || traceFile.includes("/")) {
      return c.json({ error: "Invalid trace file name" }, 400);
    }

    const content = await readTextFile(
      `${requestDir}/tasks/${taskId}/traces/${traceFile}`,
    );
    if (content === null) {
      return c.json({ error: "Trace file not found" }, 404);
    }

    return c.json({ name: traceFile, content });
  },
);

export { projectRequestsApi };
