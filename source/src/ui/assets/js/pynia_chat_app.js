/* Pynia ACP chat WebView */
(function () {
    const $ = (id) => document.getElementById(id);
    let bridge = null;
    let labels = {};
    let pendingPermissionId = null;
    let busy = false;
    let logoSrc = "";
    let applyingConfig = false;
    let agentReady = false;
    let pendingAttachments = [];

    function setTheme(theme) {
        const root = document.documentElement;
        Object.entries(theme || {}).forEach(([key, value]) => {
            if (key === "logo") {
                logoSrc = value || "";
                return;
            }
            root.style.setProperty("--" + key.split("_").join("-"), value);
        });
    }

    function applyLabels() {
        const input = $("composerInput");
        if (input) {
            input.placeholder = agentReady
                ? (labels.composer_placeholder || "Ask Pynia…")
                : (labels.pick_agent || "Choose an agent to start this tab's chat.");
        }
        const llm = $("llmChip");
        const reason = $("reasonChip");
        const search = $("llmSearch");
        if (llm) {
            llm.setAttribute("aria-label", labels.llm || "LLM");
            llm.title = labels.llm || "LLM";
        }
        if (reason) {
            reason.setAttribute("aria-label", labels.reasoning || "Reasoning");
            reason.title = labels.reasoning || "Reasoning";
        }
        if (search) search.placeholder = labels.search_models || "Search models";
        if ($("permAllowOnce")) $("permAllowOnce").textContent = labels.allow_once || "Allow once";
        if ($("permAllowAlways")) $("permAllowAlways").textContent = labels.allow_always || "Always allow";
        if ($("permReject")) $("permReject").textContent = labels.reject || "Reject";
        const settings = $("settingsBtn");
        if (settings) {
            const title = labels.settings || labels.open_settings || "Settings";
            settings.title = title;
            settings.setAttribute("aria-label", title);
        }
        const loadingLabel = $("pyniaLoading") && $("pyniaLoading").querySelector("span");
        if (loadingLabel && !busy) loadingLabel.textContent = labels.working || "Pynia is working…";
        const send = $("sendBtn");
        if (send) send.setAttribute("aria-label", busy ? (labels.cancel || "Stop") : (labels.send || "Send"));
    }

    function renderMarkdown(text) {
        try {
            if (window.marked) {
                const html = window.marked.parse(text || "");
                const wrap = document.createElement("div");
                wrap.innerHTML = html;
                wrap.querySelectorAll("pre code").forEach((block) => {
                    if (window.hljs) window.hljs.highlightElement(block);
                });
                return wrap.innerHTML;
            }
        } catch (err) { /* fall through */ }
        const div = document.createElement("div");
        div.textContent = text || "";
        return div.innerHTML;
    }

    function scrollToBottom() {
        const box = $("messages");
        box.scrollTop = box.scrollHeight;
    }

    let llmState = { values: [], current: "", hidden: true, loading: false, label: "LLM" };
    let reasonState = { values: [], current: "", hidden: true, loading: false, label: "Reasoning" };
    let llmActive = 0;
    let reasonActive = 0;

    function filterValues(values, query) {
        const needle = (query || "").trim().toLowerCase();
        const list = values || [];
        if (!needle) return list.slice();
        return list.filter((item) => {
            const blob = [item.name, item.value, item.description].join(" ").toLowerCase();
            return blob.indexOf(needle) >= 0;
        });
    }

    function currentName(state) {
        const hit = (state.values || []).find((item) => item.value === state.current);
        return (hit && hit.name) || state.current || "…";
    }

    function closePopovers() {
        ["llmPopover", "reasonPopover"].forEach((id) => {
            const el = $(id);
            if (!el) return;
            el.hidden = true;
            el.classList.remove("is-open");
        });
        const llmChip = $("llmChip");
        const reasonChip = $("reasonChip");
        if (llmChip) llmChip.setAttribute("aria-expanded", "false");
        if (reasonChip) reasonChip.setAttribute("aria-expanded", "false");
    }

    function renderOptionList(listEl, values, current, activeIndex, onPick) {
        listEl.replaceChildren();
        if (!values.length) {
            const empty = document.createElement("div");
            empty.className = "config-empty";
            empty.textContent = labels.no_models_found || "No models found";
            listEl.appendChild(empty);
            return;
        }
        values.forEach((item, idx) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "config-option"
                + (item.value === current ? " selected" : "")
                + (idx === activeIndex ? " active" : "");
            btn.setAttribute("role", "option");
            btn.dataset.value = item.value;
            const name = document.createElement("span");
            name.textContent = item.name || item.value;
            btn.appendChild(name);
            if (item.description) {
                const meta = document.createElement("span");
                meta.className = "meta";
                meta.textContent = item.description;
                btn.appendChild(meta);
            }
            btn.addEventListener("mousedown", (ev) => ev.preventDefault());
            btn.addEventListener("click", () => onPick(item.value));
            listEl.appendChild(btn);
        });
        const active = listEl.querySelector(".config-option.active");
        if (active && active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
    }

    function refreshLlmList() {
        const list = $("llmList");
        if (!list) return;
        const filtered = filterValues(llmState.values || [], ($("llmSearch") && $("llmSearch").value) || "");
        if (llmActive >= filtered.length) llmActive = Math.max(0, filtered.length - 1);
        renderOptionList(list, filtered, llmState.current, llmActive, pickLlm);
    }

    function refreshReasonList() {
        const list = $("reasonList");
        if (!list) return;
        const values = reasonState.values || [];
        if (reasonActive >= values.length) reasonActive = Math.max(0, values.length - 1);
        renderOptionList(list, values, reasonState.current, reasonActive, pickReason);
    }

    function pickLlm(value) {
        closePopovers();
        if (!value || applyingConfig) return;
        llmState.current = value;
        updateChips();
        if (bridge) bridge.setConfig("model", value);
    }

    function pickReason(value) {
        closePopovers();
        if (!value || applyingConfig) return;
        reasonState.current = value;
        updateChips();
        if (bridge) bridge.setConfig("reasoning", value);
    }

    function updateChips() {
        const llmWrap = $("llmWrap");
        const reasonWrap = $("reasonWrap");
        const llmChip = $("llmChip");
        const reasonChip = $("reasonChip");
        if (llmWrap) llmWrap.hidden = !!(llmState.hidden && !llmState.loading);
        if (reasonWrap) reasonWrap.hidden = !!(reasonState.hidden || reasonState.loading);
        if (llmChip) {
            llmChip.disabled = !agentReady || !!llmState.loading;
            llmChip.textContent = llmState.loading ? "…" : currentName(llmState);
            const title = llmState.label || labels.llm || "LLM";
            llmChip.title = title;
            llmChip.setAttribute("aria-label", title);
        }
        if (reasonChip) {
            reasonChip.disabled = !agentReady || !!reasonState.loading;
            reasonChip.textContent = reasonState.loading ? "…" : currentName(reasonState);
            const title = reasonState.label || labels.reasoning || "Reasoning";
            reasonChip.title = title;
            reasonChip.setAttribute("aria-label", title);
        }
    }

    function setConfigOptions(payload) {
        applyingConfig = true;
        try {
            closePopovers();
            const data = payload || {};
            llmState = Object.assign(
                { values: [], current: "", hidden: true, loading: false, label: "LLM" },
                data.model || {}
            );
            reasonState = Object.assign(
                { values: [], current: "", hidden: true, loading: false, label: "Reasoning" },
                data.reasoning || {}
            );
            updateChips();
            refreshLlmList();
            refreshReasonList();
        } finally {
            applyingConfig = false;
        }
    }

    function openPopover(which) {
        if (!agentReady) return;
        const pop = which === "llm" ? $("llmPopover") : $("reasonPopover");
        const chip = which === "llm" ? $("llmChip") : $("reasonChip");
        if (!pop || !chip || chip.disabled) return;
        const opening = !pop.classList.contains("is-open");
        closePopovers();
        if (!opening) return;
        pop.hidden = false;
        pop.classList.add("is-open");
        chip.setAttribute("aria-expanded", "true");
        if (which === "llm") {
            const search = $("llmSearch");
            llmActive = Math.max(0, (llmState.values || []).findIndex((item) => item.value === llmState.current));
            if (search) {
                search.placeholder = labels.search_models || "Search models";
                search.value = "";
                search.focus();
            }
            refreshLlmList();
        } else {
            reasonActive = Math.max(0, (reasonState.values || []).findIndex((item) => item.value === reasonState.current));
            refreshReasonList();
        }
    }

    function moveActive(which, delta) {
        if (which === "llm") {
            const filtered = filterValues(llmState.values || [], ($("llmSearch") && $("llmSearch").value) || "");
            if (!filtered.length) return;
            llmActive = (llmActive + delta + filtered.length) % filtered.length;
            refreshLlmList();
        } else {
            const values = reasonState.values || [];
            if (!values.length) return;
            reasonActive = (reasonActive + delta + values.length) % values.length;
            refreshReasonList();
        }
    }

    function confirmActive(which) {
        if (which === "llm") {
            const filtered = filterValues(llmState.values || [], ($("llmSearch") && $("llmSearch").value) || "");
            const item = filtered[llmActive];
            if (item) pickLlm(item.value);
        } else {
            const item = (reasonState.values || [])[reasonActive];
            if (item) pickReason(item.value);
        }
    }

    function onPickerKey(which, ev) {
        if (ev.key === "ArrowDown") {
            ev.preventDefault();
            moveActive(which, 1);
        } else if (ev.key === "ArrowUp") {
            ev.preventDefault();
            moveActive(which, -1);
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            confirmActive(which);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            closePopovers();
        }
    }

    function setPicker(agents) {
        const picker = $("picker");
        const grid = $("pickerGrid");
        grid.replaceChildren();
        (agents || []).forEach((agent) => {
            const btn = document.createElement("button");
            btn.className = "agent-card" + (agent.ready ? "" : " disabled");
            btn.type = "button";
            const img = document.createElement("img");
            img.alt = "";
            if (agent.icon) img.src = agent.icon;
            const name = document.createElement("div");
            name.textContent = agent.label || "";
            const status = document.createElement("div");
            status.className = "status";
            status.textContent = agent.status_label || "";
            btn.append(img, name, status);
            btn.addEventListener("click", () => {
                if (!agent.ready) {
                    if (bridge) bridge.openSettings();
                    return;
                }
                if (bridge) bridge.selectAgent(agent.id);
            });
            grid.appendChild(btn);
        });
        picker.hidden = !agents || !agents.length;
    }

    function hidePicker() {
        const picker = $("picker");
        if (picker) picker.hidden = true;
    }

    function showNotice(text) {
        hidePicker();
        hideLoading();
        const el = addMessage("assistant", "", "error");
        el.textContent = text || "";
    }

    function setHeader(payload) {
        $("chatTitle").textContent = payload.title || "Pynia";
        $("tabContext").textContent = payload.subtitle || "";
        const icon = $("agentIcon");
        if (payload.icon) {
            icon.src = payload.icon;
            icon.hidden = false;
        } else {
            icon.hidden = true;
        }
        $("recreatedNote").hidden = !payload.recreated;
        $("recreatedNote").textContent = payload.recreated_note || "";
        $("pickerHint").textContent = labels.pick_agent || "Choose an agent to start this tab's chat.";
        applyLabels();
    }

    function clearMessages() {
        $("messages").innerHTML = "";
    }

    function addMessage(role, html, extraClass) {
        const el = document.createElement("div");
        el.className = "bubble " + role + (extraClass ? " " + extraClass : "");
        el.innerHTML = html;
        $("messages").appendChild(el);
        scrollToBottom();
        return el;
    }

    function hideLoading() {
        const el = $("pyniaLoading");
        if (el) el.remove();
    }

    function showLoading() {
        if ($("pyniaLoading")) {
            scrollToBottom();
            return;
        }
        hidePicker();
        const el = document.createElement("div");
        el.id = "pyniaLoading";
        el.className = "pynia-loading";
        if (logoSrc) {
            const img = document.createElement("img");
            img.alt = "Pynia";
            img.src = logoSrc;
            el.appendChild(img);
        } else {
            const mark = document.createElement("span");
            mark.className = "pynia-loading-mark";
            el.appendChild(mark);
        }
        const label = document.createElement("span");
        label.textContent = labels.working || "Pynia is working…";
        el.appendChild(label);
        $("messages").appendChild(el);
        scrollToBottom();
    }

    function setMessages(messages) {
        hideLoading();
        clearMessages();
        (messages || []).forEach((msg) => {
            if (msg.role === "user") {
                const el = addMessage("user", "");
                fillUserBubble(el, msg.content || "", msg.attachments || []);
            } else if (msg.error) {
                const el = addMessage("assistant", "", "error");
                el.textContent = msg.content || "";
            } else if ((msg.content || "").trim()) {
                addMessage("assistant", renderMarkdown(msg.content || ""));
            }
        });
        if ((messages || []).length > 0 && agentReady) {
            $("picker").hidden = true;
        }
    }

    function appendChunk(text) {
        hidePicker();
        hideLoading();
        let last = $("messages").lastElementChild;
        if (!last || !last.classList.contains("assistant") || last.dataset.stream !== "1") {
            last = addMessage("assistant", "");
            last.dataset.stream = "1";
            last.dataset.raw = "";
        }
        last.dataset.raw = (last.dataset.raw || "") + (text || "");
        last.innerHTML = renderMarkdown(last.dataset.raw);
        scrollToBottom();
    }

    function setThinking(_text) {
        if ($("messages").querySelector(".bubble.assistant[data-stream='1']")) return;
        showLoading();
    }

    function addTool(payload) {
        hideLoading();
        const el = document.createElement("div");
        el.className = "tool-card" + (payload && payload.error ? " error" : "");
        const title = (payload && payload.title) || "tool";
        el.textContent = payload && payload.error ? (title + ": " + payload.error) : title;
        $("messages").appendChild(el);
        if (busy) showLoading();
        scrollToBottom();
    }

    function setBusy(isBusy) {
        busy = !!isBusy;
        const send = $("sendBtn");
        if (send) {
            send.classList.toggle("stop", busy);
            send.hidden = false;
            send.disabled = busy ? false : !agentReady;
            send.setAttribute("aria-label", busy ? (labels.cancel || "Stop") : (labels.send || "Send"));
        }
        $("messages").setAttribute("aria-busy", busy ? "true" : "false");
        if (busy) showLoading();
        else hideLoading();
    }

    function showPermission(payload) {
        pendingPermissionId = payload.id;
        $("permissionBar").hidden = false;
        $("permissionText").textContent = payload.text || labels.permission_title || "Allow this action?";
    }

    function hidePermission() {
        pendingPermissionId = null;
        $("permissionBar").hidden = true;
    }

    function sendCurrent() {
        if (busy || !agentReady) return;
        const input = $("composerInput");
        const text = (input.value || "").trim();
        if (!text && !pendingAttachments.length) return;
        const attachments = pendingAttachments.slice();
        pendingAttachments = [];
        renderAttachRow();
        input.value = "";
        autosizeComposer();
        hidePicker();
        const el = addMessage("user", "");
        fillUserBubble(el, text, attachments.map(displayAttachment));
        showLoading();
        if (bridge) bridge.sendMessage(text, JSON.stringify(attachments));
    }

    function setComposerEnabled(enabled) {
        agentReady = !!enabled;
        const card = $("composerCard");
        const input = $("composerInput");
        const send = $("sendBtn");
        if (card) card.classList.toggle("locked", !agentReady);
        if (input) {
            input.disabled = !agentReady;
            input.placeholder = agentReady
                ? (labels.composer_placeholder || "Ask Pynia…")
                : (labels.pick_agent || "Choose an agent to start this tab's chat.");
        }
        if (send) send.disabled = busy ? false : !agentReady;
        updateChips();
    }

    function answer(optionId) {
        if (pendingPermissionId == null || !bridge) return;
        bridge.answerPermission(String(pendingPermissionId), optionId);
        hidePermission();
    }

    function bindUi() {
        $("sendBtn").addEventListener("click", () => {
            if (busy) {
                if (bridge) bridge.cancel();
                return;
            }
            sendCurrent();
        });
        $("settingsBtn").addEventListener("click", () => bridge && bridge.openSettings());
        $("permAllowOnce").addEventListener("click", () => answer("allow-once"));
        $("permAllowAlways").addEventListener("click", () => answer("allow-always"));
        $("permReject").addEventListener("click", () => answer("reject-once"));
        $("composerInput").addEventListener("input", autosizeComposer);
        $("composerInput").addEventListener("keydown", (ev) => {
            if (ev.key === "Enter" && !ev.shiftKey) {
                ev.preventDefault();
                sendCurrent();
            }
        });
        $("composerInput").addEventListener("paste", onComposerPaste);
        const card = $("composerCard");
        if (card) {
            card.addEventListener("dragover", (ev) => {
                ev.preventDefault();
            });
            card.addEventListener("drop", (ev) => {
                ev.preventDefault();
                ingestDataTransfer(ev.dataTransfer);
            });
        }
        $("llmChip").addEventListener("click", () => openPopover("llm"));
        $("reasonChip").addEventListener("click", () => openPopover("reason"));
        document.addEventListener("mousedown", (ev) => {
            if (!ev.target.closest || !ev.target.closest(".config-wrap")) closePopovers();
        });
        const search = $("llmSearch");
        if (search) {
            search.addEventListener("input", () => {
                llmActive = 0;
                refreshLlmList();
            });
            search.addEventListener("keydown", (ev) => onPickerKey("llm", ev));
        }
        const reasonPop = $("reasonPopover");
        if (reasonPop) reasonPop.addEventListener("keydown", (ev) => onPickerKey("reason", ev));
    }

    function fillUserBubble(el, text, attachments) {
        el.replaceChildren();
        if (attachments && attachments.length) {
            const row = document.createElement("div");
            row.className = "msg-attach";
            attachments.forEach((item) => {
                if (item.kind === "image" && (item.src || item.data)) {
                    const img = document.createElement("img");
                    img.alt = item.name || "image";
                    img.src = item.src || ("data:" + (item.mime || "image/png") + ";base64," + item.data);
                    row.appendChild(img);
                } else {
                    const chip = document.createElement("span");
                    chip.className = "file-chip";
                    chip.textContent = item.name || "file";
                    row.appendChild(chip);
                }
            });
            el.appendChild(row);
        }
        if (text) {
            const body = document.createElement("div");
            body.textContent = text;
            el.appendChild(body);
        }
    }

    function displayAttachment(item) {
        if (!item) return item;
        if (item.kind === "image" && item.data && !item.src) {
            return {
                kind: "image",
                name: item.name,
                mime: item.mime,
                src: "data:" + (item.mime || "image/png") + ";base64," + item.data,
            };
        }
        return { kind: item.kind || "file", name: item.name || "file", mime: item.mime || "" };
    }

    function renderAttachRow() {
        const row = $("attachRow");
        if (!row) return;
        row.replaceChildren();
        if (!pendingAttachments.length) {
            row.hidden = true;
            return;
        }
        row.hidden = false;
        pendingAttachments.forEach((item, index) => {
            const chip = document.createElement("div");
            chip.className = "attach-chip";
            if (item.kind === "image" && item.data) {
                const img = document.createElement("img");
                img.alt = item.name || "image";
                img.src = "data:" + (item.mime || "image/png") + ";base64," + item.data;
                chip.appendChild(img);
            }
            const name = document.createElement("span");
            name.className = "name";
            name.textContent = item.name || (item.kind === "image" ? "image" : "file");
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "remove";
            remove.setAttribute("aria-label", labels.remove_attachment || "Remove");
            remove.textContent = "×";
            remove.addEventListener("click", () => {
                pendingAttachments.splice(index, 1);
                renderAttachRow();
            });
            chip.append(name, remove);
            row.appendChild(chip);
        });
    }

    function addAttachments(items) {
        (items || []).forEach((item) => {
            if (!item) return;
            if (pendingAttachments.length >= 4) return;
            const dup = pendingAttachments.some((existing) => {
                if (item.data && existing.data) return existing.data === item.data;
                return existing.name && item.name && existing.name === item.name && existing.kind === item.kind;
            });
            if (dup) return;
            pendingAttachments.push(item);
        });
        renderAttachRow();
        focusComposer();
    }

    function insertComposerText(text) {
        const input = $("composerInput");
        if (!input || input.disabled || !text) return;
        const start = input.selectionStart || input.value.length;
        const end = input.selectionEnd || input.value.length;
        input.value = input.value.slice(0, start) + text + input.value.slice(end);
        const pos = start + text.length;
        input.selectionStart = input.selectionEnd = pos;
        autosizeComposer();
        input.focus();
    }

    function fileToAttachment(file) {
        return new Promise((resolve) => {
            if (!file) {
                resolve(null);
                return;
            }
            const isImage = (file.type || "").startsWith("image/");
            const reader = new FileReader();
            reader.onload = () => {
                const result = String(reader.result || "");
                if (isImage) {
                    const comma = result.indexOf(",");
                    const data = comma >= 0 ? result.slice(comma + 1) : result;
                    resolve({
                        kind: "image",
                        name: file.name || "screenshot.png",
                        mime: file.type || "image/png",
                        data: data,
                    });
                    return;
                }
                resolve({
                    kind: "file",
                    name: file.name || "file",
                    mime: file.type || "text/plain",
                    text: result,
                });
            };
            reader.onerror = () => resolve(null);
            if (isImage) reader.readAsDataURL(file);
            else reader.readAsText(file);
        });
    }

    function ingestDataTransfer(dt) {
        if (!dt) return;
        const files = dt.files ? Array.from(dt.files) : [];
        if (!files.length) return;
        Promise.all(files.map(fileToAttachment)).then((items) => {
            addAttachments(items.filter(Boolean));
        });
    }

    function onComposerPaste(ev) {
        const dt = ev.clipboardData;
        if (!dt) return;
        const files = dt.files && dt.files.length ? Array.from(dt.files) : [];
        const items = dt.items ? Array.from(dt.items) : [];
        const imageItems = items.filter((item) => item.kind === "file" && (item.type || "").startsWith("image/"));
        if (!files.length && !imageItems.length) return;
        ev.preventDefault();
        const blobs = files.length ? files : imageItems.map((item) => item.getAsFile()).filter(Boolean);
        Promise.all(blobs.map(fileToAttachment)).then((parsed) => {
            addAttachments(parsed.filter(Boolean));
        });
    }

    function autosizeComposer() {
        const input = $("composerInput");
        if (!input) return;
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
    }

    function focusComposer() {
        const input = $("composerInput");
        if (input && !input.disabled) input.focus();
    }

    window.setTheme = setTheme;
    window.setLabels = (payload) => { labels = payload || {}; applyLabels(); };
    window.setPicker = setPicker;
    window.hidePicker = hidePicker;
    window.showNotice = showNotice;
    window.setHeader = setHeader;
    window.setMessages = setMessages;
    window.clearMessages = clearMessages;
    window.appendChunk = appendChunk;
    window.setThinking = setThinking;
    window.addTool = addTool;
    window.setBusy = setBusy;
    window.setComposerEnabled = setComposerEnabled;
    window.showPermission = showPermission;
    window.hidePermission = hidePermission;
    window.setConfigOptions = setConfigOptions;
    window.addAttachments = addAttachments;
    window.insertComposerText = insertComposerText;
    window.focusComposer = focusComposer;

    bindUi();

    function onReady() {
        if (bridge && bridge.ready) bridge.ready();
    }

    if (window.qt && window.qt.webChannelTransport) {
        new QWebChannel(qt.webChannelTransport, (channel) => {
            bridge = channel.objects.bridge;
            onReady();
        });
    } else {
        document.addEventListener("DOMContentLoaded", onReady);
    }
})();
