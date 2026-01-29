const state = {
  token: localStorage.getItem("acToken") || "",
  ws: null,
  settingsFields: [],
  settingsDirty: {},
  pluginDirty: {},
  activePluginId: null,
};

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
const pluginSettingsStatus = qs("pluginSettingsStatus");

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
  statusRunId.textContent = data.run_id || "—";
  statusLedger.textContent = data.ledger_head || "—";
  statusCapture.textContent = data.capture_active ? "active" : "idle";
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

async function refreshPlugins() {
  const resp = await apiFetch("/api/plugins");
  const data = await readJson(resp);
  pluginsList.innerHTML = "";
  const plugins = data.plugins || [];
  if (!plugins.length) {
    pluginsList.textContent = "No plugins loaded";
    return;
  }
  plugins.forEach((plugin) => {
    const row = document.createElement("div");
    row.className = "table-row";
    const name = document.createElement("span");
    name.textContent = plugin.plugin_id;
    const enabled = document.createElement("span");
    enabled.innerHTML = plugin.enabled ? formatBadge("enabled") : formatBadge("disabled", "off");
    const hash = document.createElement("span");
    hash.innerHTML = plugin.hash_ok ? formatBadge("hash ok") : formatBadge("hash drift", "warn");
    const actions = document.createElement("div");
    actions.className = "actions";
    const toggle = document.createElement("button");
    toggle.className = "ghost";
    toggle.textContent = plugin.enabled ? "Disable" : "Enable";
    toggle.onclick = async () => {
      const endpoint = plugin.enabled ? "disable" : "enable";
      await apiFetch(`/api/plugins/${plugin.plugin_id}/${endpoint}`, { method: "POST" });
      refreshPlugins();
    };
    const settingsBtn = document.createElement("button");
    settingsBtn.textContent = "Configure";
    settingsBtn.onclick = () => loadPluginSettings(plugin.plugin_id);
    actions.appendChild(toggle);
    actions.appendChild(settingsBtn);
    row.appendChild(name);
    row.appendChild(enabled);
    row.appendChild(hash);
    row.appendChild(actions);
    pluginsList.appendChild(row);
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
  label.textContent = field.path || "";
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
  return fields.filter((field) => (field.path || "").toLowerCase().includes(q));
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
  const fields = filterFields(state.settingsFields, query);
  settingsList.innerHTML = "";
  if (!fields.length) {
    settingsList.textContent = "No settings found";
    return;
  }
  const fragment = document.createDocumentFragment();
  fields.forEach((field) => {
    renderField(fragment, field, state.settingsDirty);
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
  pluginSettingsTitle.textContent = `Plugin Settings · ${pluginId}`;
  pluginSettingsStatus.textContent = "";
  const fields = flattenSettings(settings);
  pluginSettingsList.innerHTML = "";
  if (!fields.length) {
    pluginSettingsList.textContent = "No settings exposed";
    return;
  }
  const fragment = document.createDocumentFragment();
  fields.forEach((field) => {
    renderField(fragment, field, state.pluginDirty);
  });
  pluginSettingsList.appendChild(fragment);
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
}

async function connectTelemetry() {
  if (!telemetryState) return;
  if (state.ws) {
    state.ws.close();
  }
  try {
    const wsUrl = `${location.origin.replace("http", "ws")}/api/telemetry/ws`;
    state.ws = new WebSocket(wsUrl);
    state.ws.onopen = () => setStatus("live", true);
    state.ws.onclose = () => setStatus("offline", false);
    state.ws.onerror = () => setStatus("error", false);
    state.ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        telemetryPayload.textContent = JSON.stringify(data, null, 2);
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
  configOutput.textContent = JSON.stringify(data, null, 2);
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
qs("refreshKeys")?.addEventListener("click", refreshKeys);
qs("refreshEgress")?.addEventListener("click", refreshEgress);
qs("runQuery")?.addEventListener("click", runQuery);
qs("verifyLedger")?.addEventListener("click", () => runVerify("/api/verify/ledger"));
qs("verifyAnchors")?.addEventListener("click", () => runVerify("/api/verify/anchors"));
qs("verifyEvidence")?.addEventListener("click", () => runVerify("/api/verify/evidence"));
qs("applyConfig")?.addEventListener("click", applyConfigPatch);

initNav();
refreshSettings();
refreshPlugins();
refreshStatus();
refreshAlerts();
refreshTimeline();
refreshKeys();
refreshEgress();
refreshConfig();
connectTelemetry();
