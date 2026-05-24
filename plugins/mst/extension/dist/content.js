// src/shared/constants.ts
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
function isExtensionMessage(message) {
  return typeof message === "object" && message !== null && "type" in message;
}

// src/content/styles.ts
var INSPECT_OVERLAY_BORDER_COLOR = "#4A90D9";
var INSPECT_OVERLAY_BACKGROUND = "rgba(74, 144, 217, 0.1)";
var INSPECT_OVERLAY_Z_INDEX = 2147483647;
var INSPECT_OVERLAY_MIN_SIZE = 8;
var INSPECT_OVERLAY_HOST_ATTRIBUTE = "data-gm-inspector-overlay";
var INSPECT_OVERLAY_STYLES = `
  :host {
    position: absolute;
    width: 0;
    height: 0;
    top: 0;
    left: 0;
    pointer-events: none;
    z-index: ${INSPECT_OVERLAY_Z_INDEX};
  }

  .gm-inspector-box {
    position: absolute;
    border: 2px solid ${INSPECT_OVERLAY_BORDER_COLOR};
    background: ${INSPECT_OVERLAY_BACKGROUND};
    box-sizing: border-box;
    pointer-events: none;
  }

  .gm-inspector-label {
    position: absolute;
    top: 0;
    left: 0;
    max-width: 400px;
    padding: 2px 6px;
    border-radius: 4px;
    background: ${INSPECT_OVERLAY_BORDER_COLOR};
    color: #ffffff;
    box-sizing: border-box;
    font: 12px/1.4 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    pointer-events: none;
  }
`;

// src/content/selector-display.ts
function isUniqueSelector(selector, target) {
  try {
    const matches = target.ownerDocument.querySelectorAll(selector);
    return matches.length === 1 && matches[0] === target;
  } catch {
    return false;
  }
}
function getNthOfTypeIndex(element) {
  if (!element.parentElement) {
    return 1;
  }
  const tagName = element.tagName.toLowerCase();
  const siblings = Array.from(element.parentElement.children).filter((item) => item.tagName.toLowerCase() === tagName);
  return siblings.indexOf(element) + 1;
}
function getUniqueSelector(element) {
  const tagName = element.tagName.toLowerCase();
  if (element.id) {
    const byId = `#${CSS.escape(element.id)}`;
    if (isUniqueSelector(byId, element)) {
      return byId;
    }
  }
  const classes = Array.from(element.classList).map((className) => className.trim()).filter(Boolean).map((className) => `.${CSS.escape(className)}`);
  if (classes.length > 0) {
    const byClass = `${tagName}${classes.join("")}`;
    if (isUniqueSelector(byClass, element)) {
      return byClass;
    }
    const withNth = `${byClass}:nth-of-type(${getNthOfTypeIndex(element)})`;
    if (isUniqueSelector(withNth, element)) {
      return withNth;
    }
  }
  const defaultSelector = `${tagName}:nth-of-type(${getNthOfTypeIndex(element)})`;
  if (isUniqueSelector(defaultSelector, element)) {
    return defaultSelector;
  }
  return defaultSelector;
}
function formatTagName(element) {
  const normalized = element.tagName.toLowerCase();
  return normalized[0] ? normalized[0].toUpperCase() + normalized.slice(1) : normalized;
}
function getCSSPath(element) {
  const pathParts = [];
  let current = element;
  let depth = 0;
  while (current && depth < 5) {
    pathParts.unshift(formatTagName(current));
    current = current.parentElement;
    depth += 1;
  }
  return pathParts.join(" > ");
}

// src/content/highlighter.ts
var Highlighter = class {
  doc;
  host;
  box;
  label;
  shadowRoot;
  currentTarget = null;
  constructor(options = {}) {
    this.doc = options.doc ?? document;
    this.host = this.doc.createElement("div");
    this.host.setAttribute(INSPECT_OVERLAY_HOST_ATTRIBUTE, "true");
    this.host.style.display = "none";
    this.host.style.position = "absolute";
    this.host.style.pointerEvents = "none";
    this.host.style.zIndex = "2147483647";
    this.shadowRoot = this.host.attachShadow({ mode: "open" });
    const style = this.doc.createElement("style");
    const box = this.doc.createElement("div");
    const label = this.doc.createElement("div");
    style.textContent = INSPECT_OVERLAY_STYLES;
    box.className = "gm-inspector-box";
    label.className = "gm-inspector-label";
    this.shadowRoot.append(style, box, label);
    this.box = box;
    this.label = label;
  }
  mount() {
    const container = this.doc.body ?? this.doc.documentElement;
    if (container && !this.host.isConnected) {
      container.appendChild(this.host);
    }
  }
  unmount() {
    this.hide();
    if (this.host.isConnected) {
      this.host.remove();
    }
  }
  isOverlayElement(node) {
    return !!node && (node === this.host || this.host.contains(node));
  }
  setTarget(target) {
    if (!target) {
      this.currentTarget = null;
      this.hide();
      return;
    }
    const win = this.doc.defaultView;
    if (!win) {
      return;
    }
    const rect = target.getBoundingClientRect();
    const width = Math.max(rect.width, INSPECT_OVERLAY_MIN_SIZE);
    const height = Math.max(rect.height, INSPECT_OVERLAY_MIN_SIZE);
    const left = rect.left + win.scrollX;
    const top = rect.top + win.scrollY;
    if (target !== this.currentTarget) {
      this.label.textContent = this.buildLabelText(target, rect);
    }
    this.host.style.left = `${left}px`;
    this.host.style.top = `${top}px`;
    this.host.style.width = `${width}px`;
    this.host.style.height = `${height}px`;
    this.box.style.width = `${width}px`;
    this.box.style.height = `${height}px`;
    this.host.style.display = "block";
    const labelHeight = this.label.offsetHeight || 20;
    const labelWidth = this.label.offsetWidth || 100;
    const maxLeft = win.innerWidth - labelWidth - win.scrollX;
    const clampedLeft = Math.max(-left, Math.min(0, maxLeft - left));
    this.label.style.top = rect.top > labelHeight ? `${-labelHeight}px` : `${height}px`;
    this.label.style.left = `${clampedLeft}px`;
    this.currentTarget = target;
  }
  refresh() {
    this.setTarget(this.currentTarget);
  }
  hide() {
    this.host.style.display = "none";
    this.currentTarget = null;
  }
  buildLabelText(target, rect) {
    const tag = target.tagName.toLowerCase();
    let identifier = "";
    if (target.id) {
      identifier = `#${target.id}`;
    } else {
      const classes = Array.from(target.classList).slice(0, 2);
      if (classes.length > 0) {
        identifier = classes.map((className) => `.${className}`).join("");
      }
    }
    const size = `${Math.round(rect.width)}\xD7${Math.round(rect.height)}`;
    const path = getCSSPath(target);
    return `${tag}${identifier}  ${size}  ${path}`;
  }
};

// src/content/navigator.ts
var Navigator = class {
  current = null;
  setCurrent(target) {
    this.current = target;
  }
  getCurrent() {
    return this.current;
  }
  move(direction) {
    const next = this.getNextTarget(direction);
    if (next) {
      this.current = next;
    }
    return this.current;
  }
  getNextTarget(direction) {
    if (!this.current) {
      return null;
    }
    switch (direction) {
      case "ArrowUp": {
        if (this.current === document.body) {
          return this.current;
        }
        if (this.current === document.documentElement) {
          return document.body;
        }
        const parent = this.current.parentElement;
        if (!parent) {
          return this.current;
        }
        if (parent === document.documentElement) {
          return document.body;
        }
        return parent;
      }
      case "ArrowDown": {
        return this.current.firstElementChild || this.current;
      }
      case "ArrowLeft": {
        return this.current.previousElementSibling || this.current;
      }
      case "ArrowRight": {
        return this.current.nextElementSibling || this.current;
      }
      default:
        return this.current;
    }
  }
};

// src/content/panel-styles.ts
var INLINE_PANEL_STYLES = `
  :host {
    position: fixed;
    pointer-events: none;
    z-index: 2147483647;
  }

  .gm-inline-panel {
    pointer-events: auto;
    width: min(340px, 92vw);
    background: #1e1e1e;
    color: #e8e8e8;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    padding: 8px;
    box-sizing: border-box;
    font-family: Menlo, Consolas, monospace;
    font-size: 12px;
    display: grid;
    gap: 6px;
  }

  .gm-inline-panel textarea,
  .gm-inline-panel input {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid #3c3c3c;
    background: #252525;
    color: inherit;
    border-radius: 2px;
    padding: 4px 6px;
    font-size: 12px;
  }

  .gm-inline-panel textarea {
    resize: vertical;
    min-height: 56px;
    font-family: inherit;
    font-size: 12px;
  }

  .gm-path,
  .gm-selector {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding: 4px 6px;
    border: 1px solid #3c3c3c;
    background: #252525;
    border-radius: 2px;
  }

  .gm-path {
    color: #a8a8a8;
  }

  .gm-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    margin-top: 2px;
  }

  .gm-action-btn {
    padding: 6px 8px;
    border-radius: 2px;
    border: 1px solid #3c3c3c;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font-family: Menlo, Consolas, monospace;
    font-size: 12px;
  }

  .gm-action-btn:focus-visible,
  .gm-tag-chip:focus-visible,
  .gm-action-list textarea:focus-visible {
    outline: 1px solid #0078d4;
    outline-offset: 1px;
  }

  .gm-action-immediate {
    background: #0078d4;
    color: #ffffff;
    border-color: #0078d4;
  }

  .gm-action-queue {
    background: #3c3c3c;
  }

  .gm-action-list {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }

  .gm-tag-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: #2f2f2f;
    border: 1px solid #3c3c3c;
    border-radius: 10px;
    padding: 2px 6px;
    font-size: 11px;
    color: #d2d2d2;
  }

  .gm-tag-remove {
    border: none;
    background: transparent;
    color: #b0b0b0;
    cursor: pointer;
    font-size: 12px;
    line-height: 1;
    padding: 0;
  }

  .gm-tag-input-shell {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .gm-tag-input-shell input {
    flex: 1;
    min-width: 0;
    font-family: inherit;
  }

  .gm-tag-add-btn {
    width: 26px;
    height: 26px;
    border-radius: 2px;
    border: 1px solid #3c3c3c;
    background: #303030;
    color: #f0f0f0;
    cursor: pointer;
    font-family: Menlo, Consolas, monospace;
    padding: 0;
  }

  .gm-divider {
    height: 1px;
    background: #3c3c3c;
    width: 100%;
  }

  @media (prefers-color-scheme: light) {
    .gm-inline-panel {
      background: #ffffff;
      color: #333333;
      border-color: #d8d8d8;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    }

    .gm-inline-panel textarea,
    .gm-inline-panel input,
    .gm-path,
    .gm-selector {
      background: #f5f5f5;
      border-color: #d8d8d8;
      color: #333333;
    }

    .gm-path {
      color: #444;
    }

    .gm-action-queue {
      background: #f0f0f0;
      color: #333333;
    }

    .gm-action-list {
      color: #333333;
    }

    .gm-tag-chip {
      background: #f0f0f0;
      color: #333333;
      border-color: #d8d8d8;
    }
  }
`;

// src/content/tag-input.ts
var TAG_STORAGE_KEY = "gm-inspector-tags";
var TagInput = class {
  container;
  chipArea;
  input;
  addButton;
  datalist;
  tags = /* @__PURE__ */ new Set();
  onTagsChange;
  constructor(container, onTagsChange) {
    this.container = container;
    this.onTagsChange = onTagsChange;
    const chipArea = document.createElement("div");
    chipArea.className = "gm-action-list";
    this.chipArea = chipArea;
    const inputShell = document.createElement("div");
    inputShell.className = "gm-tag-input-shell";
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "#";
    input.autocomplete = "off";
    input.maxLength = 40;
    const addButton = document.createElement("button");
    addButton.type = "button";
    addButton.textContent = "+";
    addButton.className = "gm-tag-add-btn";
    addButton.setAttribute("aria-label", "\uD0DC\uADF8 \uCD94\uAC00");
    this.addButton = addButton;
    const datalist = document.createElement("datalist");
    const datalistId = `gm-panel-tag-options-${Date.now()}`;
    datalist.id = datalistId;
    input.setAttribute("list", datalistId);
    this.datalist = datalist;
    inputShell.appendChild(input);
    inputShell.appendChild(addButton);
    inputShell.appendChild(datalist);
    this.input = input;
    inputShell.appendChild(input);
    inputShell.appendChild(addButton);
    this.container.appendChild(chipArea);
    this.container.appendChild(inputShell);
    this.container.appendChild(datalist);
    addButton.addEventListener("click", () => {
      this.addTag();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        this.addTag();
      }
    });
    void this.loadStoredTags();
  }
  reset() {
    this.setTags([]);
  }
  getTags() {
    return [...this.tags];
  }
  setTags(nextTags) {
    this.tags.clear();
    nextTags.forEach((tag) => {
      const normalized = this.normalize(tag);
      if (normalized) {
        this.tags.add(normalized);
      }
    });
    this.renderChips();
    this.notify();
  }
  addTag() {
    const normalized = this.normalize(this.input.value);
    if (!normalized) {
      return;
    }
    if (this.tags.has(normalized)) {
      this.input.value = "";
      return;
    }
    this.tags.add(normalized);
    this.renderChips();
    this.input.value = "";
    this.notify();
    void this.persistTag(normalized);
  }
  removeTag(tag) {
    this.tags.delete(tag);
    this.renderChips();
    this.notify();
  }
  renderChips() {
    this.chipArea.innerHTML = "";
    this.tags.forEach((tag) => {
      const chip = document.createElement("span");
      chip.className = "gm-tag-chip";
      const label = document.createElement("span");
      label.textContent = `#${tag}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "gm-tag-remove";
      remove.textContent = "\xD7";
      remove.setAttribute("aria-label", `\uD0DC\uADF8 ${tag} \uC0AD\uC81C`);
      remove.addEventListener("click", () => {
        this.removeTag(tag);
      });
      chip.append(label, remove);
      this.chipArea.appendChild(chip);
    });
  }
  normalize(value) {
    return value.trim().replace(/^#/, "").toLowerCase();
  }
  notify() {
    this.onTagsChange?.(this.getTags());
  }
  async loadStoredTags() {
    if (!chrome.storage || !chrome.storage.local) {
      return;
    }
    try {
      const result = await chrome.storage.local.get(TAG_STORAGE_KEY);
      const stored = result[TAG_STORAGE_KEY];
      if (!Array.isArray(stored)) {
        return;
      }
      stored.forEach((value) => {
        const normalized = this.normalize(String(value));
        if (normalized) {
          const option = document.createElement("option");
          option.value = normalized;
          this.datalist.appendChild(option);
        }
      });
    } catch {
      return;
    }
  }
  async persistTag(tag) {
    if (!chrome.storage || !chrome.storage.local) {
      return;
    }
    try {
      const result = await chrome.storage.local.get(TAG_STORAGE_KEY);
      const stored = Array.isArray(result[TAG_STORAGE_KEY]) ? result[TAG_STORAGE_KEY] : [];
      const next = Array.from(new Set(stored.map((value) => this.normalize(String(value))).concat([tag])));
      await chrome.storage.local.set({ [TAG_STORAGE_KEY]: next });
      this.datalist.innerHTML = "";
      next.forEach((item) => {
        const option = document.createElement("option");
        option.value = item;
        this.datalist.appendChild(option);
      });
    } catch {
      return;
    }
  }
};

// src/content/degradation/component-detector.ts
var REACT_MAX_FIBER_DEPTH = 20;
var REACT_FIBER_KEY_PREFIX = "__reactFiber$";
function getRecord(value) {
  return typeof value === "object" && value !== null ? value : null;
}
function findReactFiberNode(element) {
  const target = element;
  const reactFiberKey = Object.keys(target).find((key) => key.startsWith(REACT_FIBER_KEY_PREFIX));
  if (reactFiberKey && target[reactFiberKey] != null) {
    return target[reactFiberKey];
  }
  return target._reactInternals ?? target._reactInternalInstance ?? null;
}
function normalizeName(value) {
  if (typeof value === "string") {
    return value.trim() || null;
  }
  const record = getRecord(value);
  if (!record) {
    return null;
  }
  const candidate = record.displayName ?? record.name ?? record.__name ?? record.typeName;
  if (typeof candidate === "string") {
    const name = candidate.trim();
    if (name) {
      return name;
    }
  }
  return null;
}
function detectNameFromType(type) {
  const record = getRecord(type);
  if (!record) {
    return null;
  }
  const directName = normalizeName(record.type ?? record.elementType ?? record.innerType ?? record.renderedElement);
  if (directName) {
    return directName;
  }
  if (record.type && typeof record.type === "object") {
    const typeRecord = getRecord(record.type);
    const nested = normalizeName(typeRecord?.displayName) ?? normalizeName(typeRecord?.type) ?? normalizeName(typeRecord?.name);
    if (nested) {
      return nested;
    }
  }
  if (record.render && typeof record.render === "object") {
    const renderName = normalizeName(record.render.displayName) ?? normalizeName(record.render.name);
    if (renderName) {
      return renderName;
    }
  }
  return null;
}
function detectNameFromReactFiber(fiber) {
  const start = getRecord(fiber);
  if (!start) {
    return null;
  }
  let current = start;
  let depth = 0;
  while (current && depth < REACT_MAX_FIBER_DEPTH) {
    const type = current.type ?? current.elementType;
    const byType = detectNameFromType(type);
    if (byType) {
      return byType;
    }
    const byElement = normalizeName(current.elementType?.__displayName);
    if (byElement) {
      return byElement;
    }
    const byStateNode = normalizeName(current.stateNode && current.stateNode.constructor?.name);
    if (byStateNode) {
      return byStateNode;
    }
    current = getRecord(current.return) ?? getRecord(current._owner);
    depth += 1;
  }
  return null;
}
function detectVueFromParentComponent(element) {
  const parentComponent = element.__vueParentComponent;
  if (!parentComponent || typeof parentComponent !== "object") {
    return null;
  }
  const parentRecord = parentComponent;
  const parentType = parentRecord.type;
  const direct = normalizeName(parentType);
  if (direct) {
    return direct;
  }
  const namedType = normalizeName(parentType?.name) ?? normalizeName(parentType?.__name) ?? normalizeName(parentType?.__file);
  if (namedType) {
    return namedType;
  }
  const parentTypeRecord = getRecord(parentRecord.type);
  const fromOptions = normalizeName(parentTypeRecord?.name) ?? normalizeName(parentTypeRecord?.__name) ?? normalizeName(parentTypeRecord?.options && getRecord(parentTypeRecord.options)?.name) ?? normalizeName(parentTypeRecord?.options && getRecord(parentTypeRecord.options)?.__file);
  if (fromOptions) {
    return fromOptions;
  }
  return null;
}
function detectVueFromInstance(element) {
  const vueInstance = element.__vue__;
  if (!vueInstance || typeof vueInstance !== "object") {
    return null;
  }
  const vueRecord = vueInstance;
  const vueOptions = getRecord(vueRecord.$options);
  const byOptions = normalizeName(vueOptions?.name) ?? normalizeName(vueOptions?.__file) ?? normalizeName(vueOptions?.componentName);
  if (byOptions) {
    return byOptions;
  }
  return normalizeName(vueRecord._name) ?? normalizeName(vueOptions?.__name);
}
function detectComponentName(element) {
  try {
    const reactFiber = findReactFiberNode(element);
    if (reactFiber) {
      const reactName = detectNameFromReactFiber(reactFiber);
      if (reactName) {
        return reactName;
      }
    }
    const vueName = detectVueFromParentComponent(element) ?? detectVueFromInstance(element);
    if (vueName) {
      return vueName;
    }
    if (element.tagName.includes("-")) {
      return element.tagName.toLowerCase();
    }
    return null;
  } catch {
    return null;
  }
}

// src/content/degradation/source-mapper.ts
var REACT_MAX_FIBER_DEPTH2 = 20;
var REACT_FIBER_KEY_PREFIX2 = "__reactFiber$";
function getRecord2(value) {
  return typeof value === "object" && value !== null ? value : null;
}
function normalizeSource(source) {
  if (typeof source === "string") {
    const text = source.trim();
    return text || null;
  }
  const record = getRecord2(source);
  if (!record) {
    return null;
  }
  const file = typeof record.fileName === "string" ? record.fileName.trim() : typeof record.file === "string" ? record.file.trim() : "";
  if (!file) {
    return null;
  }
  const line = typeof record.lineNumber === "number" ? record.lineNumber : typeof record.line === "number" ? record.line : null;
  if (typeof line === "number" && Number.isFinite(line)) {
    return `${file}:${line}`;
  }
  return file;
}
function extractDebugSourceFromFiber(fiber) {
  const record = getRecord2(fiber);
  if (!record) {
    return null;
  }
  const direct = normalizeSource(record._debugSource);
  if (direct) {
    return direct;
  }
  const fromReturn = normalizeSource(record.return && record.return._debugSource);
  if (fromReturn) {
    return fromReturn;
  }
  const fromOwner = normalizeSource(record._debugOwner && record._debugOwner._debugSource);
  if (fromOwner) {
    return fromOwner;
  }
  return null;
}
function detectReactSourceFromFiberChain(start) {
  const startRecord = getRecord2(start);
  if (!startRecord) {
    return null;
  }
  let current = startRecord;
  let depth = 0;
  while (current && depth < REACT_MAX_FIBER_DEPTH2) {
    const source = extractDebugSourceFromFiber(current);
    if (source) {
      return source;
    }
    current = getRecord2(current.return) ?? getRecord2(current._owner);
    depth += 1;
  }
  return null;
}
function detectReactFiberNode(element) {
  const target = element;
  const reactFiberKey = Object.keys(target).find((key) => key.startsWith(REACT_FIBER_KEY_PREFIX2));
  if (reactFiberKey && target[reactFiberKey] != null) {
    return target[reactFiberKey];
  }
  return target._reactInternals ?? target._reactInternalInstance ?? null;
}
function detectSourceFromDomAttributes(element) {
  const node = element.closest("[data-source-file]");
  if (!node) {
    return null;
  }
  const file = node.getAttribute("data-source-file");
  if (!file) {
    return null;
  }
  const line = node.getAttribute("data-source-line");
  if (!line) {
    return file;
  }
  const parsedLine = Number(line);
  if (Number.isInteger(parsedLine) && parsedLine > 0) {
    return `${file}:${parsedLine}`;
  }
  return file;
}
function isFunctionSource(value) {
  if (typeof value !== "function") {
    return null;
  }
  const text = value.toString();
  const match = text.match(/\/\*\s*#\s*sourceMappingURL=(.+)\s*\*\//) ?? text.match(/\/\/\#\s*sourceMappingURL=(.+)/);
  if (match?.[1]) {
    const file = match[1].trim();
    if (file) {
      return file;
    }
  }
  const alt = text.match(/\/\/\# sourceURL=(.+)/i);
  if (alt?.[1]) {
    return alt[1].trim();
  }
  return null;
}
function detectSourceFromWebpackModules() {
  const webpackModules = globalThis.__webpack_modules__;
  if (!webpackModules || typeof webpackModules !== "object") {
    return null;
  }
  const entries = Object.entries(webpackModules);
  for (let index = 0; index < entries.length && index < 200; index += 1) {
    const [, moduleExport] = entries[index];
    if (!moduleExport) {
      continue;
    }
    const source = normalizeSource(moduleExport) ?? normalizeSource(moduleExport.__source) ?? normalizeSource(moduleExport.source) ?? isFunctionSource(moduleExport);
    if (source) {
      return source;
    }
  }
  return null;
}
function detectSourceFromDevTools(element, fiber) {
  const hook = globalThis.__REACT_DEVTOOLS_GLOBAL_HOOK__;
  if (!hook || typeof hook !== "object") {
    return null;
  }
  const renderers = hook.renderers;
  if (!renderers) {
    return null;
  }
  const rendererEntries = Array.isArray(renderers) ? renderers.map((value, index) => [index, value]) : renderers instanceof Map ? Array.from(renderers.entries()) : [];
  for (const [rendererId, renderer] of rendererEntries) {
    const rendererRecord = getRecord2(renderer);
    if (!rendererRecord) {
      continue;
    }
    const getFiberRoots = rendererRecord.getFiberRoots;
    if (typeof getFiberRoots === "function") {
      const roots = getFiberRoots.call(renderer, rendererId);
      const rootSet = roots instanceof Set ? roots : null;
      if (!rootSet) {
        continue;
      }
      for (const root of rootSet) {
        const rootRecord = getRecord2(root);
        const rootFiber = rootRecord?.current;
        const found = detectSourceFromFiberTree(rootFiber, element);
        if (found) {
          return found;
        }
      }
    }
    const source = rendererRecord.findFiberByHostInstance ? extractDebugSourceFromFiber(rendererRecord.findFiberByHostInstance(fiber)) : null;
    if (source) {
      return source;
    }
  }
  return null;
}
function detectSourceFromFiberTree(rootFiber, target) {
  const root = getRecord2(rootFiber);
  if (!root) {
    return null;
  }
  const stack = [root];
  const visited = /* @__PURE__ */ new Set();
  let checked = 0;
  const LIMIT = 500;
  while (stack.length && checked < LIMIT) {
    const current = stack.pop();
    checked += 1;
    if (!current || visited.has(current)) {
      continue;
    }
    visited.add(current);
    const currentRecord = getRecord2(current);
    if (!currentRecord) {
      continue;
    }
    if (currentRecord.stateNode === target) {
      const source = extractDebugSourceFromFiber(currentRecord);
      if (source) {
        return source;
      }
    }
    if (currentRecord.child) {
      stack.push(currentRecord.child);
    }
    if (currentRecord.sibling) {
      stack.push(currentRecord.sibling);
    }
    if (currentRecord.return) {
      stack.push(currentRecord.return);
    }
  }
  return null;
}
function detectSourcePath(element) {
  try {
    const reactFiber = detectReactFiberNode(element);
    const sourceFromFiber = detectReactSourceFromFiberChain(reactFiber);
    if (sourceFromFiber) {
      return sourceFromFiber;
    }
    const domSource = detectSourceFromDomAttributes(element);
    if (domSource) {
      return domSource;
    }
    const sourceFromDevTools = detectSourceFromDevTools(element, reactFiber);
    if (sourceFromDevTools) {
      return sourceFromDevTools;
    }
    const sourceFromWebpack = detectSourceFromWebpackModules();
    if (sourceFromWebpack) {
      return sourceFromWebpack;
    }
    return null;
  } catch {
    return null;
  }
}

// src/content/degradation/index.ts
function collectDegradationMetadata(element) {
  try {
    const component_name = detectComponentName(element);
    const source_path = detectSourcePath(element);
    if (component_name === null && source_path === null) {
      return null;
    }
    return { component_name, source_path };
  } catch {
    return null;
  }
}

// src/content/capture.ts
var MAX_HTML_SNAPSHOT_BYTES = 50 * 1024;
function trimHtmlSnapshot(element, maxLength) {
  const html = element.outerHTML ?? "";
  if (html.length <= maxLength) {
    return html;
  }
  const clone = element.cloneNode(true);
  let removedNodes = 0;
  while (clone.childNodes.length > 0 && clone.outerHTML.length > maxLength) {
    const lastChild = clone.childNodes[clone.childNodes.length - 1];
    clone.removeChild(lastChild);
    removedNodes++;
  }
  if (removedNodes > 0 && clone.outerHTML.length > maxLength) {
    clone.textContent = "";
    const contentRemovedComment = clone.ownerDocument.createComment("truncated: content removed");
    clone.appendChild(contentRemovedComment);
    if (clone.outerHTML.length <= maxLength) {
      return clone.outerHTML;
    }
    return clone.outerHTML.slice(0, maxLength);
  }
  if (removedNodes === 0) {
    return html.slice(0, maxLength);
  }
  const truncatedComment = clone.ownerDocument.createComment(`truncated: ${removedNodes} nodes removed`);
  clone.appendChild(truncatedComment);
  if (clone.outerHTML.length <= maxLength) {
    return clone.outerHTML;
  }
  clone.removeChild(truncatedComment);
  return clone.outerHTML;
}
function buildCapturePayload(input) {
  const rect = input.element.getBoundingClientRect();
  const html = input.element.outerHTML ?? "";
  const memo = input.memo.trim();
  const selector = input.selector.trim();
  const cssPath = input.cssPath.trim();
  const degradation = collectDegradationMetadata(input.element);
  return {
    url: window.location.href,
    selector,
    css_path: cssPath,
    rect: {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height
    },
    html_snapshot: html ? trimHtmlSnapshot(input.element, MAX_HTML_SNAPSHOT_BYTES) : null,
    screenshot_data: null,
    memo,
    tags: [...input.tags],
    mode: input.mode,
    component_name: degradation?.component_name ?? null,
    source_path: degradation?.source_path ?? null
  };
}

// src/content/panel.ts
var InlinePanel = class {
  doc;
  host;
  shadowRoot;
  selectorLine;
  pathLine;
  memoInput;
  tagInputRoot;
  immediateButton;
  queueButton;
  tagInput;
  onCapture;
  panelElement;
  memoField;
  isVisible = false;
  currentSelector = "";
  currentPath = "";
  currentTarget = null;
  panelPadding = 8;
  constructor(documentRef = document, options = {}) {
    this.doc = documentRef;
    this.host = this.doc.createElement("div");
    this.host.setAttribute("data-gm-inline-panel", "true");
    this.host.style.position = "fixed";
    this.host.style.top = "0";
    this.host.style.left = "0";
    this.host.style.display = "none";
    this.host.style.zIndex = "2147483647";
    this.host.style.pointerEvents = "none";
    this.shadowRoot = this.host.attachShadow({ mode: "open" });
    const style = this.doc.createElement("style");
    style.textContent = INLINE_PANEL_STYLES;
    const panelElement = this.doc.createElement("div");
    panelElement.className = "gm-inline-panel";
    panelElement.tabIndex = -1;
    this.selectorLine = this.doc.createElement("div");
    this.selectorLine.className = "gm-selector";
    this.pathLine = this.doc.createElement("div");
    this.pathLine.className = "gm-path";
    this.memoInput = this.doc.createElement("textarea");
    this.memoInput.placeholder = "\uBA54\uBAA8 \uC785\uB825...";
    this.memoInput.rows = 3;
    this.memoInput.className = "gm-memo";
    const divider1 = this.doc.createElement("div");
    divider1.className = "gm-divider";
    this.tagInputRoot = this.doc.createElement("div");
    this.tagInput = new TagInput(this.tagInputRoot);
    const divider2 = this.doc.createElement("div");
    divider2.className = "gm-divider";
    const actions = this.doc.createElement("div");
    actions.className = "gm-actions";
    this.immediateButton = this.doc.createElement("button");
    this.immediateButton.type = "button";
    this.immediateButton.className = "gm-action-btn gm-action-immediate";
    this.immediateButton.textContent = "\uC989\uC2DC\uBAA8\uB4DC";
    this.queueButton = this.doc.createElement("button");
    this.queueButton.type = "button";
    this.queueButton.className = "gm-action-btn gm-action-queue";
    this.queueButton.textContent = "\uD050\uC5D0 \uCD94\uAC00";
    const actionList = this.doc.createElement("div");
    actionList.className = "gm-action-list";
    actionList.append(this.immediateButton, this.queueButton);
    actions.appendChild(actionList);
    panelElement.append(
      this.selectorLine,
      this.pathLine,
      this.memoInput,
      divider1,
      this.tagInputRoot,
      divider2,
      actions
    );
    this.shadowRoot.append(style, panelElement);
    this.panelElement = panelElement;
    this.memoField = this.memoInput;
    this.onCapture = options.onCapture;
    if (documentRef.body) {
      documentRef.body.appendChild(this.host);
    }
    this.immediateButton.addEventListener("click", () => {
      this.handleCapture("immediate");
    });
    this.queueButton.addEventListener("click", () => {
      this.handleCapture("batch");
    });
    this.host.addEventListener("keydown", (event) => {
      if (!this.isOpen()) {
        return;
      }
      event.stopPropagation();
    });
    this.memoInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") {
        return;
      }
      if (event.isComposing) {
        return;
      }
      if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      this.handleCapture("immediate");
    });
  }
  show(target) {
    this.currentSelector = getUniqueSelector(target);
    this.currentPath = getCSSPath(target);
    this.currentTarget = target;
    this.selectorLine.textContent = this.currentSelector;
    this.selectorLine.title = this.currentSelector;
    this.pathLine.textContent = this.currentPath;
    this.pathLine.title = this.currentPath;
    this.memoInput.value = "";
    this.tagInput.reset();
    this.host.style.display = "block";
    this.host.style.visibility = "hidden";
    const rect = target.getBoundingClientRect();
    const panelRect = this.panelElement.getBoundingClientRect();
    const panelWidth = Math.max(panelRect.width, 240);
    const panelHeight = Math.max(panelRect.height, 120);
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    let left = rect.left + rect.width / 2 - panelWidth / 2;
    let top = rect.bottom + this.panelPadding;
    if (top + panelHeight > viewportHeight - this.panelPadding) {
      top = rect.top - panelHeight - this.panelPadding;
    }
    if (top < this.panelPadding) {
      top = Math.min(rect.bottom + this.panelPadding, viewportHeight - panelHeight - this.panelPadding);
    }
    if (left + panelWidth > viewportWidth - this.panelPadding) {
      left = viewportWidth - panelWidth - this.panelPadding;
    }
    if (left < this.panelPadding) {
      left = this.panelPadding;
    }
    this.host.style.left = `${Math.max(0, Math.round(left))}px`;
    this.host.style.top = `${Math.max(0, Math.round(top))}px`;
    this.host.style.visibility = "visible";
    this.host.style.pointerEvents = "auto";
    this.isVisible = true;
    requestAnimationFrame(() => {
      if (!this.isVisible) {
        return;
      }
      this.memoInput.focus();
    });
  }
  hide() {
    this.isVisible = false;
    this.host.style.display = "none";
    this.host.style.pointerEvents = "none";
    this.host.style.visibility = "hidden";
  }
  isOpen() {
    return this.isVisible;
  }
  contains(target) {
    if (!(target instanceof Node)) return false;
    if (this.host === target || this.host.contains(target)) return true;
    return target.getRootNode() === this.shadowRoot;
  }
  handleCapture(mode) {
    if (!this.isVisible) {
      return;
    }
    if (!this.currentTarget) {
      return;
    }
    const payloadInput = {
      element: this.currentTarget,
      selector: this.currentSelector,
      cssPath: this.currentPath,
      memo: this.memoField.value,
      tags: this.tagInput.getTags(),
      mode
    };
    const payload = buildCapturePayload(payloadInput);
    void this.onCapture?.(mode, payload);
    this.hide();
  }
};

// src/content/overlay/landmark-scanner.ts
var LANDMARK_SELECTOR = [
  "header",
  "nav",
  "main",
  "aside",
  "footer",
  "section",
  "article",
  "[role=banner]",
  "[role=navigation]",
  "[role=main]",
  "[role=complementary]",
  "[role=contentinfo]",
  "[role=search]",
  "form",
  "button",
  "a[href]",
  "input",
  "select",
  "textarea"
].join(", ");
var MIN_OVERLAY_SIZE_PX = 10;
function isInputElementVisible(element) {
  if (element instanceof HTMLInputElement && element.type.toLowerCase() === "hidden") {
    return false;
  }
  return true;
}
function scanLandmarkElements(documentRef = document) {
  const discovered = documentRef.querySelectorAll(LANDMARK_SELECTOR);
  const result = [];
  for (const element of discovered) {
    if (!isLandmarkCandidate(element)) {
      continue;
    }
    if (!isElementLargeEnough(element)) {
      continue;
    }
    result.push(element);
  }
  return result;
}
function isLandmarkCandidate(element) {
  if (element.matches("a[href]")) {
    const anchor = element;
    return Boolean(anchor.getAttribute("href"));
  }
  if (!isInputElementVisible(element)) {
    return false;
  }
  const style = getComputedStyle(element);
  if (style.display === "none" || style.visibility === "hidden") {
    return false;
  }
  return true;
}
function isElementLargeEnough(element) {
  const rect = element.getBoundingClientRect();
  return rect.width >= MIN_OVERLAY_SIZE_PX && rect.height >= MIN_OVERLAY_SIZE_PX;
}

// src/content/overlay/badge-renderer.ts
var BADGE_WIDTH_PX = 24;
var BADGE_HEIGHT_PX = 18;
var BADGE_VERTICAL_OFFSET_PX = 20;
var BADGE_HORIZONTAL_GAP_PX = 4;
var BADGE_Z_INDEX = 2147483648;
var MAX_BADGE_LABEL = 2;
var OVERLAY_ID_PREFIX = "C-";
var BadgeRenderer = class {
  doc;
  host;
  shadowRoot;
  container;
  renderedBadges = /* @__PURE__ */ new Map();
  constructor(doc = document) {
    this.doc = doc;
    this.host = this.doc.createElement("div");
    this.host.style.position = "absolute";
    this.host.style.left = "0";
    this.host.style.top = "0";
    this.host.style.width = "0";
    this.host.style.height = "0";
    this.host.style.pointerEvents = "none";
    this.host.style.zIndex = String(BADGE_Z_INDEX);
    this.host.style.display = "none";
    this.shadowRoot = this.host.attachShadow({ mode: "open" });
    const style = this.doc.createElement("style");
    const container = this.doc.createElement("div");
    container.className = "gm-overlay-badge-container";
    style.textContent = this.buildStyles();
    this.shadowRoot.append(style, container);
    this.container = container;
  }
  mount() {
    const mountPoint = this.doc.body ?? this.doc.documentElement;
    if (mountPoint && !this.host.isConnected) {
      mountPoint.appendChild(this.host);
    }
  }
  unmount() {
    this.removeAll();
    if (this.host.isConnected) {
      this.host.remove();
    }
  }
  render(items, onBadgeClick) {
    this.mount();
    this.clear();
    const placed = [];
    for (const item of items) {
      const badge = this.renderBadge(item, onBadgeClick);
      const position = this.resolvePosition(item.element, placed);
      badge.style.left = `${position.left}px`;
      badge.style.top = `${position.top}px`;
      placed.push({
        left: position.left,
        top: position.top,
        width: BADGE_WIDTH_PX,
        height: BADGE_HEIGHT_PX
      });
      this.container.appendChild(badge);
      this.renderedBadges.set(item.element, badge);
    }
    this.host.style.display = "block";
  }
  removeAll() {
    this.clear();
    this.host.style.display = "none";
  }
  clear() {
    for (const badge of this.renderedBadges.values()) {
      badge.remove();
    }
    this.renderedBadges.clear();
  }
  renderBadge(item, onBadgeClick) {
    const badge = this.doc.createElement("button");
    badge.type = "button";
    badge.className = "gm-overlay-badge";
    badge.textContent = `${OVERLAY_ID_PREFIX}${String(item.index).padStart(MAX_BADGE_LABEL, "0")}`;
    badge.setAttribute("data-gm-overlay-id", String(item.index));
    badge.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      onBadgeClick(item.element);
    });
    return badge;
  }
  resolvePosition(element, placed) {
    const rect = element.getBoundingClientRect();
    const baseLeft = rect.left + this.doc.defaultView.scrollX;
    let top = rect.top + this.doc.defaultView.scrollY - BADGE_VERTICAL_OFFSET_PX;
    if (top < 0) {
      top = rect.top + this.doc.defaultView.scrollY;
    }
    let left = baseLeft;
    while (true) {
      const blocking = placed.find((item) => this.isOverlapping({ left, top }, item));
      if (!blocking) {
        break;
      }
      left = blocking.left + blocking.width + BADGE_HORIZONTAL_GAP_PX;
    }
    return {
      left,
      top,
      width: BADGE_WIDTH_PX,
      height: BADGE_HEIGHT_PX
    };
  }
  isOverlapping(candidate, existing) {
    const sameRow = Math.abs(candidate.top - existing.top) < BADGE_HEIGHT_PX;
    const horizontallyOverlap = candidate.left < existing.left + existing.width + BADGE_HORIZONTAL_GAP_PX && candidate.left + BADGE_WIDTH_PX > existing.left - BADGE_HORIZONTAL_GAP_PX;
    return sameRow && horizontallyOverlap;
  }
  buildStyles() {
    return `
      :host {
        position: absolute;
        left: 0;
        top: 0;
        width: 0;
        height: 0;
        z-index: ${BADGE_Z_INDEX};
        pointer-events: none;
      }

      .gm-overlay-badge-container {
        position: relative;
        pointer-events: none;
      }

      .gm-overlay-badge {
        position: absolute;
        width: ${BADGE_WIDTH_PX}px;
        height: ${BADGE_HEIGHT_PX}px;
        border: 0;
        border-radius: 4px;
        background: #ff6b35;
        color: #ffffff;
        font-family: 'Courier New', monospace;
        font-size: 10px;
        font-weight: 700;
        line-height: ${BADGE_HEIGHT_PX}px;
        text-align: center;
        padding: 0;
        margin: 0;
        box-sizing: border-box;
        pointer-events: auto;
        cursor: pointer;
      }
    `;
  }
};

// src/content/overlay/badge-manager.ts
var OVERLAY_BADGE_MAX_COUNT = 50;
var REFRESH_DELAY_MS = 500;
var overlayBadgeCounter = 1;
var OverlayBadgeManager = class {
  doc;
  renderer;
  onBadgeSelect;
  mutationObserver;
  win;
  active = false;
  refreshTimeoutId = null;
  scrollFrameId = 0;
  constructor(options) {
    this.doc = options.doc ?? document;
    this.onBadgeSelect = options.onBadgeSelect;
    this.renderer = new BadgeRenderer(this.doc);
    this.mutationObserver = new MutationObserver(() => this.scheduleRefresh());
    this.win = this.doc.defaultView;
  }
  activate() {
    if (this.active) {
      return;
    }
    this.active = true;
    overlayBadgeCounter = 1;
    this.renderBadges();
    this.attachObservers();
  }
  deactivate() {
    if (!this.active) {
      return;
    }
    this.active = false;
    this.detachObservers();
    this.renderer.removeAll();
  }
  refresh() {
    if (!this.active) {
      return;
    }
    this.renderBadges();
  }
  renderBadges() {
    overlayBadgeCounter = 1;
    const elements = scanLandmarkElements(this.doc).slice(0, OVERLAY_BADGE_MAX_COUNT);
    const items = elements.map((element) => ({
      element,
      index: overlayBadgeCounter++
    }));
    this.renderer.render(items, this.onBadgeSelect);
  }
  attachObservers() {
    if (!this.doc.documentElement) {
      return;
    }
    if (!this.win) {
      return;
    }
    this.mutationObserver.observe(this.doc.documentElement, {
      childList: true,
      subtree: true
    });
    this.win.addEventListener("scroll", this.handleScroll, { capture: true, passive: true });
    this.win.addEventListener("resize", this.handleResize);
  }
  detachObservers() {
    if (!this.win) {
      return;
    }
    this.mutationObserver.disconnect();
    this.win.removeEventListener("scroll", this.handleScroll, { capture: true });
    this.win.removeEventListener("resize", this.handleResize);
    if (this.refreshTimeoutId !== null) {
      clearTimeout(this.refreshTimeoutId);
      this.refreshTimeoutId = null;
    }
    if (this.scrollFrameId !== 0) {
      cancelAnimationFrame(this.scrollFrameId);
      this.scrollFrameId = 0;
    }
  }
  scheduleRefresh = () => {
    if (!this.active) {
      return;
    }
    if (this.refreshTimeoutId !== null) {
      return;
    }
    this.refreshTimeoutId = window.setTimeout(() => {
      this.refreshTimeoutId = null;
      this.renderBadges();
    }, REFRESH_DELAY_MS);
  };
  handleScroll = () => {
    if (!this.active) {
      return;
    }
    if (this.scrollFrameId !== 0) {
      return;
    }
    this.scrollFrameId = requestAnimationFrame(() => {
      this.scrollFrameId = 0;
      if (this.active) {
        this.renderBadges();
      }
    });
  };
  handleResize = () => {
    if (!this.active) {
      return;
    }
    this.renderBadges();
  };
};

// src/content/screenshot.ts
var MAX_BYTES = 1024 * 1024;
var MAX_QUALITY = 0.9;
var MIN_QUALITY = 0.3;
var QUALITY_STEP = 0.1;
var SCALE_STEP = 0.8;
async function loadImageFromDataUrl(imageDataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("\uC2A4\uD06C\uB9B0\uC0F7 \uC774\uBBF8\uC9C0 \uB85C\uB4DC \uC2E4\uD328"));
    image.src = imageDataUrl;
  });
}
function dataUrlByteLength(imageDataUrl) {
  const base64Part = imageDataUrl.split(",")[1] ?? "";
  if (!base64Part) {
    return 0;
  }
  return Math.ceil(base64Part.length * 3 / 4);
}
async function toWebP(sourceImage, width, height, quality) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(width));
  canvas.height = Math.max(1, Math.floor(height));
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("\uCE94\uBC84\uC2A4 \uB80C\uB354\uB9C1 \uCEE8\uD14D\uC2A4\uD2B8 \uC0DD\uC131 \uC2E4\uD328");
  }
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(sourceImage, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/webp", quality);
}
function reduceQuality(quality) {
  return Number(Math.max(MIN_QUALITY, quality - QUALITY_STEP).toFixed(1));
}
async function captureScreenshotToWebP() {
  const screenshot = await sendToBackground({
    type: MESSAGE_TYPES.TAKE_SCREENSHOT,
    payload: {}
  });
  if (!screenshot?.ok || !screenshot.payload?.imageDataUrl) {
    console.warn(
      "[GM] Screenshot capture failed:",
      screenshot?.ok === false ? screenshot.error : "No image data"
    );
    return null;
  }
  const sourceImage = await loadImageFromDataUrl(screenshot.payload.imageDataUrl);
  let width = sourceImage.naturalWidth || sourceImage.width || 1;
  let height = sourceImage.naturalHeight || sourceImage.height || 1;
  let quality = MAX_QUALITY;
  const MAX_ITERATIONS = 20;
  for (let i = 0; i < MAX_ITERATIONS; i++) {
    const webp = await toWebP(sourceImage, width, height, quality);
    if (dataUrlByteLength(webp) <= MAX_BYTES) {
      return webp;
    }
    if (quality > MIN_QUALITY) {
      quality = reduceQuality(quality);
      continue;
    }
    if (width <= 1 && height <= 1) {
      return webp;
    }
    width = Math.max(1, Math.floor(width * SCALE_STEP));
    height = Math.max(1, Math.floor(height * SCALE_STEP));
  }
  return await toWebP(sourceImage, width, height, quality);
}

// src/content/clipboard.ts
function getClipboardMemo(memo, fallbackSelector) {
  const source = memo.trim() || fallbackSelector.trim();
  return source;
}
function buildCaptureClipboardText(captureId, memo, selector) {
  return `/mst:plan [${captureId}] ${getClipboardMemo(memo, selector)}`.trim();
}
async function copyTextToClipboard(text) {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.opacity = "0";
  textarea.setAttribute("readonly", "true");
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    return document.execCommand("copy");
  } finally {
    textarea.remove();
  }
}

// src/content/toast.ts
var TOAST_DURATION_MS = 3e3;
var TOAST_FADE_MS = 300;
function getToastColor(type) {
  if (type === "error") {
    return "#dc3545";
  }
  return "#28a745";
}
function showToast(message, type = "success") {
  const host = document.createElement("div");
  host.style.position = "fixed";
  host.style.top = "16px";
  host.style.right = "16px";
  host.style.zIndex = "2147483647";
  host.style.pointerEvents = "none";
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `
    .gm-toast {
      font-family: Arial, sans-serif;
      min-width: 260px;
      max-width: min(420px, calc(100vw - 32px));
      color: #fff;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 14px;
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25);
      opacity: 1;
      transition: opacity 300ms ease;
      background: ${getToastColor(type)};
      word-break: keep-all;
      pointer-events: auto;
    }
  `;
  const toast = document.createElement("div");
  toast.className = "gm-toast";
  toast.textContent = message;
  shadow.append(style, toast);
  document.body.appendChild(host);
  window.setTimeout(() => {
    toast.style.opacity = "0";
  }, TOAST_DURATION_MS);
  window.setTimeout(() => {
    host.remove();
  }, TOAST_DURATION_MS + TOAST_FADE_MS);
}

// src/shared/types.ts
var OVERLAY_TOGGLE_MESSAGE = "OVERLAY_TOGGLE";

// src/content/inspector.ts
var OVERLAY_STATE_STORAGE_KEY = "gm-overlay-badge-state";
var Inspector = class {
  highlighter;
  navigator;
  panel;
  badgeManager;
  onSelect;
  cursorRestoreTarget;
  overlayEnabled = true;
  active = false;
  rafId = null;
  pendingTarget = null;
  previousBodyCursor = "";
  constructor(options = {}) {
    this.highlighter = new Highlighter();
    this.navigator = new Navigator();
    this.panel = new InlinePanel(document, {
      onCapture: (mode, payload) => {
        void this.handleCapture(mode, payload);
      }
    });
    this.onSelect = options.onSelect;
    this.cursorRestoreTarget = document.body;
    this.badgeManager = new OverlayBadgeManager({
      doc: document,
      onBadgeSelect: this.handleBadgeSelect
    });
    chrome.runtime.onMessage.addListener(this.handleRuntimeMessage);
    chrome.storage.onChanged.addListener(this.handleStorageChange);
    void this.loadOverlayState();
  }
  activate() {
    if (this.active) {
      return;
    }
    this.active = true;
    this.highlighter.mount();
    if (this.cursorRestoreTarget) {
      this.previousBodyCursor = this.cursorRestoreTarget.style.cursor;
      this.cursorRestoreTarget.style.cursor = "crosshair";
    }
    document.addEventListener("mousemove", this.handleMouseMove, { capture: true });
    document.addEventListener("click", this.handleClick, { capture: true });
    document.addEventListener("keydown", this.handleKeyDown, { capture: true });
    document.addEventListener("scroll", this.handleScroll, { capture: true });
    if (this.overlayEnabled) {
      this.badgeManager.activate();
    }
  }
  deactivate() {
    if (!this.active) {
      return;
    }
    this.active = false;
    document.removeEventListener("mousemove", this.handleMouseMove, { capture: true });
    document.removeEventListener("click", this.handleClick, { capture: true });
    document.removeEventListener("keydown", this.handleKeyDown, { capture: true });
    document.removeEventListener("scroll", this.handleScroll, { capture: true });
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.highlighter.unmount();
    this.panel.hide();
    this.pendingTarget = null;
    this.navigator.setCurrent(null);
    if (this.cursorRestoreTarget) {
      this.cursorRestoreTarget.style.cursor = this.previousBodyCursor;
    }
    this.badgeManager.deactivate();
  }
  isActive() {
    return this.active;
  }
  handleMouseMove = (event) => {
    if (!this.active) {
      return;
    }
    event.stopPropagation();
    if (this.panel.isOpen()) {
      return;
    }
    const target = this.resolveTarget(event.target);
    if (!target) {
      return;
    }
    this.pendingTarget = target;
    if (this.rafId !== null) {
      return;
    }
    this.rafId = requestAnimationFrame(() => {
      this.rafId = null;
      if (this.pendingTarget && !this.panel.isOpen()) {
        this.setCurrent(this.pendingTarget);
        this.pendingTarget = null;
      }
    });
  };
  handleClick = (event) => {
    if (!this.active) {
      return;
    }
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.pendingTarget = null;
    const target = this.resolveTarget(event.target);
    if (!target) {
      return;
    }
    if (this.panel.isOpen() && this.panel.contains(target)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (this.panel.isOpen()) {
      this.panel.hide();
      this.navigator.setCurrent(null);
      this.highlighter.hide();
      this.deactivate();
      return;
    }
    this.setCurrent(target);
    const current = this.navigator.getCurrent();
    if (current) {
      this.panel.show(current);
      this.onSelect?.(current);
    }
  };
  handleKeyDown = (event) => {
    if (!this.active) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      this.deactivate();
      return;
    }
    if (this.panel.isOpen() && this.panel.contains(event.target)) {
      return;
    }
    if (event.isComposing) {
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    if (event.key === "Enter") {
      if (this.panel.isOpen()) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        this.deactivate();
        return;
      }
      const current = this.navigator.getCurrent();
      if (!current) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      this.panel.show(current);
      this.onSelect?.(current);
      return;
    }
    if (event.key === "ArrowUp" || event.key === "ArrowDown" || event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      const next = this.navigator.move(event.key);
      if (next) {
        this.setCurrent(next);
      }
      return;
    }
    const isSingleCharacterKey = event.key.length === 1;
    const isCommonTextOrControlKey = event.key === "Tab" || event.key === " " || event.key === "Backspace" || event.key === "Delete";
    if (isSingleCharacterKey || isCommonTextOrControlKey) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    }
  };
  handleScroll = () => {
    if (!this.active) {
      return;
    }
    this.highlighter.refresh();
  };
  setCurrent(target) {
    this.navigator.setCurrent(target);
    this.highlighter.setTarget(target);
  }
  resolveTarget(target) {
    if (!(target instanceof Element)) {
      return null;
    }
    if (this.highlighter.isOverlayElement(target)) {
      return null;
    }
    if (this.panel.isOpen() && this.panel.contains(target)) {
      return null;
    }
    return target;
  }
  handleBadgeSelect = (target) => {
    const normalizedTarget = this.resolveTarget(target);
    if (!normalizedTarget) {
      return;
    }
    this.setCurrent(normalizedTarget);
    if (this.active) {
      this.panel.show(normalizedTarget);
    }
    this.onSelect?.(normalizedTarget);
  };
  async loadOverlayState() {
    const savedState = await chrome.storage.local.get(OVERLAY_STATE_STORAGE_KEY);
    const nextState = savedState[OVERLAY_STATE_STORAGE_KEY];
    if (typeof nextState === "boolean") {
      this.overlayEnabled = nextState;
    }
  }
  setOverlayEnabled(enabled) {
    const nextEnabled = Boolean(enabled);
    if (this.overlayEnabled === nextEnabled) {
      if (this.overlayEnabled && this.active) {
        this.badgeManager.refresh();
      }
      return;
    }
    this.overlayEnabled = nextEnabled;
    void chrome.storage.local.set({ [OVERLAY_STATE_STORAGE_KEY]: nextEnabled });
    if (!this.active) {
      return;
    }
    if (nextEnabled) {
      this.badgeManager.activate();
    } else {
      this.badgeManager.deactivate();
    }
  }
  handleRuntimeMessage = (message) => {
    if (!isExtensionMessage(message)) {
      return;
    }
    if (message.type !== OVERLAY_TOGGLE_MESSAGE) {
      return;
    }
    const overlayMessage = message;
    this.setOverlayEnabled(overlayMessage.payload.enabled);
  };
  handleStorageChange = (changes, areaName) => {
    if (areaName !== "local") {
      return;
    }
    const changed = changes[OVERLAY_STATE_STORAGE_KEY];
    if (!changed || typeof changed.newValue !== "boolean") {
      return;
    }
    this.setOverlayEnabled(changed.newValue);
  };
  async handleCapture(mode, payload) {
    try {
      const screenshotData = await captureScreenshotToWebP();
      const captureMessage = await sendToBackground({
        type: MESSAGE_TYPES.CAPTURE_SAVE,
        payload: {
          capture: {
            ...payload,
            screenshot_data: screenshotData
          }
        }
      });
      if (!captureMessage?.ok) {
        throw new Error(captureMessage?.error || "\uCEA1\uCC98 \uC800\uC7A5\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.");
      }
      const captureId = captureMessage.payload?.captureId ?? "CAP-000";
      if (mode === "immediate") {
        const copied = await copyTextToClipboard(buildCaptureClipboardText(captureId, payload.memo, payload.selector));
        if (copied) {
          if (screenshotData) {
            showToast("\uCEA1\uCC98 \uC644\uB8CC! \uD074\uB9BD\uBCF4\uB4DC\uC5D0 \uBCF5\uC0AC\uB428", "success");
          } else {
            showToast("\uC2A4\uD06C\uB9B0\uC0F7 \uC5C6\uC774 \uCEA1\uCC98\uB428", "success");
          }
        } else {
          showToast("\uD074\uB9BD\uBCF4\uB4DC \uBCF5\uC0AC \uC2E4\uD328. \uC218\uB3D9 \uBCF5\uC0AC\uB85C \uC9C4\uD589\uD558\uC138\uC694.", "error");
        }
      } else {
        if (screenshotData) {
          showToast("\uCEA1\uCC98\uAC00 \uD050\uC5D0 \uCD94\uAC00\uB418\uC5C8\uC2B5\uB2C8\uB2E4.", "success");
        } else {
          showToast("\uC2A4\uD06C\uB9B0\uC0F7 \uC5C6\uC774 \uCEA1\uCC98\uAC00 \uD050\uC5D0 \uCD94\uAC00\uB418\uC5C8\uC2B5\uB2C8\uB2E4.", "success");
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "\uC54C \uC218 \uC5C6\uB294 \uC624\uB958\uAC00 \uBC1C\uC0DD\uD588\uC2B5\uB2C8\uB2E4.";
      showToast(`\uCEA1\uCC98 \uC2E4\uD328: ${message}`, "error");
    } finally {
      this.deactivate();
    }
  }
};

// src/content/index.ts
var inspector = new Inspector({
  onSelect: (element) => {
    void element;
  }
});
function applyInspectMode(_enabled) {
  inspector.activate();
}
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!isExtensionMessage(message)) {
    return false;
  }
  if (message.type === MESSAGE_TYPES.TOGGLE_INSPECT) {
    const typedMessage = message;
    applyInspectMode(typedMessage.payload.enabled);
    const status = {
      type: MESSAGE_TYPES.INSPECT_STATUS,
      payload: {
        tabId: typedMessage.payload.tabId,
        enabled: typedMessage.payload.enabled
      }
    };
    sendResponse(status);
    void sendToBackground({ type: MESSAGE_TYPES.INSPECT_STATUS, payload: status.payload });
    return true;
  }
  return false;
});
//# sourceMappingURL=content.js.map
