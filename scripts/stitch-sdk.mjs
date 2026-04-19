#!/usr/bin/env node

/**
 * Stitch SDK CLI wrapper for Gran Maestro.
 *
 * Auth:
 * - API Key: STITCH_API_KEY
 * - OAuth: STITCH_ACCESS_TOKEN + GOOGLE_CLOUD_PROJECT
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const COMMANDS = [
  "generate",
  "edit",
  "variants",
  "get-screen",
  "list-screens",
  "create-project",
  "get-project",
  "list-projects",
  "init",
];

function printHelp() {
  const lines = [
    "Usage:",
    "  node scripts/stitch-sdk.mjs <command> [options]",
    "",
    "Commands:",
    "  generate       Generate a screen from prompt",
    "  edit           Edit an existing screen",
    "  variants       Generate variants for a screen",
    "  get-screen     Get a screen",
    "  list-screens   List screens in a project",
    "  create-project Create a new project",
    "  get-project    Get a project",
    "  list-projects  List all projects",
    "  init           Collect project + screens context for DESIGN.md generation",
    "",
    "Global options:",
    "  -h, --help     Show this help",
    "",
    "Generate options:",
    "  --save-dir <dir>       Save generated html/meta/image artifacts atomically",
    "  --screen-name <slug>   Filename slug required when --save-dir is provided",
    "",
    "Auth (env):",
    "  STITCH_API_KEY",
    "  or STITCH_ACCESS_TOKEN + GOOGLE_CLOUD_PROJECT",
  ];
  console.log(lines.join("\n"));
}

function parseArgs(argv) {
  const args = { _: [] };

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];

    if (!token.startsWith("--")) {
      args._.push(token);
      continue;
    }

    const maybeEq = token.indexOf("=");
    if (maybeEq > -1) {
      const key = token.slice(2, maybeEq);
      const value = token.slice(maybeEq + 1);
      args[key] = value;
      continue;
    }

    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
      continue;
    }

    args[key] = next;
    i += 1;
  }

  return args;
}

function value(args, key, fallback = undefined) {
  return args[key] ?? fallback;
}

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const PLUGIN_ROOT = path.dirname(path.dirname(SCRIPT_PATH));

class SdkMissingError extends Error {
  constructor(error) {
    const message = error instanceof Error ? error.message : String(error);
    super(message);
    this.name = "SdkMissingError";
    this.code = "MODULE_NOT_FOUND";
    this.install_required = true;
  }
}

class ArtifactSaveError extends Error {
  constructor(message, cause) {
    super(message);
    this.name = "ArtifactSaveError";
    this.cause = cause;
  }
}

function toInt(input, fallback) {
  if (input === undefined || input === null || input === "") {
    return fallback;
  }
  const parsed = Number.parseInt(String(input), 10);
  return Number.isNaN(parsed) ? fallback : parsed;
}

function toList(input) {
  if (!input) return [];
  return String(input)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function ensureAuthConfigured() {
  const hasApiKey = Boolean(process.env.STITCH_API_KEY);
  const hasOAuthToken = Boolean(process.env.STITCH_ACCESS_TOKEN);
  const hasGcpProject = Boolean(process.env.GOOGLE_CLOUD_PROJECT);

  if (hasApiKey) {
    return;
  }

  if (hasOAuthToken && hasGcpProject) {
    return;
  }

  return {
    auth_required: true,
    setup_url: "https://stitch.withgoogle.com/settings",
    env_var: "STITCH_API_KEY",
    message: "[Stitch] 인증 정보가 설정되지 않았습니다.",
    guidance: [
      'export STITCH_API_KEY="발급받은_API_키"',
      'echo \'export STITCH_API_KEY="발급받은_API_키"\' >> ~/.zshrc',
      "또는 OAuth 인증: STITCH_ACCESS_TOKEN + GOOGLE_CLOUD_PROJECT를 함께 설정하세요.",
    ],
  };
}

async function importSdkModule() {
  try {
    return await import("@google/stitch-sdk");
  } catch (error) {
    if (isSdkModuleNotFound(error)) {
      throw new SdkMissingError(error);
    }
    const cause = error instanceof Error ? error.message : String(error);
    throw new Error(`@google/stitch-sdk 로드 실패: ${cause}`);
  }
}

async function assertSdkInstalled() {
  await importSdkModule();
}

async function loadSdk() {
  const mod = await importSdkModule();
  if (!mod || !Object.prototype.hasOwnProperty.call(mod, "stitch")) {
    throw new Error("@google/stitch-sdk 모듈에서 stitch export를 찾지 못했습니다.");
  }
  return mod.stitch;
}

function isSdkModuleNotFound(error) {
  const code = error?.code;
  const message = error instanceof Error ? error.message : String(error);
  return (code === "MODULE_NOT_FOUND" || code === "ERR_MODULE_NOT_FOUND") && message.includes("@google/stitch-sdk");
}

function safeError(error) {
  if (!error) {
    return { message: "Unknown error" };
  }
  if (error instanceof Error) {
    return {
      message: maskSecrets(error.message),
      name: error.name,
      stack: maskSecrets(error.stack),
    };
  }
  return { message: maskSecrets(String(error)) };
}

function maskSecrets(text) {
  if (text === undefined || text === null) {
    return text;
  }

  let masked = String(text);
  const patterns = [
    /STITCH_API_KEY\s*=\s*[^\s"'`]+/gi,
    /Authorization:\s*Bearer\s+[^\s"'`]+/gi,
    /x-goog-api-key:\s*[^\s"'`]+/gi,
    /\bAIza[0-9A-Za-z_-]{35}\b/g,
  ];

  for (const pattern of patterns) {
    masked = masked.replace(pattern, "***REDACTED***");
  }

  return masked;
}

function safeStringify(obj, indent = 2) {
  const seen = new WeakSet();
  return JSON.stringify(
    obj,
    (_key, val) => {
      if (typeof val === "object" && val !== null) {
        if (seen.has(val)) {
          return "[Circular]";
        }
        seen.add(val);
      }
      return val;
    },
    indent,
  );
}

function normalizeSdkObject(obj) {
  if (!obj || typeof obj !== "object") return obj;
  if (typeof obj.toJSON === "function") {
    try {
      return obj.toJSON();
    } catch {
      // fall through
    }
  }
  if (obj.data && typeof obj.data === "object" && !Array.isArray(obj.data)) {
    const result = { projectId: obj.projectId };
    for (const [k, v] of Object.entries(obj.data)) {
      result[k] = v;
    }
    return result;
  }
  const result = {};
  for (const [k, v] of Object.entries(obj)) {
    if (k !== "client") {
      result[k] = v;
    }
  }
  return result;
}

function cleanObject(obj) {
  const result = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined && v !== null && v !== "") {
      result[k] = v;
    }
  }
  return result;
}

function screenName(projectId, screenId) {
  if (!projectId || !screenId) return undefined;
  return `projects/${projectId}/screens/${screenId}`;
}

function extractIdFromName(name) {
  if (!name || typeof name !== "string") return null;
  const parts = name.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : null;
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeMaybeArray(payload, key) {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (isObject(payload) && Array.isArray(payload[key])) {
    return payload[key];
  }
  return [];
}

async function maybeCall(fn) {
  if (typeof fn !== "function") return undefined;
  return fn();
}

function extractDownloadUrl(value) {
  if (typeof value === "string") {
    const normalized = value.trim();
    if (normalized.length === 0) {
      return null;
    }
    if (/^https?:\/\//i.test(normalized)) {
      return normalized;
    }
    try {
      return extractDownloadUrl(JSON.parse(normalized));
    } catch {
      return null;
    }
  }

  if (!isObject(value)) {
    return null;
  }

  const downloadUrl = value.downloadUrl;
  if (typeof downloadUrl !== "string") {
    return null;
  }

  const normalized = downloadUrl.trim();
  if (normalized.length === 0 || !/^https?:\/\//i.test(normalized)) {
    return null;
  }

  return normalized;
}

function findDownloadUrlDeep(value, seen = new WeakSet()) {
  const direct = extractDownloadUrl(value);
  if (direct) {
    return direct;
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = findDownloadUrlDeep(item, seen);
      if (nested) {
        return nested;
      }
    }
    return null;
  }

  if (!isObject(value) || seen.has(value)) {
    return null;
  }
  seen.add(value);

  for (const nested of Object.values(value)) {
    const nestedUrl = findDownloadUrlDeep(nested, seen);
    if (nestedUrl) {
      return nestedUrl;
    }
  }

  return null;
}

function extractImageDownloadUrl(screen) {
  const raw = isObject(screen?.raw) ? screen.raw : {};
  return (
    findDownloadUrlDeep(screen?.image) ||
    findDownloadUrlDeep(raw.image) ||
    findDownloadUrlDeep(raw.imageUrl) ||
    findDownloadUrlDeep(raw.previewImage) ||
    findDownloadUrlDeep(raw.screenshot) ||
    findDownloadUrlDeep(raw.thumbnail) ||
    findDownloadUrlDeep(raw.downloadUrl)
  );
}

async function downloadImageBuffer(screen) {
  const downloadUrl = extractImageDownloadUrl(screen);
  if (!downloadUrl) {
    return null;
  }

  try {
    const response = await fetch(downloadUrl);
    if (!response.ok) {
      return null;
    }
    return Buffer.from(await response.arrayBuffer());
  } catch {
    return null;
  }
}

async function resolveScreenHtml(value, screenId) {
  const downloadUrl = extractDownloadUrl(value);
  if (!downloadUrl) {
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
    return undefined;
  }

  try {
    const response = await fetch(downloadUrl);
    if (!response.ok) {
      console.error(`[stitch-sdk] getHtml download failed (screen: ${screenId ?? "unknown"}, status: ${response.status})`);
      return undefined;
    }

    const html = await response.text();
    return html.trim().length > 0 ? html : undefined;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[stitch-sdk] getHtml download failed (screen: ${screenId ?? "unknown"}): ${message}`);
    return undefined;
  }
}

async function collectScreenArtifacts(screen) {
  if (!screen) return {};

  let html;
  let image;
  let json;

  try {
    const rawHtml = await maybeCall(() => screen.getHtml());
    html = await resolveScreenHtml(rawHtml, screen?.id);
  } catch {
    html = undefined;
  }

  try {
    image = await maybeCall(() => screen.getImage());
  } catch {
    image = undefined;
  }

  try {
    json = await maybeCall(() => (typeof screen.toJSON === "function" ? screen.toJSON() : undefined));
  } catch {
    json = undefined;
  }

  const name = screen?.name || json?.name;
  const id = screen?.id || json?.id || extractIdFromName(name);

  return cleanObject({
    id,
    name,
    image,
    html,
    raw: json,
  });
}

async function normalizeGeneratedScreen(raw) {
  const payload = isObject(raw) && isObject(raw.screen) ? raw.screen : raw;
  if (!isObject(payload)) {
    return cleanObject({ raw: payload });
  }

  const name = payload.name;
  const id = payload.id || extractIdFromName(name);
  const htmlSource = payload.html ?? payload.htmlContent;

  return cleanObject({
    id,
    name,
    image: payload.image ?? payload.imageUrl ?? payload.previewImage ?? payload.screenshot,
    html: await resolveScreenHtml(htmlSource, id),
    raw: payload,
  });
}

function screenMeta(screen, prompt, source) {
  const raw = isObject(screen?.raw) ? screen.raw : {};
  const name = screen?.name ?? raw.name ?? null;
  return {
    id: screen?.id ?? raw.id ?? extractIdFromName(name) ?? null,
    name,
    created_at: new Date().toISOString(),
    prompt,
    source,
  };
}

async function unlinkIfExists(filePath) {
  try {
    await fs.unlink(filePath);
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }
}

async function saveScreenArtifacts(screen, { saveDir, slug, prompt, source }) {
  const targetDir = path.resolve(String(saveDir));
  const htmlFinal = path.join(targetDir, `${slug}.html`);
  const imageFinal = path.join(targetDir, `${slug}.png`);
  const metaFinal = path.join(targetDir, `${slug}.meta.json`);
  const pendingTmpFiles = [];
  const renamedFinalFiles = [];

  try {
    await fs.mkdir(targetDir, { recursive: true });
    const imageBuffer = await downloadImageBuffer(screen);
    const files = [
      {
        key: "html",
        tmp: path.join(targetDir, `${slug}.html.tmp`),
        final: htmlFinal,
        data: typeof screen?.html === "string" ? screen.html : "",
      },
      {
        key: "meta",
        tmp: path.join(targetDir, `${slug}.meta.json.tmp`),
        final: metaFinal,
        data: `${JSON.stringify(screenMeta(screen, prompt, source), null, 2)}\n`,
      },
    ];

    if (imageBuffer) {
      files.splice(1, 0, {
        key: "image",
        tmp: path.join(targetDir, `${slug}.png.tmp`),
        final: imageFinal,
        data: imageBuffer,
      });
    }

    for (const file of files) {
      await fs.writeFile(file.tmp, file.data);
      pendingTmpFiles.push(file.tmp);
    }

    for (const file of files) {
      await fs.rename(file.tmp, file.final);
      pendingTmpFiles.splice(pendingTmpFiles.indexOf(file.tmp), 1);
      renamedFinalFiles.push(file.final);
    }

    return {
      html: htmlFinal,
      image: imageBuffer ? imageFinal : null,
      meta: metaFinal,
    };
  } catch (error) {
    const cleanupTargets = [...pendingTmpFiles, ...renamedFinalFiles];
    await Promise.allSettled(cleanupTargets.map((filePath) => unlinkIfExists(filePath)));
    const message = error instanceof Error ? error.message : String(error);
    throw new ArtifactSaveError(`Failed to save generated screen artifacts: ${message}`, error);
  }
}

function asJsonResponse(command, data, ok = true) {
  return {
    ok,
    command,
    data,
    timestamp: new Date().toISOString(),
  };
}

function asJsonError(command, error) {
  return {
    ok: false,
    command,
    error: safeError(error),
    timestamp: new Date().toISOString(),
  };
}

function asInstallRequiredError(command, error) {
  return {
    ok: false,
    command,
    install_required: true,
    suggested_command: "npm install --omit=dev",
    cwd: PLUGIN_ROOT,
    error: {
      code: "MODULE_NOT_FOUND",
      message: maskSecrets(error instanceof Error ? error.message : String(error)),
    },
    timestamp: new Date().toISOString(),
  };
}

async function callTool(stitch, name, args) {
  return stitch.callTool(name, args);
}

async function runListProjects(stitch) {
  if (typeof stitch.projects === "function") {
    try {
      const projects = await stitch.projects();
      const normalized = normalizeMaybeArray(projects, "projects").map(normalizeSdkObject);
      return {
        projects: normalized,
        source: "sdk.projects",
      };
    } catch {
      // fall through to callTool
    }
  }

  const raw = await callTool(stitch, "list_projects", {});
  return {
    projects: raw,
    source: "sdk.callTool:list_projects",
  };
}

async function runGetProject(stitch, args) {
  const projectId = value(args, "project-id");
  if (!projectId) {
    throw new Error("--project-id is required");
  }

  // SDK project handle doesn't have get() — try listing and filtering
  if (typeof stitch.projects === "function") {
    try {
      const projects = await stitch.projects();
      const list = normalizeMaybeArray(projects, "projects");
      const match = list.find(
        (p) => String(p.projectId) === String(projectId) || (p.data && p.data.name === `projects/${projectId}`),
      );
      if (match) {
        return {
          project: normalizeSdkObject(match),
          source: "sdk.projects.find",
        };
      }
    } catch {
      // fall through to callTool
    }
  }

  try {
    const name = `projects/${projectId}`;
    const raw = await callTool(stitch, "get_project", cleanObject({ projectId, name }));
    return {
      project: raw,
      source: "sdk.callTool:get_project",
    };
  } catch {
    throw new Error(`Project ${projectId} not found. The project may not exist or the API key may not have access.`);
  }
}

async function runCreateProject(stitch, args) {
  const title = value(args, "title");
  if (!title) {
    throw new Error("--title is required");
  }

  const raw = await callTool(stitch, "create_project", { title });
  return {
    project: raw,
    source: "sdk.callTool:create_project",
  };
}

async function runListScreens(stitch, args) {
  const projectId = value(args, "project-id");
  if (!projectId) {
    throw new Error("--project-id is required");
  }

  let sdkScreens = [];
  let triedSdkScreens = false;
  const project = typeof stitch.project === "function" ? stitch.project(projectId) : null;
  if (project && typeof project.screens === "function") {
    triedSdkScreens = true;
    try {
      const screens = await project.screens();
      sdkScreens = normalizeMaybeArray(screens, "screens").map(normalizeSdkObject);
    } catch {
      sdkScreens = [];
    }
  }

  if (triedSdkScreens && sdkScreens.length > 0) {
    return {
      projectId,
      screens: sdkScreens,
      source: "sdk.project.screens",
    };
  }

  const raw = await callTool(stitch, "list_screens", { projectId });
  const mcpScreens = normalizeMaybeArray(raw, "screens").map(normalizeSdkObject);
  const useMcpScreens = mcpScreens.length > sdkScreens.length;

  return {
    projectId,
    screens: useMcpScreens ? mcpScreens : sdkScreens,
    source: triedSdkScreens ? "sdk.project.screens+callTool" : "sdk.callTool:list_screens",
  };
}

async function resolveScreenHandle(stitch, projectId, screenId) {
  if (!projectId || !screenId) {
    return null;
  }

  const project = typeof stitch.project === "function" ? stitch.project(projectId) : null;
  if (project && typeof project.getScreen === "function") {
    return project.getScreen(screenId);
  }
  // fallback: older SDK versions may use screen()
  if (project && typeof project.screen === "function") {
    return project.screen(screenId);
  }

  return null;
}

async function runGenerate(stitch, args) {
  const projectId = value(args, "project-id");
  const prompt = value(args, "prompt");
  const deviceType = value(args, "device-type", "DESKTOP");
  const modelId = value(args, "model-id");
  const saveDir = value(args, "save-dir");
  const screenSlug = value(args, "screen-name");

  if (!projectId) {
    throw new Error("--project-id is required");
  }
  if (!prompt) {
    throw new Error("--prompt is required");
  }
  if (saveDir === true) {
    throw new Error("--save-dir requires a directory");
  }
  if (saveDir && (!screenSlug || screenSlug === true)) {
    throw new Error("--screen-name is required when --save-dir is provided");
  }

  const project = typeof stitch.project === "function" ? stitch.project(projectId) : null;
  if (project && typeof project.generate === "function") {
    try {
      const generated = await project.generate(prompt, cleanObject({ deviceType, modelId }));
      let screen = await collectScreenArtifacts(generated);
      const source = "sdk.project.generate";
      if (saveDir) {
        const savedFiles = await saveScreenArtifacts(screen, {
          saveDir,
          slug: screenSlug,
          prompt,
          source,
        });
        screen = {
          ...screen,
          saved_files: savedFiles,
        };
      }
      return {
        projectId,
        prompt,
        screen,
        source,
      };
    } catch (error) {
      if (error instanceof ArtifactSaveError) {
        throw error;
      }
      // fall through to callTool
    }
  }

  const raw = await callTool(
    stitch,
    "generate_screen_from_text",
    cleanObject({
      projectId,
      prompt,
      deviceType,
      modelId,
    }),
  );

  if (saveDir) {
    const source = "sdk.callTool:generate_screen_from_text";
    const screen = await normalizeGeneratedScreen(raw);
    const savedFiles = await saveScreenArtifacts(screen, {
      saveDir,
      slug: screenSlug,
      prompt,
      source,
    });
    return {
      projectId,
      prompt,
      screen: {
        ...screen,
        saved_files: savedFiles,
      },
      source,
    };
  }

  return {
    projectId,
    prompt,
    result: raw,
    source: "sdk.callTool:generate_screen_from_text",
  };
}

async function runGetScreen(stitch, args) {
  const projectId = value(args, "project-id");
  const screenId = value(args, "screen-id");
  const name = value(args, "name") || screenName(projectId, screenId);

  if (!projectId) {
    throw new Error("--project-id is required");
  }
  if (!screenId && !name) {
    throw new Error("--screen-id or --name is required");
  }

  const handle = screenId ? await resolveScreenHandle(stitch, projectId, screenId) : null;
  if (handle) {
    try {
      const screen = await collectScreenArtifacts(handle);
      return {
        projectId,
        screen,
        source: "sdk.project.screen",
      };
    } catch {
      // fall through to callTool
    }
  }

  const raw = await callTool(
    stitch,
    "get_screen",
    cleanObject({
      projectId,
      screenId,
      name,
    }),
  );

  const screen = isObject(raw)
    ? cleanObject({
        ...raw,
        html: await resolveScreenHtml(raw.html, raw.id ?? screenId),
      })
    : raw;

  return {
    projectId,
    screen,
    source: "sdk.callTool:get_screen",
  };
}

async function runEdit(stitch, args) {
  const projectId = value(args, "project-id");
  const screenId = value(args, "screen-id");
  const prompt = value(args, "prompt");
  const modelId = value(args, "model-id");

  if (!projectId) {
    throw new Error("--project-id is required");
  }
  if (!screenId) {
    throw new Error("--screen-id is required");
  }
  if (!prompt) {
    throw new Error("--prompt is required");
  }

  const handle = await resolveScreenHandle(stitch, projectId, screenId);
  if (handle && typeof handle.edit === "function") {
    try {
      const edited = await handle.edit(prompt, cleanObject({ modelId }));
      const screen = await collectScreenArtifacts(edited);
      return {
        projectId,
        screenId,
        prompt,
        screen,
        source: "sdk.screen.edit",
      };
    } catch {
      // fall through to callTool
    }
  }

  const raw = await callTool(
    stitch,
    "edit_screens",
    cleanObject({
      projectId,
      selectedScreenIds: [screenId],
      prompt,
      modelId,
    }),
  );

  return {
    projectId,
    screenId,
    prompt,
    result: raw,
    source: "sdk.callTool:edit_screens",
  };
}

async function runVariants(stitch, args) {
  const projectId = value(args, "project-id");
  const screenId = value(args, "screen-id");
  const selectedScreenIds = toList(value(args, "screen-ids"));
  const prompt = value(args, "prompt");
  const variantCount = toInt(value(args, "variant-count"), 3);
  const creativeRange = value(args, "creative-range", "EXPLORE");
  const aspects = toList(value(args, "aspects"));
  const modelId = value(args, "model-id");

  if (!projectId) {
    throw new Error("--project-id is required");
  }
  if (!prompt) {
    throw new Error("--prompt is required");
  }

  const ids = selectedScreenIds.length ? selectedScreenIds : (screenId ? [screenId] : []);
  if (!ids.length) {
    throw new Error("--screen-id or --screen-ids is required");
  }

  if (ids.length === 1) {
    const handle = await resolveScreenHandle(stitch, projectId, ids[0]);
    if (handle && typeof handle.variants === "function") {
      try {
        const variants = await handle.variants(
          prompt,
          cleanObject({
            variantCount,
            creativeRange,
            aspects: aspects.length ? aspects : undefined,
            modelId,
          }),
        );
        return {
          projectId,
          selectedScreenIds: ids,
          prompt,
          variants,
          source: "sdk.screen.variants",
        };
      } catch {
        // fall through to callTool
      }
    }
  }

  const raw = await callTool(
    stitch,
    "generate_variants",
    cleanObject({
      projectId,
      selectedScreenIds: ids,
      prompt,
      variantOptions: cleanObject({
        variantCount,
        creativeRange,
        aspects: aspects.length ? aspects : undefined,
      }),
      modelId,
    }),
  );

  return {
    projectId,
    selectedScreenIds: ids,
    prompt,
    variants: raw,
    source: "sdk.callTool:generate_variants",
  };
}

function pickThemeHints(projectPayload, screenPayloads) {
  const theme = {
    colors: [],
    typography: [],
    mood: [],
  };

  const blobs = [projectPayload, ...screenPayloads].filter(Boolean);
  const text = JSON.stringify(blobs);

  const colorKeywords = ["primary", "secondary", "accent", "neutral", "background", "surface"];
  const fontKeywords = ["sans", "serif", "mono", "inter", "roboto", "pretendard", "noto"];
  const moodKeywords = ["minimal", "modern", "playful", "corporate", "bold", "clean", "dark", "light"];

  for (const keyword of colorKeywords) {
    if (text.toLowerCase().includes(keyword)) theme.colors.push(keyword);
  }
  for (const keyword of fontKeywords) {
    if (text.toLowerCase().includes(keyword)) theme.typography.push(keyword);
  }
  for (const keyword of moodKeywords) {
    if (text.toLowerCase().includes(keyword)) theme.mood.push(keyword);
  }

  return {
    colors: [...new Set(theme.colors)],
    typography: [...new Set(theme.typography)],
    mood: [...new Set(theme.mood)],
  };
}

async function runInit(stitch, args) {
  const projectId = value(args, "project-id");
  const maxScreens = toInt(value(args, "max-screens"), 10);

  if (!projectId) {
    throw new Error("--project-id is required");
  }

  const projectInfo = await runGetProject(stitch, { "project-id": projectId });
  const screensInfo = await runListScreens(stitch, { "project-id": projectId });

  const rawScreens = normalizeMaybeArray(screensInfo.screens, "screens");
  const targetScreens = maxScreens > 0 ? rawScreens.slice(0, maxScreens) : rawScreens;

  const detailedScreens = [];
  for (const item of targetScreens) {
    const name = item?.name;
    const inferredId = item?.id || extractIdFromName(name);
    if (!inferredId) {
      detailedScreens.push({
        id: null,
        name,
        meta: item,
      });
      continue;
    }

    try {
      const detail = await runGetScreen(stitch, {
        "project-id": projectId,
        "screen-id": inferredId,
        name,
      });
      detailedScreens.push(
        cleanObject({
          id: inferredId,
          name,
          detail: detail.screen,
        }),
      );
    } catch {
      detailedScreens.push(
        cleanObject({
          id: inferredId,
          name,
          meta: item,
        }),
      );
    }
  }

  const theme = pickThemeHints(projectInfo.project, detailedScreens);

  return {
    projectId,
    project: projectInfo.project,
    screens: detailedScreens,
    summary: {
      screenCount: rawScreens.length,
      sampledScreenCount: detailedScreens.length,
      theme,
    },
    source: "sdk.init",
  };
}

async function main() {
  const argv = process.argv.slice(2);
  const parsed = parseArgs(argv);

  const top = parsed._[0];
  const wantHelp = top === "--help" || top === "-h" || parsed.help;
  const initAlias = Boolean(parsed.init);

  if (wantHelp) {
    printHelp();
    process.exit(0);
  }

  let command = top || (initAlias ? "init" : undefined);
  if (command === "--init") {
    command = "init";
  }

  if (!command) {
    const payload = asJsonError(command, new Error("Command is required"));
    console.error(JSON.stringify(payload, null, 2));
    process.exit(1);
  }

  if (!COMMANDS.includes(command)) {
    const payload = asJsonError(command, new Error(`Unknown command: ${command}`));
    console.error(JSON.stringify(payload, null, 2));
    process.exit(1);
  }

  try {
    await assertSdkInstalled();
    const authStatus = ensureAuthConfigured();
    if (authStatus?.auth_required) {
      const response = asJsonResponse(command, authStatus, false);
      const payload = { ...response, ...authStatus };
      console.log(JSON.stringify(payload, null, 2));
      process.exit(0);
    }

    const stitch = await loadSdk();
    let data;

    switch (command) {
      case "generate":
        data = await runGenerate(stitch, parsed);
        break;
      case "edit":
        data = await runEdit(stitch, parsed);
        break;
      case "variants":
        data = await runVariants(stitch, parsed);
        break;
      case "get-screen":
        data = await runGetScreen(stitch, parsed);
        break;
      case "list-screens":
        data = await runListScreens(stitch, parsed);
        break;
      case "create-project":
        data = await runCreateProject(stitch, parsed);
        break;
      case "get-project":
        data = await runGetProject(stitch, parsed);
        break;
      case "list-projects":
        data = await runListProjects(stitch, parsed);
        break;
      case "init":
        data = await runInit(stitch, parsed);
        break;
      default:
        throw new Error(`Unhandled command: ${command}`);
    }

    const payload = asJsonResponse(command, data, true);
    console.log(safeStringify(payload));
  } catch (error) {
    if (error instanceof SdkMissingError || error?.install_required) {
      const payload = asInstallRequiredError(command, error);
      console.log(safeStringify(payload));
      process.exit(2);
    }
    const payload = asJsonError(command, error);
    console.error(safeStringify(payload));
    process.exit(1);
  }
}

main();
