import { setRegistry, PLUGIN_ROOT } from "../config.ts";
import { projectConfigApi } from "./config.ts";

const TEST_PROJECT_ID = "proj-config-test";

let serial = Promise.resolve();

function runSerialTest(name: string, fn: () => Promise<void>) {
  Deno.test(name, async () => {
    const prev = serial;
    let release = () => {};
    serial = new Promise<void>((resolve) => {
      release = resolve;
    });

    await prev;
    try {
      await fn();
    } finally {
      release();
    }
  });
}

async function writeJson(path: string, data: unknown): Promise<void> {
  await Deno.writeTextFile(path, `${JSON.stringify(data, null, 2)}\n`);
}

async function readJson<T>(path: string): Promise<T> {
  const text = await Deno.readTextFile(path);
  return JSON.parse(text) as T;
}

function setupRegistry(baseDir: string): void {
  setRegistry({
    projects: [
      {
        id: TEST_PROJECT_ID,
        name: "test-project",
        path: baseDir,
        registered_at: "2026-04-02T00:00:00.000Z",
      },
    ],
  });
}

runSerialTest("PUT /api/config stores overrides in config.json and merged result in config.resolved.json", async () => {
  const baseDir = await Deno.makeTempDir({ prefix: "config-route-test-" });

  await writeJson(`${baseDir}/config.json`, {
    code_review: { enabled: false },
  });

  setupRegistry(baseDir);

  try {
    const nextConfig = {
      stitch: { enabled: false },
      code_review: { enabled: true },
      plan_review: { enabled: false },
    };

    const response = await projectConfigApi.request("http://localhost/config", {
      method: "PUT",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify(nextConfig),
    });

    assertEquals(response.status, 200);
    const payload = await response.json() as { ok: boolean };
    assertEquals(payload.ok, true);

    const writtenOverrides = await readJson<Record<string, unknown>>(`${baseDir}/config.json`);
    const resolved = await readJson<Record<string, unknown>>(`${baseDir}/config.resolved.json`);
    const defaults = await readJson<Record<string, unknown>>(`${PLUGIN_ROOT}/templates/defaults/config.json`);

    assertEquals(writtenOverrides, {
      stitch: { enabled: false },
      plan_review: { enabled: false },
    });

    assertEquals(getByPath(resolved, "stitch.enabled"), false);
    assertEquals(getByPath(resolved, "code_review.enabled"), true);
    assertEquals(getByPath(resolved, "plan_review.enabled"), false);

    assertEquals(
      getByPath(resolved, "workflow.default_agent"),
      getByPath(defaults, "workflow.default_agent"),
    );
  } finally {
    setRegistry({ projects: [] });
    await Deno.remove(baseDir, { recursive: true });
  }
});

function getByPath(root: Record<string, unknown>, path: string): unknown {
  const keys = path.split(".");
  let current: unknown = root;

  for (const key of keys) {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[key];
  }

  return current;
}

function assertEquals(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Assertion failed: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}
