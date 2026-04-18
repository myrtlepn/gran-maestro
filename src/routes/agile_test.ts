import { fromFileUrl, join } from "https://deno.land/std@0.224.0/path/mod.ts";
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
    JSON.stringify(
      { agi_id: "AGI-001", pln: ["PLN-1"], req: ["REQ-1"] },
      null,
      2,
    ) + "\n",
  );
  await Deno.writeTextFile(
    `${sessionDir}/objective/objective.md`,
    objectiveContent,
  );

  return {
    baseDir,
    cleanup: async () => {
      await Deno.remove(baseDir, { recursive: true });
    },
  };
}

async function copyDirectoryRecursive(
  sourceDir: string,
  targetDir: string,
): Promise<void> {
  await Deno.mkdir(targetDir, { recursive: true });

  for await (const entry of Deno.readDir(sourceDir)) {
    const sourcePath = join(sourceDir, entry.name);
    const targetPath = join(targetDir, entry.name);

    if (entry.isDirectory) {
      await copyDirectoryRecursive(sourcePath, targetPath);
      continue;
    }

    if (entry.isFile) {
      await Deno.copyFile(sourcePath, targetPath);
    }
  }
}

async function setupSampleAgiFixture(
  agiId = "AGI-016",
): Promise<
  { baseDir: string; sessionDir: string; cleanup: () => Promise<void> }
> {
  const tempRoot = await Deno.makeTempDir({ prefix: "agile-route-sample-" });
  const baseDir = join(tempRoot, ".gran-maestro");
  const sourceDir = fromFileUrl(
    new URL(`../../../../agile/${agiId}`, import.meta.url),
  );
  const sessionDir = join(baseDir, "agile", agiId);

  await copyDirectoryRecursive(sourceDir, sessionDir);

  return {
    baseDir,
    sessionDir,
    cleanup: async () => {
      await Deno.remove(tempRoot, { recursive: true });
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
Deno.test("GET /agile/sessions/:agiId exposes integrationReview, alignmentCheck, deferred_dod_count from fixture", async () => {
  const fixture = await setupSampleAgiFixture();

  try {
    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-016",
    );
    assertEquals(response.status, 200);

    const payload = await response.json() as {
      session: Record<string, unknown>;
      sprints: Array<Record<string, unknown>>;
    };

    assertEquals(payload.session.current_sprint, 5);
    assertEquals(payload.session.deferred_dod_count, 0);

    const sprintsById = new Map(
      payload.sprints.map((sprint) =>
        [String(sprint.sprint_id), sprint] as const
      ),
    );

    const sprintS02 = sprintsById.get("S02");
    assert(sprintS02);
    assertEquals(sprintS02.status, "done");
    assertEquals(
      sprintS02.user_observable_change,
      "agile CLI에서 result/objective-transition에 --dod-ref/--domain/--evidence-ref 플래그 사용 가능. DoD 마커에 evidence_refs 자동 누적.",
    );
    assertEquals(sprintS02.integrationReview, {
      verdict: {
        new_island_threshold: 0.2,
        exceeded: false,
        force_wire_recommended: false,
        escape_hatch_used: false,
        escape_reason: null,
      },
      ratios: {
        new_island: 0,
      },
      files: {
        new_island: 0,
      },
      force_wire_recommended: false,
    });
    assertEquals(sprintS02.alignmentCheck, {
      verdict: "aligned",
      raw_excerpt:
        "# Alignment Check — S02 ## 판정: aligned ## A. DoD-변경 매핑 충실도",
    });

    const sprintS00 = sprintsById.get("S00");
    assert(sprintS00);
    assertEquals(sprintS00.integrationReview, null);
    assertEquals(sprintS00.alignmentCheck, null);

    const sprintS03 = sprintsById.get("S03");
    assert(sprintS03);
    assertEquals(sprintS03.integrationReview, {
      verdict: {
        new_island_threshold: 0.2,
        exceeded: false,
        force_wire_recommended: false,
        escape_hatch_used: false,
        escape_reason: null,
      },
      ratios: {
        new_island: 0,
      },
      files: {
        new_island: 0,
      },
      force_wire_recommended: false,
    });
    assertEquals(sprintS03.alignmentCheck, null);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId counts proposed_done DoD markers", async () => {
  const fixture = await setupSessionFixture(
    {
      steering_every: 3,
    },
    [
      "# Objective",
      "",
      "<!-- dod:DOD-001 status:proposed_done priority:must -->",
      "DOD-001",
      "",
      "<!-- dod:DOD-002 status:done priority:must -->",
      "DOD-002",
      "",
      "<!-- dod:DOD-003 status:proposed_done priority:should -->",
      "DOD-003",
      "",
    ].join("\n"),
  );

  try {
    const sprintDir = `${fixture.baseDir}/agile/AGI-001/sprints/S01`;
    await Deno.mkdir(sprintDir, { recursive: true });
    await Deno.writeTextFile(
      `${sprintDir}/result.json`,
      JSON.stringify(
        {
          sprint_id: "S01",
          status: "done",
          sprint_goals: [],
        },
        null,
        2,
      ) + "\n",
    );

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001",
    );
    assertEquals(response.status, 200);

    const payload = await response.json() as {
      session: Record<string, unknown>;
    };
    assertEquals(payload.session.deferred_dod_count, 2);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId falls back to null when integration-review.json is invalid", async () => {
  const fixture = await setupSampleAgiFixture();

  try {
    await Deno.writeTextFile(
      `${fixture.sessionDir}/sprints/S02/integration-review.json`,
      "{ invalid json",
    );

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-016",
    );
    assertEquals(response.status, 200);

    const payload = await response.json() as {
      sprints: Array<Record<string, unknown>>;
    };
    const sprintS02 = payload.sprints.find((sprint) =>
      sprint.sprint_id === "S02"
    );

    assert(sprintS02);
    assertEquals(sprintS02.integrationReview, null);
    assertEquals(sprintS02.alignmentCheck, {
      verdict: "aligned",
      raw_excerpt:
        "# Alignment Check — S02 ## 판정: aligned ## A. DoD-변경 매핑 충실도",
    });
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

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
    const listPayload = await listResponse.json() as Array<
      Record<string, unknown>
    >;
    assertEquals(listPayload.length, 1);
    assertEquals(listPayload[0].steering_every, 5);
    assertEquals(listPayload[0].queue_size, 0);
    assertEquals(listPayload[0].refs_count, 0);

    const detailResponse = await app.request(
      "http://localhost/agile/sessions/AGI-001",
    );
    assertEquals(detailResponse.status, 200);
    const detailPayload = await detailResponse.json() as {
      session: Record<string, unknown>;
    };

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

    const responseA = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
    assertEquals(responseA.status, 200);
    const etagA = responseA.headers.get("ETag");

    const responseB = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
    assertEquals(responseB.status, 200);
    const etagB = responseB.headers.get("ETag");

    assert(etagA !== null && etagA.length > 0);
    assertEquals(etagA, etagB);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/objective/files returns objective root + detail markdown files", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const detailsDir = `${fixture.baseDir}/agile/AGI-001/objective/details`;
    await Deno.mkdir(detailsDir, { recursive: true });
    await Deno.writeTextFile(`${detailsDir}/architecture.md`, "# Architecture");
    await Deno.writeTextFile(`${detailsDir}/frontend-design.md`, "# Frontend");
    await Deno.writeTextFile(`${detailsDir}/readme.txt`, "ignore");

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective/files",
    );
    assertEquals(response.status, 200);
    const payload = await response.json() as {
      files: Array<Record<string, unknown>>;
    };

    assertEquals(payload.files, [
      { name: "objective.md", path: "objective/objective.md", type: "root" },
      {
        name: "architecture.md",
        path: "objective/details/architecture.md",
        type: "detail",
      },
      {
        name: "frontend-design.md",
        path: "objective/details/frontend-design.md",
        type: "detail",
      },
    ]);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/objective/files returns empty list when details directory is missing", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective/files",
    );
    assertEquals(response.status, 200);
    const payload = await response.json() as { files: unknown[] };
    assertEquals(payload.files, []);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/objective/details/:filename returns details content", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const detailsDir = `${fixture.baseDir}/agile/AGI-001/objective/details`;
    await Deno.mkdir(detailsDir, { recursive: true });
    await Deno.writeTextFile(
      `${detailsDir}/architecture.md`,
      "# Architecture detail",
    );

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective/details/architecture.md",
    );
    assertEquals(response.status, 200);
    const payload = await response.json() as { content: string; path: string };

    assertEquals(payload.content, "# Architecture detail");
    assertEquals(payload.path, "objective/details/architecture.md");
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/objective/details/:filename returns 404 for missing file", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const detailsDir = `${fixture.baseDir}/agile/AGI-001/objective/details`;
    await Deno.mkdir(detailsDir, { recursive: true });

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective/details/nonexistent.md",
    );
    assertEquals(response.status, 404);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/objective/details/:filename rejects traversal-style filename", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const detailsDir = `${fixture.baseDir}/agile/AGI-001/objective/details`;
    await Deno.mkdir(detailsDir, { recursive: true });

    const app = createApp(fixture.baseDir);

    const parentTraversal = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective/details/..hack.md",
    );
    assertEquals(parentTraversal.status, 400);

    const encodedSlashTraversal = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective/details/subdir%2Fhack.md",
    );
    assertEquals(encodedSlashTraversal.status, 400);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/sprints/:sprintId/result-details/files returns sprint result-detail markdown files", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const resultDetailsDir =
      `${fixture.baseDir}/agile/AGI-001/sprints/S01/result-details`;
    await Deno.mkdir(resultDetailsDir, { recursive: true });
    await Deno.writeTextFile(`${resultDetailsDir}/frontend.md`, "# Frontend");
    await Deno.writeTextFile(
      `${resultDetailsDir}/architecture.md`,
      "# Architecture",
    );
    await Deno.writeTextFile(`${resultDetailsDir}/notes.txt`, "ignore");

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/sprints/S01/result-details/files",
    );
    assertEquals(response.status, 200);
    const payload = await response.json() as {
      files: Array<Record<string, unknown>>;
    };

    assertEquals(payload.files, [
      {
        name: "architecture.md",
        path: "sprints/S01/result-details/architecture.md",
      },
      { name: "frontend.md", path: "sprints/S01/result-details/frontend.md" },
    ]);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/sprints/:sprintId/result-details/files returns empty list when directory is missing", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/sprints/S01/result-details/files",
    );
    assertEquals(response.status, 200);
    const payload = await response.json() as { files: unknown[] };
    assertEquals(payload.files, []);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/sprints/:sprintId/result-details/:filename returns result-detail content", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const resultDetailsDir =
      `${fixture.baseDir}/agile/AGI-001/sprints/S01/result-details`;
    await Deno.mkdir(resultDetailsDir, { recursive: true });
    await Deno.writeTextFile(
      `${resultDetailsDir}/frontend.md`,
      "# Frontend detail",
    );

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/sprints/S01/result-details/frontend.md",
    );
    assertEquals(response.status, 200);
    const payload = await response.json() as { content: string; path: string };

    assertEquals(payload.content, "# Frontend detail");
    assertEquals(payload.path, "sprints/S01/result-details/frontend.md");
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/sprints/:sprintId/result-details/:filename returns 404 for missing file", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const resultDetailsDir =
      `${fixture.baseDir}/agile/AGI-001/sprints/S01/result-details`;
    await Deno.mkdir(resultDetailsDir, { recursive: true });

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/sprints/S01/result-details/nonexistent.md",
    );
    assertEquals(response.status, 404);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/sprints/:sprintId/result-details/:filename rejects traversal-style filename", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const resultDetailsDir =
      `${fixture.baseDir}/agile/AGI-001/sprints/S01/result-details`;
    await Deno.mkdir(resultDetailsDir, { recursive: true });

    const app = createApp(fixture.baseDir);

    const parentTraversal = await app.request(
      "http://localhost/agile/sessions/AGI-001/sprints/S01/result-details/..%2Fhack.md",
    );
    assertEquals(parentTraversal.status, 400);

    const encodedSlashTraversal = await app.request(
      "http://localhost/agile/sessions/AGI-001/sprints/S01/result-details/subdir%2Fhack.md",
    );
    assertEquals(encodedSlashTraversal.status, 400);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/file serves image files with matching Content-Type", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const relativePath = "sprints/S01/screenshots/screen.png";
    const imageFile = `${fixture.baseDir}/agile/AGI-001/${relativePath}`;
    await Deno.mkdir(
      `${fixture.baseDir}/agile/AGI-001/sprints/S01/screenshots`,
      { recursive: true },
    );
    const expectedBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    await Deno.writeFile(imageFile, expectedBytes);

    const app = createApp(fixture.baseDir);
    const response = await app.request(
      `http://localhost/agile/sessions/AGI-001/file?path=${
        encodeURIComponent(relativePath)
      }`,
    );

    assertEquals(response.status, 200);
    assertEquals(response.headers.get("Content-Type"), "image/png");
    const actualBytes = new Uint8Array(await response.arrayBuffer());
    assertEquals(Array.from(actualBytes), Array.from(expectedBytes));
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/file returns 400 when path includes traversal segment", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/file?path=..%2Fsecret.png",
    );
    assertEquals(response.status, 400);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/file returns 404 when image file does not exist", async () => {
  const fixture = await setupSessionFixture({
    steering_every: 3,
  }, "Objective root");

  try {
    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/file?path=sprints%2FS01%2Fscreenshots%2Fmissing.png",
    );
    assertEquals(response.status, 404);
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

    const getBefore = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
    assertEquals(getBefore.status, 200);
    const etagBefore = getBefore.headers.get("ETag");
    assert(etagBefore !== null && etagBefore.length > 0);

    const putResponse = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "If-Match": etagBefore,
        },
        body: JSON.stringify({ content: "Objective after update" }),
      },
    );
    assertEquals(putResponse.status, 200);
    const etagFromPut = putResponse.headers.get("ETag");
    assert(etagFromPut !== null && etagFromPut.length > 0);

    const getAfter = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
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

  const objectiveFile =
    `${fixture.baseDir}/agile/AGI-001/objective/objective.md`;
  const originalReadTextFile = Deno.readTextFile;
  const mutableDeno = Deno as unknown as {
    readTextFile: typeof Deno.readTextFile;
  };
  let objectiveReadCount = 0;

  try {
    const app = createApp(fixture.baseDir);

    const getBefore = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
    assertEquals(getBefore.status, 200);
    const etagBefore = getBefore.headers.get("ETag");
    assert(etagBefore !== null && etagBefore.length > 0);

    mutableDeno.readTextFile =
      (async (path: string | URL, options?: Deno.ReadFileOptions) => {
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

    const putResponse = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "If-Match": etagBefore,
        },
        body: JSON.stringify({ content: "Client stale write" }),
      },
    );

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

    const getBefore = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
    assertEquals(getBefore.status, 200);
    const staleEtag = getBefore.headers.get("ETag");
    assert(staleEtag !== null && staleEtag.length > 0);

    await Deno.writeTextFile(
      `${fixture.baseDir}/agile/AGI-001/objective/objective.md`,
      "Changed by another writer",
    );

    const putResponse = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "If-Match": staleEtag,
        },
        body: JSON.stringify({ content: "Client stale write" }),
      },
    );

    assertEquals(putResponse.status, 409);
    const current = await Deno.readTextFile(
      `${fixture.baseDir}/agile/AGI-001/objective/objective.md`,
    );
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

    const putResponse = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content: "After compatibility write" }),
      },
    );

    assertEquals(putResponse.status, 200);

    const getAfter = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
    const payloadAfter = await getAfter.json() as { content: string };
    assertEquals(payloadAfter.content, "After compatibility write");
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/objective parses project DoD markers and new objective sections", async () => {
  const fixture = await setupSessionFixture(
    {
      steering_every: 3,
    },
    [
      "# Objective",
      "",
      "## 프로젝트 완료 기준 (DoD)",
      "- [ ] DOD-001: 성능 개선",
      "<!-- dod:DOD-001 status:todo priority:must -->",
      "- [x] DOD-002: 오류율 개선",
      "<!-- dod:DOD-002 status:done priority:should -->",
      "",
      "## 설계 결정 (Architecture Decisions)",
      "| ID | 결정 내용 |",
      "| --- | --- |",
      "| ADR-001 | API 캐시 적용 |",
      "",
      "## 제약사항 (Out-of-scope / 기술 / 비즈니스)",
      "### Out-of-scope",
      "- 레거시 마이그레이션 제외",
      "",
      "## 우선순위 (MoSCoW)",
      "- **Must**",
      "  - 신규 Objective 구조 렌더링",
      "",
      "## 프로젝트 NFR",
      "| 분류 | 요구사항 |",
      "| --- | --- |",
      "| 성능 | p95 250ms |",
      "",
      "## 리스크 레지스터",
      "| 리스크 | 가능성 | 영향 |",
      "| --- | --- | --- |",
      "| 파싱 누락 | 중 | 중 |",
      "",
      "## 참조 레퍼런스",
      "- REF-001: https://example.com",
      "",
    ].join("\n"),
  );

  try {
    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
    assertEquals(response.status, 200);
    const payload = await response.json() as Record<string, unknown>;
    const parsed = payload.parsed as Record<string, unknown>;
    const dods = parsed.dods as Array<Record<string, unknown>>;
    const sections = parsed.sections as Array<Record<string, unknown>>;

    assertEquals(Array.isArray(dods), true);
    assertEquals(dods.length, 2);
    assertEquals(dods[0].dod, "DOD-001");
    assertEquals(dods[0].status, "todo");
    assertEquals(dods[0].priority, "must");
    assertEquals(dods[1].dod, "DOD-002");
    assertEquals(dods[1].status, "done");
    assertEquals(dods[1].priority, "should");

    const sectionKeys = sections.map((section) => String(section.key));
    assert(sectionKeys.includes("architecture_decisions"));
    assert(sectionKeys.includes("constraints"));
    assert(sectionKeys.includes("moscow"));
    assert(sectionKeys.includes("nfr"));
    assert(sectionKeys.includes("risks"));
    assert(sectionKeys.includes("references"));
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("GET /agile/sessions/:agiId/objective parses DoD contentText from line after marker", async () => {
  const fixture = await setupSessionFixture(
    {
      steering_every: 3,
    },
    [
      "# Objective",
      "",
      "## 프로젝트 완료 기준 (DoD)",
      "<!-- dod:DOD-001 status:todo priority:must -->",
      "**DOD-001: 인증 플로우 검증**",
      "",
      "<!-- dod:DOD-002 status:done priority:should -->",
      "**DOD-002: 감사 로그 보존**",
      "",
      "<!-- dod:DOD-003 status:todo priority:could -->",
      "**DOD-003: 롤백 절차 문서화**",
      "",
    ].join("\n"),
  );

  try {
    const app = createApp(fixture.baseDir);
    const response = await app.request(
      "http://localhost/agile/sessions/AGI-001/objective",
    );
    assertEquals(response.status, 200);
    const payload = await response.json() as Record<string, unknown>;
    const parsed = payload.parsed as Record<string, unknown>;
    const dods = parsed.dods as Array<Record<string, unknown>>;

    assertEquals(Array.isArray(dods), true);
    assertEquals(dods.length, 3);
    assertEquals(dods[0].contentText, "**DOD-001: 인증 플로우 검증**");
    assertEquals(dods[1].contentText, "**DOD-002: 감사 로그 보존**");
    assertEquals(dods[2].contentText, "**DOD-003: 롤백 절차 문서화**");

    const contentTexts = dods.map((dod) => String(dod.contentText ?? ""));
    const uniqueCount = new Set(contentTexts).size;
    assertEquals(uniqueCount, 3);
    assertEquals(contentTexts.includes("## 프로젝트 완료 기준 (DoD)"), false);
  } finally {
    await fixture.cleanup();
    setRegistry({ projects: [] });
  }
});

Deno.test("PATCH /agile/:agiId/objective reinserts DoD markers for edited objective content", async () => {
  const fixture = await setupSessionFixture(
    {
      steering_every: 3,
    },
    [
      "# Objective",
      "",
      "## 프로젝트 완료 기준 (DoD)",
      "- [ ] DOD-010: Objective 마커 유지",
      "<!-- dod:DOD-010 status:todo priority:must -->",
      "",
    ].join("\n"),
  );

  try {
    const app = createApp(fixture.baseDir);
    const patchResponse = await app.request(
      "http://localhost/agile/AGI-001/objective",
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          content: [
            "# Objective",
            "",
            "## 프로젝트 완료 기준 (DoD)",
            "- [ ] DOD-010: Objective 마커 유지 (edited)",
            "",
          ].join("\n"),
        }),
      },
    );

    assertEquals(patchResponse.status, 200);
    const payload = await patchResponse.json() as { content: string };
    assert(
      payload.content.includes(
        "<!-- dod:DOD-010 status:todo priority:must -->",
      ),
    );
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
    throw new Error(
      `Assertion failed: expected ${expectedJson}, received ${actualJson}`,
    );
  }
}
