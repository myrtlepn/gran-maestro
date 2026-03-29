import { setRegistry } from "../config.ts";
import { projectAgileApi } from "./agile.ts";

type SessionSeed = Record<string, unknown> & {
  objective?: { path?: string; version?: number };
};

async function setupSessionFixture(
  session: SessionSeed,
  objectiveContent = "Initial objective",
): Promise<{ baseDir: string; cleanup: () => Promise<void> }> {
  const baseDir = await Deno.makeTempDir({ prefix: "agile-route-test-" });
  const sessionDir = `${baseDir}/agile/AGI-001`;

  await Deno.mkdir(`${sessionDir}/index`, { recursive: true });
  await Deno.mkdir(`${sessionDir}/objective`, { recursive: true });
  await Deno.writeTextFile(
    `${sessionDir}/session.json`,
    JSON.stringify(
      {
        id: "AGI-001",
        status: "running",
        current_sprint: 1,
        created_at: "2026-03-26T14:37:06.353708+00:00",
        updated_at: "2026-03-26T14:37:27.637313+00:00",
        objective: {
          path: "objective/objective.md",
          version: 2,
        },
        ...session,
      },
      null,
      2,
    ) + "\n",
  );
  await Deno.writeTextFile(
    `${sessionDir}/index/links.json`,
    JSON.stringify({ agi_id: "AGI-001", pln: ["PLN-1"], req: ["REQ-1"] }, null, 2) + "\n",
  );
  await Deno.writeTextFile(`${sessionDir}/objective/objective.md`, objectiveContent);

  return {
    baseDir,
    cleanup: async () => {
      await Deno.remove(baseDir, { recursive: true });
    },
  };
}

function createApp(baseDir: string) {
  setRegistry({
    projects: [
      {
        id: "proj-test",
        name: "test-project",
        path: baseDir,
        registered_at: "2026-03-29T00:00:00.000Z",
      },
    ],
  });
  return projectAgileApi;
}

Deno.test("GET /agile/sessions exposes steering_every, queue_size, refs_count", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
    queue: ["TASK-1", "TASK-2"],
    refs: ["PLN-1"],
  });

  try {
    const app = createApp(fixture.baseDir);
    const response = await app.request("http://localhost/agile/sessions");
    assertEquals(response.status, 200);

    const payload = await response.json() as Array<Record<string, unknown>>;
    assertEquals(payload.length, 1);
    assertEquals(payload[0].id, "AGI-001");
    assertEquals(payload[0].steering_every, 3);
    assertEquals(payload[0].queue_size, 2);
    assertEquals(payload[0].refs_count, 1);

    // Regression: existing fields still returned.
    assertEquals(payload[0].status, "running");
    assertEquals(payload[0].current_sprint, 1);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions and /agile/sessions/:agiId default queue/refs to empty arrays", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 5,
  });

  try {
    const app = createApp(fixture.baseDir);

    const listResponse = await app.request("http://localhost/agile/sessions");
    assertEquals(listResponse.status, 200);
    const listPayload = await listResponse.json() as Array<Record<string, unknown>>;
    assertEquals(listPayload.length, 1);
    assertEquals(listPayload[0].steering_every, 5);
    assertEquals(listPayload[0].queue_size, 0);
    assertEquals(listPayload[0].refs_count, 0);

    const detailResponse = await app.request("http://localhost/agile/sessions/AGI-001");
    assertEquals(detailResponse.status, 200);
    const detailPayload = await detailResponse.json() as { session: Record<string, unknown> };

    assertEquals(detailPayload.session.steering_every, 5);
    assertEquals(detailPayload.session.queue, []);
    assertEquals(detailPayload.session.refs, []);

    // Regression: existing links/objective blocks still returned.
    assert("links" in detailPayload);
    assert("session" in detailPayload);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/objective returns stable non-empty ETag", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective content A");

  try {
    const app = createApp(fixture.baseDir);

    const responseA = await app.request("http://localhost/agile/sessions/AGI-001/objective");
    assertEquals(responseA.status, 200);
    const etagA = responseA.headers.get("ETag");

    const responseB = await app.request("http://localhost/agile/sessions/AGI-001/objective");
    assertEquals(responseB.status, 200);
    const etagB = responseB.headers.get("ETag");

    assert(etagA !== null && etagA.length > 0);
    assertEquals(etagA, etagB);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("PUT /agile/sessions/:agiId/objective succeeds when If-Match matches current ETag", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective before update");

  try {
    const app = createApp(fixture.baseDir);

    const getBefore = await app.request("http://localhost/agile/sessions/AGI-001/objective");
    assertEquals(getBefore.status, 200);
    const etagBefore = getBefore.headers.get("ETag");
    assert(etagBefore !== null && etagBefore.length > 0);

    const putResponse = await app.request("http://localhost/agile/sessions/AGI-001/objective", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "If-Match": etagBefore,
      },
      body: JSON.stringify({ content: "Objective after update" }),
    });
    assertEquals(putResponse.status, 200);
    const etagFromPut = putResponse.headers.get("ETag");
    assert(etagFromPut !== null && etagFromPut.length > 0);

    const getAfter = await app.request("http://localhost/agile/sessions/AGI-001/objective");
    const payloadAfter = await getAfter.json() as { content: string };
    const etagAfter = getAfter.headers.get("ETag");

    assertEquals(payloadAfter.content, "Objective after update");
    assert(etagAfter !== null && etagAfter.length > 0);
    assert(etagAfter !== etagBefore);
    assertEquals(etagFromPut, etagAfter);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("PUT /agile/sessions/:agiId/objective revalidates If-Match immediately before write", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Original objective");

  const objectiveFile = `${fixture.baseDir}/agile/AGI-001/objective/objective.md`;
  const originalReadTextFile = Deno.readTextFile;
  const mutableDeno = Deno as unknown as { readTextFile: typeof Deno.readTextFile };
  let objectiveReadCount = 0;

  try {
    const app = createApp(fixture.baseDir);

    const getBefore = await app.request("http://localhost/agile/sessions/AGI-001/objective");
    assertEquals(getBefore.status, 200);
    const etagBefore = getBefore.headers.get("ETag");
    assert(etagBefore !== null && etagBefore.length > 0);

    mutableDeno.readTextFile = (async (path: string | URL, options?: Deno.ReadFileOptions) => {
      if (path === objectiveFile) {
        objectiveReadCount += 1;
        if (objectiveReadCount === 1) {
          return "Original objective";
        }
        if (objectiveReadCount === 2) {
          return "Changed by another writer";
        }
      }
      return await originalReadTextFile(path, options);
    }) as typeof Deno.readTextFile;

    const putResponse = await app.request("http://localhost/agile/sessions/AGI-001/objective", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "If-Match": etagBefore,
      },
      body: JSON.stringify({ content: "Client stale write" }),
    });

    assertEquals(putResponse.status, 409);
    assert(objectiveReadCount >= 2);

    const current = await originalReadTextFile(objectiveFile);
    assertEquals(current, "Original objective");
  } finally {
    mutableDeno.readTextFile = originalReadTextFile;
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("PUT /agile/sessions/:agiId/objective returns 409 when If-Match is stale", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Original objective");

  try {
    const app = createApp(fixture.baseDir);

    const getBefore = await app.request("http://localhost/agile/sessions/AGI-001/objective");
    assertEquals(getBefore.status, 200);
    const staleEtag = getBefore.headers.get("ETag");
    assert(staleEtag !== null && staleEtag.length > 0);

    await Deno.writeTextFile(`${fixture.baseDir}/agile/AGI-001/objective/objective.md`, "Changed by another writer");

    const putResponse = await app.request("http://localhost/agile/sessions/AGI-001/objective", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "If-Match": staleEtag,
      },
      body: JSON.stringify({ content: "Client stale write" }),
    });

    assertEquals(putResponse.status, 409);
    const current = await Deno.readTextFile(`${fixture.baseDir}/agile/AGI-001/objective/objective.md`);
    assertEquals(current, "Changed by another writer");
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("PUT /agile/sessions/:agiId/objective keeps backward compatibility without If-Match", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Before compatibility write");

  try {
    const app = createApp(fixture.baseDir);

    const putResponse = await app.request("http://localhost/agile/sessions/AGI-001/objective", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ content: "After compatibility write" }),
    });

    assertEquals(putResponse.status, 200);

    const getAfter = await app.request("http://localhost/agile/sessions/AGI-001/objective");
    const payloadAfter = await getAfter.json() as { content: string };
    assertEquals(payloadAfter.content, "After compatibility write");
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});
function assert(condition: unknown, message?: string): asserts condition {
  if (!condition) {
    throw new Error(message ?? "Assertion failed");
  }
}

function assertEquals(actual: unknown, expected: unknown): void {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);
  if (actualJson !== expectedJson) {
    throw new Error(`Assertion failed: expected ${expectedJson}, received ${actualJson}`);
  }
}
