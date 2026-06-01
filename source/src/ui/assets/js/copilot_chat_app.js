(() => {
    const state = {
        labels: {},
        bridge: null,
        models: [],
        sessions: [],
        usage: {},
        references: [],
        attachments: [],
        maxAttachments: 4,
        maxImageBytes: 4 * 1024 * 1024,
        streamingEl: null,
        thinkingEl: null,
        workEl: null,
        currentTurn: null,
        loading: false,
        selectedModel: "",
        selectedEffort: "auto",
        supportedEfforts: [],
        historyCollapsed: false,
        modelQuery: "",
        toolCount: 0,
        completedTools: 0,
        activityInterval: null,
        activityStartedAt: 0,
        activityPhase: "",
        activityDetail: "",
        authReady: false,
        thinkingText: "",
        thinkingStartedAt: 0,
        pasteBusy: false,
        recentAttachmentKeys: new Set(),
        supportsVision: true,
        usagePanelOpen: false,
        usageUpdating: false,
        accountPickerOpen: false,
        accountPicker: {},
        accountSwitchBusy: false,
    };

    const $ = (id) => document.getElementById(id);
    const label = (key, fallback = "") => state.labels[key] || fallback || "";
    const escapeHtml = (value) => String(value || "").replace(/[&<>"]/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
    }[ch]));

    function writeDebug(payload) {
        const log = $("debugLog");
        if (!log) return;
        log.textContent = JSON.stringify(payload || {}, null, 2);
    }

    function callBridge(method, payload) {
        if (!state.bridge || typeof state.bridge[method] !== "function") return;
        try {
            state.bridge[method](typeof payload === "string" ? payload : JSON.stringify(payload || {}));
        } catch (err) {
            writeDebug({ bridgeError: String(err), method });
        }
    }

    async function callBridgeResult(method, ...args) {
        if (!state.bridge || typeof state.bridge[method] !== "function") return null;
        try {
            let result = state.bridge[method](...args);
            if (result && typeof result.then === "function") {
                result = await result;
            }
            return result;
        } catch (err) {
            writeDebug({ bridgeResultError: String(err), method });
            return null;
        }
    }

    function renderStaticLabels() {
        document.querySelectorAll("[data-label]").forEach((node) => {
            const key = node.getAttribute("data-label");
            node.textContent = label(key, node.textContent);
            node.setAttribute("title", label(key, ""));
            node.setAttribute("aria-label", label(key, ""));
        });
        document.querySelectorAll("[data-title]").forEach((node) => {
            const key = node.getAttribute("data-title");
            node.setAttribute("title", label(key, ""));
            node.setAttribute("aria-label", label(key, ""));
        });
        document.querySelectorAll("[data-placeholder]").forEach((node) => {
            node.setAttribute("placeholder", label(node.getAttribute("data-placeholder"), ""));
        });
        renderUsage();
        renderModels();
        renderEfforts(state.supportedEfforts);
    }

    function markdown(text) {
        if (window.marked && typeof window.marked.parse === "function") {
            return window.marked.parse(String(text || ""));
        }
        return escapeHtml(text).replace(/\n/g, "<br>");
    }

    function enhanceCodeBlocks(root) {
        root.querySelectorAll("pre code").forEach((code) => {
            try {
                if (window.hljs) window.hljs.highlightElement(code);
            } catch (_) {}
            const pre = code.closest("pre");
            if (!pre || pre.dataset.enhanced === "true") return;
            pre.dataset.enhanced = "true";

            const actions = document.createElement("div");
            actions.className = "code-actions";

            const copy = document.createElement("button");
            copy.className = "text-command";
            copy.type = "button";
            copy.textContent = label("copy", "");
            copy.addEventListener("click", () => {
                if (navigator.clipboard) navigator.clipboard.writeText(code.textContent || "");
            });

            const insert = document.createElement("button");
            insert.className = "text-command";
            insert.type = "button";
            insert.textContent = label("insert", "");
            insert.addEventListener("click", () => callBridge("insertCode", code.textContent || ""));

            actions.append(copy, insert);
            pre.parentNode.insertBefore(actions, pre);
        });
    }

    function scrollToBottom() {
        const messages = $("messages");
        if (messages) messages.scrollTop = messages.scrollHeight;
    }

    function hideWelcome() {
        const welcome = $("welcome");
        if (welcome) {
            welcome.hidden = true;
            welcome.style.display = "none";
        }
    }

    function showWelcome() {
        const welcome = $("welcome");
        if (welcome) {
            welcome.hidden = false;
            welcome.style.display = "";
        }
    }

    function ensureActivityLine() {
        let el = $("activityLine");
        if (el) return el;
        el = document.createElement("div");
        el.id = "activityLine";
        el.className = "activity-line";
        el.hidden = true;
        $("messages").appendChild(el);
        return el;
    }

    function updateActivityLine() {
        const el = $("activityLine");
        if (!el || el.hidden) return;
        const secs = Math.max(0, Math.floor((Date.now() - (state.activityStartedAt || Date.now())) / 1000));
        const phase = state.activityPhase || label("waiting_response", "");
        const detail = state.activityDetail ? ` · ${state.activityDetail}` : "";
        el.innerHTML = `<span class="activity-dot" aria-hidden="true"></span><span>${escapeHtml(phase)}${escapeHtml(detail)} <span class="activity-elapsed">${secs}s</span></span>`;
        scrollToBottom();
    }

    function startActivityTimer() {
        if (state.activityInterval) return;
        state.activityStartedAt = Date.now();
        ensureActivityLine().hidden = false;
        updateActivityLine();
        state.activityInterval = window.setInterval(updateActivityLine, 1000);
    }

    function stopActivityTimer() {
        if (state.activityInterval) {
            window.clearInterval(state.activityInterval);
            state.activityInterval = null;
        }
        const el = $("activityLine");
        if (el) {
            el.hidden = true;
            el.style.display = "none";
        }
    }

    function setActivity(payload) {
        payload = payload || {};
        if (payload.phase) state.activityPhase = payload.phase;
        if (Object.prototype.hasOwnProperty.call(payload, "detail")) {
            state.activityDetail = payload.detail || "";
        }
        state.activityStartedAt = Date.now();
        hideWelcome();
        startActivityTimer();
        updateActivityLine();
    }

    function summarizeThinkingPreview(text) {
        const lines = String(text || "").trim().split(/\n+/).filter(Boolean);
        if (!lines.length) return "";
        let line = lines[lines.length - 1].trim();
        if (line.length > 120) line = `${line.slice(0, 117)}...`;
        return line;
    }

    function setAuthGate(payload) {
        payload = payload || {};
        const status = payload.status || "locked";
        const chatMain = document.querySelector(".chat-main");
        const gate = $("authGate");
        const authBtn = $("authBtn");
        const logoutBtn = $("logoutBtn");
        const switchAccountBtn = $("switchAccountBtn");
        const badge = $("authGateBadge");
        const title = $("authGateTitle");
        const message = $("authGateMessage");
        const code = $("authGateCode");
        const action = $("authGateAction");

        state.authReady = status === "ready";

        if (authBtn) {
            authBtn.classList.toggle("ready", state.authReady);
            authBtn.disabled = !state.authReady && status === "signing_in";
        }
        if (logoutBtn) logoutBtn.hidden = !state.authReady;
        if (switchAccountBtn) switchAccountBtn.hidden = !state.authReady;

        if (chatMain) chatMain.classList.toggle("chat-locked", !state.authReady);

        if (gate) {
            gate.hidden = state.authReady;
            if (badge) badge.className = `auth-gate-badge ${status}`;
            if (title) title.textContent = payload.title || "";
            if (message) message.textContent = payload.message || "";
            if (code) {
                if (payload.code) {
                    code.hidden = false;
                    code.textContent = payload.code;
                } else {
                    code.hidden = true;
                    code.textContent = "";
                }
            }
            if (action) {
                if (payload.action_label) {
                    action.hidden = false;
                    action.textContent = payload.action_label;
                    action.dataset.action = payload.action || "sign_in";
                } else {
                    action.hidden = true;
                    action.dataset.action = "";
                }
            }
        }

        const input = $("composerInput");
        if (input) {
            input.disabled = !state.authReady;
            input.placeholder = state.authReady
                ? label("input_placeholder", "")
                : label("chat_locked_placeholder", label("input_placeholder", ""));
        }
    }

    function setWorking(working) {
        const active = !!working;
        state.loading = active;
        const app = $("app");
        if (app) app.classList.toggle("working", active);
        const sendBtn = $("sendBtn");
        const cancelBtn = $("cancelBtn");
        if (sendBtn) sendBtn.hidden = active;
        if (cancelBtn) cancelBtn.hidden = !active;
        if (!active) stopActivityTimer();
    }

    const REF_TOKEN_RE = /#(?:tab|block)(?::[^\s#,\.!\?]+|\d+)/gi;

    function refKind(token) {
        const lower = String(token || "").toLowerCase();
        if (lower.startsWith("#tab")) return "tab";
        if (lower.startsWith("#block")) return "block";
        return "ref";
    }

    function formatMessageHtml(content) {
        const placeholders = [];
        const raw = String(content || "");
        const withTokens = raw.replace(REF_TOKEN_RE, (match) => {
            const key = `__REF_${placeholders.length}__`;
            placeholders.push(match);
            return key;
        });
        let html = markdown(withTokens);
        placeholders.forEach((token, index) => {
            const kind = refKind(token);
            const pill = `<span class="ref-pill ref-pill-${kind}" data-ref="${escapeHtml(token)}" title="${escapeHtml(token)}">${escapeHtml(token)}</span>`;
            html = html.split(`__REF_${index}__`).join(pill);
        });
        return html;
    }

    function renderAttachedReferences(container, references) {
        if (!container || !Array.isArray(references) || !references.length) return;
        const wrap = document.createElement("div");
        wrap.className = "message-refs";
        references.forEach((ref) => {
            const token = ref.reference || ref.insert_text || "";
            const kind = ref.type || refKind(token);
            const pill = document.createElement("button");
            pill.type = "button";
            pill.className = `ref-pill ref-pill-attached ref-pill-${kind}`;
            pill.textContent = token || ref.label || "";
            pill.title = ref.label || ref.detail || token;
            pill.addEventListener("click", () => callBridge("openReference", token));
            wrap.appendChild(pill);
        });
        container.appendChild(wrap);
    }

    function addMessage(role, content, id, references, attachments) {
        hideWelcome();
        const row = document.createElement("article");
        row.className = `message-row ${role || "assistant"}`;
        row.dataset.messageId = id || `${Date.now()}`;

        const stack = document.createElement("div");
        stack.className = "message-stack";

        if (role === "user") {
            renderMessageAttachments(stack, attachments);
            renderAttachedReferences(stack, references);
        }

        const bubble = document.createElement("div");
        bubble.className = "message";
        bubble.innerHTML = formatMessageHtml(content || "");
        stack.appendChild(bubble);
        row.appendChild(stack);

        $("messages").appendChild(row);
        enhanceCodeBlocks(row);
        row.querySelectorAll(".ref-pill[data-ref]").forEach((pill) => {
            pill.addEventListener("click", () => callBridge("openReference", pill.dataset.ref || ""));
        });
        scrollToBottom();
        return row;
    }

    function clearMessages() {
        const messages = $("messages");
        if (messages) {
            messages.querySelectorAll(".message-row,.thinking-block,.work-block,.status-line,#activityLine").forEach((node) => node.remove());
        }
        const welcome = $("welcome");
        if (welcome) welcome.hidden = false;
        showWelcome();
        stopActivityTimer();
        state.streamingEl = null;
        state.thinkingEl = null;
        state.workEl = null;
        state.toolCount = 0;
        state.completedTools = 0;
        clearAttachments();
        setWorking(false);
    }

    function showThinking() {
        hideWelcome();
        setActivity({ phase: label("thinking", ""), detail: label("waiting_response", "") });
        if ($("thinkingStatus")) {
            setWorking(true);
            return;
        }
        const line = document.createElement("div");
        line.className = "status-line thinking-status";
        line.id = "thinkingStatus";
        line.innerHTML = `<span>${escapeHtml(label("waiting_response", ""))}</span><span class="thinking-dots" aria-hidden="true"></span>`;
        $("messages").appendChild(line);
        setWorking(true);
        scrollToBottom();
    }

    function hideThinking() {
        const line = $("thinkingStatus");
        if (line) line.remove();
    }

    function startThinkingBlock() {
        hideWelcome();
        if (state.thinkingEl) return;
        const block = document.createElement("details");
        block.className = "thinking-block live";
        block.setAttribute("open", "");
        block.innerHTML = `<summary><span>${escapeHtml(label("thinking", ""))}</span><span class="thinking-summary-status">${escapeHtml(label("thinking_live", label("waiting_response", "")))}</span></summary><div class="thinking-block-content"></div>`;
        $("messages").appendChild(block);
        state.thinkingEl = block;
        state.thinkingText = "";
        state.thinkingStartedAt = Date.now();
        setActivity({ phase: label("thinking", ""), detail: label("thinking_live", "") });
        scrollToBottom();
    }

    function appendThinking(text) {
        startThinkingBlock();
        const chunk = String(text || "");
        if (!chunk) return;
        state.thinkingText += chunk;
        const content = state.thinkingEl && state.thinkingEl.querySelector(".thinking-block-content");
        if (content) content.textContent = state.thinkingText;
        const preview = summarizeThinkingPreview(state.thinkingText);
        const status = state.thinkingEl && state.thinkingEl.querySelector(".thinking-summary-status");
        if (status) status.textContent = preview || label("thinking_live", "");
        setActivity({ phase: label("thinking", ""), detail: preview || label("thinking_live", "") });
        scrollToBottom();
    }

    function endThinkingBlock() {
        if (!state.thinkingEl) return;
        state.thinkingEl.classList.remove("live");
        state.thinkingEl.classList.add("complete");
        const secs = Math.max(1, Math.round((Date.now() - (state.thinkingStartedAt || Date.now())) / 1000));
        const status = state.thinkingEl.querySelector(".thinking-summary-status");
        if (status) {
            status.textContent = label("thinking_complete", "").replace("{seconds}", String(secs));
        }
        state.thinkingEl = null;
        state.thinkingText = "";
        state.thinkingStartedAt = 0;
    }

    function startStreaming() {
        hideThinking();
        endThinkingBlock();
        const row = addMessage("assistant", "", `stream-${Date.now()}`);
        state.streamingEl = row.querySelector(".message");
    }

    function streamChunk(chunk) {
        if (!state.streamingEl) startStreaming();
        const current = state.streamingEl.dataset.raw || "";
        const next = current + String(chunk || "");
        state.streamingEl.dataset.raw = next;
        state.streamingEl.innerHTML = formatMessageHtml(next);
        enhanceCodeBlocks(state.streamingEl);
        scrollToBottom();
    }

    function endStreaming() {
        state.streamingEl = null;
    }

    function ensureWorkBlock() {
        hideWelcome();
        if (state.workEl) return state.workEl;
        const block = document.createElement("details");
        block.className = "work-block";
        block.innerHTML = `<summary><span>${escapeHtml(label("work_title", label("thinking", "")))}</span><span class="work-status">${escapeHtml(label("work_running", label("tool_running", "")))}</span></summary><div class="work-list"></div>`;
        $("messages").appendChild(block);
        state.workEl = block;
        return block;
    }

    function updateWorkStatus(done) {
        if (!state.workEl) return;
        const status = state.workEl.querySelector(".work-status");
        if (!status) return;
        status.textContent = done ? label("work_complete", label("tool_ok", "")) : label("work_running", label("tool_running", ""));
    }

    function addToolUse(toolName, argSummary, toolId) {
        const block = ensureWorkBlock();
        state.toolCount += 1;
        updateWorkStatus(false);
        setActivity({
            phase: label("activity_running_tool", "Running {tool}...").replace("{tool}", toolName),
            detail: argSummary || "",
        });

        const row = document.createElement("div");
        row.className = "tool-row running";
        row.dataset.toolName = toolName;
        row.dataset.toolId = toolId || `${toolName}-${state.toolCount}`;
        row.innerHTML = `<div class="tool-row-head"><span>${escapeHtml(toolName)}</span><span>${escapeHtml(label("tool_running", ""))}</span></div><div class="tool-row-detail">${escapeHtml(argSummary || "")}</div>`;
        block.querySelector(".work-list").appendChild(row);
        scrollToBottom();
        return row.dataset.toolId;
    }

    function updateToolStatus(toolName, _status, isError, resultPreview, toolId) {
        const rows = Array.from(document.querySelectorAll(".tool-row"));
        let row = toolId ? rows.find((node) => node.dataset.toolId === toolId) : null;
        if (!row) {
            row = rows.find((node) => node.dataset.toolName === toolName && node.classList.contains("running"));
        }
        if (!row) return;
        row.classList.remove("running");
        row.classList.toggle("error", !!isError);
        const statusEl = row.querySelector(".tool-row-head span:last-child");
        if (statusEl) statusEl.textContent = isError ? label("tool_error", "") : label("tool_ok", "");
        const content = row.querySelector(".tool-row-detail");
        if (content && resultPreview) content.textContent = resultPreview;
        state.completedTools = Math.min(state.toolCount, state.completedTools + 1);
        updateWorkStatus(state.toolCount > 0 && state.completedTools >= state.toolCount);
        scrollToBottom();
    }

    function completeAllRunningTools() {
        const running = Array.from(document.querySelectorAll(".tool-row.running"));
        running.forEach((row) => {
            row.classList.remove("running");
            const statusEl = row.querySelector(".tool-row-head span:last-child");
            if (statusEl) statusEl.textContent = label("tool_ok", "");
        });
        if (running.length) {
            state.completedTools = state.toolCount;
            updateWorkStatus(true);
        }
    }

    function endToolGroup() {
        completeAllRunningTools();
    }

    function formatMultiplier(multiplier) {
        if (multiplier == null || multiplier === "") return "";
        const value = Number(multiplier);
        if (!Number.isFinite(value)) return "";
        return `${value.toLocaleString()}x`;
    }

    function selectedModel() {
        return state.models.find((model) => String(model.id) === String(state.selectedModel)) || state.models[0] || null;
    }

    function renderModels() {
        const current = selectedModel();
        const labelEl = $("modelPickerLabel");
        if (labelEl) labelEl.textContent = current ? (current.name || current.id) : "";
        renderModelList();
    }

    function renderModelList() {
        const list = $("modelList");
        if (!list) return;
        const query = String(state.modelQuery || "").trim().toLowerCase();
        list.innerHTML = "";

        const models = state.models.filter((model) => {
            const haystack = `${model.id || ""} ${model.name || ""}`.toLowerCase();
            return !query || haystack.includes(query);
        });

        if (!models.length) {
            const empty = document.createElement("div");
            empty.className = "model-empty";
            empty.textContent = label("no_models_found", "");
            list.appendChild(empty);
            return;
        }

        models.forEach((model) => {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "model-option";
            item.dataset.modelId = model.id || "";
            item.classList.toggle("selected", String(model.id) === String(state.selectedModel));

            const effort = model.default_reasoning_effort || (Array.isArray(model.supported_reasoning_efforts) && model.supported_reasoning_efforts[0]) || "";
            const meta = [effort ? label(`effort_${effort}`, effort) : "", formatMultiplier(model.multiplier)].filter(Boolean).join(" - ");
            item.innerHTML = `<span class="model-option-name">${escapeHtml(model.name || model.id)}</span><span class="model-option-meta">${escapeHtml(meta)}</span>`;
            item.addEventListener("click", () => {
                state.selectedModel = model.id || "";
                closeModelPicker();
                renderModels();
                callBridge("selectModel", state.selectedModel);
            });
            list.appendChild(item);
        });
    }

    function openModelPicker() {
        const menu = $("modelPickerMenu");
        const btn = $("modelPickerBtn");
        if (!menu || !btn) return;
        menu.hidden = false;
        renderModelList();
        const rect = btn.getBoundingClientRect();
        const menuHeight = Math.min(340, window.innerHeight * 0.45);
        menu.style.width = "320px";
        menu.style.maxWidth = `${Math.max(240, window.innerWidth - 24)}px`;
        menu.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - 332))}px`;
        menu.style.bottom = `${Math.max(12, window.innerHeight - rect.top + 8)}px`;
        menu.style.top = "auto";
        const search = $("modelSearch");
        if (search) {
            search.value = state.modelQuery;
            setTimeout(() => search.focus(), 0);
        }
    }

    function closeModelPicker() {
        const menu = $("modelPickerMenu");
        if (menu) menu.hidden = true;
    }

    function renderEfforts(supported) {
        const select = $("effortSelect");
        if (!select) return;
        const efforts = ["auto", "low", "medium", "high", "xhigh"];
        const supportedList = Array.isArray(supported) ? supported : [];
        state.supportedEfforts = supportedList;
        select.innerHTML = "";
        efforts.forEach((effort) => {
            const option = document.createElement("option");
            option.value = effort;
            option.textContent = label(`effort_${effort}`, effort);
            option.disabled = effort !== "auto" && supportedList.length > 0 && !supportedList.includes(effort);
            select.appendChild(option);
        });
        select.value = state.selectedEffort || "auto";
    }

    function usageSummaryText(usage) {
        if (usage.available && usage.used != null && usage.total != null) {
            return label("usage_format", "{used}/{total}").replace("{used}", usage.used).replace("{total}", usage.total);
        }
        if (usage.available && usage.used != null) {
            return label("usage_used_format", "{used}").replace("{used}", usage.used);
        }
        if (usage.available && usage.remaining_percentage != null) {
            return label("usage_remaining_format", "{remaining}%").replace("{remaining}", usage.remaining_percentage);
        }
        return label("usage_unavailable", "");
    }

    function setUsagePanelOpen(open) {
        state.usagePanelOpen = !!open;
        const panel = $("usagePanel");
        const button = $("usageStatusBtn");
        if (panel) panel.hidden = !state.usagePanelOpen;
        if (button) button.setAttribute("aria-expanded", state.usagePanelOpen ? "true" : "false");
        if (state.usagePanelOpen) setAccountPickerOpen(false);
    }

    function setAccountPickerOpen(open) {
        state.accountPickerOpen = !!open;
        const panel = $("accountPicker");
        if (panel) panel.hidden = !state.accountPickerOpen;
    }

    function renderAccountPicker() {
        const list = $("accountPickerList");
        if (!list) return;
        const data = state.accountPicker || {};
        const current = data.current || "";
        list.innerHTML = "";
        const accounts = Array.isArray(data.accounts) ? data.accounts : [];
        if (!accounts.length) {
            const empty = document.createElement("div");
            empty.className = "account-picker-item-meta";
            empty.style.padding = "8px 10px";
            empty.textContent = label("account_picker_empty", "No saved accounts yet.");
            list.appendChild(empty);
            return;
        }
        accounts.forEach((account) => {
            const username = account.username || "";
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "account-picker-item";
            if (username === current) btn.classList.add("current");
            const ready = !!account.ready;
            const meta = ready
                ? label("account_ready", "Ready to switch")
                : label("account_needs_login", "Sign in required");
            let badge = "";
            if (username === current) {
                badge = `<span class="account-picker-item-badge">${escapeHtml(label("account_current", "Current"))}</span>`;
            } else if (ready) {
                badge = `<span class="account-picker-item-badge">${escapeHtml(label("account_ready_short", "Ready"))}</span>`;
            }
            btn.innerHTML = `<div class="account-picker-item-main"><div class="account-picker-item-name">@${escapeHtml(username)}</div><div class="account-picker-item-meta">${escapeHtml(meta)}</div></div>${badge}`;
            btn.addEventListener("click", () => {
                setAccountPickerOpen(false);
                setAccountSwitchBusy({
                    visible: true,
                    username,
                    kind: "switch",
                });
                callBridge("selectAccount", { username });
            });
            list.appendChild(btn);
        });
    }

    function openAccountPicker(payload) {
        state.accountPicker = payload || {};
        renderAccountPicker();
        setUsagePanelOpen(false);
        setAccountPickerOpen(true);
    }

    function setAccountSwitchBusy(payload) {
        payload = payload || {};
        const overlay = $("accountSwitchOverlay");
        const title = $("accountSwitchTitle");
        const message = $("accountSwitchMessage");
        const visible = !!payload.visible;
        state.accountSwitchBusy = visible;
        if (overlay) overlay.hidden = !visible;
        if (!visible) return;
        const username = payload.username || "";
        const kind = payload.kind || "switch";
        if (title) {
            title.textContent = payload.title || label(
                kind === "add" ? "account_switch_add_title" : "account_switch_title",
                kind === "add" ? "Adding account" : "Switching account",
            );
        }
        if (message) {
            let text = payload.message || "";
            if (!text && kind === "add") {
                text = label("account_switch_add_message", "Starting GitHub sign in...");
            } else if (!text && username) {
                text = label("account_switch_message", "Connecting to @{username}...")
                    .replace("{username}", username);
            }
            message.textContent = text;
        }
        setAccountPickerOpen(false);
        setUsagePanelOpen(false);
    }

    function runtimePhaseLabel(phase) {
        if (!phase) return "";
        return label(`runtime_update_${phase}`, label("usage_panel_updating", ""));
    }

    function runtimePhasesForUpdate(cli) {
        const phases = ["checking"];
        if (cli.cli_update_available) {
            phases.push("downloading_cli", "installing_cli");
        }
        if (cli.sdk_update_available) {
            phases.push("downloading_sdk", "installing_sdk");
        }
        phases.push("complete");
        return phases;
    }

    function renderUpdateProgress(cli, updating) {
        const box = $("usagePanelUpdateProgress");
        if (!box) return;
        const phase = cli.update_phase || "";
        if (!updating || !phase) {
            box.hidden = true;
            box.innerHTML = "";
            return;
        }
        const phases = runtimePhasesForUpdate(cli);
        const activeIndex = Math.max(0, phases.indexOf(phase));
        box.hidden = false;
        box.innerHTML = phases.map((step, index) => {
            const done = index < activeIndex || (phase === "complete" && step !== "complete");
            const current = step === phase;
            const cls = done ? "done" : current ? "active" : "pending";
            return `<div class="usage-panel-progress-step ${cls}">${escapeHtml(runtimePhaseLabel(step))}</div>`;
        }).join("");
    }

    function renderUsagePanel() {
        const usage = state.usage || {};
        const cli = usage.cli || {};
        const sdk = usage.sdk || {};
        const title = $("usagePanelTitle");
        const planHint = $("usagePanelPlanHint");
        const quota = $("usagePanelQuota");
        const reset = $("usagePanelReset");
        const cliRow = $("usagePanelCli");
        const sdkRow = $("usagePanelSdk");
        const updateSection = $("usagePanelUpdateSection");
        const updateBtn = $("usagePanelUpdateBtn");
        const updateStatus = $("usagePanelUpdateStatus");

        if (title) {
            title.textContent = usage.username
                ? label("usage_panel_title_user", "GitHub Copilot").replace("{username}", usage.username)
                : label("usage_panel_title", "GitHub Copilot");
        }
        if (planHint) {
            planHint.textContent = usage.available
                ? label("usage_panel_plan_included", "")
                : label("usage_panel_plan_unknown", "");
        }
        if (quota) quota.textContent = usageSummaryText(usage);
        if (reset) {
            reset.textContent = usage.reset_date
                ? label("usage_panel_reset", "").replace("{reset_date}", usage.reset_date)
                : "";
        }
        if (cliRow) {
            const version = cli.version || label("usage_panel_not_installed", "Not installed");
            const source = cli.source_label || cli.source || "";
            cliRow.innerHTML = `<span>${escapeHtml(label("usage_panel_cli", "CLI"))}</span><strong>${escapeHtml(version)}${source ? ` · ${escapeHtml(source)}` : ""}</strong>`;
        }
        if (sdkRow) {
            const version = sdk.version || cli.sdk_version || label("usage_unavailable", "");
            const latest = cli.latest_sdk_version || "";
            const latestHint = latest && latest !== version ? ` · latest ${latest}` : "";
            sdkRow.innerHTML = `<span>${escapeHtml(label("usage_panel_sdk", "SDK"))}</span><strong>${escapeHtml(version)}${escapeHtml(latestHint)}</strong>`;
        }
        if (updateSection && updateBtn && updateStatus) {
            const hasUpdate = !!(cli.cli_update_available || cli.sdk_update_available);
            const showUpdate = !!(
                (hasUpdate && cli.can_update)
                || state.usageUpdating
                || cli.update_error
                || cli.restart_required
            );
            updateSection.hidden = !showUpdate;
            updateBtn.hidden = !hasUpdate || state.usageUpdating || cli.restart_required;
            updateBtn.textContent = label("usage_panel_update_runtime", label("usage_panel_update", "Update"));
            updateBtn.disabled = state.usageUpdating || !hasUpdate || !cli.can_update;
            renderUpdateProgress(cli, state.usageUpdating);
            if (cli.restart_required) {
                updateStatus.textContent = label("usage_panel_restart_required", "");
            } else if (cli.update_error) {
                updateStatus.textContent = cli.update_error;
            } else if (state.usageUpdating) {
                updateStatus.textContent = runtimePhaseLabel(cli.update_phase) || label("usage_panel_updating", "Updating...");
            } else if (hasUpdate) {
                const parts = [];
                if (cli.version && cli.latest_version && cli.cli_update_available) {
                    parts.push(`CLI ${cli.version} → ${cli.latest_version}`);
                }
                if (cli.sdk_version && cli.latest_sdk_version && cli.sdk_update_available) {
                    parts.push(`SDK ${cli.sdk_version} → ${cli.latest_sdk_version}`);
                }
                updateStatus.textContent = parts.join(" · ");
            } else {
                updateStatus.textContent = "";
            }
        }
        const switchAccount = $("usagePanelSwitchAccount");
        if (switchAccount) switchAccount.hidden = !state.authReady;
    }

    function renderUsage() {
        const usage = state.usage || {};
        const labelNode = $("usageStatusLabel");
        const badge = $("usageUpdateBadge");
        const button = $("usageStatusBtn");
        if (labelNode) labelNode.textContent = usageSummaryText(usage);
        if (button) button.hidden = !state.authReady;
        if (badge) {
            const showBadge = !!(usage.cli && (usage.cli.cli_update_available || usage.cli.sdk_update_available) && !state.usageUpdating);
            badge.hidden = !showBadge;
            badge.textContent = showBadge ? "1" : "";
        }
        renderUsagePanel();
    }

    function renderSessions() {
        const list = $("historyList");
        const search = $("historySearch");
        if (!list) return;
        const query = (search && search.value || "").toLowerCase();
        list.innerHTML = "";
        const sessions = state.sessions.filter((session) => !query || String(session.name || "").toLowerCase().includes(query));

        if (!sessions.length) {
            const empty = document.createElement("div");
            empty.className = "history-meta";
            empty.textContent = label("no_sessions", "");
            list.appendChild(empty);
            return;
        }

        sessions.forEach((session) => {
            const item = document.createElement("button");
            item.className = "history-item";
            item.type = "button";
            item.dataset.sessionId = session.id || "";
            item.innerHTML = `<div class="history-title">${escapeHtml(session.name || label("untitled_chat", ""))}</div><div class="history-meta">${escapeHtml(String(session.timestamp || "").slice(0, 16).replace("T", " "))}</div>`;
            item.addEventListener("click", () => callBridge("restoreChat", session.id || ""));
            list.appendChild(item);
        });
    }

    function formatBytes(size) {
        const value = Number(size || 0);
        if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
        if (value >= 1024) return `${Math.round(value / 1024)} KB`;
        return `${value} B`;
    }

    function decodeBase64ToBytes(data) {
        const raw = String(data || "").trim();
        if (!raw) return null;
        const payload = raw.startsWith("data:") ? raw.split(",")[1] || "" : raw;
        try {
            const binary = atob(payload);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
            return bytes;
        } catch (_) {
            return null;
        }
    }

    function attachmentDataUrl(item) {
        if (!item) return "";
        const mime = item.mimeType || "image/png";
        const data = item.data || "";
        if (data.startsWith("data:")) return data;
        if (data) return `data:${mime};base64,${data}`;
        return ensureAttachmentPreviewUrl(item);
    }

    function ensureAttachmentPreviewUrl(item) {
        if (!item) return "";
        if (item.blobUrl) return item.blobUrl;
        if (item.previewUrl && (item.previewUrl.startsWith("blob:") || item.previewUrl.startsWith("data:"))) {
            return item.previewUrl;
        }
        const mime = item.mimeType || "image/png";
        const bytes = decodeBase64ToBytes(item.data || "");
        if (bytes && bytes.length) {
            try {
                item.blobUrl = URL.createObjectURL(new Blob([bytes], { type: mime }));
                return item.blobUrl;
            } catch (_) {}
        }
        const data = item.data || "";
        return data.startsWith("data:") ? data : `data:${mime};base64,${data}`;
    }

    function revokeAttachmentPreview(item) {
        if (item && item.blobUrl) {
            try {
                URL.revokeObjectURL(item.blobUrl);
            } catch (_) {}
            item.blobUrl = "";
        }
    }

    function attachmentPreviewUrl(item) {
        return attachmentDataUrl(item) || ensureAttachmentPreviewUrl(item);
    }

    function openAttachmentLightbox(item) {
        const overlay = $("imageLightbox");
        const img = $("imageLightboxImage");
        const caption = $("imageLightboxCaption");
        if (!overlay || !img) return;
        const url = attachmentDataUrl(item);
        if (!url) return;
        img.src = url;
        img.alt = item.name || "attachment";
        if (caption) caption.textContent = item.name || "";
        overlay.hidden = false;
        document.body.classList.add("lightbox-open");
    }

    function closeAttachmentLightbox() {
        const overlay = $("imageLightbox");
        const img = $("imageLightboxImage");
        const caption = $("imageLightboxCaption");
        if (!overlay) return;
        overlay.hidden = true;
        if (img) img.removeAttribute("src");
        if (caption) caption.textContent = "";
        document.body.classList.remove("lightbox-open");
    }

    function renderMessageAttachments(container, attachments) {
        if (!container || !Array.isArray(attachments) || !attachments.length) return;
        const wrap = document.createElement("div");
        wrap.className = "message-attachments";
        attachments.forEach((item) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "message-attachment-thumb";
            button.title = item.name || label("view_attachment", "View image");
            button.setAttribute("aria-label", item.name || label("view_attachment", "View image"));

            const img = document.createElement("img");
            img.className = "message-attachment-image";
            img.src = attachmentDataUrl(item);
            img.alt = item.name || "attachment";
            img.draggable = false;
            button.appendChild(img);

            button.addEventListener("click", () => openAttachmentLightbox(item));
            wrap.appendChild(button);
        });
        container.appendChild(wrap);
    }

    function isImageFile(file) {
        if (!file) return false;
        const type = String(file.type || "").toLowerCase();
        if (type.startsWith("image/")) return true;
        const name = String(file.name || "").toLowerCase();
        if (/\.(png|jpe?g|gif|webp|bmp)$/.test(name)) return true;
        // Screenshot paste on Windows often yields an unnamed blob.
        return !type && Number(file.size || 0) > 0;
    }

    function collectClipboardImages(event) {
        const clipboard = event.clipboardData;
        if (!clipboard) return [];
        const imageFiles = [];
        const seen = new Set();

        const addFile = (file) => {
            if (!isImageFile(file)) return;
            const key = `${file.name}:${file.size}:${file.type}`;
            if (seen.has(key)) return;
            seen.add(key);
            imageFiles.push(file);
        };

        if (clipboard.files && clipboard.files.length) {
            for (const file of clipboard.files) addFile(file);
        }
        if (clipboard.items) {
            for (const item of clipboard.items) {
                if (item.kind !== "file") continue;
                addFile(item.getAsFile());
            }
        }
        return imageFiles;
    }

    function syncAttachmentStrip(showPending = false) {
        const wrap = $("attachmentChips");
        const card = $("composerCard");
        const hasItems = state.attachments.length > 0;
        const show = hasItems || showPending;
        if (wrap) {
            wrap.hidden = !show;
            wrap.classList.toggle("has-items", show);
            if (!show) {
                wrap.innerHTML = "";
            }
        }
        if (card) {
            card.classList.toggle("has-attachments", hasItems);
        }
    }

    function paintAttachmentFrame(frame, item) {
        if (!frame || !item) return;
        const url = attachmentPreviewUrl(item);
        frame.style.backgroundImage = "";
        const preload = new Image();
        preload.onload = () => {
            frame.style.backgroundImage = `url("${url}")`;
        };
        preload.onerror = () => {};
        preload.src = url;
    }

    function setAttachmentPending(pending) {
        const wrap = $("attachmentChips");
        if (!wrap) return;
        if (!pending) {
            syncAttachmentStrip(false);
            if (state.attachments.length) {
                renderAttachmentChips();
            } else {
                forceComposerRepaint();
            }
            return;
        }
        syncAttachmentStrip(true);
        wrap.innerHTML = "";
        const chip = document.createElement("div");
        chip.className = "attachment-chip pending";
        chip.textContent = label("attachment_loading", "Loading image...");
        wrap.appendChild(chip);
        forceComposerRepaint();
    }

    function resetComposerInputHeight() {
        const input = $("composerInput");
        if (!input) return;
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
    }

    function forceComposerRepaint() {
        const card = $("composerCard");
        const wrap = $("attachmentChips");
        if (card) void card.offsetHeight;
        if (wrap) void wrap.offsetHeight;
        resetComposerInputHeight();
    }

    function renderAttachmentChips() {
        const wrap = $("attachmentChips");
        if (!wrap) return;
        if (!state.attachments.length) {
            syncAttachmentStrip(false);
            forceComposerRepaint();
            return;
        }
        syncAttachmentStrip(false);
        wrap.innerHTML = "";
        state.attachments.forEach((item) => {
            const chip = document.createElement("div");
            chip.className = "attachment-chip";
            chip.dataset.id = item.id;
            chip.title = item.name || label("remove_attachment", "Remove");

            const frame = document.createElement("div");
            frame.className = "attachment-chip-frame";
            frame.setAttribute("role", "img");
            frame.setAttribute("aria-label", item.name || "attachment");
            paintAttachmentFrame(frame, item);
            chip.appendChild(frame);
            frame.addEventListener("click", () => openAttachmentLightbox(item));

            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "attachment-chip-remove";
            remove.textContent = "×";
            remove.title = label("remove_attachment", "Remove");
            remove.addEventListener("click", (event) => {
                event.stopPropagation();
                removeAttachment(item.id);
            });
            chip.appendChild(remove);
            wrap.appendChild(chip);
        });
        forceComposerRepaint();
    }

    function showComposerError(message) {
        const box = $("composerError");
        if (!box) return;
        if (!message) {
            box.hidden = true;
            box.textContent = "";
            return;
        }
        box.textContent = String(message);
        box.hidden = false;
    }

    function showAttachmentError(message) {
        showComposerError(message);
    }

    function attachmentKey(item) {
        const data = String(item && item.data || "");
        return `${item && item.mimeType || "image/png"}:${item && item.size || data.length}:${data.slice(0, 96)}`;
    }

    function rememberAttachmentKey(key) {
        state.recentAttachmentKeys.add(key);
        setTimeout(() => state.recentAttachmentKeys.delete(key), 900);
    }

    function pushAttachment(item) {
        const key = attachmentKey(item);
        if (state.recentAttachmentKeys.has(key)) return false;
        if (state.attachments.some((existing) => attachmentKey(existing) === key)) return false;
        rememberAttachmentKey(key);
        state.attachments.push(item);
        return true;
    }

    function updateComposerAttachmentState() {
        renderAttachmentChips();
        if (state.attachments.length) showComposerError("");
    }

    function canAddAttachments(count = 1) {
        return (state.attachments.length + count) <= state.maxAttachments;
    }

    function readFileAsAttachment(file) {
        return new Promise((resolve, reject) => {
            if (!isImageFile(file)) {
                reject(new Error(label("attachment_invalid_type", "Unsupported image type.")));
                return;
            }
            if (file.size > state.maxImageBytes) {
                reject(new Error(label("attachment_too_large", "Image is too large.")));
                return;
            }
            const reader = new FileReader();
            reader.onload = () => {
                const result = String(reader.result || "");
                const comma = result.indexOf(",");
                const data = comma >= 0 ? result.slice(comma + 1) : result;
                const mimeType = String(file.type || "").toLowerCase() || "image/png";
                resolve({
                    id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
                    name: file.name || "image.png",
                    mimeType,
                    data,
                    size: file.size,
                    previewUrl: result,
                    source: "user",
                });
            };
            reader.onerror = () => reject(new Error(label("attachment_read_failed", "Could not read image.")));
            reader.readAsDataURL(file);
        });
    }

    async function addAttachmentFiles(fileList) {
        const files = Array.from(fileList || []).filter(Boolean);
        if (!files.length) {
            setAttachmentPending(false);
            return;
        }
        if (!canAddAttachments(files.length)) {
            setAttachmentPending(false);
            showAttachmentError(label("attachment_limit_reached", "Too many images attached."));
            return;
        }
        for (const file of files) {
            if (!canAddAttachments(1)) {
                showAttachmentError(label("attachment_limit_reached", "Too many images attached."));
                break;
            }
            try {
                const attachment = await readFileAsAttachment(file);
                if (pushAttachment(attachment)) {
                    showComposerError("");
                }
            } catch (err) {
                showAttachmentError(String(err.message || err));
            }
        }
        setAttachmentPending(false);
        updateComposerAttachmentState();
        focusComposer();
    }

    function removeAttachment(id) {
        const item = state.attachments.find((entry) => entry.id === id);
        if (item) revokeAttachmentPreview(item);
        state.attachments = state.attachments.filter((entry) => entry.id !== id);
        updateComposerAttachmentState();
    }

    function clearAttachments() {
        state.attachments.forEach(revokeAttachmentPreview);
        state.attachments = [];
        updateComposerAttachmentState();
    }

    function addComposerAttachment(payload) {
        const item = payload || {};
        const data = item.data || "";
        if (!data) return false;
        if (!canAddAttachments(1) && !state.attachments.some((entry) => attachmentKey(entry) === attachmentKey(item))) {
            showAttachmentError(label("attachment_limit_reached", "Too many images attached."));
            return false;
        }
        const mimeType = item.mimeType || item.mime_type || "image/png";
        const size = Number(item.size || Math.ceil((data.length * 3) / 4));
        if (size > state.maxImageBytes) {
            showAttachmentError(label("attachment_too_large", "Image is too large."));
            return false;
        }
        const nextItem = {
            id: item.id || `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            name: item.name || "image.png",
            mimeType,
            data,
            size,
            previewUrl: "",
            source: item.source || "clipboard",
        };
        ensureAttachmentPreviewUrl(nextItem);
        const added = pushAttachment(nextItem);
        setAttachmentPending(false);
        updateComposerAttachmentState();
        if (added || state.attachments.length) {
            showComposerError("");
            focusComposer();
        }
        return added || state.attachments.some((entry) => attachmentKey(entry) === attachmentKey(nextItem));
    }

    async function readHostClipboardImage() {
        const raw = await callBridgeResult("readClipboardImageJson");
        if (typeof raw !== "string" || !raw) return null;
        try {
            const payload = JSON.parse(raw);
            return payload && payload.data ? payload : null;
        } catch (err) {
            writeDebug({ clipboardImageError: String(err) });
            return null;
        }
    }

    async function readHostClipboardText() {
        const text = await callBridgeResult("readClipboardText");
        return typeof text === "string" ? text : "";
    }

    async function processComposerPaste(event) {
        if (state.pasteBusy) return;
        state.pasteBusy = true;
        setAttachmentPending(true);

        try {
            const imageFiles = event && event.clipboardData ? collectClipboardImages(event) : [];
            if (imageFiles.length) {
                await addAttachmentFiles(imageFiles);
                return;
            }

            const payload = await readHostClipboardImage();
            if (payload && addComposerAttachment(payload)) {
                return;
            }

            setAttachmentPending(false);
            const text = await readHostClipboardText();
            if (text) {
                insertComposerText(text);
            }
        } catch (err) {
            setAttachmentPending(false);
            writeDebug({ pasteError: String(err) });
        } finally {
            state.pasteBusy = false;
        }
    }

    function handleComposerPaste(event) {
        event.preventDefault();
        event.stopPropagation();
        void processComposerPaste(event);
    }

    function handleHostClipboardPaste() {
        void processComposerPaste(null);
    }

    function setAttachmentLimits(payload) {
        payload = payload || {};
        const defaultMax = 4;
        if (payload.max_attachments != null) {
            const parsed = Number(payload.max_attachments);
            if (!Number.isNaN(parsed) && parsed > 0) {
                state.maxAttachments = Math.max(defaultMax, parsed);
            }
        }
        if (payload.max_image_bytes != null) {
            const parsed = Number(payload.max_image_bytes);
            if (!Number.isNaN(parsed) && parsed > 0) {
                state.maxImageBytes = parsed;
            }
        }
    }

    function renderReferenceChips() {
        const wrap = $("referenceChips");
        if (!wrap) return;
        wrap.innerHTML = "";
        state.references.forEach((ref, index) => {
            const token = ref.reference || ref.insert_text || ref.label || "";
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = `reference-chip ref-pill-${ref.type || refKind(token)}`;
            chip.innerHTML = `<span class="ref-chip-icon">${ref.type === "tab" ? "T" : "B"}</span><span>${escapeHtml(token)}</span>`;
            chip.title = ref.label || ref.detail || token;
            chip.addEventListener("click", () => {
                state.references.splice(index, 1);
                renderReferenceChips();
            });
            wrap.appendChild(chip);
        });
    }

    function showReferenceSuggestions(payload) {
        const suggestions = Array.isArray(payload) ? payload : [];
        const box = $("referenceSuggestions");
        if (!box) return;
        box.innerHTML = "";
        if (!suggestions.length) {
            box.hidden = true;
            return;
        }
        suggestions.forEach((suggestion) => {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "suggestion-item";
            item.innerHTML = `<span>${escapeHtml(suggestion.insert_text || suggestion.reference || suggestion.label)}</span><span class="suggestion-detail">${escapeHtml(suggestion.label || "")} ${escapeHtml(suggestion.detail || "")}</span>`;
            item.addEventListener("click", () => {
                const input = $("composerInput");
                if (!input) return;
                input.value = input.value.replace(/#[\w:.-]*$/, suggestion.insert_text || suggestion.reference || "");
                state.references.push(suggestion);
                renderReferenceChips();
                box.hidden = true;
                input.focus();
            });
            box.appendChild(item);
        });
        box.hidden = false;
    }

    function setTurnState(turn) {
        const previousTurnId = state.currentTurn && state.currentTurn.turn_id;
        if (turn && turn.turn_id && turn.turn_id !== previousTurnId) {
            state.workEl = null;
            state.toolCount = 0;
            state.completedTools = 0;
        }
        state.currentTurn = turn || null;
        setWorking(!!turn && ["sending", "thinking", "streaming", "running_tool"].includes(turn.state));
        writeDebug(turn || {});
        if (turn && ["error", "timed_out", "cancelled"].includes(turn.state)) {
            stopActivityTimer();
            hideThinking();
            endThinkingBlock();
            endStreaming();
            endToolGroup();
            const row = addMessage("error", turn.error || turn.state, `error-${turn.turn_id || Date.now()}`);
            if (turn.can_retry) {
                const bubble = row && row.querySelector(".message");
                if (bubble) {
                    const retry = document.createElement("button");
                    retry.type = "button";
                    retry.className = "retry-turn-btn";
                    retry.textContent = label("retry_turn", "Retry");
                    retry.addEventListener("click", () => callBridge("retryTurn", turn.turn_id || ""));
                    bubble.appendChild(retry);
                }
            }
        }
    }

    function applyHistoryCollapsed(collapsed, persist) {
        state.historyCollapsed = !!collapsed;
        const app = $("app");
        if (app) app.classList.toggle("history-collapsed", state.historyCollapsed);
        if (persist) callBridge("setHistoryCollapsed", { collapsed: state.historyCollapsed });
    }

    function setAppState(payload) {
        payload = payload || {};
        if (payload.tab_name && $("tabContext")) $("tabContext").textContent = payload.tab_name;
        if (payload.auth_label && $("authBtn")) $("authBtn").textContent = payload.auth_label;
        if (Object.prototype.hasOwnProperty.call(payload, "auth_ready")) {
            const authBtn = $("authBtn");
            const logoutBtn = $("logoutBtn");
            const switchAccountBtn = $("switchAccountBtn");
            if (authBtn) authBtn.classList.toggle("ready", !!payload.auth_ready);
            if (logoutBtn) logoutBtn.hidden = !payload.auth_ready;
            if (switchAccountBtn) switchAccountBtn.hidden = !payload.auth_ready;
            state.authReady = !!payload.auth_ready;
            renderUsage();
        }
        if (payload.selected_model) state.selectedModel = payload.selected_model;
        if (payload.selected_effort) state.selectedEffort = payload.selected_effort;
        if (payload.supported_efforts) renderEfforts(payload.supported_efforts);
        if (Object.prototype.hasOwnProperty.call(payload, "history_collapsed")) applyHistoryCollapsed(!!payload.history_collapsed, false);
        if (typeof payload.loading === "boolean") setWorking(payload.loading);
        renderModels();
    }

    function sendCurrentMessage() {
        const input = $("composerInput");
        if (!input) return;
        const text = input.value.trim();
        if ((!text && !state.attachments.length) || state.loading || !state.authReady) return;
        const attachments = state.attachments.map(({ name, mimeType, data, size, source }) => ({
            name,
            mimeType,
            data,
            size,
            source,
        }));
        callBridge("sendMessage", {
            text: text || label("attachment_only_prompt", "What do you see in this image?"),
            references: state.references,
            attachments,
        });
        input.value = "";
        input.style.height = "auto";
        state.references = [];
        state.attachments = [];
        showComposerError("");
        renderReferenceChips();
        renderAttachmentChips();
    }

    function wireEvents() {
        $("sendBtn").addEventListener("click", sendCurrentMessage);
        $("cancelBtn").addEventListener("click", () => callBridge("cancelTurn", state.currentTurn && state.currentTurn.turn_id || ""));
        $("newChatBtn").addEventListener("click", () => callBridge("createNewChat", {}));
        $("toggleHistoryBtn").addEventListener("click", () => applyHistoryCollapsed(!state.historyCollapsed, true));
        $("toggleHistoryHeaderBtn").addEventListener("click", () => applyHistoryCollapsed(!state.historyCollapsed, true));
        $("refreshModelsBtn").addEventListener("click", () => callBridge("refreshModels", {}));
        const usageStatusBtn = $("usageStatusBtn");
        const usagePanelClose = $("usagePanelClose");
        const usagePanelUpdateBtn = $("usagePanelUpdateBtn");
        const usagePanelSubscription = $("usagePanelSubscription");
        if (usageStatusBtn) {
            usageStatusBtn.addEventListener("click", (event) => {
                event.stopPropagation();
                const nextOpen = !state.usagePanelOpen;
                setUsagePanelOpen(nextOpen);
                if (nextOpen) callBridge("refreshUsagePanel", { check_latest: true });
            });
        }
        if (usagePanelClose) {
            usagePanelClose.addEventListener("click", () => setUsagePanelOpen(false));
        }
        if (usagePanelUpdateBtn) {
            usagePanelUpdateBtn.addEventListener("click", () => callBridge("updateCopilotCli", {}));
        }
        if (usagePanelSubscription) {
            usagePanelSubscription.addEventListener("click", () => callBridge("openCopilotSubscription", {}));
        }
        const usagePanelSwitchAccount = $("usagePanelSwitchAccount");
        if (usagePanelSwitchAccount) {
            usagePanelSwitchAccount.addEventListener("click", () => {
                setUsagePanelOpen(false);
                callBridge("switchAccount", {});
            });
        }
        const switchAccountBtn = $("switchAccountBtn");
        if (switchAccountBtn) {
            switchAccountBtn.addEventListener("click", (event) => {
                event.stopPropagation();
                callBridge("switchAccount", {});
            });
        }
        const accountPickerClose = $("accountPickerClose");
        if (accountPickerClose) {
            accountPickerClose.addEventListener("click", () => setAccountPickerOpen(false));
        }
        const accountPickerAdd = $("accountPickerAdd");
        if (accountPickerAdd) {
            accountPickerAdd.addEventListener("click", () => {
                setAccountPickerOpen(false);
                setAccountSwitchBusy({ visible: true, kind: "add" });
                callBridge("addAccount", {});
            });
        }
        document.addEventListener("click", (event) => {
            if (state.accountPickerOpen) {
                const wrap = document.querySelector(".account-picker-wrap");
                if (wrap && !wrap.contains(event.target)) setAccountPickerOpen(false);
            }
            if (!state.usagePanelOpen) return;
            const wrap = document.querySelector(".usage-status-wrap");
            if (wrap && !wrap.contains(event.target)) setUsagePanelOpen(false);
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                if (state.accountPickerOpen) setAccountPickerOpen(false);
                if (state.usagePanelOpen) setUsagePanelOpen(false);
            }
        });
        $("authBtn").addEventListener("click", () => {
            if (state.authReady) return;
            callBridge("authAction", { action: "sign_in" });
        });
        const logoutBtn = $("logoutBtn");
        if (logoutBtn) {
            logoutBtn.addEventListener("click", () => callBridge("authAction", { action: "logout" }));
        }
        const authGateAction = $("authGateAction");
        if (authGateAction) {
            authGateAction.addEventListener("click", () => {
                const action = authGateAction.dataset.action || "sign_in";
                callBridge("authAction", { action });
            });
        }
        $("historySearch").addEventListener("input", renderSessions);
        $("effortSelect").addEventListener("change", (event) => callBridge("selectReasoningEffort", event.target.value));

        $("modelPickerBtn").addEventListener("click", (event) => {
            event.stopPropagation();
            const menu = $("modelPickerMenu");
            if (menu && menu.hidden) openModelPicker();
            else closeModelPicker();
        });
        $("modelSearch").addEventListener("input", (event) => {
            state.modelQuery = event.target.value || "";
            renderModelList();
        });
        $("modelPickerMenu").addEventListener("click", (event) => event.stopPropagation());
        document.addEventListener("click", closeModelPicker);
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeModelPicker();
                closeAttachmentLightbox();
            }
        });

        const lightbox = $("imageLightbox");
        const lightboxClose = $("imageLightboxClose");
        const lightboxBackdrop = $("imageLightboxBackdrop");
        if (lightboxClose) lightboxClose.addEventListener("click", closeAttachmentLightbox);
        if (lightboxBackdrop) lightboxBackdrop.addEventListener("click", closeAttachmentLightbox);
        if (lightbox) {
            lightbox.addEventListener("click", (event) => {
                if (event.target === lightbox) closeAttachmentLightbox();
            });
        }

        const input = $("composerInput");
        const composerCard = $("composerCard");
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                sendCurrentMessage();
            }
        });
        input.addEventListener("paste", handleComposerPaste);
        input.addEventListener("input", () => {
            input.style.height = "auto";
            input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
            const token = (input.value.match(/#[\w:.-]*$/) || [""])[0];
            if (token && token.length > 1) callBridge("listReferences", token);
            else $("referenceSuggestions").hidden = true;
        });

        const attachBtn = $("attachBtn");
        const attachInput = $("attachInput");
        if (attachBtn && attachInput) {
            attachBtn.addEventListener("click", () => attachInput.click());
            attachInput.addEventListener("change", () => {
                addAttachmentFiles(attachInput.files);
                attachInput.value = "";
            });
        }

        if (composerCard) {
            ["dragenter", "dragover"].forEach((eventName) => {
                composerCard.addEventListener(eventName, (event) => {
                    event.preventDefault();
                    composerCard.classList.add("drag-over");
                });
            });
            ["dragleave", "drop"].forEach((eventName) => {
                composerCard.addEventListener(eventName, (event) => {
                    event.preventDefault();
                    composerCard.classList.remove("drag-over");
                    if (eventName === "drop") {
                        addAttachmentFiles(event.dataTransfer && event.dataTransfer.files);
                    }
                });
            });
        }
    }

    function initBridge() {
        if (window.qt && window.QWebChannel) {
            new QWebChannel(qt.webChannelTransport, (channel) => {
                state.bridge = channel.objects.bridge;
                if (state.bridge && state.bridge.onWebViewReady) state.bridge.onWebViewReady();
            });
        }
    }

    function focusComposer() {
        const input = $("composerInput");
        if (!input) return;
        input.focus();
        const end = input.value.length;
        input.setSelectionRange(end, end);
    }

    function insertComposerText(text) {
        const input = $("composerInput");
        if (!input || typeof text !== "string") return;
        const value = text;
        if (!value || value === "[object Promise]") return;
        const start = input.selectionStart ?? input.value.length;
        const end = input.selectionEnd ?? input.value.length;
        input.value = input.value.slice(0, start) + value + input.value.slice(end);
        const cursor = start + value.length;
        input.setSelectionRange(cursor, cursor);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
    }

    window.setLabels = (labels) => {
        state.labels = Object.assign({}, state.labels, labels || {});
        renderStaticLabels();
    };
    window.setWelcomeText = (title, message) => {
        const welcomeTitle = $("welcomeTitle");
        const welcomeText = $("welcomeText");
        if (welcomeTitle) welcomeTitle.textContent = title || "";
        if (welcomeText) welcomeText.textContent = message || "";
    };
    window.setTheme = (theme) => {
        Object.entries(theme || {}).forEach(([key, value]) => {
            document.documentElement.style.setProperty(`--${key.replace(/_/g, "-")}`, value);
        });
    };
    window.addMessage = addMessage;
    window.hideWelcome = hideWelcome;
    window.clearMessages = clearMessages;
    window.scrollToBottom = scrollToBottom;
    window.showThinking = showThinking;
    window.hideThinking = hideThinking;
    window.startThinkingBlock = startThinkingBlock;
    window.appendThinking = appendThinking;
    window.endThinkingBlock = endThinkingBlock;
    window.startStreaming = startStreaming;
    window.streamChunk = streamChunk;
    window.endStreaming = endStreaming;
    window.addToolUse = addToolUse;
    window.updateToolStatus = updateToolStatus;
    window.completeAllRunningTools = completeAllRunningTools;
    window.endToolGroup = endToolGroup;
    window.setModels = (payload) => {
        state.models = Array.isArray(payload && payload.models) ? payload.models : [];
        state.selectedModel = payload && payload.selected_model || state.selectedModel;
        renderModels();
        renderEfforts(payload && payload.supported_efforts || []);
    };
    window.setUsage = (payload) => {
        state.usage = payload || {};
        if (Object.prototype.hasOwnProperty.call(payload || {}, "updating")) {
            state.usageUpdating = !!payload.updating;
        }
        renderUsage();
    };
    window.openAccountPicker = openAccountPicker;
    window.setAccountSwitchBusy = setAccountSwitchBusy;
    window.setSessions = (payload) => {
        state.sessions = Array.isArray(payload && payload.sessions) ? payload.sessions : [];
        renderSessions();
    };
    window.setActivity = setActivity;
    window.stopActivityTimer = stopActivityTimer;
    window.setTurnState = setTurnState;
    window.setAppState = setAppState;
    window.setAuthGate = setAuthGate;
    window.showReferenceSuggestions = showReferenceSuggestions;
    window.focusComposer = focusComposer;
    window.addComposerAttachment = addComposerAttachment;
    window.insertComposerText = insertComposerText;
    window.handleHostClipboardPaste = handleHostClipboardPaste;
    window.setAttachmentLimits = setAttachmentLimits;

    document.addEventListener("DOMContentLoaded", () => {
        wireEvents();
        renderStaticLabels();
        renderEfforts([]);
        initBridge();
    });
})();