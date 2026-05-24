// src/shared/constants.ts
var DEFAULT_SERVER_ORIGIN = "http://127.0.0.1:3847";
var SERVER_ENDPOINTS = {
  HEALTH: "/api/health",
  PROJECTS: "/api/projects"
};
var MESSAGE_TYPES = {
  TOGGLE_INSPECT: "TOGGLE_INSPECT",
  INSPECT_STATUS: "INSPECT_STATUS",
  CAPTURE_DATA: "CAPTURE_DATA",
  SAVE_CAPTURE: "SAVE_CAPTURE",
  TAKE_SCREENSHOT: "TAKE_SCREENSHOT",
  CAPTURE_SAVE: "CAPTURE_SAVE",
  SERVER_STATUS: "SERVER_STATUS",
  SERVER_STATUS_QUERY: "SERVER_STATUS_QUERY",
  PROJECTS_REFRESH: "PROJECTS_REFRESH"
};
var STORAGE_KEYS = {
  SERVER_STATUS: "server-status-connected",
  LAST_CAPTURE: "last-capture",
  SYNC_STATUS: "sync-status",
  SERVER_ORIGIN: "server-origin-override",
  SELECTED_PROJECT: "selected-project"
};

// src/shared/types.ts
var OVERLAY_TOGGLE_MESSAGE = "OVERLAY_TOGGLE";

// src/shared/messages.ts
async function sendToBackground(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}

// src/popup/popup.ts
var SERVER_STATUS_POLL_MS = 3e3;
var INSPECT_ERROR_TIMEOUT_MS = 3e3;
var INSPECT_ERROR_TEXT = "Please reload the page and try again";
var INSPECT_TEXT = "Pick an element on the page";
var toggleButton = document.getElementById("inspectToggle");
var inspectText = document.getElementById("inspectText");
var serverStatusDot = document.getElementById("serverStatusDot");
var serverStatusText = document.getElementById("serverStatusText");
var projectSelect = document.getElementById("projectSelect");
var refreshProjectsButton = document.getElementById("refreshProjects");
var overlayToggleButton = document.getElementById("overlayToggle");
var overlayText = document.getElementById("overlayText");
var overlayStateStorageKey = "gm-overlay-badge-state";
var disconnectedServerTooltip = "/mst:dashboard\uB85C \uC11C\uBC84\uB97C \uC2DC\uC791\uD558\uC138\uC694";
var activeTabId = null;
var isOverlayEnabled = true;
var isProjectCatalogLoaded = false;
var lastServerConnected = false;
var inspectErrorTimeout = null;
var cachedProjects = [];
function applyInspectModeUI() {
  if (toggleButton) {
    toggleButton.textContent = "Pick Element";
  }
  if (inspectText) {
    inspectText.textContent = INSPECT_TEXT;
  }
}
function applyOverlayModeUI(enabled) {
  isOverlayEnabled = enabled;
  if (overlayToggleButton) {
    overlayToggleButton.textContent = enabled ? "Hide Element IDs" : "Show Element IDs";
  }
  if (overlayText) {
    overlayText.textContent = enabled ? "Element IDs: ON" : "Element IDs: OFF";
  }
}
function applyServerStatusUI(connected) {
  if (serverStatusDot) {
    serverStatusDot.classList.toggle("online", connected);
  }
  if (serverStatusText) {
    serverStatusText.textContent = connected ? "Server: connected" : "Server: disconnected";
    if (connected) {
      serverStatusText.removeAttribute("title");
    } else {
      serverStatusText.title = disconnectedServerTooltip;
    }
  }
}
function isStaleProjectFallback() {
  if (!projectSelect) {
    return false;
  }
  return Array.from(projectSelect.options).some((option) => option.value === "default");
}
function clearProjectOptions() {
  if (!projectSelect) {
    return;
  }
  projectSelect.options.length = 0;
}
function createProjectOption(value, text) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = text;
  return option;
}
function renderDisconnectedProjectFallback() {
  if (!projectSelect) {
    return;
  }
  clearProjectOptions();
  projectSelect.disabled = false;
  const selectProjectOption = createProjectOption("", "Select project");
  const defaultProjectOption = createProjectOption("default", "default");
  selectProjectOption.selected = true;
  defaultProjectOption.selected = false;
  projectSelect.append(selectProjectOption, defaultProjectOption);
}
function renderConnectedNoProjectPlaceholder() {
  if (!projectSelect) {
    return;
  }
  clearProjectOptions();
  projectSelect.disabled = false;
  const selectProjectOption = createProjectOption("", "Select project");
  selectProjectOption.selected = true;
  projectSelect.appendChild(selectProjectOption);
}
function populateProjectDropdown(projects) {
  if (!projectSelect) {
    return;
  }
  clearProjectOptions();
  for (const project of projects) {
    projectSelect.appendChild(createProjectOption(project.id, project.name));
  }
  projectSelect.disabled = false;
}
function isNonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}
function normalizeProject(data) {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const candidate = data;
  if (typeof candidate.id !== "string" || typeof candidate.name !== "string" || typeof candidate.path !== "string" || typeof candidate.registered_at !== "string") {
    return null;
  }
  return {
    id: candidate.id,
    name: candidate.name,
    path: candidate.path,
    registered_at: candidate.registered_at
  };
}
function showInspectErrorMessage() {
  if (!inspectText) {
    return;
  }
  if (inspectErrorTimeout !== null) {
    clearTimeout(inspectErrorTimeout);
  }
  inspectText.textContent = INSPECT_ERROR_TEXT;
  inspectErrorTimeout = window.setTimeout(() => {
    inspectErrorTimeout = null;
    applyInspectModeUI();
  }, INSPECT_ERROR_TIMEOUT_MS);
}
async function readServerOrigin() {
  const serverConfig = await chrome.storage.local.get(STORAGE_KEYS.SERVER_ORIGIN);
  const configured = serverConfig[STORAGE_KEYS.SERVER_ORIGIN];
  return typeof configured === "string" && configured.trim().length > 0 ? configured : DEFAULT_SERVER_ORIGIN;
}
async function fetchProjects() {
  const serverOrigin = await readServerOrigin();
  const endpoint = `${serverOrigin}${SERVER_ENDPOINTS.PROJECTS}`;
  try {
    const response = await fetch(endpoint, {
      method: "GET",
      signal: AbortSignal.timeout(5e3)
    });
    if (!response.ok) {
      console.warn(
        `[Gran Maestro] fetchProjects failed: HTTP ${response.status} ${response.statusText}`
      );
      return [];
    }
    const body = await response.json();
    if (!Array.isArray(body)) {
      console.warn(
        "[Gran Maestro] fetchProjects failed: unexpected response structure",
        body
      );
      return [];
    }
    const projects = body.map((entry) => normalizeProject(entry)).filter((project) => project !== null);
    return projects;
  } catch (error) {
    console.warn("[Gran Maestro] fetchProjects failed:", error);
    return [];
  }
}
function getSavedProjectId(state) {
  const savedProject = state[STORAGE_KEYS.SELECTED_PROJECT];
  return isNonEmptyString(savedProject) ? savedProject : "";
}
async function applyProjectState(projects) {
  if (!projectSelect) {
    return;
  }
  const state = await chrome.storage.local.get(STORAGE_KEYS.SELECTED_PROJECT);
  const savedProject = getSavedProjectId(state);
  const hasSavedProject = savedProject.length > 0 && projects.some((project) => project.id === savedProject);
  if (hasSavedProject) {
    projectSelect.value = savedProject;
    return;
  }
  const fallbackProjectId = projects[0]?.id;
  if (!fallbackProjectId) {
    return;
  }
  projectSelect.value = fallbackProjectId;
  await chrome.storage.local.set({ [STORAGE_KEYS.SELECTED_PROJECT]: fallbackProjectId });
}
async function hydrateProjectUI() {
  if (!projectSelect) {
    return;
  }
  const projects = await fetchProjects();
  cachedProjects = projects;
  isProjectCatalogLoaded = true;
  if (projects.length === 0) {
    renderConnectedNoProjectPlaceholder();
    return;
  }
  populateProjectDropdown(projects);
  await applyProjectState(projects);
}
async function handleServerStatusChange(connected) {
  const previousConnection = lastServerConnected;
  applyServerStatusUI(connected);
  if (connected === previousConnection) {
    if (!connected) {
      if (!isProjectCatalogLoaded) {
        renderDisconnectedProjectFallback();
      }
      return;
    }
    if (isStaleProjectFallback()) {
      await hydrateProjectUI();
    }
    return;
  }
  lastServerConnected = connected;
  if (connected) {
    await hydrateProjectUI();
    return;
  }
  if (previousConnection && isProjectCatalogLoaded) {
    if (cachedProjects.length > 0) {
      if (projectSelect) {
        projectSelect.disabled = true;
      }
      return;
    }
    renderDisconnectedProjectFallback();
    return;
  }
  renderDisconnectedProjectFallback();
}
async function refreshServerStatus() {
  const serverStatus = await sendToBackground({
    type: MESSAGE_TYPES.SERVER_STATUS_QUERY,
    payload: {}
  });
  await handleServerStatusChange(serverStatus.payload.connected);
  return serverStatus.payload.connected;
}
async function queryActiveTabId() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const activeTab = tabs[0];
  if (!activeTab?.id) {
    throw new Error("Active tab not found");
  }
  return activeTab.id;
}
async function hydrateOverlayUI() {
  const overlayState = await chrome.storage.local.get(overlayStateStorageKey);
  const hasStoredOverlayState = Object.prototype.hasOwnProperty.call(
    overlayState,
    overlayStateStorageKey
  );
  const overlayStateValue = hasStoredOverlayState ? Boolean(overlayState[overlayStateStorageKey]) : true;
  applyOverlayModeUI(overlayStateValue);
}
async function setupConnectionPolling() {
  await refreshServerStatus();
  window.setInterval(() => {
    void refreshServerStatus();
  }, SERVER_STATUS_POLL_MS);
}
function setupListeners() {
  if (toggleButton) {
    toggleButton.addEventListener("click", async () => {
      if (activeTabId === null) {
        return;
      }
      const message = {
        type: MESSAGE_TYPES.TOGGLE_INSPECT,
        payload: {
          tabId: activeTabId,
          enabled: true
        }
      };
      try {
        const response = await sendToBackground(message);
        if (!response || !("payload" in response) || "ok" in response && response.ok === false) {
          throw new Error(INSPECT_ERROR_TEXT);
        }
        const inspectPayload = response.payload;
        if (!inspectPayload || typeof inspectPayload.enabled !== "boolean") {
          throw new Error(INSPECT_ERROR_TEXT);
        }
        applyInspectModeUI();
        window.close();
      } catch {
        showInspectErrorMessage();
      }
    });
  }
  if (projectSelect) {
    projectSelect.addEventListener("change", async () => {
      await chrome.storage.local.set({
        [STORAGE_KEYS.SELECTED_PROJECT]: projectSelect.value
      });
    });
  }
  if (refreshProjectsButton) {
    refreshProjectsButton.addEventListener("click", () => {
      void hydrateProjectUI();
    });
  }
  if (overlayToggleButton) {
    overlayToggleButton.addEventListener("click", async () => {
      if (activeTabId === null) {
        return;
      }
      const nextState = !isOverlayEnabled;
      const message = {
        type: OVERLAY_TOGGLE_MESSAGE,
        payload: {
          tabId: activeTabId,
          enabled: nextState
        }
      };
      try {
        await chrome.tabs.sendMessage(activeTabId, message);
        await chrome.storage.local.set({ [overlayStateStorageKey]: nextState });
        applyOverlayModeUI(nextState);
      } catch {
        applyOverlayModeUI(isOverlayEnabled);
      }
    });
  }
}
async function bootstrap() {
  try {
    activeTabId = await queryActiveTabId();
    await hydrateOverlayUI();
    applyServerStatusUI(false);
    renderDisconnectedProjectFallback();
    await setupConnectionPolling();
    if (lastServerConnected) {
      await hydrateProjectUI();
    }
  } catch {
    applyInspectModeUI();
    applyServerStatusUI(false);
  }
}
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === MESSAGE_TYPES.SERVER_STATUS) {
    const statusMessage = message;
    void handleServerStatusChange(statusMessage.payload.connected);
  }
  if (message?.type === MESSAGE_TYPES.INSPECT_STATUS) {
    return;
  }
  if (message?.type === MESSAGE_TYPES.PROJECTS_REFRESH) {
    void hydrateProjectUI();
  }
});
bootstrap().catch(() => {
  applyInspectModeUI();
  applyServerStatusUI(false);
});
setupListeners();
//# sourceMappingURL=popup.js.map
