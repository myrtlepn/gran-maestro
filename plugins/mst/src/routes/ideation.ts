import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import type { IdeationSession, SessionParticipant } from "../types.ts";
import { dirExists, listDirs, readJsonFile, readTextFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

const projectIdeationApi = new Hono();
const LEGACY_AGENTS = new Set(["codex", "gemini", "claude"]);

function getKeyRole(key: string): string {
  const match = key.match(/^(.+)\(([^()]+)\)$/);
  return match?.[1] ? match[1] : key;
}

function getKeyProvider(key: string): string {
  const match = key.match(/\(([^()]+)\)$/);
  return match?.[1] ? match[1] : key;
}

function normalizeStatus(value: unknown): string {
  if (
    value &&
    typeof value === "object" &&
    "status" in (value as Record<string, unknown>)
  ) {
    const status = (value as Record<string, unknown>).status;
    if (typeof status === "string") return status;
  }
  return "pending";
}

function normalizeParticipants(session: Record<string, unknown>): SessionParticipant[] {
  const participants = session.participants;
  if (Array.isArray(participants)) {
    return participants
      .filter((entry): entry is Record<string, unknown> =>
        !!entry && typeof entry === "object"
      )
      .map((entry) => {
        const participant = entry as Record<string, unknown>;
        const key = typeof participant.key === "string" ? participant.key : "";
        const provider = typeof participant.provider === "string"
          ? participant.provider
          : key
          ? getKeyProvider(key)
          : "";
        return {
          key,
          role: typeof participant.role === "string"
            ? participant.role
            : getKeyRole(key),
          perspective: typeof participant.perspective === "string"
            ? participant.perspective
            : undefined,
          type: typeof participant.type === "string" ? participant.type : "opinion",
          status: normalizeStatus(participant),
          provider,
        };
      })
      .filter((participant) => participant.key);
  }

  const roles = session.roles;
  if (roles && typeof roles === "object" && !Array.isArray(roles)) {
    return Object.entries(roles).map(([key, value]) => {
      const role = value && typeof value === "object"
        ? value as Record<string, unknown>
        : {};
      const provider = typeof role.provider === "string"
        ? role.provider
        : getKeyProvider(key);
      return {
        key,
        role: typeof role.role === "string" ? role.role : getKeyRole(key),
        perspective: typeof role.perspective === "string"
          ? role.perspective
          : undefined,
        type: typeof role.type === "string" ? role.type : "opinion",
        status: normalizeStatus(role),
        provider,
      };
    });
  }

  const opinions = session.opinions;
  if (opinions && typeof opinions === "object" && !Array.isArray(opinions)) {
    return Object.entries(opinions).map(([key, value]) => ({
      key,
      role: getKeyRole(key),
      perspective: undefined,
      type: "opinion",
      status: normalizeStatus(value),
      provider: getKeyProvider(key),
    }));
  }

  return [];
}

function getLegacyParticipantKey(key: string): string {
  if (key.includes("(")) return key.slice(0, key.indexOf("("));
  return key;
}

async function readFileWithLegacyFallback(
  baseDir: string,
  key: string,
  prefix: string,
): Promise<string | null> {
  const direct = await readTextFile(`${baseDir}/${prefix}-${key}.md`);
  if (direct !== null) return direct;

  const legacyKey = getLegacyParticipantKey(key);
  if (!legacyKey || LEGACY_AGENTS.has(legacyKey)) return null;
  return await readTextFile(`${baseDir}/${prefix}-${legacyKey}.md`);
}

projectIdeationApi.get("/ideation", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const ideationDir = `${baseDir}/ideation`;
  if (!(await dirExists(ideationDir))) {
    return c.json([]);
  }

  const dirs = await listDirs(ideationDir);
  const sessions: IdeationSession[] = [];

  for (const dir of dirs) {
    const sessionJsonPath = `${ideationDir}/${dir}/session.json`;
    const sessionJson = await readJsonFile<IdeationSession>(sessionJsonPath);
    if (sessionJson) {
      const rawSession = sessionJson as Record<string, unknown>;
      const participants = normalizeParticipants(rawSession);
      let createdAt = sessionJson.created_at;
      if (!createdAt || createdAt.includes("T00:00:00")) {
        try {
          const stat = await Deno.stat(sessionJsonPath);
          if (stat.mtime) {
            createdAt = stat.mtime.toISOString();
          }
        } catch (_error) {
          // ignore fallback failure
        }
      }
      sessions.push({
        ...sessionJson,
        id: sessionJson.id || dir,
        created_at: createdAt,
        participants,
      });
    }
  }

  sessions.sort((a, b) => {
    const aTime = a.created_at ?? "";
    const bTime = b.created_at ?? "";
    return bTime.localeCompare(aTime);
  });

  return c.json(sessions);
});

projectIdeationApi.get("/ideation/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  const sessionDir = `${baseDir}/ideation/${id}`;

  const session = await readJsonFile<IdeationSession>(
    `${sessionDir}/session.json`
  );
  if (!session) {
    return c.json({ error: "Session not found" }, 404);
  }

  const rawSession = session as Record<string, unknown>;
  const participants = normalizeParticipants(rawSession);
  const participantKeys = participants.length > 0
    ? participants.map((p) => p.key)
    : ["codex", "gemini", "claude"];
  const keyList = participantKeys.length > 0 ? participantKeys : ["codex", "gemini", "claude"];

  const opinions: Record<string, string | null> = {};
  for (const key of keyList) {
    opinions[key] = await readFileWithLegacyFallback(sessionDir, key, "opinion");
  }

  const critiques: Record<string, string | null> = {};
  const critics = session.critics || {};
  for (const key of Object.keys(critics)) {
    critiques[key] = await readTextFile(`${sessionDir}/critique-${key}.md`);
  }
  const synthesis = await readTextFile(`${sessionDir}/synthesis.md`);
  const discussion = await readTextFile(`${sessionDir}/discussion.md`);

  return c.json({
    session: { ...session, id: session.id || id, participants },
    opinions,
    critiques,
    synthesis,
    discussion,
  });
});

export { projectIdeationApi };
