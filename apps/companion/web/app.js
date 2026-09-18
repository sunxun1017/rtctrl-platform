"use strict";
(() => {
    const $ = id => document.getElementById(id);
    const labels = {
        offline: ["等待连接", "连接语音服务后，可开启设备麦克风。"],
        connecting: ["正在连接", "正在与语音服务建立连接，请稍候。"],
        idle: ["我在这里", "按住说话，松开后我会回答你。"],
        listening: ["我在听", "正在采集设备麦克风，松开按钮结束。"],
        thinking: ["想一想", "录音已结束，正在等待语音服务回复。"],
        speaking: ["正在回答", "你可以停止回答，再开始下一次对话。"],
        error: ["需要处理", "请查看下方提示，检查设备和服务配置。"],
        muted: ["麦克风已静音", "开启麦克风后，按住按钮才会录音。"]
    };
    const emotions = {neutral:"平静",happy:"开心",sad:"低落",angry:"认真",surprised:"惊喜",thinking:"思考",calm:"平静"};
    let current = {connected:false, muted:true, state:"offline"};
    let reachable = false;
    let held = false;
    let pending = 0;
    let actionQueue = Promise.resolve();
    let actionError = "";
    let statusRevision = 0;
    let displayedError = "";
    function showError(message) {
        const value = String(message || "");
        if (value !== displayedError) {
            $("error").textContent = value;
            displayedError = value;
        }
        $("error").hidden = !value;
    }
    async function request(url, options = {}, timeout = 5000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            const response = await fetch(url, {...options, signal:controller.signal, cache:"no-store"});
            const body = await response.json();
            if (!response.ok || body.ok === false) {
                throw new Error(typeof body.error === "string" ? body.error : "设备请求失败（" + response.status + "）");
            }
            return body;
        } finally { clearTimeout(timer); }
    }
    function render() {
        const state = !reachable ? "offline" : (current.muted && current.state === "idle" ? "muted" : current.state);
        let [label, hint] = labels[state] || ["等待状态", "正在同步设备状态。"];
        const demo = current.capabilities && current.capabilities.mode === "demo";
        const local = !demo && current.capabilities && current.capabilities.voice_backend === "local";
        $("mode-banner").hidden = !demo && !local && reachable;
        $("mode-banner").textContent = demo ? "演示模式 · 模拟对话流程，不采集麦克风、不播放真实声音、不连接语音后端。" : local ? "本地识别与合成 · 千帆文字回答" : "正在获取设备运行模式…";
        $("privacy-note").textContent = demo ? "当前操作仅演示交互。真实语音需要配置后端与设备声卡，并切换运行模式。" : local ? "音频只在设备本地处理，识别后的文字会发送到千帆生成回答。松开结束录音；静音将停止采集。" : "音频在按住说话期间发送到已配置的后端。松开结束录音；静音将停止采集。";
        if (!current.capabilities) $("privacy-note").textContent = "正在确认语音处理方式。麦克风默认静音，开启后按住按钮才会录音。";
        $("input-hint").textContent = demo ? "模拟交互 · 空格 / 回车也可按住体验" : "使用设备麦克风 · 空格 / 回车也可按住说话";
        if (demo) {
            const demoHints = {offline:"点击开始演示，体验设备的对话流程。", muted:"点击启用演示交互，再按住按钮体验。", idle:"按住按钮，松开后查看示例回答。", listening:"正在演示聆听状态，未采集声音；松开查看示例回答。", thinking:"正在准备预设示例回答，未调用真实后端。", speaking:"正在展示预设回答，未播放真实声音。"};
            hint = demoHints[state] || hint;
        }
        if (local) {
            const localLabels = {offline:["等待准备", "点击准备语音，加载本地识别与合成模型。"], connecting:["正在准备", "正在加载本地语音模型，请稍候。"], listening:["我在听", "正在采集设备麦克风，松开后在本地识别。"]};
            [label, hint] = localLabels[state] || [label, hint];
        }
        if (!demo && ["thinking", "speaking"].includes(state)) {
            const progressLabels = {
                waiting_recognition:["等待识别", "录音已结束，正在等待服务识别你说的话。"],
                waiting_reply:["等待回答", "已识别你的话，正在等待回答。"],
                waiting_audio:["等待语音", "服务正在准备语音回复，设备尚未收到声音数据。"],
                receiving_audio:["收到语音回复", "语音已送往设备播放；如没有声音，请检查音量和扬声器。"],
                complete:["本轮已完成", "这一轮对话已结束，稍候可再次按住说话。"],
                failed:["本轮未完成", "请查看错误提示，处理后再重试。"]
            };
            if (local) {
                progressLabels.waiting_recognition = ["本地识别中", "录音已结束，正在设备上识别你说的话。音频不会上传。"];
                progressLabels.waiting_reply = ["等待千帆回答", "已将识别文字发送到千帆，正在等待回答。音频保留在本地处理。"];
                progressLabels.waiting_audio = ["本地合成中", "正在设备上将回答合成为声音，请稍候。完成后由设备扬声器播放。"];
                progressLabels.receiving_audio = ["正在播放回答", "本地合成的语音已送往设备播放；如没有声音，请检查音量和扬声器。"];
            }
            [label, hint] = progressLabels[current.voice_progress] || (state === "speaking" ? progressLabels.waiting_audio : progressLabels.waiting_recognition);
        }
        $("avatar").dataset.voiceProgress = demo ? "receiving_audio" : current.voice_progress || (state === "speaking" ? "waiting_audio" : "idle");
        $("avatar").dataset.state = state;
        $("avatar").dataset.emotion = emotions[current.emotion] ? current.emotion : "neutral";
        $("avatar").setAttribute("aria-label", label);
        $("state-label").textContent = label;
        $("state-hint").textContent = hint;
        $("connection").textContent = !reachable ? "控制台连接中断" : current.connected ? (demo ? "演示已就绪" : local ? "本地语音已就绪" : "语音服务已连接") : (demo ? "控制台在线 · 演示未开始" : local ? "控制台在线 · 本地语音未准备" : "控制台在线 · 语音未连接");
        $("connection-dot").classList.toggle("online", reachable && !!current.connected);
        $("connect").textContent = current.connected ? (demo ? "结束演示" : local ? "关闭语音" : "断开语音服务") : (demo ? "开始演示" : local ? "准备语音" : "连接语音服务");
        $("connect").disabled = !reachable || pending > 0 || current.state === "connecting";
        $("mute").textContent = current.muted ? (demo ? "启用演示交互" : "开启麦克风") : (demo ? "暂停演示交互" : "立即静音");
        $("mute").setAttribute("aria-pressed", String(!!current.muted));
        $("mute").disabled = !reachable;
        $("talk").disabled = !reachable || !current.connected || current.muted || (!held && (pending > 0 || !["idle", "listening"].includes(current.state)));
        $("talk").textContent = held ? (demo ? "模拟聆听 · 松开继续" : "正在听 · 松开结束") : (demo ? "按住体验对话" : "按住说话");
        if (held && ["thinking", "speaking", "error", "offline"].includes(current.state)) $("talk").textContent = "已结束录音 · 请松开";
        $("talk").classList.toggle("held", held && current.state === "listening");
        $("interrupt").disabled = !reachable || !["speaking","thinking","listening"].includes(current.state);
        $("emotion").textContent = emotions[current.emotion] || "平静";
        $("transcript").textContent = current.transcript || "你的话会出现在这里";
        $("reply").textContent = current.reply || (local ? "点击准备语音，待本地模型就绪后开启麦克风。" : "准备好后，连接服务并开启麦克风。");
        const face = current.face || {};
        $("face-state").textContent = face.available ? (face.running ? "运行中" : "已连接 · 未运行") : "未连接";
        const faces = Array.isArray(face.faces) ? face.faces.filter(item => item && typeof item === "object").slice(0, 16) : [];
        $("face-summary").textContent = !face.available ? "人脸服务暂不可用，语音功能可独立使用。" :
            !face.running ? "等待人脸服务启动" : faces.length ? "画面中发现 " + faces.length + " 张人脸" : "画面中暂未检测到人脸";
        const list = document.createDocumentFragment();
        for (const face of faces) {
            const row = document.createElement("li");
            const name = document.createElement("strong");
            name.textContent = !face.name || face.name === "unknown" ? "未登记访客" : String(face.name);
            const score = document.createElement("span");
            score.textContent = Number.isFinite(Number(face.similarity)) ? "相似度 " + Number(face.similarity).toFixed(3) : "";
            row.append(name, score);
            list.append(row);
        }
        $("faces").replaceChildren(list);
        const m = current.metrics || {};
        const finite = value => typeof value === "number" && Number.isFinite(value);
        const metrics = [];
        if (finite(m.memory_used_mb) && finite(m.memory_total_mb)) metrics.push("内存 " + Math.round(m.memory_used_mb) + " / " + Math.round(m.memory_total_mb) + " MB");
        if (finite(m.system_cpu_percent)) metrics.push("整机 CPU " + m.system_cpu_percent.toFixed(1) + "%" + (finite(m.cpu_logical_cores) ? "（" + m.cpu_logical_cores + "核）" : ""));
        metrics.push(finite(m.npu_load_percent) ? "NPU " + m.npu_load_percent.toFixed(0) + "%" : "NPU 暂无读数");
        if (local) metrics.push("ASR / TTS：CPU");
        if (finite(m.rss_mb)) metrics.push("伴随服务 " + m.rss_mb.toFixed(1) + " MB");
        if (finite(m.local_speech_rss_mb)) metrics.push("本地语音模型 " + m.local_speech_rss_mb.toFixed(1) + " MB");
        if (finite(m.local_speech_cpu_percent)) metrics.push("语音 CPU " + m.local_speech_cpu_percent.toFixed(1) + "%（单核100%）");
        if (finite(m.local_speech_peak_rss_mb)) metrics.push("语音峰值 " + m.local_speech_peak_rss_mb.toFixed(1) + " MB");
        if (finite(m.local_speech_threads)) metrics.push("语音线程 " + m.local_speech_threads);
        if (local && m.local_speech_running === false) metrics.push("本地模型进程未运行");
        if (finite(m.cpu_percent)) metrics.push("伴随服务 CPU " + m.cpu_percent.toFixed(1) + "%");
        if (face.available && finite(face.fps)) metrics.push("识别 " + face.fps.toFixed(1) + " FPS");
        $("metrics").textContent = metrics.join(" · ") || "暂未提供资源数据";
        if (finite(m.capture_peak_amplitude)) {
            const peak = m.capture_peak_amplitude;
            $("metrics").textContent += " · 本轮录音峰值 " + peak + " / 32768" +
                (peak > 0 ? "（" + (20 * Math.log10(peak / 32768)).toFixed(1) + " dBFS，" + (peak / 32768 * 100).toFixed(1) + "%）" : "（本轮尚无有效电平）");
        }
        const c = current.capabilities || {};
        const capabilities = [];
        if (c.audio_input === false || c.recording === false) capabilities.push("录音未就绪");
        if (c.playback === false || c.audio_output === false) capabilities.push("播放未就绪");
        if (c.wake_word === false) capabilities.push("唤醒词未启用");
        if (c.aec === false || c.automatic_barge_in === false) capabilities.push("按住说话；回答时请先点击停止，不支持直接说话打断");
        $("capabilities").textContent = capabilities.join(" · ");
        showError(actionError || (typeof current.error === "string" ? current.error : ""));
    }
    function action(name) {
        pending++;
        statusRevision++;
        render();
        actionQueue = actionQueue.then(async () => {
            try {
                const next = await request("/api/action", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action:name})}, 15000);
                if (next && typeof next.state === "string") { current = next; reachable = true; }
                actionError = "";
            } catch (error) {
                actionError = error.name === "AbortError" ? "操作超时，请检查设备连接。" : error.message;
            } finally {
                pending--;
                statusRevision++;
                render();
            }
        });
        return actionQueue;
    }
    function startTalk(event) {
        if (held || $("talk").disabled) return;
        if (event.type === "pointerdown" && event.button !== 0) return;
        event.preventDefault();
        held = true;
        if (event.pointerId !== undefined) $("talk").setPointerCapture(event.pointerId);
        action("listen");
    }
    function stopTalk() {
        if (!held) return;
        held = false;
        action("stop");
    }
    $("connect").addEventListener("click", () => { stopTalk(); action(current.connected ? "disconnect" : "connect"); });
    $("mute").addEventListener("click", () => { stopTalk(); action(current.muted ? "unmute" : "mute"); });
    $("interrupt").addEventListener("click", () => { stopTalk(); action("interrupt"); });
    $("talk").addEventListener("pointerdown", startTalk);
    $("talk").addEventListener("pointerup", stopTalk);
    $("talk").addEventListener("pointercancel", stopTalk);
    $("talk").addEventListener("lostpointercapture", stopTalk);
    $("talk").addEventListener("contextmenu", event => event.preventDefault());
    $("talk").addEventListener("keydown", event => {
        if ([" ", "Enter"].includes(event.key)) {
            event.preventDefault();
            if (!event.repeat) startTalk(event);
        }
    });
    $("talk").addEventListener("keyup", event => {
        if ([" ", "Enter"].includes(event.key)) { event.preventDefault(); stopTalk(); }
    });
    $("talk").addEventListener("blur", stopTalk);
    window.addEventListener("blur", stopTalk);
    document.addEventListener("visibilitychange", () => { if (document.hidden) stopTalk(); });
    window.addEventListener("pagehide", () => {
        if (held) {
            held = false;
            // Server-side recording timeout remains the fallback if this request is lost.
            fetch("/api/action", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action:"stop"}), keepalive:true}).catch(() => {});
        }
    });
    async function poll() {
        const revision = statusRevision;
        try {
            const next = await request("/api/status");
            if (revision === statusRevision && pending === 0) {
                current = next;
                reachable = true;
                $("updated").textContent = "刚刚同步";
                render();
            }
        } catch (error) {
            reachable = false;
            stopTalk();
            $("updated").textContent = "同步中断";
            render();
            showError("无法连接设备控制台，正在自动重试。");
        } finally {
            setTimeout(poll, 1000);
        }
    }
    // Wi-Fi is managed independently from voice. Opening this panel only reads status.
    let network = {available:false, busy:false, networks:[]};
    let networkLoading = false;
    let networkSubmitting = false;
    let networkTimer = null;
    let networkRevision = 0;
    let networkMessage = "";
    const networkPanel = $("network-panel");
    function selectedNetwork() {
        return network.networks.find(item => item.service === $("network-select").value);
    }
    function renderNetwork() {
        const selected = $("network-select").value;
        const list = document.createDocumentFragment();
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = network.networks.length ? "请选择网络" : "暂无网络，请点击扫描 Wi-Fi";
        list.append(placeholder);
        for (const item of network.networks) {
            const option = document.createElement("option");
            option.value = item.service;
            option.textContent = item.ssid + (item.connected && !network.stale && network.service_available !== false && network.service_available !== null ? " · 已连接" : "") + (item.security === "none" || item.security === "open" ? " · 开放网络" : "");
            list.append(option);
        }
        $("network-select").replaceChildren(list);
        $("network-select").value = network.networks.some(item => item.service === selected) ? selected : "";
        const item = selectedNetwork();
        const supported = item && !item.hidden && ["psk", "open", "none"].includes(item.security);
        const busy = network.busy || networkSubmitting;
        const unavailable = !network.available || network.service_available === false;
        const stateUncertain = !!network.stale || network.service_available === null;
        $("network-enable").disabled = unavailable || busy;
        $("network-scan").disabled = unavailable || busy;
        $("network-select").disabled = unavailable || busy || !network.networks.length;
        $("network-password").disabled = unavailable || busy || stateUncertain || !item || !supported || item.connected || item.security === "none" || item.security === "open";
        $("network-connect").disabled = unavailable || busy || stateUncertain || !item || item.connected || !supported;
        $("network-disconnect").disabled = unavailable || busy || stateUncertain || !item || !item.connected;
        $("network-count").textContent = network.available ? network.networks.length + " 个网络" : "";
        const statuses = {idle:"网络管理已就绪。点击扫描发现附近的 Wi-Fi。", enabling:"正在开启 Wi-Fi，设备可能重连已保存的网络…", scanning:"正在扫描附近的 Wi-Fi…", connecting:"正在连接所选网络…", disconnecting:"正在断开所选网络…", error:"上次网络操作失败，请查看提示后重试。"};
        const status = statuses[network.status] || "";
        $("network-status").textContent = !network.available ? "当前设备未启用 Wi-Fi 管理，网线可继续使用。" : network.service_available === false ? "设备的 Wi-Fi 管理服务暂不可用，网线可继续使用。" : busy ? (status && network.status !== "idle" ? status : "正在处理网络操作，请稍候…") : item && !supported ? "此网络类型暂不支持连接，可选择普通密码网络或开放网络。" : status || "网络管理已就绪。点击扫描发现附近的 Wi-Fi。";
        const refreshError = typeof network.refresh_error === "string" ? network.refresh_error : "";
        const refresh = network.stale ? "网络状态已过期，不能确认是否已连接。刷新完成前，连接和断开暂不可用。" : network.refreshing ? "正在后台刷新网络状态，当前网络操作仍可使用。" : network.service_available === null ? "正在确认设备网络服务是否可用…" : "";
        $("network-refresh").textContent = [refresh, refreshError].filter(Boolean).join(" ");
        $("network-refresh").hidden = !refresh && !refreshError;
        const address = item && item.connected && !network.stale && !unavailable && network.service_available !== null && typeof item.ipv4 === "string" ? item.ipv4 : "";
        $("network-address").textContent = address ? "所选 Wi-Fi 已连接 · IPv4：" + address : "";
        $("network-address").hidden = !address;
        const error = networkMessage || (typeof network.error === "string" ? network.error : "");
        $("network-error").textContent = error;
        $("network-error").hidden = !error;
    }
    function acceptNetwork(value) {
        if (!value || typeof value !== "object") throw new Error("invalid network status");
        network = {...value, networks:Array.isArray(value.networks) ? value.networks.filter(item => item && typeof item.service === "string" && typeof item.ssid === "string").slice(0,128) : []};
        renderNetwork();
    }
    function scheduleNetwork() {
        if (networkTimer !== null) clearTimeout(networkTimer);
        networkTimer = null;
        if (networkPanel.open && !document.hidden) networkTimer = setTimeout(pollNetwork, 3000);
    }
    async function pollNetwork() {
        if (!networkPanel.open || document.hidden || networkLoading || networkSubmitting) return;
        networkLoading = true;
        const revision = networkRevision;
        try {
            const next = await request("/api/network");
            if (revision === networkRevision) { networkMessage = ""; acceptNetwork(next); }
        } catch (_) {
            if (revision === networkRevision) {
                networkMessage = "无法读取网络状态，展开此区域时会自动重试。网线可继续使用。";
                network.stale = true;
                renderNetwork();
            }
        } finally {
            networkLoading = false;
            scheduleNetwork();
        }
    }
    async function networkAction(action) {
        if (networkSubmitting || network.busy || !network.available || network.service_available === false) return;
        if (["connect", "disconnect"].includes(action) && (network.stale || network.service_available === null)) return;
        const item = selectedNetwork();
        if (!["scan", "enable"].includes(action) && !item) return;
        if (action === "connect" && (item.hidden || !["psk", "open", "none"].includes(item.security))) return;
        const body = {action};
        if (item && !["scan", "enable"].includes(action)) body.service = item.service;
        if (action === "connect") body.password = $("network-password").disabled ? "" : $("network-password").value;
        // Clear immediately, including failed submissions; never persist credentials.
        $("network-password").value = "";
        networkSubmitting = true;
        networkRevision++;
        networkMessage = "";
        renderNetwork();
        try {
            const next = await request("/api/network", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}, 15000);
            if (typeof next.available === "boolean") acceptNetwork(next);
            else network.busy = true;
        } catch (_) {
            networkMessage = "网络操作未完成，请查看设备状态后重试。若正在切换 Wi-Fi，控制台可能暂时断开。";
        } finally {
            delete body.password;
            networkSubmitting = false;
            networkRevision++;
            renderNetwork();
            scheduleNetwork();
        }
    }
    $("network-enable").addEventListener("click", () => networkAction("enable"));
    $("network-scan").addEventListener("click", () => networkAction("scan"));
    $("network-form").addEventListener("submit", event => { event.preventDefault(); networkAction("connect"); });
    $("network-disconnect").addEventListener("click", () => networkAction("disconnect"));
    $("network-select").addEventListener("change", () => { $("network-password").value = ""; renderNetwork(); });
    networkPanel.addEventListener("toggle", () => {
        if (networkPanel.open && !document.hidden) pollNetwork();
        else { $("network-password").value = ""; scheduleNetwork(); }
    });
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && networkPanel.open) pollNetwork();
        else scheduleNetwork();
    });
    // Device settings are read on expansion; edits require an explicit application.
    const devicePanel = $("device-panel");
    const deviceFields = {
        volume:{key:"volume_percent", unit:"%", min:0, max:100},
        speaker:{key:"speaker_enabled"},
        mic_gain:{key:"mic_gain_db", unit:" dB", values:[0,6,12,18,24,30,36,42]},
        brightness:{key:"brightness_percent", unit:"%", min:10, max:100}
    };
    let device = {available:false, supported:{}};
    let deviceLoading = false, deviceSubmitting = false, deviceTimer = null;
    let deviceRevision = 0, deviceMessage = "";
    const deviceDirty = new Set();
    function validDeviceValue(name, value) {
        const field = deviceFields[name];
        return name === "speaker" ? typeof value === "boolean" : Number.isInteger(value) &&
            (field.values ? field.values.includes(value) : value >= field.min && value <= field.max);
    }
    function renderDevice() {
        const usable = device.available && !device.error && !deviceMessage;
        const busy = deviceSubmitting || device.busy;
        $("device-status").textContent = deviceSubmitting ? "正在应用设置并读取设备实际值…" :
            !usable ? "设备设置暂不可用，展开此区域时会自动重试。" : device.busy ? "设备正在处理设置，请稍候。" : "已读取设备设置；修改后点击对应的应用按钮。";
        $("device-error").textContent = deviceMessage || device.error || "";
        $("device-error").hidden = !$("device-error").textContent;
        $("device-diagnostic").textContent = typeof device.diagnostic === "string" ? device.diagnostic : "";
        for (const [name, field] of Object.entries(deviceFields)) {
            const input = $("device-" + name);
            const value = device[field.key];
            const readable = name === "mic_gain" ? typeof value === "number" && Number.isFinite(value) :
                name === "brightness" ? Number.isInteger(value) && value >= 0 && value <= 100 : validDeviceValue(name, value);
            const known = usable && device.supported[name] === true && readable;
            input.disabled = !known || busy;
            $("device-" + name + "-apply").disabled = !known || busy || !deviceDirty.has(name);
            $("device-" + name + "-current").textContent = known ? (device.busy ? "上次读取：" : "设备当前：") +
                (name === "speaker" ? (value ? "已打开" : "已关闭") : value + field.unit) :
                usable && device.supported[name] === false ? "此设备暂不支持" : "状态未知";
            if (!known) {
                deviceDirty.delete(name);
                input.value = "";
            } else if (!deviceDirty.has(name) && document.activeElement !== input) {
                input.value = name === "mic_gain" && !field.values.includes(value) ? "" :
                    name === "brightness" ? String(Math.max(field.min, value)) : String(value);
            }
            if (known && name === "brightness" && value < field.min) {
                deviceDirty.add(name);
                $("device-" + name + "-apply").disabled = !!busy;
            }
            if (name === "volume" || name === "brightness") {
                $("device-" + name + "-value").textContent = known ? input.value + "%" : "—";
                input.setAttribute("aria-valuetext", known ? input.value + "%" : "状态未知");
            }
        }
    }
    function acceptDevice(next) {
        if (!next || typeof next.available !== "boolean" || !next.supported || typeof next.supported !== "object") throw new Error("设备设置响应无效");
        device = next;
        renderDevice();
    }
    function scheduleDevice() {
        if (deviceTimer !== null) clearTimeout(deviceTimer);
        deviceTimer = null;
        if (devicePanel.open && !document.hidden) deviceTimer = setTimeout(pollDevice, 5000);
    }
    async function pollDevice() {
        if (!devicePanel.open || document.hidden || deviceLoading || deviceSubmitting) return;
        deviceLoading = true;
        const revision = deviceRevision;
        try {
            const next = await request("/api/device");
            if (revision === deviceRevision) { deviceMessage = ""; acceptDevice(next); }
        } catch (_) {
            if (revision === deviceRevision) {
                device = {available:false, supported:{}};
                deviceMessage = "无法读取设备设置，恢复连接后再试。";
                renderDevice();
            }
        } finally { deviceLoading = false; scheduleDevice(); }
    }
    async function applyDevice(name) {
        const input = $("device-" + name);
        if (input.disabled || !deviceDirty.has(name) || deviceSubmitting) return;
        const value = name === "speaker" ? input.value === "true" : Number(input.value);
        if (!validDeviceValue(name, value)) return;
        deviceSubmitting = true;
        deviceRevision++;
        deviceMessage = "";
        renderDevice();
        try {
            const next = await request("/api/device", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action:"set_" + name, value})}, 10000);
            deviceDirty.delete(name);
            acceptDevice(next);
            // Read-back wins over the submitted value, even when the field retains focus.
            if (validDeviceValue(name, device[deviceFields[name].key])) input.value = String(device[deviceFields[name].key]);
        } catch (error) {
            device = {available:false, supported:{}};
            deviceMessage = error.name === "AbortError" ? "设置请求超时，无法确认结果，正在重新读取设备。" : error.message;
        } finally {
            deviceSubmitting = false;
            deviceRevision++;
            renderDevice();
            scheduleDevice();
        }
    }
    for (const name of Object.keys(deviceFields)) {
        $("device-" + name).addEventListener("input", () => { deviceDirty.add(name); renderDevice(); });
        $("device-" + name + "-form").addEventListener("submit", event => { event.preventDefault(); applyDevice(name); });
    }
    devicePanel.addEventListener("toggle", () => { if (devicePanel.open) pollDevice(); else scheduleDevice(); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden && devicePanel.open) pollDevice(); else scheduleDevice(); });
    render();
    poll();
})();
