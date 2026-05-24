import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { join } from "https://deno.land/std@0.224.0/path/mod.ts";
import { setRegistry } from "../config.ts";
import { projectDesignsApi } from "./designs.ts";

const TEST_PROJECT_ID = "proj-designs-test";

function assertEquals(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Assertion failed: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}

function assert(condition: unknown, message = "Assertion failed"): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

async function writeJson(path: string, data: unknown): Promise<void> {
  await Deno.writeTextFile(path, `${JSON.stringify(data, null, 2)}\n`);
}

async function setupFixture(): Promise<{ app: Hono; root: string; baseDir: string }> {
  const root = await Deno.makeTempDir({ prefix: "designs-route-test-" });
  const baseDir = join(root, ".gran-maestro");
  const desDir = join(baseDir, "designs", "DES-001");
  await Deno.mkdir(join(desDir, "screens"), { recursive: true });

  await writeJson(join(desDir, "design.json"), {
    id: "DES-001",
    title: "Nested design artifacts",
    status: "active",
    screens: [
      {
        slug: "recovery-journal-today",
        title: "Recovery Journal Today",
        stitch_screen_id: "screen-remote-1",
        html: "screens/recovery-journal-today.html",
        image: "screens/recovery-journal-today.png",
        meta: "screens/recovery-journal-today.meta.json",
      },
      {
        id: "screen-001",
        title: "Legacy screen",
      },
    ],
  });
  await Deno.writeTextFile(join(desDir, "screens", "recovery-journal-today.html"), "<html><body>Recovery Journal</body></html>");
  await Deno.writeTextFile(join(desDir, "screen-001.md"), "## Legacy screen\n");
  await Deno.writeTextFile(join(desDir, "screen-001.html"), "<html><body>Legacy</body></html>");

  setRegistry({
    projects: [
      {
        id: TEST_PROJECT_ID,
        name: "designs-test",
        path: baseDir,
        registered_at: "2026-05-24T00:00:00.000Z",
      },
    ],
  });

  const app = new Hono();
  app.route("/api/projects/:projectId", projectDesignsApi);
  return { app, root, baseDir };
}

Deno.test("design detail normalizes nested Stitch HTML artifacts into screen files", async () => {
  const fixture = await setupFixture();
  try {
    const response = await fixture.app.request(
      `http://localhost/api/projects/${TEST_PROJECT_ID}/designs/DES-001`,
    );
    assertEquals(response.status, 200);
    const payload = await response.json();

    assertEquals(payload.screen_files, ["screen-001.md", "recovery-journal-today.html"]);
    assertEquals(payload.screen_html_files["screen-001.md"], "screen-001.html");
    assertEquals(payload.screen_html_files["recovery-journal-today.html"], "screens/recovery-journal-today.html");
    assertEquals(payload.screens[0].id, "recovery-journal-today");
    assertEquals(payload.screens[0].html_file, "screens/recovery-journal-today.html");
  } finally {
    setRegistry({ projects: [] });
    await Deno.remove(fixture.root, { recursive: true });
  }
});

Deno.test("design HTML endpoint serves nested screen artifacts and rejects unsafe screen files", async () => {
  const fixture = await setupFixture();
  try {
    const okResponse = await fixture.app.request(
      `http://localhost/api/projects/${TEST_PROJECT_ID}/designs/DES-001/screens/recovery-journal-today.html/html`,
    );
    assertEquals(okResponse.status, 200);
    assert((await okResponse.text()).includes("Recovery Journal"));

    const markdownResponse = await fixture.app.request(
      `http://localhost/api/projects/${TEST_PROJECT_ID}/designs/DES-001/screens/recovery-journal-today.html`,
    );
    assertEquals(markdownResponse.status, 200);
    assertEquals(await markdownResponse.json(), { exists: false, content: null });

    const unsafeResponse = await fixture.app.request(
      `http://localhost/api/projects/${TEST_PROJECT_ID}/designs/DES-001/screens/..%2Fsecret.html/html`,
    );
    assertEquals(unsafeResponse.status, 400);
  } finally {
    setRegistry({ projects: [] });
    await Deno.remove(fixture.root, { recursive: true });
  }
});
