import {
  basename,
  dirname,
  join,
  normalize,
} from "https://deno.land/std@0.224.0/path/mod.ts";
import { BASE_DIR } from "./config.ts";

export type FlowEvent = Record<string, unknown> & {
  session_id?: string;
  mst_session_id?: string;
  timestamp?: string;
  ts?: string;
};

export type ExecutionFlowView = Record<string, unknown> & {
  view_kind: "dod017.execution-flow.dashboard-view";
  mst_session_id?: string;
};

export type GraphConsistencyDiagnostic = {
  code: string;
  severity: "info" | "warning" | "error";
  detail: string;
  mst_session_id?: string;
  legacy_session_id?: string;
  field?: string;
};

export type GraphConsistency = {
  status: "consistent" | "degraded" | "mismatch";
  diagnostics: GraphConsistencyDiagnostic[];
  event_count: number;
  joined_event_count: number;
  orphan_event_count?: number;
};

export type SessionGraphView = Record<string, unknown> & {
  view_kind: "gran-maestro.session-graph.dashboard-view";
  mst_session_id: string;
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  events: FlowEvent[];
  worktrees: {
    session: Record<string, unknown> | null;
    children: Record<string, unknown>[];
  };
  recovery_action: unknown;
  graph_consistency: GraphConsistency;
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

function lifecycleEventFamily(eventType: string | undefined): string {
  if (!eventType) return "unknown";
  if (eventType.startsWith("session_")) return "session";
  if (eventType.startsWith("child_")) return "child";
  if (eventType.includes("worktree")) return "worktree";
  if (eventType.includes("cleanup")) return "cleanup";
  if (eventType.includes("recovery")) return "recovery";
  return eventType.split("_", 1)[0] || "unknown";
}

function flowEventIdentity(event: FlowEvent): string | undefined {
  return stringValue(event.idempotency_key) ?? stringValue(event.event_id);
}

function normalizeLifecycleEvent(event: FlowEvent): FlowEvent {
  const eventType = stringValue(event.event_type);
  const canonical = eventCanonicalSessionId(event);
  const timestamp = flowTimestamp(event);
  const identity = flowEventIdentity(event) ?? [canonical, eventType, timestamp].filter(Boolean).join(":");
  return {
    schema_version: event.schema_version ?? 1,
    ...event,
    event_id: stringValue(event.event_id) ?? identity,
    idempotency_key: stringValue(event.idempotency_key) ?? identity,
    ordering_key: stringValue(event.ordering_key) ?? timestamp,
    event_family: stringValue(event.event_family) ?? lifecycleEventFamily(eventType),
    replay_compatible: canonical ? event.replay_compatible ?? true : false,
  };
}

function normalizeLifecycleEvents(events: FlowEvent[]): {
  events: FlowEvent[];
  diagnostics: GraphConsistencyDiagnostic[];
} {
  const diagnostics: GraphConsistencyDiagnostic[] = [];
  const seen = new Set<string>();
  const normalized: FlowEvent[] = [];
  let previousSourceOrder = "";
  const sourceOrderedEvents = [...events].sort((a, b) => {
    const left = typeof a.__source_order === "number" ? a.__source_order : 0;
    const right = typeof b.__source_order === "number" ? b.__source_order : 0;
    return left - right;
  });
  for (const event of sourceOrderedEvents) {
    const item = normalizeLifecycleEvent(event);
    const orderingKey = stringValue(item.ordering_key) ?? flowTimestamp(item);
    if (previousSourceOrder && orderingKey && orderingKey < previousSourceOrder) {
      diagnostics.push({
        code: "out_of_order_lifecycle_event",
        severity: "warning",
        detail: "lifecycle event source order differs from replay ordering",
        mst_session_id: eventCanonicalSessionId(item),
      });
    }
    if (orderingKey) previousSourceOrder = orderingKey;

    const identity = flowEventIdentity(item);
    if (identity && seen.has(identity)) {
      diagnostics.push({
        code: "duplicate_lifecycle_event",
        severity: "warning",
        detail: "duplicate lifecycle event idempotency key ignored",
        mst_session_id: eventCanonicalSessionId(item),
        field: "idempotency_key",
        idempotency_key: identity,
      } as GraphConsistencyDiagnostic & { idempotency_key: string });
      continue;
    }
    if (identity) seen.add(identity);
    normalized.push(item);
  }
  normalized.sort((a, b) => {
    const left = stringValue(a.ordering_key) ?? flowTimestamp(a);
    const right = stringValue(b.ordering_key) ?? flowTimestamp(b);
    return left.localeCompare(right);
  });
  return { events: normalized, diagnostics };
}

function parseFlowLine(line: string, sessionId?: string): FlowEvent | null {
  const trimmed = line.trim();
  if (!trimmed) return null;

  try {
    const parsed = JSON.parse(trimmed);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return normalizeLifecycleEvent({
      ...(parsed as Record<string, unknown>),
      session_id: typeof parsed.session_id === "string"
        ? parsed.session_id
        : sessionId,
    });
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
  let sourceOrder = 0;

  for (const path of await listFlowFiles(baseDir)) {
    const sessionId = sessionIdFromFlowPath(path);
    try {
      const text = await Deno.readTextFile(path);
      for (const line of text.split("\n")) {
        const event = parseFlowLine(line, sessionId);
        if (event) events.push({ ...event, __source_order: sourceOrder++ });
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

function arrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item) => item && typeof item === "object" && !Array.isArray(item)) as Record<string, unknown>[]
    : [];
}

function eventCanonicalSessionId(event: FlowEvent): string | undefined {
  return stringValue(event.mst_session_id);
}

function eventLegacySessionId(event: FlowEvent): string | undefined {
  return stringValue(event.session_id);
}

function eventSessionId(event: FlowEvent): string | undefined {
  return eventCanonicalSessionId(event) ?? eventLegacySessionId(event);
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
    const nodes = arrayRecords(projection.nodes);
    const edges = arrayRecords(projection.edges);
    const projectionWorktrees = objectRecord(projection.worktrees);
    const sessionWorktree = objectRecord(projection.session_worktree);
    const nestedSessionWorktree = objectRecord(projectionWorktrees.session);
    const childWorktrees = arrayRecords(projection.child_worktrees);
    const nestedChildWorktrees = arrayRecords(projectionWorktrees.children);
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
      nodes,
      edges,
      worktrees: {
        session: Object.keys(sessionWorktree).length
          ? sessionWorktree
          : Object.keys(nestedSessionWorktree).length
          ? nestedSessionWorktree
          : null,
        children: childWorktrees.length ? childWorktrees : nestedChildWorktrees,
      },
      recovery_action: projection.recovery_action ?? objectRecord(projection.recovery).primary_action ?? null,
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

function diagnosticStatus(
  diagnostics: GraphConsistencyDiagnostic[],
): GraphConsistency["status"] {
  if (diagnostics.some((diagnostic) => diagnostic.severity === "error")) {
    return "mismatch";
  }
  if (diagnostics.length) return "degraded";
  return "consistent";
}

function fieldSessionMismatchDiagnostic(
  mstSessionId: string,
  source: Record<string, unknown>,
  field: string,
): GraphConsistencyDiagnostic | undefined {
  const value = stringValue(source[field]);
  if (!value || value === mstSessionId) return undefined;
  return {
    code: "worktree_session_mismatch",
    severity: "error",
    detail: `${field} does not match graph mst_session_id`,
    mst_session_id: mstSessionId,
    field,
  };
}

function worktreeSessionDiagnostics(
  mstSessionId: string,
  worktrees: { session: Record<string, unknown> | null; children: Record<string, unknown>[] },
): GraphConsistencyDiagnostic[] {
  const diagnostics: GraphConsistencyDiagnostic[] = [];
  if (worktrees.session) {
    const diagnostic = fieldSessionMismatchDiagnostic(
      mstSessionId,
      worktrees.session,
      "mst_session_id",
    );
    if (diagnostic) diagnostics.push(diagnostic);
  }

  for (const child of worktrees.children) {
    const diagnostic = fieldSessionMismatchDiagnostic(
      mstSessionId,
      child,
      "parent_mst_session_id",
    ) ?? fieldSessionMismatchDiagnostic(mstSessionId, child, "mst_session_id");
    if (diagnostic) diagnostics.push(diagnostic);
  }
  return diagnostics;
}

function eventConsistencyDiagnostics(
  mstSessionId: string,
  events: FlowEvent[],
): GraphConsistencyDiagnostic[] {
  const diagnostics: GraphConsistencyDiagnostic[] = [];
  for (const event of events) {
    const canonical = eventCanonicalSessionId(event);
    const legacy = eventLegacySessionId(event);
    if (canonical === mstSessionId && legacy && legacy !== mstSessionId) {
      diagnostics.push({
        code: "legacy_session_id_mismatch",
        severity: "warning",
        detail: "event legacy session_id differs from canonical mst_session_id",
        mst_session_id: mstSessionId,
        legacy_session_id: legacy,
      });
    }
  }
  return diagnostics;
}

export function getFlowViewConsistencyDiagnostics(
  events: FlowEvent[],
  executionFlowViews: ExecutionFlowView[],
): GraphConsistencyDiagnostic[] {
  const projectedSessionIds = new Set(
    executionFlowViews
      .map((view) => stringValue(view.mst_session_id))
      .filter((value): value is string => Boolean(value)),
  );
  const diagnostics: GraphConsistencyDiagnostic[] = [];

  for (const event of events) {
    const canonical = eventCanonicalSessionId(event);
    const legacy = eventLegacySessionId(event);
    if (!canonical && legacy) {
      diagnostics.push({
        code: "legacy_only_event",
        severity: "warning",
        detail: "event has legacy session_id but no canonical mst_session_id",
        legacy_session_id: legacy,
      });
      continue;
    }
    if (canonical && !projectedSessionIds.has(canonical)) {
      diagnostics.push({
        code: "orphan_flow_event",
        severity: "warning",
        detail: "event has canonical mst_session_id without execution-flow projection",
        mst_session_id: canonical,
        legacy_session_id: legacy,
      });
    }
  }

  return diagnostics;
}

export function buildSessionGraphViews(
  events: FlowEvent[],
  executionFlowViews: ExecutionFlowView[],
): SessionGraphView[] {
  return executionFlowViews
    .filter((view) => Boolean(view.mst_session_id))
    .map((view) => {
      const mstSessionId = String(view.mst_session_id);
      const viewWorktrees = objectRecord(view.worktrees);
      const sessionWorktree = objectRecord(viewWorktrees.session);
      const children = arrayRecords(viewWorktrees.children);
      const worktrees = {
        session: Object.keys(sessionWorktree).length ? sessionWorktree : null,
        children,
      };
      const recovery = objectRecord(view.recovery);
      const joinedEventState = normalizeLifecycleEvents(
        events.filter((event) => eventCanonicalSessionId(event) === mstSessionId),
      );
      const joinedEvents = joinedEventState.events;
      const diagnostics = [
        ...joinedEventState.diagnostics,
        ...eventConsistencyDiagnostics(mstSessionId, joinedEvents),
        ...worktreeSessionDiagnostics(mstSessionId, worktrees),
      ];
      return {
        view_kind: "gran-maestro.session-graph.dashboard-view",
        schema_version: 1,
        mst_session_id: mstSessionId,
        root_mst_id: view.root_mst_id,
        status: view.blocker ? "blocked" : "active",
        nodes: arrayRecords(view.nodes),
        edges: arrayRecords(view.edges),
        events: joinedEvents,
        current_node: view.current_node,
        last_transition: view.last_transition,
        next_action: view.next_action ?? null,
        blocker: view.blocker ?? null,
        coverage: view.coverage ?? {},
        worktrees,
        recovery_action: view.recovery_action ?? recovery.primary_action ?? null,
        projection_status: view.projection_status ?? {},
        graph_consistency: {
          status: diagnosticStatus(diagnostics),
          diagnostics,
          event_count: events.length,
          joined_event_count: joinedEvents.length,
        },
        display_only: true,
        next_action_authority: false,
        transition_authority: "dod016_transition_graph",
      };
    });
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
