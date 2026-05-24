// src/shared/constants.ts
var DEFAULT_SERVER_ORIGIN = "http://127.0.0.1:3847";
var DEFAULT_HEALTH_CHECK_MS = 1e4;
var DEFAULT_REQUEST_TIMEOUT_MS = 5e3;
var REQUEST_POLL_INTERVAL_MS = 1e4;
var OFFLINE_SYNC_DELAY_MS = 1e3;
var OFFLINE_SYNC_MAX_ATTEMPTS = 3;
var SERVER_ENDPOINTS = {
  HEALTH: "/api/health",
  PROJECTS: "/api/projects"
};
function capturesEndpoint(projectId) {
  return `/api/projects/${projectId}/captures`;
}
var SERVER_DB = {
  NAME: "gran-maestro-extension",
  OFFLINE_STORE: "gm-offline-captures",
  KEY_PATH: "localId",
  CREATED_AT_INDEX: "createdAt"
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

// src/shared/messages.ts
async function sendToContent(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}
function isExtensionMessage(message) {
  return typeof message === "object" && message !== null && "type" in message;
}

// src/background/server-client.ts
var ServerRequestError = class extends Error {
  status;
  isOffline;
  constructor(message, details) {
    super(message);
    this.status = details?.status;
    this.isOffline = Boolean(details?.isOffline);
  }
};
function isAbortError(error) {
  return error instanceof DOMException && error.name === "AbortError";
}
function requestTimeoutSignal(timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, timeoutMs);
  return {
    signal: controller.signal,
    cancel: () => clearTimeout(timer)
  };
}
async function parseJsonSafe(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}
async function readServerConfig() {
  const config = await chrome.storage.local.get(STORAGE_KEYS.SERVER_ORIGIN);
  const configured = config[STORAGE_KEYS.SERVER_ORIGIN];
  return {
    baseUrl: typeof configured === "string" && configured.trim().length > 0 ? configured : DEFAULT_SERVER_ORIGIN
  };
}
function buildEndpoint(baseUrl, path) {
  return `${baseUrl}${path}`;
}
async function getSelectedProjectId() {
  const state = await chrome.storage.local.get(STORAGE_KEYS.SELECTED_PROJECT);
  const projectId = state[STORAGE_KEYS.SELECTED_PROJECT];
  if (typeof projectId === "string" && projectId.length > 0) {
    return projectId;
  }
  throw new ServerRequestError("No project selected");
}
function extractCaptureId(payload) {
  if (typeof payload === "string") {
    return payload;
  }
  if (typeof payload !== "object" || payload === null) {
    return null;
  }
  const objectPayload = payload;
  if (typeof objectPayload.id === "string") {
    return objectPayload.id;
  }
  return null;
}
async function postCaptureRaw(config, capturePayload, projectId) {
  const headers = {
    "Content-Type": "application/json"
  };
  const timeout = requestTimeoutSignal(DEFAULT_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(
      buildEndpoint(config.baseUrl, capturesEndpoint(projectId)),
      {
        method: "POST",
        headers,
        body: JSON.stringify(capturePayload),
        signal: timeout.signal
      }
    );
    return response;
  } finally {
    timeout.cancel();
  }
}
async function healthCheck() {
  const config = await readServerConfig();
  const timeout = requestTimeoutSignal(DEFAULT_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(
      buildEndpoint(config.baseUrl, SERVER_ENDPOINTS.HEALTH),
      {
        method: "GET",
        signal: timeout.signal
      }
    );
    if (!response.ok) {
      return false;
    }
    try {
      const body = await response.json();
      return body?.ok === true;
    } catch (error) {
      console.warn("healthCheck: failed to parse response JSON", error);
      return false;
    }
  } catch (error) {
    if (isAbortError(error) || error instanceof TypeError) {
      return false;
    }
    return false;
  } finally {
    timeout.cancel();
  }
}
async function postCapture(capturePayload) {
  const config = await readServerConfig();
  const projectId = await getSelectedProjectId();
  let response = null;
  try {
    response = await postCaptureRaw(config, capturePayload, projectId);
  } catch (error) {
    throw new ServerRequestError("CAPTURE_SAVE failed while posting capture", {
      isOffline: true
    });
  }
  if (!response.ok) {
    throw new ServerRequestError(`CAPTURE_SAVE failed with status ${response.status}`, {
      status: response.status
    });
  }
  const body = await parseJsonSafe(response);
  const captureId = extractCaptureId(body);
  if (!captureId) {
    throw new ServerRequestError("CAPTURE_SAVE response did not include id");
  }
  return captureId;
}

// src/background/connection-monitor.ts
var initialized = false;
var isConnected = null;
var timerId = null;
var listeners = /* @__PURE__ */ new Set();
async function updateConnectionState(nextConnected) {
  const previous = isConnected;
  isConnected = nextConnected;
  await chrome.storage.local.set({ [STORAGE_KEYS.SERVER_STATUS]: nextConnected });
  if (previous !== nextConnected) {
    listeners.forEach((listener) => listener(nextConnected));
    chrome.runtime.sendMessage({
      type: MESSAGE_TYPES.SERVER_STATUS,
      payload: {
        connected: nextConnected
      }
    }).catch(() => {
    });
    if (nextConnected) {
      chrome.runtime.sendMessage({
        type: MESSAGE_TYPES.PROJECTS_REFRESH,
        payload: {}
      }).catch(() => {
      });
    }
  }
}
async function checkHealth() {
  let connected = false;
  try {
    connected = await healthCheck();
  } catch {
    connected = false;
  }
  await updateConnectionState(connected);
}
function onConnectionChange(listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
function initializeConnectionMonitor() {
  if (initialized) {
    return;
  }
  initialized = true;
  checkHealth().catch(() => {
    void updateConnectionState(false);
  });
  const runCheck = () => {
    void checkHealth();
  };
  timerId = self.setInterval(runCheck, DEFAULT_HEALTH_CHECK_MS);
  if (chrome.alarms && chrome.alarms.create) {
    const alarmName = "gm-server-health-check";
    chrome.alarms.create(alarmName, {
      periodInMinutes: Math.max(DEFAULT_HEALTH_CHECK_MS / 6e4, 1 / 6)
    });
    chrome.alarms.onAlarm.addListener((alarm) => {
      if (alarm.name !== alarmName) {
        return;
      }
      runCheck();
    });
  }
  chrome.runtime.onStartup.addListener(() => {
    runCheck();
  });
  if (REQUEST_POLL_INTERVAL_MS <= 0) {
    return;
  }
}

// src/background/offline-store.ts
var dbPromise = null;
function requestToPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error("IndexedDB request failed"));
    };
  });
}
function transactionToPromise(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => {
      resolve();
    };
    transaction.onabort = () => {
      reject(transaction.error ?? new Error("IndexedDB transaction aborted"));
    };
    transaction.onerror = () => {
      reject(transaction.error ?? new Error("IndexedDB transaction failed"));
    };
  });
}
async function openOfflineDatabase() {
  if (dbPromise) {
    return dbPromise;
  }
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(SERVER_DB.NAME);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(SERVER_DB.OFFLINE_STORE)) {
        const store = db.createObjectStore(SERVER_DB.OFFLINE_STORE, {
          keyPath: SERVER_DB.KEY_PATH
        });
        store.createIndex(SERVER_DB.CREATED_AT_INDEX, "createdAt", {
          unique: false
        });
      }
    };
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error("Failed to open IndexedDB"));
      dbPromise = null;
    };
  });
  return dbPromise;
}
function createLocalCaptureId() {
  const randomValue = typeof crypto.randomUUID === "function" ? crypto.randomUUID().replace(/-/g, "") : Math.random().toString(16).slice(2, 10);
  return `LOCAL-${randomValue.slice(0, 8).toUpperCase()}`;
}
async function queueOfflineCapture(capturePayload) {
  const db = await openOfflineDatabase();
  const record = {
    localId: createLocalCaptureId(),
    payload: capturePayload,
    createdAt: (/* @__PURE__ */ new Date()).toISOString(),
    syncAttempts: 0
  };
  const tx = db.transaction(SERVER_DB.OFFLINE_STORE, "readwrite");
  const store = tx.objectStore(SERVER_DB.OFFLINE_STORE);
  requestToPromise(store.put(record));
  await transactionToPromise(tx);
  return record;
}
async function getOfflineCaptures() {
  const db = await openOfflineDatabase();
  const tx = db.transaction(SERVER_DB.OFFLINE_STORE, "readonly");
  const store = tx.objectStore(SERVER_DB.OFFLINE_STORE);
  const index = store.index(SERVER_DB.CREATED_AT_INDEX);
  const rows = [];
  const cursorRequest = index.openCursor();
  await new Promise((resolve, reject) => {
    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result;
      if (cursor) {
        rows.push(cursor.value);
        cursor.continue();
        return;
      }
      resolve();
    };
    cursorRequest.onerror = () => {
      reject(cursorRequest.error ?? new Error("Failed to read offline queue"));
    };
  });
  await transactionToPromise(tx);
  return rows;
}
async function deleteOfflineCapture(localId) {
  const db = await openOfflineDatabase();
  const tx = db.transaction(SERVER_DB.OFFLINE_STORE, "readwrite");
  requestToPromise(tx.objectStore(SERVER_DB.OFFLINE_STORE).delete(localId));
  await transactionToPromise(tx);
}
async function markOfflineCaptureFailed(localId, existingAttempts) {
  const db = await openOfflineDatabase();
  const tx = db.transaction(SERVER_DB.OFFLINE_STORE, "readonly");
  const request = tx.objectStore(SERVER_DB.OFFLINE_STORE).get(localId);
  const existing = await requestToPromise(request);
  await transactionToPromise(tx);
  if (!existing) {
    return;
  }
  const record = existing;
  const attempts = existingAttempts + 1;
  const nextRecord = {
    ...record,
    syncAttempts: attempts > OFFLINE_SYNC_MAX_ATTEMPTS ? OFFLINE_SYNC_MAX_ATTEMPTS : attempts
  };
  const writeTx = db.transaction(SERVER_DB.OFFLINE_STORE, "readwrite");
  requestToPromise(writeTx.objectStore(SERVER_DB.OFFLINE_STORE).put(nextRecord));
  await transactionToPromise(writeTx);
}

// src/background/sync-manager.ts
var syncing = false;
function updateSyncState(state) {
  chrome.storage.local.set({
    [STORAGE_KEYS.SYNC_STATUS]: state
  });
}
function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
async function syncOne(record) {
  try {
    await postCapture(record.payload);
    await deleteOfflineCapture(record.localId);
    return true;
  } catch (error) {
    const nextAttempts = record.syncAttempts + 1;
    await markOfflineCaptureFailed(record.localId, record.syncAttempts);
    if (nextAttempts < OFFLINE_SYNC_MAX_ATTEMPTS) {
      return false;
    }
    return false;
  }
}
async function syncOfflineQueue() {
  if (syncing) {
    return;
  }
  syncing = true;
  let totalCount = 0;
  let syncedCount = 0;
  try {
    const offlineCaptures = await getOfflineCaptures();
    totalCount = offlineCaptures.length;
    updateSyncState({ syncing: true, totalCount, syncedCount });
    for (const record of offlineCaptures) {
      const synced = await syncOne(record);
      if (synced) {
        syncedCount += 1;
      }
      if (syncedCount < totalCount) {
        await delay(OFFLINE_SYNC_DELAY_MS);
      }
      updateSyncState({ syncing: true, totalCount, syncedCount });
    }
    updateSyncState({
      syncing: false,
      totalCount,
      syncedCount
    });
  } finally {
    syncing = false;
  }
}

// src/background/index.ts
async function readServerStatus() {
  const status = await chrome.storage.local.get(STORAGE_KEYS.SERVER_STATUS);
  return Boolean(status[STORAGE_KEYS.SERVER_STATUS]);
}
async function handleCaptureSave(capture) {
  try {
    const captureId = await postCapture(capture);
    return {
      ok: true,
      payload: {
        captureId
      }
    };
  } catch (error) {
    if (error instanceof ServerRequestError && error.isOffline) {
      const queued = await queueOfflineCapture(capture);
      return {
        ok: true,
        payload: {
          captureId: queued.localId
        }
      };
    }
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Unknown error"
    };
  }
}
function setupConnectionListener() {
  onConnectionChange(async (connected) => {
    if (!connected) {
      return;
    }
    try {
      await syncOfflineQueue();
    } catch {
    }
  });
}
chrome.runtime.onInstalled.addListener(() => {
  console.log("Gran Maestro extension installed");
  chrome.storage.local.set({ [STORAGE_KEYS.SERVER_STATUS]: false });
});
initializeConnectionMonitor();
setupConnectionListener();
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!isExtensionMessage(message)) {
    return false;
  }
  (async () => {
    if (message.type === MESSAGE_TYPES.TOGGLE_INSPECT) {
      const typedMessage = message;
      const responseFromContent = await sendToContent(
        typedMessage.payload.tabId,
        message
      );
      if (!responseFromContent?.payload || typeof responseFromContent.payload.enabled !== "boolean") {
        sendResponse({
          ok: false,
          error: "Invalid inspect status response"
        });
        return;
      }
      sendResponse({
        ok: true,
        type: MESSAGE_TYPES.INSPECT_STATUS,
        payload: responseFromContent.payload
      });
      return;
    }
    if (message.type === MESSAGE_TYPES.SERVER_STATUS_QUERY) {
      const connected = await readServerStatus();
      const response = {
        type: MESSAGE_TYPES.SERVER_STATUS,
        payload: { connected }
      };
      sendResponse(response);
      return;
    }
    if (message.type === MESSAGE_TYPES.TAKE_SCREENSHOT) {
      try {
        const windowId = sender?.tab?.windowId;
        const imageDataUrl = windowId ? await chrome.tabs.captureVisibleTab(windowId, { format: "png" }) : await chrome.tabs.captureVisibleTab({ format: "png" });
        const response = {
          ok: true,
          payload: { imageDataUrl }
        };
        sendResponse(response);
      } catch (error) {
        console.error(
          "[GM] captureVisibleTab error:",
          error instanceof Error ? error.message : error
        );
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : "Screenshot capture failed"
        });
      }
      return;
    }
    if (message.type === MESSAGE_TYPES.CAPTURE_SAVE) {
      const typedMessage = message;
      const capture = typedMessage.payload.capture;
      const tabId = typedMessage.payload.tabId ?? sender?.tab?.id ?? null;
      await chrome.storage.local.set({
        [STORAGE_KEYS.LAST_CAPTURE]: {
          tabId,
          capture
        }
      });
      const response = await handleCaptureSave(capture);
      sendResponse(response);
      return;
    }
    if (message.type === MESSAGE_TYPES.CAPTURE_DATA || message.type === MESSAGE_TYPES.SAVE_CAPTURE) {
      await chrome.storage.local.set({
        [STORAGE_KEYS.LAST_CAPTURE]: message.payload
      });
      sendResponse({ ok: true });
      return;
    }
    if (message.type === MESSAGE_TYPES.INSPECT_STATUS) {
      sendResponse({
        ok: true
      });
      return;
    }
    sendResponse({ ok: false, error: `Unhandled message type: ${message.type}` });
  })().catch((error) => {
    sendResponse({
      ok: false,
      error: error instanceof Error ? error.message : "Unknown error"
    });
  });
  return true;
});
//# sourceMappingURL=background.js.map
