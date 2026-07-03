(function () {
  "use strict";

  const chatEl        = document.getElementById("chat");
  const statusDot     = document.getElementById("statusDot");
  const statusLabel   = document.getElementById("statusLabel");
  const micBtn        = document.getElementById("micBtn");
  const alwaysOnChk   = document.getElementById("alwaysOnChk");
  const textInput     = document.getElementById("textInput");
  const sendBtn       = document.getElementById("sendBtn");
  const clearBtn      = document.getElementById("clearBtn");
  const confirmOverlay = document.getElementById("confirmOverlay");
  const confirmPath   = document.getElementById("confirmPath");
  const confirmYes    = document.getElementById("confirmYes");
  const confirmNo     = document.getElementById("confirmNo");

  const settingsBtn      = document.getElementById("settingsBtn");
  const settingsOverlay  = document.getElementById("settingsOverlay");
  const providerSelect   = document.getElementById("providerSelect");
  const modelSelect      = document.getElementById("modelSelect");
  const refreshModelsBtn = document.getElementById("refreshModelsBtn");
  const keyHint          = document.getElementById("keyHint");
  const settingsSave     = document.getElementById("settingsSave");
  const settingsCancel   = document.getElementById("settingsCancel");

  const cpuFill  = document.getElementById("cpuFill");
  const cpuValue = document.getElementById("cpuValue");
  const ramFill  = document.getElementById("ramFill");
  const ramValue = document.getElementById("ramValue");

  const STATE_META = {
    idle:      { label: "ONLINE",     color: "#00ff88" },
    thinking:  { label: "PENSANDO",   color: "#00d4ff" },
    listening: { label: "ESCUCHANDO", color: "#00ff99" },
    speaking:  { label: "HABLANDO",   color: "#7777ff" },
  };

  let currentStreamBody = null;

  function scrollDown() {
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function makeMsg(tag, label) {
    const div = document.createElement("div");
    div.className = "msg msg-" + tag;
    const lab = document.createElement("span");
    lab.className = "msg-label";
    lab.textContent = label;
    const body = document.createElement("span");
    body.className = "msg-body";
    div.appendChild(lab);
    div.appendChild(body);
    chatEl.appendChild(div);
    scrollDown();
    return body;
  }

  window.jarvisWriteLine = function (tag, label, text) {
    const body = makeMsg(tag, label);
    body.textContent = text;
    scrollDown();
  };

  window.jarvisBeginJarvisMessage = function () {
    currentStreamBody = makeMsg("jarvis", "JARVIS");
  };

  window.jarvisAppendToken = function (chunk) {
    if (!currentStreamBody) currentStreamBody = makeMsg("jarvis", "JARVIS");
    currentStreamBody.textContent += chunk;
    scrollDown();
  };

  window.jarvisEndJarvisMessage = function () {
    currentStreamBody = null;
  };

  window.jarvisClearChat = function () {
    chatEl.innerHTML = "";
    window.jarvisWriteLine("jarvis", "JARVIS", "Sesión borrada. ¿En qué puedo asistirle?");
  };

  window.jarvisUpdateStats = function (cpu, ram) {
    cpuFill.style.width = cpu + "%";
    cpuFill.classList.toggle("high", cpu >= 85);
    cpuValue.textContent = Math.round(cpu) + "%";

    ramFill.style.width = ram + "%";
    ramFill.classList.toggle("high", ram >= 85);
    ramValue.textContent = Math.round(ram) + "%";
  };

  window.jarvisSetLevel = function (level) {
    if (window.JarvisOrb) window.JarvisOrb.setLevel(level);
  };

  window.jarvisSetState = function (state) {
    const meta = STATE_META[state] || STATE_META.idle;
    statusLabel.textContent = meta.label;
    statusLabel.style.color = meta.color;
    statusDot.style.background = meta.color;
    statusDot.style.boxShadow = `0 0 8px ${meta.color}, 0 0 16px ${meta.color}`;
    micBtn.classList.toggle("active", state === "listening");
    if (window.JarvisOrb) window.JarvisOrb.setState(state);
  };

  window.jarvisShowConfirm = function (path) {
    confirmPath.textContent = path;
    confirmOverlay.classList.add("show");
  };

  function hideConfirm() {
    confirmOverlay.classList.remove("show");
  }

  confirmYes.addEventListener("click", () => {
    hideConfirm();
    pywebview.api.confirm_response(true);
  });
  confirmNo.addEventListener("click", () => {
    hideConfirm();
    pywebview.api.confirm_response(false);
  });

  function trySend() {
    const text = textInput.value.trim();
    if (!text) return;
    textInput.value = "";
    pywebview.api.send_message(text);
  }

  sendBtn.addEventListener("click", trySend);
  textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") trySend();
  });
  textInput.focus();

  micBtn.addEventListener("click", () => pywebview.api.toggle_mic());
  alwaysOnChk.addEventListener("change", () =>
    pywebview.api.toggle_always_on(alwaysOnChk.checked)
  );
  clearBtn.addEventListener("click", () => pywebview.api.clear_chat());

  // ── Configuración de proveedor de IA ─────────────────────────────────

  let providersCache = [];

  function populateModelSelect(models, selected) {
    modelSelect.innerHTML = "";
    models.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      if (m === selected) opt.selected = true;
      modelSelect.appendChild(opt);
    });
  }

  function updateKeyHint() {
    const p = providersCache.find((p) => p.id === providerSelect.value);
    keyHint.textContent = p && !p.has_key
      ? "⚠ Falta la API key para este proveedor (revisa tu archivo .env)"
      : "";
  }

  async function openSettings() {
    providersCache = await pywebview.api.get_providers();
    const cfg = await pywebview.api.get_provider_config();

    providerSelect.innerHTML = "";
    providersCache.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.label + (p.has_key ? "" : " (sin key)");
      if (p.id === cfg.provider) opt.selected = true;
      providerSelect.appendChild(opt);
    });

    const models = await pywebview.api.get_provider_models(cfg.provider);
    populateModelSelect(models, cfg.model);
    updateKeyHint();
    settingsOverlay.classList.add("show");
  }

  function closeSettings() {
    settingsOverlay.classList.remove("show");
  }

  settingsBtn.addEventListener("click", openSettings);
  settingsCancel.addEventListener("click", closeSettings);

  providerSelect.addEventListener("change", async () => {
    updateKeyHint();
    const models = await pywebview.api.get_provider_models(providerSelect.value);
    populateModelSelect(models, models[0]);
  });

  refreshModelsBtn.addEventListener("click", async () => {
    const models = await pywebview.api.get_provider_models(providerSelect.value);
    const current = modelSelect.value;
    populateModelSelect(models, models.includes(current) ? current : models[0]);
  });

  settingsSave.addEventListener("click", () => {
    pywebview.api.set_provider(providerSelect.value, modelSelect.value);
    closeSettings();
  });

  if (window.JarvisOrb) {
    window.JarvisOrb.init(document.getElementById("orbStage"));
  }
})();
