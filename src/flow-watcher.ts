import {
  basename,
  dirname,
  join,
  normalize,
} from "https://deno.land/std@0.224.0/path/mod.ts";
import { BASE_DIR } from "./config.ts";

export type FlowEvent = Record<string, unknown> & {
  session_id?: string;
  timestamp?: string;
  ts?: string;
};

export type ExecutionFlowView = Record<string, unknown> & {
  view_kind: "dod017.execution-flow.dashboard-view";
  mst_session_id?: string;
};

type Subscriber = (event: FlowEvent) => void;

const FLOW_DETAIL_FILENAME = "flow-detail.ndjson";
const EXECUTION_FLOW_FILENAME = "execution-flow.json";
const POLL_INTERVAL_MS = 250;

const subscribers = new Map<string, Set<Subscriber>>();
const sessionFilePositions = new Map<string, number>();
const pendingFragments = new Map<string, string>();
const watcherStarted = new Set<string>();
const activeWatchers = new Map<string, Deno.FsWatcher>();
const activePollers = new Map<string, number>();

function normalizeBaseDir(baseDir: string): string {
  return normalize(baseDir || BASE_DIR);
}

function subscriberKey(baseDir: string, agiId: string): string {
  return `${normalizeBaseDir(baseDir)}\0${agiId}`;
}

function stateDirFor(baseDir: string): string {
  return join(normalizeBaseDir(baseDir), "state");
}

function sessionsDirFor(baseDir: string): string {
  return join(normalizeBaseDir(baseDir), "sessions");
}

function sessionIdFromFlowPath(path: string): string | undefined {
  const name = basename(path);
  if (name !== FLOW_DETAIL_FILENAME) return undefined;
  return basename(dirname(path));
}

function flowTimestamp(event: FlowEvent): string {
  const value = event.ts ?? event.timestamp ?? "";
  return typeof value === "string" ? value : String(value);
}

function parseFlowLine(line: string, sessionId?: string): FlowEvent | null {
  const trimmed = line.trim();
  if (!trimmed) return null;

  try {
    const parsed = JSON.parse(trimmed);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return {
      ...(parsed as Record<string, unknown>),
      session_id: typeof parsed.session_id === "string"
        ? parsed.session_id
        : sessionId,
    };
  } catch {
    return null;
  }
}

async function listFlowFiles(baseDir: string): Promise<string[]> {
  const stateDir = stateDirFor(baseDir);
  const files: string[] = [];

  try {
    for await (const entry of Deno.readDir(stateDir)) {
      if (!entry.isDirectory) continue;
      files.push(join(stateDir, entry.name, FLOW_DETAIL_FILENAME));
    }
  } catch {
    return [];
  }

  return files;
}

async function listExecutionFlowFiles(baseDir: string): Promise<string[]> {
  const sessionsDir = sessionsDirFor(baseDir);
  const files: string[] = [];

  try {
    for await (const entry of Deno.readDir(sessionsDir)) {
      if (!entry.isDirectory) continue;
      files.push(join(sessionsDir, entry.name, EXECUTION_FLOW_FILENAME));
    }
  } catch {
    return [];
  }

  return files;
}

async function primeExistingFilePositions(baseDir: string): Promise<void> {
  for (const path of await listFlowFiles(baseDir)) {
    try {
      const stat = await Deno.stat(path);
      sessionFilePositions.set(path, stat.size);
      pendingFragments.delete(path);
    } catch {
      // ignore missing per-session files
    }
  }
}

export async function getFlowEvents(
  _agiId: string,
  baseDir = BASE_DIR,
): Promise<FlowEvent[]> {
  const events: FlowEvent[] = [];

  for (const path of await listFlowFiles(baseDir)) {
    const sessionId = sessionIdFromFlowPath(path);
    try {
      const text = await Deno.readTextFile(path);
      for (const line of text.split("\n")) {
        const event = parseFlowLine(line, sessionId);
        if (event) events.push(event);
      }
    } catch {
      // ignore sessions without flow logs
    }
  }

  events.sort((a, b) => flowTimestamp(a).localeCompare(flowTimestamp(b)));
  return events;
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

async function readCurrentHistoryHead(sessionDir: string): Promise<string | undefined> {
  try {
    return (await Deno.readTextFile(join(sessionDir, "history.head"))).trim() ||
      undefined;
  } catch {
    return undefined;
  }
}

async function dashboardViewFromProjection(path: string): Promise<ExecutionFlowView | null> {
  try {
    const parsed = JSON.parse(await Deno.readTextFile(path));
    const projection = objectRecord(parsed);
    if (!Object.keys(projection).length) return null;

    const source = objectRecord(projection.source);
    const coverage = objectRecord(projection.coverage);
    const nodes = Array.isArray(projection.nodes) ? projection.nodes : [];
    const edges = Array.isArray(projection.edges) ? projection.edges : [];
    const currentHead = await readCurrentHistoryHead(dirname(path));
    const sourceHead = stringValue(source.history_head);
    const sourceHash = stringValue(source.source_hash) ??
      stringValue(source.cumulative_hash);
    const stale = Boolean(
      currentHead && sourceHead &&
        (sourceHead !== currentHead || (sourceHash && sourceHash !== currentHead)),
    );

    return {
      view_kind: "dod017.execution-flow.dashboard-view",
      schema_version: 1,
      projection_kind: projection.projection_kind ?? "dod017.execution-flow",
      mst_session_id: stringValue(projection.mst_session_id),
      root_mst_id: stringValue(projection.root_mst_id),
      source: {
        source_kind: source.source_kind ?? "verified_history_ledger",
        ledger_path: source.ledger_path,
        history_head: source.history_head,
        source_hash: sourceHash,
        projection_schema_version: projection.projection_schema_version,
        projection_hash: projection.projection_hash,
        projection_created_at: projection.projection_created_at ??
          source.projection_created_at,
      },
      projection_status: {
        stale,
        drift: stale,
        read_only: stale,
        regenerate_required: stale,
        source_history_head: sourceHead,
        current_history_head: currentHead ?? sourceHead,
      },
      coverage: {
        recognized_event_families: Array.isArray(coverage.recognized_event_families)
          ? coverage.recognized_event_families
          : [],
        missing_event_families: Array.isArray(coverage.missing_event_families)
          ? coverage.missing_event_families
          : [],
        required_event_families: Array.isArray(coverage.required_event_families)
          ? coverage.required_event_families
          : [],
        node_count: nodes.length,
        edge_count: edges.length,
      },
      current_node: projection.current_node,
      last_transition: projection.last_transition,
      next_action: projection.next_action,
      blocker: projection.blocker,
      views: projection.views ?? {},
      display_only: true,
      derived_artifact: true,
      next_action_authority: false,
      transition_authority: "dod016_transition_graph",
    };
  } catch {
    return null;
  }
}

export async function getExecutionFlowViews(
  _agiId: string,
  baseDir = BASE_DIR,
): Promise<ExecutionFlowView[]> {
  const views: ExecutionFlowView[] = [];
  for (const path of await listExecutionFlowFiles(baseDir)) {
    const view = await dashboardViewFromProjection(path);
    if (view) views.push(view);
  }
  return views.sort((a, b) =>
    String(a.mst_session_id ?? "").localeCompare(String(b.mst_session_id ?? ""))
  );
}

export function subscribeFlowSse(
  agiId: string,
  send: Subscriber,
  baseDir = BASE_DIR,
): () => void {
  const key = subscriberKey(baseDir, agiId);
  let set = subscribers.get(key);
  if (!set) {
    set = new Set();
    subscribers.set(key, set);
  }

  set.add(send);
  return () => {
    set?.delete(send);
    if (set?.size === 0) {
      subscribers.delete(key);
    }
  };
}

export async function initFlowWatcher(baseDir = BASE_DIR): Promise<void> {
  const normalizedBaseDir = normalizeBaseDir(baseDir);
  if (watcherStarted.has(normalizedBaseDir)) return;
  watcherStarted.add(normalizedBaseDir);

  const stateDir = stateDirFor(normalizedBaseDir);
  await Deno.mkdir(stateDir, { recursive: true }).catch(() => {});
  await primeExistingFilePositions(normalizedBaseDir);

  let watcher: Deno.FsWatcher;
  try {
    watcher = Deno.watchFs(stateDir, { recursive: true });
  } catch {
    startPoller(normalizedBaseDir);
    return;
  }

  activeWatchers.set(normalizedBaseDir, watcher);
  startPoller(normalizedBaseDir);

  void (async () => {
    try {
      for await (const event of watcher) {
        if (event.kind !== "create" && event.kind !== "modify") continue;

        for (const path of event.paths) {
          if (!path.endsWith(FLOW_DETAIL_FILENAME)) continue;

          const newEvents = await readNewLines(path);
          for (const flowEvent of newEvents) {
            broadcastFlowEvent(normalizedBaseDir, flowEvent);
          }
        }
      }
    } catch {
      // watcher closed or unavailable
    } finally {
      activeWatchers.delete(normalizedBaseDir);
      watcherStarted.delete(normalizedBaseDir);
      const poller = activePollers.get(normalizedBaseDir);
      if (poller !== undefined) {
        clearInterval(poller);
        activePollers.delete(normalizedBaseDir);
      }
    }
  })();
}

function startPoller(baseDir: string): void {
  if (activePollers.has(baseDir)) return;

  activePollers.set(
    baseDir,
    setInterval(() => {
      void pollFlowFiles(baseDir);
    }, POLL_INTERVAL_MS),
  );
}

async function pollFlowFiles(baseDir: string): Promise<void> {
  for (const path of await listFlowFiles(baseDir)) {
    const newEvents = await readNewLines(path);
    for (const flowEvent of newEvents) {
      broadcastFlowEvent(baseDir, flowEvent);
    }
  }
}

function broadcastFlowEvent(baseDir: string, event: FlowEvent): void {
  const prefix = `${normalizeBaseDir(baseDir)}\0`;
  for (const [key, set] of subscribers.entries()) {
    if (!key.startsWith(prefix)) continue;

    for (const send of set) {
      try {
        send(event);
      } catch {
        // ignore per-subscriber failures
      }
    }
  }
}

async function readNewLines(path: string): Promise<FlowEvent[]> {
  let file: Deno.FsFile | null = null;

  try {
    const stat = await Deno.stat(path);
    const lastPos = sessionFilePositions.get(path) ?? 0;

    if (stat.size <= lastPos) {
      sessionFilePositions.set(path, stat.size);
      pendingFragments.delete(path);
      return [];
    }

    file = await Deno.open(path, { read: true });
    await file.seek(lastPos, Deno.SeekMode.Start);

    const buf = new Uint8Array(stat.size - lastPos);
    const bytesRead = await file.read(buf);
    sessionFilePositions.set(path, stat.size);

    if (!bytesRead) return [];

    const chunk = new TextDecoder().decode(buf.subarray(0, bytesRead));
    const combined = `${pendingFragments.get(path) ?? ""}${chunk}`;
    const parts = combined.split("\n");

    if (combined.endsWith("\n")) {
      pendingFragments.delete(path);
    } else {
      pendingFragments.set(path, parts.pop() ?? "");
    }

    const sessionId = sessionIdFromFlowPath(path);
    const events: FlowEvent[] = [];
    for (const line of parts) {
      const event = parseFlowLine(line, sessionId);
      if (event) events.push(event);
    }
    return events;
  } catch {
    return [];
  } finally {
    try {
      file?.close();
    } catch {
      // ignore close failure
    }
  }
}

export function closeFlowWatchersForTest(): void {
  for (const watcher of activeWatchers.values()) {
    try {
      watcher.close();
    } catch {
      // ignore already closed watchers
    }
  }
  for (const poller of activePollers.values()) {
    clearInterval(poller);
  }
  activeWatchers.clear();
  activePollers.clear();
  watcherStarted.clear();
  subscribers.clear();
  sessionFilePositions.clear();
  pendingFragments.clear();
}
