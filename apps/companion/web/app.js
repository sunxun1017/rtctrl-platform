"use strict";
(() => {
    const $ = id => document.getElementById(id);
    const labels = {
        offline: ["等待连接", "连接语音服务后，可开启设备麦克风。"],
        connecting: ["正在连接", "正在与语音服务建立连接，请稍候。"],
        idle: ["我在这里", "按住说话，松开后我会回答你。"],
        listening: ["我在听", "正在采集设备麦克风，松开按钮结束。"],
        thinking: ["想一想", "已收到你的话，正在准备回答。"],
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
        $("mode-banner").hidden = !demo && reachable;
        $("mode-banner").textContent = demo ? "演示模式 · 模拟对话流程，不采集麦克风、不播放真实声音、不连接语音后端。" : "正在获取设备运行模式…";
        $("privacy-note").textContent = demo ? "当前操作仅演示交互。真实语音需要配置后端与设备声卡，并切换运行模式。" : "音频在按住说话期间发送到已配置的后端。松开结束录音；静音将停止采集。";
        $("input-hint").textContent = demo ? "模拟交互 · 空格 / 回车也可按住体验" : "使用设备麦克风 · 空格 / 回车也可按住说话";
        if (demo) {
            const demoHints = {offline:"点击开始演示，体验设备的对话流程。", muted:"点击启用演示交互，再按住按钮体验。", idle:"按住按钮，松开后查看示例回答。", listening:"正在演示聆听状态，未采集声音；松开查看示例回答。", thinking:"正在准备预设示例回答，未调用真实后端。", speaking:"正在展示预设回答，未播放真实声音。"};
            hint = demoHints[state] || hint;
        }
        $("avatar").dataset.state = state;
        $("avatar").dataset.emotion = emotions[current.emotion] ? current.emotion : "neutral";
        $("avatar").setAttribute("aria-label", label);
        $("state-label").textContent = label;
        $("state-hint").textContent = hint;
        $("connection").textContent = !reachable ? "控制台连接中断" : current.connected ? (demo ? "演示已就绪" : "语音服务已连接") : (demo ? "控制台在线 · 演示未开始" : "控制台在线 · 语音未连接");
        $("connection-dot").classList.toggle("online", reachable && !!current.connected);
        $("connect").textContent = current.connected ? (demo ? "结束演示" : "断开语音服务") : (demo ? "开始演示" : "连接语音服务");
        $("connect").disabled = !reachable || pending > 0 || current.state === "connecting";
        $("mute").textContent = current.muted ? (demo ? "启用演示交互" : "开启麦克风") : (demo ? "暂停演示交互" : "立即静音");
        $("mute").setAttribute("aria-pressed", String(!!current.muted));
        $("mute").disabled = !reachable;
        $("talk").disabled = !reachable || !current.connected || current.muted || (!held && (pending > 0 || !["idle", "listening"].includes(current.state)));
        $("talk").textContent = held ? (demo ? "模拟聆听 · 松开继续" : "正在听 · 松开结束") : (demo ? "按住体验对话" : "按住说话");
        $("talk").classList.toggle("held", held);
        $("interrupt").disabled = !reachable || !["speaking","thinking","listening"].includes(current.state);
        $("emotion").textContent = emotions[current.emotion] || "平静";
        $("transcript").textContent = current.transcript || "你的话会出现在这里";
        $("reply").textContent = current.reply || "准备好后，连接服务并开启麦克风。";
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
        if (finite(m.rss_mb)) metrics.push("伴随服务 " + m.rss_mb.toFixed(1) + " MB");
        if (finite(m.cpu_percent)) metrics.push("伴随服务 CPU " + m.cpu_percent.toFixed(1) + "%");
        if (face.available && finite(face.fps)) metrics.push("识别 " + face.fps.toFixed(1) + " FPS");
        $("metrics").textContent = metrics.join(" · ") || "暂未提供资源数据";
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
    render();
    poll();
})();
