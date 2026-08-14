/* Pynia ACP chat WebView */
(function () {
    const $ = (id) => document.getElementById(id);
    let bridge = null;
    let labels = {};
    let pendingPermissionId = null;
    let busy = false;

    function setTheme(theme) {
        const root = document.documentElement;
        Object.entries(theme || {}).forEach(([key, value]) => {
            root.style.setProperty("--" + key.split("_").join("-"), value);
        });
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
        $("settingsBtn").textContent = labels.open_settings || "Settings";
        $("pickerHint").textContent = labels.pick_agent || "Choose an agent to start this tab's chat.";
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

    function setMessages(messages) {
        clearMessages();
        (messages || []).forEach((msg) => {
            if (msg.role === "user") {
                const el = addMessage("user", "");
                el.textContent = msg.content || "";
            } else {
                addMessage("assistant", renderMarkdown(msg.content || ""));
            }
        });
        if ((messages || []).length > 0) {
            $("picker").hidden = true;
        }
    }

    function appendChunk(text) {
        $("picker").hidden = true;
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

    function setThinking(text) {
        let el = document.getElementById("thinkingLive");
        if (!el) {
            el = document.createElement("div");
            el.id = "thinkingLive";
            el.className = "thinking";
            $("messages").appendChild(el);
        }
        el.textContent = text || labels.thinking || "Thinking…";
        scrollToBottom();
    }

    function addTool(payload) {
        const el = document.createElement("div");
        el.className = "tool-card";
        el.textContent = payload.title || payload.sessionUpdate || "tool";
        $("messages").appendChild(el);
        scrollToBottom();
    }

    function setBusy(isBusy) {
        busy = !!isBusy;
        $("cancelBtn").hidden = !busy;
        $("sendBtn").hidden = busy;
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
        if (busy) return;
        const input = $("composerInput");
        const text = (input.value || "").trim();
        if (!text) return;
        input.value = "";
        if (bridge) bridge.sendMessage(text);
    }

    function answer(optionId) {
        if (pendingPermissionId == null || !bridge) return;
        bridge.answerPermission(String(pendingPermissionId), optionId);
        hidePermission();
    }

    function bindUi() {
        $("sendBtn").addEventListener("click", sendCurrent);
        $("cancelBtn").addEventListener("click", () => bridge && bridge.cancel());
        $("settingsBtn").addEventListener("click", () => bridge && bridge.openSettings());
        $("permAllowOnce").addEventListener("click", () => answer("allow-once"));
        $("permAllowAlways").addEventListener("click", () => answer("allow-always"));
        $("permReject").addEventListener("click", () => answer("reject-once"));
        $("composerInput").addEventListener("keydown", (ev) => {
            if (ev.key === "Enter" && !ev.shiftKey) {
                ev.preventDefault();
                sendCurrent();
            }
        });
    }

    window.setTheme = setTheme;
    window.setLabels = (payload) => { labels = payload || {}; };
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
    window.showPermission = showPermission;
    window.hidePermission = hidePermission;
    window.focusComposer = () => $("composerInput").focus();

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
