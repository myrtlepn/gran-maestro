import { setRegistry, PLUGIN_ROOT } from "../config.ts";
import { projectPresetsApi } from "./presets.ts";

const TEST_PROJECT_ID = "proj-presets-test";

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

async function setupFixture(overrides: Record<string, unknown> = {}): Promise<{
  baseDir: string;
  cleanup: () => Promise<void>;
}> {
  const baseDir = await Deno.makeTempDir({ prefix: "presets-route-test-" });
  await writeJson(`${baseDir}/config.json`, overrides);

  setupRegistry(baseDir);

  return {
    baseDir,
    cleanup: async () => {
      setRegistry({ projects: [] });
      await Deno.remove(baseDir, { recursive: true });
    },
  };
}

function hasOwn(obj: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

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

runSerialTest("GET /api/presets returns 15 builtin presets with required fields", async () => {
  const fixture = await setupFixture();

  try {
    const response = await projectPresetsApi.request("http://localhost/presets");
    assertEquals(response.status, 200);

    const payload = await response.json() as {
      builtin: Array<Record<string, unknown>>;
    };

    assertEquals(payload.builtin.length, 15);

    for (const preset of payload.builtin) {
      assert(hasOwn(preset, "id"));
      assert(hasOwn(preset, "name"));
      assert(hasOwn(preset, "wizardCategory"));
      assert(hasOwn(preset, "tier"));
    }
  } finally {
    await fixture.cleanup();
  }
});

runSerialTest("POST diff returns non-empty changes for representative presets", async () => {
  const fixture = await setupFixture();
  const presetIds = ["codex-primary-performance", "claude-only-budget", "claude-codex-efficient", "full-team-performance"];

  try {
    for (const presetId of presetIds) {
      const response = await projectPresetsApi.request(`http://localhost/presets/${presetId}/diff`, {
        method: "POST",
      });
      assertEquals(response.status, 200);

      const payload = await response.json() as {
        changes: Array<Record<string, unknown>>;
      };

      assert(Array.isArray(payload.changes));
      assert(payload.changes.length >= 1);

      for (const change of payload.changes) {
        assert(hasOwn(change, "path"));
        assert(hasOwn(change, "from"));
        assert(hasOwn(change, "to"));
      }
    }
  } finally {
    await fixture.cleanup();
  }
});

runSerialTest("POST apply writes config files and matches claude-only-budget values", async () => {
  const fixture = await setupFixture();

  try {
    const response = await projectPresetsApi.request("http://localhost/presets/claude-only-budget/apply", {
      method: "POST",
    });
    assertEquals(response.status, 200);

    const payload = await response.json() as { ok: boolean; changes: unknown[] };
    assertEquals(payload.ok, true);
    assert(payload.changes.length >= 1);

    const presetData = await readJson<Record<string, unknown>>(
      `${PLUGIN_ROOT}/templates/defaults/presets/provider/claude-only-budget.json`,
    );
    const resolved = await readJson<Record<string, unknown>>(`${fixture.baseDir}/config.resolved.json`);
    const overrides = await readJson<Record<string, unknown>>(`${fixture.baseDir}/config.json`);

    const resolvedPathsToVerify = [
      "ideation.agents.claude.tier",
      "ideation.agents.codex.count",
      "models.roles.pm_conductor.tier",
      "plan_review.enabled",
    ];

    for (const path of resolvedPathsToVerify) {
      assertEquals(getByPath(resolved, path), getByPath(presetData, path));
    }

    const overridePathsToVerify = [
      "ideation.agents.codex.count",
      "models.roles.pm_conductor.tier",
      "plan_review.enabled",
    ];

    for (const path of overridePathsToVerify) {
      assertEquals(getByPath(overrides, path), getByPath(presetData, path));
    }
  } finally {
    await fixture.cleanup();
  }
});

runSerialTest("404 for nonexistent preset on diff/apply", async () => {
  const fixture = await setupFixture();

  try {
    const diffResponse = await projectPresetsApi.request(
      "http://localhost/presets/nonexistent-preset/diff",
      { method: "POST" },
    );
    assertEquals(diffResponse.status, 404);

    const applyResponse = await projectPresetsApi.request(
      "http://localhost/presets/nonexistent-preset/apply",
      { method: "POST" },
    );
    assertEquals(applyResponse.status, 404);
  } finally {
    await fixture.cleanup();
  }
});

function assert(condition: unknown, message?: string): asserts condition {
  if (!condition) {
    throw new Error(message ?? "Assertion failed");
  }
}

function assertEquals(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Assertion failed: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}
