import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import type { DiscussionSession, SessionParticipant } from "../types.ts";
import { dirExists, listDirs, readJsonFile, readTextFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

const projectDiscussionApi = new Hono();

function getKeyRole(key: string): string {
  const match = key.match(/^(.+)\(([^()]+)\)$/);
  return match?.[1] ? match[1] : key;
}

function getKeyProvider(key: string): string {
  const match = key.match(/\(([^()]+)\)$/);
  return match?.[1] ? match[1] : key;
}

function getLegacyKey(key: string): string {
  return key.includes("(") ? key.slice(0, key.indexOf("(")) : "";
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

  return [];
}

async function readRoundResponse(roundPath: string, key: string): Promise<string | null> {
  const direct = await readTextFile(`${roundPath}/${key}.md`);
  if (direct !== null) return direct;

  const legacyKey = getLegacyKey(key);
  if (!legacyKey) return null;
  return await readTextFile(`${roundPath}/${legacyKey}.md`);
}

projectDiscussionApi.get("/discussion", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const discussionDir = `${baseDir}/discussion`;
  if (!(await dirExists(discussionDir))) {
    return c.json([]);
  }

  const dirs = await listDirs(discussionDir);
  const sessions: DiscussionSession[] = [];

  for (const dir of dirs) {
    const sessionJsonPath = `${discussionDir}/${dir}/session.json`;
    const sessionJson = await readJsonFile<DiscussionSession>(sessionJsonPath);
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

projectDiscussionApi.get("/discussion/:id", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const id = c.req.param("id");
  const sessionDir = `${baseDir}/discussion/${id}`;

  const session = await readJsonFile<DiscussionSession>(
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

  const rounds: Array<{
    round: number;
    responses: Record<string, string | null>;
    critiques: Record<string, string | null>;
    synthesis: string | null;
  }> = [];

  const roundsDir = `${sessionDir}/rounds`;
  if (await dirExists(roundsDir)) {
    const roundDirs = (await listDirs(roundsDir)).sort();
    const keyList = participantKeys.length > 0
      ? participantKeys
      : ["codex", "gemini", "claude"];
    const criticKeys = Object.keys((session.critics || {}));
    for (const rd of roundDirs) {
      const roundPath = `${roundsDir}/${rd}`;
      const responses: Record<string, string | null> = {};
      for (const key of keyList) {
        responses[key] = await readRoundResponse(roundPath, key);
      }

      const roundCritiques: Record<string, string | null> = {};
      for (const key of criticKeys) {
        roundCritiques[key] = await readTextFile(`${roundPath}/critique-${key}.md`);
      }

      rounds.push({
        round: parseInt(rd, 10),
        responses,
        critiques: roundCritiques,
        synthesis: await readTextFile(`${roundPath}/synthesis.md`),
      });
    }
  }

  const consensus = await readTextFile(`${sessionDir}/consensus.md`);

  return c.json({
    ...session,
    id: session.id || id,
    participants,
    rounds,
    consensus,
  });
});

export { projectDiscussionApi };
