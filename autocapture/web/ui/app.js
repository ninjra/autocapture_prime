const state = {
  token: localStorage.getItem("acToken") || "",
  ws: null,
  settingsFields: [],
  settingsDirty: {},
  settingsGroupOpen: {},
  pluginDirty: {},
  activePluginId: null,
  activePluginGroupId: null,
  activePluginOptionGroup: null,
  showAllPluginSettings: localStorage.getItem("acPluginShowAll") === "true",
  plugins: [],
  pluginGroups: [],
  activePluginSettings: {},
  config: {},
  telemetry: {},
  status: {},
  activityFilters: {
    activity: localStorage.getItem("acFilterActivity") !== "false",
    changes: localStorage.getItem("acFilterChanges") !== "false",
    bookmarks: localStorage.getItem("acFilterBookmarks") !== "false",
  },
};

let telemetryRenderAt = 0;

const qs = (id) => document.getElementById(id);

const tokenInput = qs("token");
const saveTokenBtn = qs("saveToken");
const telemetryState = qs("telemetryState");
const telemetryPayload = qs("telemetryPayload");
const statusRunId = qs("runId");
const statusLedger = qs("ledgerHead");
const statusCapture = qs("captureState");
const alertsList = qs("alertsList");
const timelineList = qs("timelineList");
const pluginsList = qs("pluginsList");
const pluginGroupsList = qs("pluginGroupsList");
const pluginGroupTitle = qs("pluginGroupTitle");
const pluginGroupMeta = qs("pluginGroupMeta");
const pluginGroupControls = qs("pluginGroupControls");
const pluginEnableAll = qs("pluginEnableAll");
const pluginDisableAll = qs("pluginDisableAll");
const keysPayload = qs("keysPayload");
const queryInput = qs("queryInput");
const queryOutput = qs("queryOutput");
const verifyOutput = qs("verifyOutput");
const configPatch = qs("configPatch");
const configOutput = qs("configOutput");
const egressList = qs("egressList");
const settingsList = qs("settingsList");
const settingsFilter = qs("settingsFilter");
const settingsApply = qs("settingsApply");
const settingsReload = qs("settingsReload");
const settingsStatus = qs("settingsStatus");
const pluginSettingsList = qs("pluginSettingsList");
const pluginSettingsApply = qs("pluginSettingsApply");
const pluginSettingsTitle = qs("pluginSettingsTitle");
const pluginSettingsSubtitle = qs("pluginSettingsSubtitle");
const pluginSettingsStatus = qs("pluginSettingsStatus");
const pluginOptionGroups = qs("pluginOptionGroups");
const pluginShowAll = qs("pluginShowAll");
const quickCaptureToggle = qs("quickCaptureToggle");
const quickPause10 = qs("quickPause10");
const quickPause30 = qs("quickPause30");
const quickResume = qs("quickResume");
const quickPrivacyMode = qs("quickPrivacyMode");
const quickFidelityMode = qs("quickFidelityMode");
const bookmarkNote = qs("bookmarkNote");
const bookmarkTags = qs("bookmarkTags");
const bookmarkSave = qs("bookmarkSave");
const bookmarkStatus = qs("bookmarkStatus");
const bookmarkList = qs("bookmarkList");
const quickPauseStatus = qs("quickPauseStatus");
const fidelitySummary = qs("fidelitySummary");
const healthSparkScreenshot = qs("healthSparkScreenshot");
const healthSparkVideo = qs("healthSparkVideo");
const healthScreenshot = qs("healthScreenshot");
const healthVideo = qs("healthVideo");
const healthQueue = qs("healthQueue");
const healthLag = qs("healthLag");
const healthEvent = qs("healthEvent");
const refreshHealthBtn = qs("refreshHealth");
const storageDir = qs("storageDir");
const storageFree = qs("storageFree");
const storageDays = qs("storageDays");
const storageEvidence = qs("storageEvidence");
const storageDerived = qs("storageDerived");
const refreshStorageBtn = qs("refreshStorage");
const storageHint = qs("storageHint");
const configHistoryList = qs("configHistoryList");
const configHistoryStatus = qs("configHistoryStatus");
const refreshConfigHistoryBtn = qs("refreshConfigHistory");
const configUndoLast = qs("configUndoLast");
const activityTimelineList = qs("activityTimelineList");
const refreshActivityTimelineBtn = qs("refreshActivityTimeline");
const filterActivity = qs("filterActivity");
const filterChanges = qs("filterChanges");
const filterBookmarks = qs("filterBookmarks");

if (tokenInput) {
  tokenInput.value = state.token;
}

function setToken(value) {
  state.token = value || "";
  localStorage.setItem("acToken", state.token);
  if (tokenInput) {
    tokenInput.value = state.token;
  }
}

function apiFetch(path, options = {}) {
  const headers = options.headers || {};
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
    headers["X-AC-Token"] = state.token;
  }
  return fetch(path, { ...options, headers });
}

async function readJson(resp) {
  try {
    return await resp.json();
  } catch (err) {
    return { ok: false, error: "invalid_json" };
  }
}

function setStatus(text, ok = true) {
  if (!telemetryState) return;
  telemetryState.textContent = text;
  telemetryState.classList.toggle("badge", true);
  telemetryState.classList.toggle("warn", !ok);
}

function showPanel(name) {
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  });
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.panel === name);
  });
  if (location.hash !== `#${name}`) {
    history.replaceState(null, "", `#${name}`);
  }
}

function initNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => showPanel(btn.dataset.panel));
  });
  const hash = (location.hash || "").replace("#", "");
  if (hash) {
    showPanel(hash);
  } else {
    showPanel("settings");
  }
}

async function refreshStatus() {
  const resp = await apiFetch("/api/status");
  const data = await readJson(resp);
  state.status = data || {};
  statusRunId.textContent = data.run_id || "—";
  statusLedger.textContent = data.ledger_head || "—";
  statusCapture.textContent = data.capture_active ? "active" : "idle";
  updateQuickControls();
}

async function refreshAlerts() {
  const resp = await apiFetch("/api/alerts");
  const data = await readJson(resp);
  alertsList.innerHTML = "";
  const alerts = data.alerts || [];
  if (!alerts.length) {
    const li = document.createElement("li");
    li.textContent = "No active alerts";
    alertsList.appendChild(li);
    return;
  }
  alerts.forEach((alert) => {
    const li = document.createElement("li");
    li.textContent = `[${alert.severity}] ${alert.title} · ${alert.ts_utc || ""}`;
    alertsList.appendChild(li);
  });
}

async function refreshTimeline() {
  const resp = await apiFetch("/api/timeline?limit=25");
  const data = await readJson(resp);
  timelineList.innerHTML = "";
  const events = data.events || [];
  if (!events.length) {
    const li = document.createElement("li");
    li.textContent = "No journal activity";
    timelineList.appendChild(li);
    return;
  }
  events.forEach((event) => {
    const li = document.createElement("li");
    const label = event.event_type || event.event || "event";
    const ts = event.ts_utc || "";
    li.textContent = `${label} · ${ts}`;
    timelineList.appendChild(li);
  });
}

function formatBadge(text, variant = "") {
  return `<span class="badge ${variant}">${text}</span>`;
}

const SETTINGS_GROUPS = [
  {
    id: "capture",
    title: "Capture",
    description: "Screenshots, video, audio, and input capture.",
    prefixes: ["capture"],
    summary: [
      "capture.screenshot.enabled",
      "capture.video.enabled",
      "capture.audio.enabled",
      "capture.cursor.enabled",
    ],
  },
  {
    id: "storage",
    title: "Storage & Encryption",
    description: "Where data lives and how it is protected.",
    prefixes: ["storage"],
    summary: [
      "storage.data_dir",
      "storage.encryption_required",
      "storage.fsync_policy",
      "storage.retention.evidence",
    ],
  },
  {
    id: "privacy",
    title: "Privacy & Egress",
    description: "Outbound sanitization and cloud policies.",
    prefixes: ["privacy", "gateway"],
    summary: [
      "privacy.egress.enabled",
      "privacy.egress.default_sanitize",
      "privacy.egress.allow_raw_egress",
      "privacy.cloud.enabled",
    ],
  },
  {
    id: "runtime",
    title: "Runtime",
    description: "Mode enforcement, budgets, and activity signals.",
    prefixes: ["runtime", "performance", "alerts"],
    summary: [
      "runtime.idle_window_s",
      "runtime.mode_enforcement.suspend_workers",
      "runtime.telemetry.enabled",
      "performance.startup_ms",
    ],
  },
  {
    id: "processing",
    title: "Processing",
    description: "Idle and on-query processing pipelines.",
    prefixes: ["processing"],
    summary: [
      "processing.idle.enabled",
      "processing.on_query.allow_decode_extract",
      "processing.sst.enabled",
    ],
  },
  {
    id: "models",
    title: "Models & AI",
    description: "LLM, VLM, OCR, and model paths.",
    prefixes: ["models", "llm", "indexing", "retrieval"],
    summary: [
      "llm.model",
      "models.vlm_path",
      "models.reranker_path",
      "retrieval.vector_enabled",
    ],
  },
  {
    id: "web",
    title: "Web & UI",
    description: "Console access and auth.",
    prefixes: ["web"],
    summary: ["web.bind_port", "web.allow_remote"],
  },
  {
    id: "plugins",
    title: "Plugins & Hosting",
    description: "Plugin hosting policies and locks.",
    prefixes: ["plugins"],
    summary: ["plugins.hosting.mode", "plugins.locks.enforce"],
  },
  {
    id: "research",
    title: "Research & PromptOps",
    description: "Background research and prompt operations.",
    prefixes: ["research", "promptops"],
    summary: ["research.enabled", "promptops.enabled"],
  },
  {
    id: "time",
    title: "Time & Locale",
    description: "Timezone and relative time parsing.",
    prefixes: ["time"],
    summary: ["time.timezone", "runtime.timezone"],
  },
];

const PLUGIN_GROUPS = [
  {
    id: "capture",
    title: "Capture (Base Layer)",
    kinds: ["capture.source", "capture.audio", "capture.screenshot", "tracking.input", "tracking.cursor", "tracking.clipboard", "tracking.file_activity", "window.metadata"],
    settingsPrefixes: ["capture", "runtime", "backpressure"],
  },
  {
    id: "vlm",
    title: "Vision & VLM",
    kinds: ["vision.extractor"],
    capability: "vision.extractor",
    settingsPrefixes: ["processing", "models", "indexing"],
  },
  {
    id: "ocr",
    title: "OCR",
    kinds: ["ocr.engine"],
    capability: "ocr.engine",
    settingsPrefixes: ["processing", "models", "indexing"],
  },
  {
    id: "retrieval",
    title: "Retrieval & Ranking",
    kinds: ["retrieval.strategy", "embedder.text", "reranker"],
    capability: "retrieval.strategy",
    settingsPrefixes: ["retrieval", "indexing", "models"],
  },
  {
    id: "processing",
    title: "Processing & Pipelines",
    kinds: ["processing.pipeline", "processing.stage.hooks"],
    capability: "processing.stage.hooks",
    settingsPrefixes: ["processing"],
  },
  {
    id: "storage",
    title: "Storage & Proof",
    kinds: ["storage.metadata_store", "ledger.writer", "journal.writer", "anchor.writer"],
    settingsPrefixes: ["storage"],
  },
  {
    id: "privacy",
    title: "Privacy & Egress",
    kinds: ["egress.gateway", "privacy.egress_sanitizer"],
    settingsPrefixes: ["privacy", "gateway"],
  },
  {
    id: "runtime",
    title: "Runtime & Budgeting",
    kinds: ["runtime.governor", "runtime.scheduler", "capture.backpressure", "observability.logger"],
    settingsPrefixes: ["runtime", "performance", "alerts"],
  },
  {
    id: "answers",
    title: "Answering & Citations",
    kinds: ["answer.builder", "citation.validator"],
    capability: "answer.builder",
    settingsPrefixes: [],
  },
  {
    id: "time",
    title: "Time & Locale",
    kinds: ["time.intent_parser"],
    settingsPrefixes: ["time", "runtime"],
  },
  {
    id: "devtools",
    title: "Devtools",
    kinds: ["devtools.ast_ir", "devtools.diffusion", "meta.configurator", "meta.policy"],
    settingsPrefixes: ["devtools", "plugins"],
  },
  {
    id: "other",
    title: "Other",
    kinds: [],
    settingsPrefixes: [],
  },
];

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
}

function prettyLabel(path) {
  if (!path) return "";
  return path
    .split(".")
    .map((part) => capitalize(part.replace(/_/g, " ")))
    .join(" · ");
}

function formatSummaryValue(value) {
  if (typeof value === "boolean") return value ? "ON" : "OFF";
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return `${value.length} items`;
  if (typeof value === "object") return "custom";
  return String(value);
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let idx = 0;
  let v = bytes;
  while (v >= 1024 && idx < units.length - 1) {
    v /= 1024;
    idx += 1;
  }
  return `${v.toFixed(v >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function formatTs(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch (err) {
    return String(value);
  }
}

function formatAgo(value) {
  if (!value) return "—";
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return String(value);
  const delta = Math.max(0, Date.now() - ts);
  const seconds = Math.round(delta / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function renderSparkline(container, values) {
  if (!container) return;
  container.innerHTML = "";
  if (!values || !values.length) {
    container.textContent = "—";
    return;
  }
  const maxValue = Math.max(...values, 1);
  values.forEach((value) => {
    const bar = document.createElement("span");
    const height = Math.max(4, Math.round((value / maxValue) * 28));
    bar.className = "spark-bar";
    bar.style.height = `${height}px`;
    if (!value) {
      bar.classList.add("dim");
    }
    container.appendChild(bar);
  });
}

function pluginDisplayName(plugin) {
  if (!plugin || !plugin.plugin_id) return "Plugin";
  const raw = String(plugin.plugin_id || "");
  const trimmed = raw.replace(/^builtin\./, "").replace(/^mx\./, "");
  return trimmed
    .split(".")
    .map((part) =>
      part
        .replace(/_/g, " ")
        .split(" ")
        .map((word) => capitalize(word))
        .join(" ")
    )
    .join(" ");
}

function pluginKinds(plugin) {
  const kinds = new Set();
  (plugin.kinds || []).forEach((kind) => kinds.add(kind));
  (plugin.provides || []).forEach((kind) => kinds.add(kind));
  return Array.from(kinds);
}

function pluginTelemetry(pluginId) {
  const latest = (state.telemetry.latest || {})[`plugin.${pluginId}`];
  return latest || null;
}

function findPluginByKind(kind) {
  if (!kind) return null;
  const enabled = state.plugins.filter((plugin) => plugin.enabled);
  const pool = enabled.length ? enabled : state.plugins;
  for (const plugin of pool) {
    if ((plugin.kinds || []).includes(kind) || (plugin.provides || []).includes(kind)) {
      return plugin;
    }
  }
  return null;
}

function filterFieldsByPrefixes(fields, prefixes, showAll) {
  if (showAll || !prefixes || !prefixes.length) return fields;
  return fields.filter((field) => {
    const path = field.path || "";
    return prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}.`));
  });
}

function buildPluginFieldGroups(settings) {
  const groups = [];
  if (!settings || typeof settings !== "object" || Array.isArray(settings)) {
    groups.push({ name: "General", fields: flattenSettings(settings) });
    return groups;
  }
  const topKeys = Object.keys(settings).filter(
    (key) => settings[key] && typeof settings[key] === "object" && !Array.isArray(settings[key])
  );
  if (!topKeys.length) {
    groups.push({ name: "General", fields: flattenSettings(settings) });
    return groups;
  }
  topKeys.forEach((key) => {
    groups.push({ name: key, fields: flattenSettings(settings[key], [key]) });
  });
  return groups;
}

function groupPlugins(plugins) {
  const groups = PLUGIN_GROUPS.map((def) => ({ ...def, plugins: [] }));
  plugins.forEach((plugin) => {
    const kinds = pluginKinds(plugin);
    let matched = false;
    groups.forEach((group) => {
      if (group.id === "other") return;
      const match = kinds.some((kind) => group.kinds.includes(kind));
      if (match) {
        group.plugins.push(plugin);
        matched = true;
      }
    });
    if (!matched) {
      groups.find((g) => g.id === "other")?.plugins.push(plugin);
    }
  });
  return groups.filter((group) => group.plugins.length);
}

function selectPluginGroup(groupId) {
  state.activePluginGroupId = groupId;
  state.activePluginId = null;
  state.activePluginOptionGroup = null;
  renderPluginGroups();
  renderPluginList();
  renderPluginDetail();
}

function selectPlugin(pluginId) {
  state.activePluginId = pluginId;
  state.activePluginOptionGroup = null;
  loadPluginSettings(pluginId);
}

function renderPluginGroups() {
  if (!pluginGroupsList) return;
  pluginGroupsList.innerHTML = "";
  state.pluginGroups.forEach((group) => {
    const item = document.createElement("div");
    item.className = "group-item";
    if (group.id === state.activePluginGroupId) {
      item.classList.add("active");
    }
    const title = document.createElement("div");
    title.className = "group-title";
    title.textContent = group.title;
    const meta = document.createElement("div");
    meta.className = "group-meta";
    const enabledCount = group.plugins.filter((plugin) => plugin.enabled).length;
    meta.textContent = `${enabledCount}/${group.plugins.length} enabled`;
    item.appendChild(title);
    item.appendChild(meta);
    item.addEventListener("click", () => selectPluginGroup(group.id));
    pluginGroupsList.appendChild(item);
  });
}

async function toggleGroupEnabled(group, enabled) {
  const tasks = group.plugins.map((plugin) => {
    const endpoint = enabled ? "enable" : "disable";
    return apiFetch(`/api/plugins/${plugin.plugin_id}/${endpoint}`, { method: "POST" });
  });
  await Promise.all(tasks);
  await refreshPlugins();
  await refreshConfigHistory();
}

async function updateCapabilityPolicy(capability, patch) {
  if (!capability) return;
  const payload = {
    plugins: {
      capabilities: {
        [capability]: patch,
      },
    },
  };
  await apiFetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patch: payload }),
  });
  await refreshConfig();
  renderPluginList();
}

function renderGroupControls(group) {
  if (!pluginGroupControls) return;
  pluginGroupControls.innerHTML = "";
  const enabledCount = group.plugins.filter((plugin) => plugin.enabled).length;
  const enabled = enabledCount > 0;
  const enableRow = document.createElement("div");
  enableRow.className = "control-row";
  const enableLabel = document.createElement("label");
  enableLabel.textContent = "Group enabled";
  const enableToggle = document.createElement("input");
  enableToggle.type = "checkbox";
  enableToggle.checked = enabled;
  enableToggle.addEventListener("change", async () => {
    await toggleGroupEnabled(group, enableToggle.checked);
  });
  enableRow.appendChild(enableLabel);
  enableRow.appendChild(enableToggle);
  pluginGroupControls.appendChild(enableRow);

  if (group.capability) {
    const policy = ((state.config.plugins || {}).capabilities || {})[group.capability] || {};
    const modeRow = document.createElement("div");
    modeRow.className = "control-row";
    const modeLabel = document.createElement("label");
    modeLabel.textContent = "Allow multiple providers";
    const modeToggle = document.createElement("input");
    modeToggle.type = "checkbox";
    modeToggle.checked = String(policy.mode || "single") === "multi";
    modeToggle.addEventListener("change", async () => {
      await updateCapabilityPolicy(group.capability, { mode: modeToggle.checked ? "multi" : "single" });
    });
    modeRow.appendChild(modeLabel);
    modeRow.appendChild(modeToggle);
    pluginGroupControls.appendChild(modeRow);

    if (modeToggle.checked) {
      const maxRow = document.createElement("div");
      maxRow.className = "control-row";
      const maxLabel = document.createElement("label");
      maxLabel.textContent = "Max providers";
      const maxInput = document.createElement("input");
      maxInput.type = "number";
      maxInput.min = "0";
      maxInput.value = policy.max_providers ?? 0;
      maxInput.addEventListener("change", async () => {
        const value = parseInt(maxInput.value || "0", 10);
        await updateCapabilityPolicy(group.capability, { max_providers: value });
      });
      maxRow.appendChild(maxLabel);
      maxRow.appendChild(maxInput);
      pluginGroupControls.appendChild(maxRow);
    }
  }
}

function renderPluginList() {
  if (!pluginsList) return;
  pluginsList.innerHTML = "";
  const group = state.pluginGroups.find((g) => g.id === state.activePluginGroupId);
  if (!group) {
    pluginsList.textContent = "Select a plugin group.";
    if (pluginGroupTitle) pluginGroupTitle.textContent = "Select a group";
    if (pluginGroupMeta) pluginGroupMeta.textContent = "";
    if (pluginGroupControls) pluginGroupControls.innerHTML = "";
    return;
  }
  if (pluginGroupTitle) pluginGroupTitle.textContent = group.title;
  if (pluginGroupMeta) {
    const enabledCount = group.plugins.filter((plugin) => plugin.enabled).length;
    pluginGroupMeta.textContent = `${enabledCount}/${group.plugins.length} enabled`;
  }
  renderGroupControls(group);
  group.plugins.forEach((plugin) => {
    const row = document.createElement("div");
    row.className = "table-row";
    if (plugin.plugin_id === state.activePluginId) {
      row.classList.add("active");
    }
    const name = document.createElement("div");
    name.className = "plugin-name";
    const title = document.createElement("span");
    title.className = "plugin-title";
    title.textContent = pluginDisplayName(plugin);
    const hint = document.createElement("span");
    hint.className = "plugin-id";
    hint.textContent = plugin.plugin_id;
    name.appendChild(title);
    name.appendChild(hint);
    const enabled = document.createElement("span");
    enabled.innerHTML = plugin.enabled ? formatBadge("enabled") : formatBadge("disabled", "off");
    const hash = document.createElement("span");
    hash.innerHTML = plugin.hash_ok ? formatBadge("hash ok") : formatBadge("hash drift", "warn");
    const lastOutput = document.createElement("span");
    const telemetry = pluginTelemetry(plugin.plugin_id);
    if (telemetry && telemetry.ts_utc) {
      const size = telemetry.output_bytes ? ` · ${formatBytes(telemetry.output_bytes)}` : "";
      lastOutput.textContent = `${formatAgo(telemetry.ts_utc)}${size}`;
    } else {
      lastOutput.textContent = "—";
    }
    const actions = document.createElement("div");
    actions.className = "actions";
    const toggle = document.createElement("button");
    toggle.className = "ghost";
    toggle.textContent = plugin.enabled ? "Disable" : "Enable";
    toggle.onclick = async () => {
      const endpoint = plugin.enabled ? "disable" : "enable";
      await apiFetch(`/api/plugins/${plugin.plugin_id}/${endpoint}`, { method: "POST" });
      await refreshPlugins();
      await refreshConfigHistory();
    };
    const settingsBtn = document.createElement("button");
    settingsBtn.textContent = "Configure";
    settingsBtn.onclick = () => selectPlugin(plugin.plugin_id);
    actions.appendChild(toggle);
    actions.appendChild(settingsBtn);
    row.appendChild(name);
    row.appendChild(enabled);
    row.appendChild(hash);
    row.appendChild(lastOutput);
    row.appendChild(actions);
    pluginsList.appendChild(row);
  });
}

function renderPluginDetail() {
  if (!pluginSettingsList) return;
  pluginSettingsList.innerHTML = "";
  if (pluginOptionGroups) pluginOptionGroups.innerHTML = "";
  if (!state.activePluginId) {
    pluginSettingsList.textContent = "Select a plugin to configure.";
    if (pluginSettingsTitle) pluginSettingsTitle.textContent = "Plugin Details";
    if (pluginSettingsSubtitle) pluginSettingsSubtitle.textContent = "";
    if (pluginShowAll) {
      pluginShowAll.checked = false;
      pluginShowAll.disabled = true;
    }
    return;
  }
  const info = state.plugins.find((plugin) => plugin.plugin_id === state.activePluginId);
  const group = state.pluginGroups.find((item) => item.id === state.activePluginGroupId);
  const groupLabel = group ? group.title : "";
  const displayName = pluginDisplayName(info);
  if (pluginSettingsTitle) pluginSettingsTitle.textContent = `Plugin · ${displayName}`;
  if (pluginSettingsSubtitle) {
    const status = info && info.enabled ? "enabled" : "disabled";
    const version = info && info.version ? `v${info.version}` : "";
    const pluginId = info && info.plugin_id ? info.plugin_id : "";
    pluginSettingsSubtitle.textContent = [groupLabel, status, version, pluginId].filter(Boolean).join(" · ");
  }
  const settings = state.activePluginSettings || {};
  const groups = buildPluginFieldGroups(settings);
  const prefixes = (group && group.settingsPrefixes) || [];
  const showAll = state.showAllPluginSettings || !prefixes.length;
  if (pluginShowAll) {
    if (!prefixes.length) {
      pluginShowAll.checked = true;
      pluginShowAll.disabled = true;
    } else {
      pluginShowAll.disabled = false;
      pluginShowAll.checked = state.showAllPluginSettings;
    }
  }
  const visibleGroups = groups
    .map((entry) => ({
      name: entry.name,
      fields: filterFieldsByPrefixes(entry.fields, prefixes, showAll),
    }))
    .filter((entry) => entry.fields.length);
  if (!visibleGroups.length) {
    pluginSettingsList.textContent = showAll
      ? "No settings exposed"
      : 'No settings in this group. Enable "Show all settings" to view full plugin options.';
    return;
  }
  const groupNames = visibleGroups.map((entry) => entry.name);
  const activeGroup = groupNames.includes(state.activePluginOptionGroup)
    ? state.activePluginOptionGroup
    : groupNames[0];
  state.activePluginOptionGroup = activeGroup;
  if (pluginOptionGroups) {
    visibleGroups.forEach((entry) => {
      const btn = document.createElement("button");
      btn.className = "pill-btn";
      if (entry.name === activeGroup) btn.classList.add("active");
      btn.textContent = entry.name;
      btn.addEventListener("click", () => {
        state.activePluginOptionGroup = entry.name;
        renderPluginDetail();
      });
      pluginOptionGroups.appendChild(btn);
    });
  }
  const activeEntry = visibleGroups.find((entry) => entry.name === activeGroup);
  const fields = activeEntry ? activeEntry.fields : [];
  if (!fields.length) {
    pluginSettingsList.textContent = "No settings exposed";
    return;
  }
  const fragment = document.createDocumentFragment();
  fields.forEach((field) => {
    renderField(fragment, { ...field, label: prettyLabel(field.path || "") }, state.pluginDirty);
  });
  pluginSettingsList.appendChild(fragment);
}

async function refreshPlugins() {
  const resp = await apiFetch("/api/plugins");
  const data = await readJson(resp);
  state.plugins = data.plugins || [];
  state.pluginGroups = groupPlugins(state.plugins);
  if (!state.activePluginGroupId && state.pluginGroups.length) {
    state.activePluginGroupId = state.pluginGroups[0].id;
  }
  renderPluginGroups();
  renderPluginList();
  renderPluginDetail();
}

async function postConfigPatch(patch) {
  await apiFetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patch }),
  });
  await refreshConfig();
}

function updateQuickControls() {
  if (quickCaptureToggle) {
    quickCaptureToggle.checked = Boolean(state.status.capture_active);
  }
  if (quickPauseStatus) {
    if (state.status.paused_until_utc) {
      quickPauseStatus.textContent = `Paused until ${formatTs(state.status.paused_until_utc)}`;
    } else {
      quickPauseStatus.textContent = state.status.capture_active ? "Capture running" : "Capture stopped";
    }
  }
  if (quickPrivacyMode) {
    const privacy = state.config.privacy || {};
    const egressEnabled = privacy.egress?.enabled !== false;
    const cloudEnabled = privacy.cloud?.enabled === true;
    quickPrivacyMode.checked = !egressEnabled && !cloudEnabled;
  }
  if (quickFidelityMode) {
    quickFidelityMode.checked = localStorage.getItem("acFidelityMode") === "true";
  }
  if (fidelitySummary) {
    const video = state.config.capture?.video || {};
    const activity = video.activity || {};
    fidelitySummary.textContent =
      `FPS ${video.fps_target ?? "—"} · Q ${video.jpeg_quality ?? "—"} · ` +
      `Active ${activity.active_fps ?? "—"}fps/${activity.active_bitrate_kbps ?? "—"}kbps · ` +
      `Idle ${activity.idle_fps ?? "—"}fps/${activity.idle_bitrate_kbps ?? "—"}kbps`;
  }
}

function applyTelemetryPayload(payload) {
  if (!payload || !payload.telemetry) return;
  state.telemetry = payload.telemetry || {};
  const now = Date.now();
  if (now - telemetryRenderAt < 750) {
    return;
  }
  telemetryRenderAt = now;
  updateCaptureHealth();
  renderPluginList();
}

function updateCaptureHealth() {
  const latest = state.telemetry.latest || {};
  if (healthQueue) {
    const cap = latest.capture || {};
    const depth = cap.queue_depth ?? "—";
    const max = cap.queue_depth_max ?? "—";
    healthQueue.textContent = `${depth} / ${max}`;
  }
  if (healthLag) {
    const cap = latest.capture || {};
    const lag = cap.lag_ms ? `${Math.round(cap.lag_ms)} ms` : "—";
    const interval = cap.frame_interval_ms ? `${Math.round(cap.frame_interval_ms)} ms` : "—";
    healthLag.textContent = `${lag} · ${interval}`;
  }
  if (healthScreenshot) {
    const shot = latest["capture.screenshot"] || null;
    if (shot && shot.ts_utc) {
      const size = shot.output_bytes ? ` · ${formatBytes(shot.output_bytes)}` : "";
      const saved = shot.saved_frames ? ` · ${shot.saved_frames}/${shot.seen_frames} saved` : "";
      healthScreenshot.textContent = `${formatAgo(shot.ts_utc)}${size}${saved}`;
    } else {
      healthScreenshot.textContent = "—";
    }
  }
  if (healthVideo) {
    const vid = latest["capture.output"] || null;
    if (vid && vid.ts_utc) {
      const size = vid.output_bytes ? ` · ${formatBytes(vid.output_bytes)}` : "";
      const frames = vid.frame_count ? ` · ${vid.frame_count} frames` : "";
      healthVideo.textContent = `${formatAgo(vid.ts_utc)}${size}${frames}`;
    } else {
      healthVideo.textContent = "—";
    }
  }
  const history = state.telemetry.history || {};
  const shotHistory = (history["capture.screenshot"] || []).slice(-20);
  const shotValues = shotHistory.map((item) => Number(item.write_ms || 0));
  renderSparkline(healthSparkScreenshot, shotValues);
  const videoHistory = (history["capture.output"] || []).slice(-20);
  const videoValues = videoHistory.map((item) => Number(item.write_ms || 0));
  renderSparkline(healthSparkVideo, videoValues);
}

async function refreshHealth() {
  await refreshTimelineSummary();
  const resp = await apiFetch("/api/telemetry");
  const data = await readJson(resp);
  applyTelemetryPayload(data);
}

async function refreshTimelineSummary() {
  if (!healthEvent) return;
  const resp = await apiFetch("/api/timeline?limit=1");
  const data = await readJson(resp);
  const events = data.events || [];
  if (!events.length) {
    healthEvent.textContent = "—";
    return;
  }
  const event = events[0];
  const label = event.event_type || event.event || "event";
  const ts = event.ts_utc || "";
  healthEvent.textContent = `${label} · ${formatAgo(ts)}`;
}

async function refreshStorage() {
  const usageResp = await apiFetch("/api/storage/usage");
  const usage = await readJson(usageResp);
  if (storageDir) storageDir.textContent = usage.data_dir || "—";
  if (storageFree) {
    const free = formatBytes(usage.free_bytes);
    const total = formatBytes(usage.total_bytes);
    storageFree.textContent = `${free} / ${total}`;
  }
  const forecastResp = await apiFetch("/api/storage/forecast");
  const forecast = await readJson(forecastResp);
  if (storageDays) {
    storageDays.textContent = forecast.days_remaining === null ? "—" : `${forecast.days_remaining} days`;
  }
  if (storageEvidence) {
    storageEvidence.textContent = formatBytes(forecast.evidence_bytes_per_day);
  }
  if (storageDerived) {
    storageDerived.textContent = formatBytes(forecast.derived_bytes_per_day);
  }
  if (storageHint) {
    if (forecast.samples && forecast.samples >= 2) {
      storageHint.textContent = "";
    } else {
      storageHint.textContent = "Run capture to record disk pressure samples for runway forecasting.";
    }
  }
}

async function refreshConfigHistory() {
  if (!configHistoryList) return;
  const resp = await apiFetch("/api/config/history?limit=20");
  const data = await readJson(resp);
  const changes = data.changes || [];
  configHistoryList.innerHTML = "";
  if (!changes.length) {
    configHistoryList.textContent = "No changes recorded yet";
    return;
  }
  const fragment = document.createDocumentFragment();
  changes
    .slice()
    .reverse()
    .forEach((change) => {
      const row = document.createElement("div");
      row.className = "history-item";
      const meta = document.createElement("div");
      meta.className = "history-meta";
      const scope = change.scope || "config";
      const ts = change.ts_utc ? formatAgo(change.ts_utc) : "—";
      const plugin = change.plugin_id ? ` · ${change.plugin_id}` : "";
      meta.textContent = `${scope}${plugin} · ${ts}`;
      const actions = document.createElement("div");
      actions.className = "history-actions";
      const btn = document.createElement("button");
      btn.className = "ghost";
      btn.textContent = "Revert";
      btn.addEventListener("click", async () => {
        if (configHistoryStatus) configHistoryStatus.textContent = "Reverting...";
        await apiFetch("/api/config/revert", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ change_id: change.id }),
        });
        if (configHistoryStatus) configHistoryStatus.textContent = "Reverted";
        await refreshSettings();
        await refreshConfig();
        await refreshConfigHistory();
      });
      actions.appendChild(btn);
      row.appendChild(meta);
      row.appendChild(actions);
      fragment.appendChild(row);
    });
  configHistoryList.appendChild(fragment);
}

async function refreshBookmarks() {
  if (!bookmarkList) return;
  const resp = await apiFetch("/api/bookmarks?limit=5");
  const data = await readJson(resp);
  const bookmarks = data.bookmarks || [];
  bookmarkList.innerHTML = "";
  if (!bookmarks.length) {
    const li = document.createElement("li");
    li.textContent = "No bookmarks yet";
    bookmarkList.appendChild(li);
    return;
  }
  bookmarks
    .slice()
    .reverse()
    .forEach((entry) => {
      const li = document.createElement("li");
      const tags = entry.tags && entry.tags.length ? ` · ${entry.tags.join(", ")}` : "";
      li.textContent = `${entry.note}${tags}`;
      bookmarkList.appendChild(li);
    });
}

async function refreshActivityTimeline() {
  if (!activityTimelineList) return;
  const [timelineResp, historyResp, bookmarkResp] = await Promise.all([
    apiFetch("/api/timeline?limit=25"),
    apiFetch("/api/config/history?limit=25"),
    apiFetch("/api/bookmarks?limit=25"),
  ]);
  const timelineData = await readJson(timelineResp);
  const historyData = await readJson(historyResp);
  const bookmarkData = await readJson(bookmarkResp);
  const events = (timelineData.events || []).map((event) => ({
    ts_utc: event.ts_utc || "",
    type: "activity",
    label: event.event_type || event.event || "event",
    detail: event.event_id || event.record_id || "",
  }));
  const changes = (historyData.changes || []).map((change) => ({
    ts_utc: change.ts_utc || "",
    type: "changes",
    label: `${change.scope || "config"}${change.plugin_id ? ` · ${change.plugin_id}` : ""}`,
    detail: change.id || "",
  }));
  const bookmarks = (bookmarkData.bookmarks || []).map((bookmark) => ({
    ts_utc: bookmark.ts_utc || "",
    type: "bookmarks",
    label: bookmark.note || "bookmark",
    detail: bookmark.id || "",
  }));
  let items = [...events, ...changes, ...bookmarks];
  items = items.filter((item) => {
    if (item.type === "activity" && !state.activityFilters.activity) return false;
    if (item.type === "changes" && !state.activityFilters.changes) return false;
    if (item.type === "bookmarks" && !state.activityFilters.bookmarks) return false;
    return true;
  });
  items.sort((a, b) => {
    const at = Date.parse(a.ts_utc || "") || 0;
    const bt = Date.parse(b.ts_utc || "") || 0;
    return bt - at;
  });
  activityTimelineList.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.textContent = "No activity yet";
    activityTimelineList.appendChild(li);
    return;
  }
  items.slice(0, 30).forEach((item) => {
    const li = document.createElement("li");
    const meta = item.detail ? ` · ${item.detail}` : "";
    li.textContent = `${item.label} · ${formatAgo(item.ts_utc)}${meta}`;
    activityTimelineList.appendChild(li);
  });
}

async function refreshKeys() {
  const resp = await apiFetch("/api/keys");
  const data = await readJson(resp);
  keysPayload.textContent = JSON.stringify(data, null, 2);
}

async function refreshEgress() {
  const resp = await apiFetch("/api/egress/requests");
  const data = await readJson(resp);
  egressList.innerHTML = "";
  const requests = data.requests || [];
  if (!requests.length) {
    const li = document.createElement("li");
    li.textContent = "No pending approvals";
    egressList.appendChild(li);
    return;
  }
  requests.forEach((req) => {
    const li = document.createElement("li");
    const header = document.createElement("div");
    header.textContent = `${req.approval_id} · ${req.policy_id}`;
    const meta = document.createElement("div");
    meta.textContent = `hash: ${req.packet_hash} · schema v${req.schema_version}`;
    const actions = document.createElement("div");
    actions.className = "actions";
    const approve = document.createElement("button");
    approve.textContent = "Approve";
    approve.onclick = async () => {
      const res = await apiFetch("/api/egress/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_id: req.approval_id }),
      });
      const payload = await readJson(res);
      li.innerHTML = "";
      const done = document.createElement("div");
      done.textContent = `Approved · token ${payload.token}`;
      li.appendChild(done);
    };
    const deny = document.createElement("button");
    deny.className = "ghost";
    deny.textContent = "Deny";
    deny.onclick = async () => {
      await apiFetch("/api/egress/deny", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_id: req.approval_id }),
      });
      refreshEgress();
    };
    actions.appendChild(approve);
    actions.appendChild(deny);
    li.appendChild(header);
    li.appendChild(meta);
    li.appendChild(actions);
    egressList.appendChild(li);
  });
}

async function runQuery() {
  const query = (queryInput.value || "").trim();
  if (!query) return;
  queryOutput.textContent = "";
  const resp = await apiFetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  const data = await readJson(resp);
  queryOutput.textContent = JSON.stringify(data, null, 2);
}

async function runVerify(endpoint) {
  verifyOutput.textContent = "";
  const resp = await apiFetch(endpoint, { method: "POST" });
  const data = await readJson(resp);
  verifyOutput.textContent = JSON.stringify(data, null, 2);
}

function setNested(target, path, value) {
  const parts = path.split(".");
  let cursor = target;
  for (let i = 0; i < parts.length - 1; i += 1) {
    const part = parts[i];
    if (!cursor[part] || typeof cursor[part] !== "object" || Array.isArray(cursor[part])) {
      cursor[part] = {};
    }
    cursor = cursor[part];
  }
  cursor[parts[parts.length - 1]] = value;
}

function buildPatch(dirty) {
  const patch = {};
  Object.entries(dirty).forEach(([path, value]) => {
    setNested(patch, path, value);
  });
  return patch;
}

function inferType(value) {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  if (Array.isArray(value)) return "array";
  if (value && typeof value === "object") return "object";
  return "string";
}

function parseValue(type, raw, enumValues) {
  if (enumValues && enumValues.length) {
    return raw;
  }
  if (type === "boolean") {
    return Boolean(raw);
  }
  if (type === "integer") {
    const val = parseInt(raw, 10);
    if (Number.isNaN(val)) throw new Error("invalid integer");
    return val;
  }
  if (type === "number") {
    const val = parseFloat(raw);
    if (Number.isNaN(val)) throw new Error("invalid number");
    return val;
  }
  if (type === "array" || type === "object") {
    return JSON.parse(raw || "null");
  }
  return raw;
}

function renderField(container, field, dirtyStore) {
  const row = document.createElement("div");
  row.className = "settings-row";
  const label = document.createElement("div");
  label.className = "settings-path";
  const labelTitle = field.label || prettyLabel(field.path || "") || field.path || "";
  const labelText = document.createElement("span");
  labelText.className = "settings-label";
  labelText.textContent = labelTitle;
  const labelHint = document.createElement("span");
  labelHint.className = "settings-hint";
  labelHint.textContent = field.path || "";
  label.appendChild(labelText);
  label.appendChild(labelHint);
  const inputWrap = document.createElement("div");
  inputWrap.className = "settings-input";

  let input;
  if (field.enum && Array.isArray(field.enum)) {
    input = document.createElement("select");
    field.enum.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      if (String(value) === String(field.value)) {
        option.selected = true;
      }
      input.appendChild(option);
    });
  } else if (field.type === "boolean") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(field.value);
  } else if (field.type === "integer" || field.type === "number") {
    input = document.createElement("input");
    input.type = "number";
    input.value = field.value ?? "";
  } else if (field.type === "array" || field.type === "object") {
    input = document.createElement("textarea");
    input.value = JSON.stringify(field.value ?? null, null, 2);
  } else {
    input = document.createElement("input");
    input.type = "text";
    input.value = field.value ?? "";
  }

  const onChange = () => {
    try {
      let value;
      if (field.type === "boolean") {
        value = input.checked;
      } else {
        value = parseValue(field.type, input.value, field.enum);
      }
      dirtyStore[field.path] = value;
      input.classList.remove("warn");
    } catch (err) {
      input.classList.add("warn");
    }
  };

  input.addEventListener("change", onChange);
  inputWrap.appendChild(input);
  row.appendChild(label);
  row.appendChild(inputWrap);
  container.appendChild(row);
}

function filterFields(fields, query) {
  if (!query) return fields;
  const q = query.toLowerCase();
  return fields.filter((field) => {
    const path = (field.path || "").toLowerCase();
    const label = (field.label || "").toLowerCase();
    return path.includes(q) || label.includes(q);
  });
}

function settingsGroupForPath(path) {
  const prefix = (path || "").split(".")[0];
  for (const group of SETTINGS_GROUPS) {
    if (group.prefixes && group.prefixes.includes(prefix)) {
      return group.id;
    }
  }
  return "other";
}

function buildSettingsGroups(fields) {
  const grouped = {};
  fields.forEach((field) => {
    const id = settingsGroupForPath(field.path);
    if (!grouped[id]) grouped[id] = [];
    grouped[id].push(field);
  });
  const groups = SETTINGS_GROUPS.map((def) => {
    const groupFields = (grouped[def.id] || []).slice().sort((a, b) => (a.path || "").localeCompare(b.path || ""));
    const summaryFields = (def.summary || [])
      .map((path) => groupFields.find((field) => field.path === path))
      .filter(Boolean);
    return {
      id: def.id,
      title: def.title,
      description: def.description,
      fields: groupFields,
      summaryFields,
      open: Boolean(state.settingsGroupOpen[def.id]),
    };
  }).filter((group) => group.fields.length);
  if (grouped.other && grouped.other.length) {
    groups.push({
      id: "other",
      title: "Other",
      description: "Everything else.",
      fields: grouped.other.slice().sort((a, b) => (a.path || "").localeCompare(b.path || "")),
      summaryFields: [],
      open: Boolean(state.settingsGroupOpen.other),
    });
  }
  return groups;
}

async function refreshSettings() {
  const resp = await apiFetch("/api/settings/schema");
  const data = await readJson(resp);
  state.settingsFields = data.fields || [];
  state.settingsDirty = {};
  renderSettings();
}

function renderSettings() {
  if (!settingsList) return;
  const query = (settingsFilter?.value || "").trim();
  const fields = state.settingsFields.map((field) => ({
    ...field,
    label: field.label || prettyLabel(field.path || ""),
  }));
  settingsList.innerHTML = "";
  if (query) {
    const filtered = filterFields(fields, query);
    if (!filtered.length) {
      settingsList.textContent = "No settings found";
      return;
    }
    const fragment = document.createDocumentFragment();
    filtered.forEach((field) => {
      renderField(fragment, field, state.settingsDirty);
    });
    settingsList.appendChild(fragment);
    return;
  }
  const groups = buildSettingsGroups(fields);
  if (!groups.length) {
    settingsList.textContent = "No settings found";
    return;
  }
  const fragment = document.createDocumentFragment();
  groups.forEach((group) => {
    const card = document.createElement("div");
    card.className = "settings-group";

    const header = document.createElement("div");
    header.className = "settings-group-header";
    const title = document.createElement("div");
    title.className = "group-title";
    title.textContent = group.title;
    const desc = document.createElement("div");
    desc.className = "group-meta";
    desc.textContent = group.description || "";
    header.appendChild(title);
    header.appendChild(desc);
    card.appendChild(header);

    if (group.summaryFields.length) {
      const essentials = document.createElement("div");
      essentials.className = "settings-essentials";
      const essentialsTitle = document.createElement("div");
      essentialsTitle.className = "settings-section-title";
      essentialsTitle.textContent = "Essentials";
      essentials.appendChild(essentialsTitle);
      group.summaryFields.forEach((field) => {
        renderField(essentials, field, state.settingsDirty);
      });
      card.appendChild(essentials);
    }

    const advancedFields = group.fields.filter(
      (field) => !group.summaryFields.find((summary) => summary.path === field.path)
    );
    if (advancedFields.length) {
      const detail = document.createElement("details");
      detail.className = "settings-advanced";
      detail.open = Boolean(group.open);
      detail.addEventListener("toggle", () => {
        state.settingsGroupOpen[group.id] = detail.open;
      });
      const summary = document.createElement("summary");
      summary.textContent = `Advanced (${advancedFields.length})`;
      detail.appendChild(summary);
      const body = document.createElement("div");
      body.className = "settings-group-body";
      advancedFields.forEach((field) => {
        renderField(body, field, state.settingsDirty);
      });
      detail.appendChild(body);
      card.appendChild(detail);
    }

    fragment.appendChild(card);
  });
  settingsList.appendChild(fragment);
}

function flattenSettings(obj, prefix = []) {
  const fields = [];
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    const keys = Object.keys(obj);
    if (!keys.length) {
      if (prefix.length) {
        fields.push({ path: prefix.join("."), type: "object", value: obj });
      }
      return fields;
    }
    keys.forEach((key) => {
      const value = obj[key];
      if (value && typeof value === "object" && !Array.isArray(value)) {
        fields.push(...flattenSettings(value, prefix.concat(key)));
      } else {
        fields.push({ path: prefix.concat(key).join("."), type: inferType(value), value });
      }
    });
    return fields;
  }
  fields.push({ path: prefix.join("."), type: inferType(obj), value: obj });
  return fields;
}

async function loadPluginSettings(pluginId) {
  const resp = await apiFetch(`/api/plugins/${pluginId}/settings`);
  const data = await readJson(resp);
  const settings = data.settings || {};
  state.pluginDirty = {};
  state.activePluginId = pluginId;
  state.activePluginSettings = settings;
  if (pluginSettingsStatus) {
    pluginSettingsStatus.textContent = "";
  }
  renderPluginDetail();
}

async function applySettings() {
  if (!Object.keys(state.settingsDirty).length) {
    settingsStatus.textContent = "No changes to apply";
    return;
  }
  settingsStatus.textContent = "Applying...";
  const patch = buildPatch(state.settingsDirty);
  const resp = await apiFetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patch }),
  });
  const data = await readJson(resp);
  settingsStatus.textContent = data.error ? `Error: ${data.error}` : "Applied";
  await refreshSettings();
  await refreshConfigHistory();
}

async function applyPluginSettings() {
  if (!state.activePluginId) {
    pluginSettingsStatus.textContent = "Select a plugin";
    return;
  }
  if (!Object.keys(state.pluginDirty).length) {
    pluginSettingsStatus.textContent = "No changes to apply";
    return;
  }
  pluginSettingsStatus.textContent = "Applying...";
  const patch = buildPatch(state.pluginDirty);
  const resp = await apiFetch(`/api/plugins/${state.activePluginId}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patch }),
  });
  const data = await readJson(resp);
  pluginSettingsStatus.textContent = data.error ? `Error: ${data.error}` : "Applied";
  await loadPluginSettings(state.activePluginId);
  await refreshConfigHistory();
}

async function connectTelemetry() {
  if (!telemetryState) return;
  if (state.ws) {
    state.ws.close();
  }
  try {
    const wsUrl = `${location.origin.replace("http", "ws")}/api/ws/telemetry`;
    state.ws = new WebSocket(wsUrl);
    state.ws.onopen = () => setStatus("live", true);
    state.ws.onclose = () => setStatus("offline", false);
    state.ws.onerror = () => setStatus("error", false);
    state.ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        telemetryPayload.textContent = JSON.stringify(data, null, 2);
        applyTelemetryPayload(data);
      } catch (err) {
        telemetryPayload.textContent = String(evt.data || "");
      }
    };
  } catch (err) {
    setStatus("offline", false);
  }
}

async function refreshConfig() {
  const resp = await apiFetch("/api/config");
  const data = await readJson(resp);
  state.config = data || {};
  configOutput.textContent = JSON.stringify(data, null, 2);
  updateQuickControls();
}

async function applyConfigPatch() {
  let patch = {};
  try {
    patch = JSON.parse(configPatch.value || "{}");
  } catch (err) {
    configOutput.textContent = `Invalid JSON: ${err}`;
    return;
  }
  const resp = await apiFetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patch }),
  });
  const data = await readJson(resp);
  configOutput.textContent = JSON.stringify(data, null, 2);
  refreshConfigHistory();
}

if (saveTokenBtn) {
  saveTokenBtn.addEventListener("click", () => setToken(tokenInput.value));
}

if (settingsFilter) {
  settingsFilter.addEventListener("input", renderSettings);
}

if (settingsApply) {
  settingsApply.addEventListener("click", applySettings);
}

if (settingsReload) {
  settingsReload.addEventListener("click", refreshSettings);
}

if (pluginSettingsApply) {
  pluginSettingsApply.addEventListener("click", applyPluginSettings);
}

if (pluginShowAll) {
  pluginShowAll.addEventListener("change", () => {
    state.showAllPluginSettings = pluginShowAll.checked;
    localStorage.setItem("acPluginShowAll", state.showAllPluginSettings ? "true" : "false");
    renderPluginDetail();
  });
}

quickCaptureToggle?.addEventListener("change", async () => {
  if (quickCaptureToggle.checked) {
    await apiFetch("/api/run/start", { method: "POST" });
  } else {
    await apiFetch("/api/run/stop", { method: "POST" });
  }
  refreshStatus();
});

quickPause10?.addEventListener("click", async () => {
  await apiFetch("/api/run/pause", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ minutes: 10 }),
  });
  refreshStatus();
});

quickPause30?.addEventListener("click", async () => {
  await apiFetch("/api/run/pause", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ minutes: 30 }),
  });
  refreshStatus();
});

quickResume?.addEventListener("click", async () => {
  await apiFetch("/api/run/resume", { method: "POST" });
  refreshStatus();
});

quickPrivacyMode?.addEventListener("change", async () => {
  const baselineKey = "acPrivacyBaseline";
  if (quickPrivacyMode.checked) {
    const baseline = {
      egress_enabled: state.config.privacy?.egress?.enabled,
      cloud_enabled: state.config.privacy?.cloud?.enabled,
    };
    localStorage.setItem(baselineKey, JSON.stringify(baseline));
    await postConfigPatch({ privacy: { egress: { enabled: false }, cloud: { enabled: false } } });
  } else {
    let baseline = null;
    try {
      baseline = JSON.parse(localStorage.getItem(baselineKey) || "null");
    } catch (err) {
      baseline = null;
    }
    const egressEnabled = baseline && typeof baseline.egress_enabled === "boolean" ? baseline.egress_enabled : true;
    const cloudEnabled = baseline && typeof baseline.cloud_enabled === "boolean" ? baseline.cloud_enabled : false;
    await postConfigPatch({ privacy: { egress: { enabled: egressEnabled }, cloud: { enabled: cloudEnabled } } });
  }
  refreshConfig();
});

quickFidelityMode?.addEventListener("change", async () => {
  const modeKey = "acFidelityMode";
  const baselineKey = "acFidelityBaseline";
  if (quickFidelityMode.checked) {
    const video = state.config.capture?.video || {};
    const activity = video.activity || {};
    const baseline = {
      fps_target: video.fps_target,
      jpeg_quality: video.jpeg_quality,
      activity_active_fps: activity.active_fps,
      activity_idle_fps: activity.idle_fps,
      activity_active_bitrate: activity.active_bitrate_kbps,
      activity_idle_bitrate: activity.idle_bitrate_kbps,
      activity_active_quality: activity.active_jpeg_quality,
      activity_idle_quality: activity.idle_jpeg_quality,
      activity_preserve: activity.preserve_quality,
    };
    localStorage.setItem(baselineKey, JSON.stringify(baseline));
    localStorage.setItem(modeKey, "true");
    const backpressure = state.config.backpressure || {};
    const maxFps = backpressure.max_fps || video.fps_target || 30;
    const maxBitrate = backpressure.max_bitrate_kbps || activity.active_bitrate_kbps || 8000;
    const highQuality = Math.max(video.jpeg_quality || 90, 95);
    await postConfigPatch({
      capture: {
        video: {
          fps_target: maxFps,
          jpeg_quality: highQuality,
          activity: {
            active_fps: maxFps,
            idle_fps: maxFps,
            active_bitrate_kbps: maxBitrate,
            idle_bitrate_kbps: maxBitrate,
            active_jpeg_quality: highQuality,
            idle_jpeg_quality: highQuality,
            preserve_quality: true,
          },
        },
      },
    });
  } else {
    let baseline = null;
    try {
      baseline = JSON.parse(localStorage.getItem(baselineKey) || "null");
    } catch (err) {
      baseline = null;
    }
    localStorage.setItem(modeKey, "false");
    if (baseline) {
      await postConfigPatch({
        capture: {
          video: {
            fps_target: baseline.fps_target,
            jpeg_quality: baseline.jpeg_quality,
            activity: {
              active_fps: baseline.activity_active_fps,
              idle_fps: baseline.activity_idle_fps,
              active_bitrate_kbps: baseline.activity_active_bitrate,
              idle_bitrate_kbps: baseline.activity_idle_bitrate,
              active_jpeg_quality: baseline.activity_active_quality,
              idle_jpeg_quality: baseline.activity_idle_quality,
              preserve_quality: baseline.activity_preserve,
            },
          },
        },
      });
    }
  }
  refreshConfig();
});

bookmarkSave?.addEventListener("click", async () => {
  if (!bookmarkNote) return;
  const note = bookmarkNote.value.trim();
  if (!note) return;
  const tags = bookmarkTags?.value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
  if (bookmarkStatus) bookmarkStatus.textContent = "Saving...";
  await apiFetch("/api/bookmarks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note, tags }),
  });
  bookmarkNote.value = "";
  if (bookmarkTags) bookmarkTags.value = "";
  if (bookmarkStatus) bookmarkStatus.textContent = "Saved";
  refreshBookmarks();
});

refreshHealthBtn?.addEventListener("click", refreshHealth);
refreshStorageBtn?.addEventListener("click", refreshStorage);
refreshConfigHistoryBtn?.addEventListener("click", refreshConfigHistory);
configUndoLast?.addEventListener("click", async () => {
  if (configHistoryStatus) configHistoryStatus.textContent = "Reverting latest...";
  const resp = await apiFetch("/api/config/history?limit=1");
  const data = await readJson(resp);
  const latest = (data.changes || []).slice(-1)[0];
  if (!latest) {
    if (configHistoryStatus) configHistoryStatus.textContent = "No changes to undo";
    return;
  }
  await apiFetch("/api/config/revert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ change_id: latest.id }),
  });
  if (configHistoryStatus) configHistoryStatus.textContent = "Reverted";
  await refreshSettings();
  await refreshConfig();
  await refreshConfigHistory();
});

qs("runStart")?.addEventListener("click", async () => {
  await apiFetch("/api/run/start", { method: "POST" });
  refreshStatus();
});

qs("runStop")?.addEventListener("click", async () => {
  await apiFetch("/api/run/stop", { method: "POST" });
  refreshStatus();
});

qs("refreshAlerts")?.addEventListener("click", refreshAlerts);
qs("refreshTimeline")?.addEventListener("click", refreshTimeline);
qs("refreshPlugins")?.addEventListener("click", refreshPlugins);
qs("reloadPlugins")?.addEventListener("click", async () => {
  await apiFetch("/api/plugins/reload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  refreshPlugins();
});
pluginEnableAll?.addEventListener("click", async () => {
  const group = state.pluginGroups.find((item) => item.id === state.activePluginGroupId);
  if (group) {
    await toggleGroupEnabled(group, true);
  }
});
pluginDisableAll?.addEventListener("click", async () => {
  const group = state.pluginGroups.find((item) => item.id === state.activePluginGroupId);
  if (group) {
    await toggleGroupEnabled(group, false);
  }
});
qs("refreshKeys")?.addEventListener("click", refreshKeys);
qs("refreshEgress")?.addEventListener("click", refreshEgress);
qs("runQuery")?.addEventListener("click", runQuery);
qs("verifyLedger")?.addEventListener("click", () => runVerify("/api/verify/ledger"));
qs("verifyAnchors")?.addEventListener("click", () => runVerify("/api/verify/anchors"));
qs("verifyEvidence")?.addEventListener("click", () => runVerify("/api/verify/evidence"));
qs("applyConfig")?.addEventListener("click", applyConfigPatch);
refreshActivityTimelineBtn?.addEventListener("click", refreshActivityTimeline);
filterActivity?.addEventListener("change", () => {
  state.activityFilters.activity = filterActivity.checked;
  localStorage.setItem("acFilterActivity", state.activityFilters.activity ? "true" : "false");
  refreshActivityTimeline();
});
filterChanges?.addEventListener("change", () => {
  state.activityFilters.changes = filterChanges.checked;
  localStorage.setItem("acFilterChanges", state.activityFilters.changes ? "true" : "false");
  refreshActivityTimeline();
});
filterBookmarks?.addEventListener("change", () => {
  state.activityFilters.bookmarks = filterBookmarks.checked;
  localStorage.setItem("acFilterBookmarks", state.activityFilters.bookmarks ? "true" : "false");
  refreshActivityTimeline();
});

initNav();
if (filterActivity) filterActivity.checked = state.activityFilters.activity;
if (filterChanges) filterChanges.checked = state.activityFilters.changes;
if (filterBookmarks) filterBookmarks.checked = state.activityFilters.bookmarks;
refreshSettings();
refreshConfig().then(refreshPlugins);
refreshStatus();
refreshAlerts();
refreshTimeline();
refreshTimelineSummary();
refreshHealth();
refreshStorage();
refreshConfigHistory();
refreshBookmarks();
refreshActivityTimeline();
refreshKeys();
refreshEgress();
connectTelemetry();
