const UI_PREFS_KEY = "law-study-workbench.ui.v2";
const DEFAULT_UI_PREFERENCES = {
  theme: "dark",
  density: "comfortable",
  motion: "full",
  fontScale: "100",
};

const state = {
  view: "today",
  info: null,
  today: null,
  sources: [],
  selectedSourceId: null,
  units: [],
  activeSession: null,
  learningModel: null,
  feedback: null,
  startedAtMs: null,
  timerHandle: null,
  importPolling: null,
  draftSaveTimer: null,
  retrievalSummary: null,
  retrievalDue: [],
  retrievalAll: [],
  retrievalQueue: [],
  retrievalActive: null,
  retrievalReveal: null,
  retrievalResult: null,
  retrievalStartedAtMs: null,
  retrievalCompleted: 0,
  retrievalQueueLabel: "到期复习",
  retrievalSubmitting: false,
  unitQuery: "",
  unitFilter: "all",
  unitSort: "page",
  unitVisibleCount: 25,
  retrievalQuery: "",
  retrievalFilter: "all",
  retrievalSort: "due",
  retrievalVisibleCount: 20,
  sourcePaneCollapsed: false,
  dialogContext: null,
  unitDialogContext: null,
  unitSelection: null,
  pdfViewer: null,
  draftStatus: "saved",
  portableImportResult: null,
  preferences: loadUiPreferences(),
};

const viewMeta = {
  today: ["学习任务", "今日学习", "先处理今天真正该做的任务，再回到教材与卡片。"],
  library: ["本地知识库", "本地教材库", "导入、解析并沉淀教材来源，让知识单元和页码可追溯。"],
  study: ["完整复现", "闭卷学习", "先独立作答，再对照来源，保留真实提取证据而不是阅读痕迹。"],
  retrieval: ["主动提取", "挖空与闪卡", "把长知识拆成可复测的小节点，用短提取巩固术语、要件和例外。"],
  model: ["学习证据", "学习证据画像", "查看真实作答、错误修复和最近证据，不把聚合统计冒充个体预测模型。"],
  settings: ["数据主权", "设置与数据", "管理目标、隐私边界和本地学习数据，保证知识资产掌握在自己手里。"],
};

const $ = (selector) => document.querySelector(selector);
const content = $("#content");
let pageKeyHandler = null;

function setPageKeyHandler(handler) {
  if (pageKeyHandler) document.removeEventListener("keydown", pageKeyHandler);
  pageKeyHandler = handler || null;
  if (pageKeyHandler) document.addEventListener("keydown", pageKeyHandler);
}

function isEditableTarget(target) {
  return Boolean(target?.closest?.("input, textarea, select, [contenteditable=\"true\"]"));
}

function loadUiPreferences() {
  try {
    const raw = localStorage.getItem(UI_PREFS_KEY);
    return { ...DEFAULT_UI_PREFERENCES, ...(raw ? JSON.parse(raw) : {}) };
  } catch (_) {
    return { ...DEFAULT_UI_PREFERENCES };
  }
}

function saveUiPreferences() {
  try {
    localStorage.setItem(UI_PREFS_KEY, JSON.stringify(state.preferences));
  } catch (_) {
    // 在受限预览环境中 localStorage 可能不可用，界面偏好仍应即时生效。
  }
  applyUiPreferences();
}

function resolvedTheme(preference = state.preferences.theme) {
  if (preference !== "system") return preference;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyUiPreferences() {
  const root = document.documentElement;
  root.dataset.theme = resolvedTheme();
  root.dataset.themePreference = state.preferences.theme;
  root.dataset.density = state.preferences.density;
  root.dataset.motion = state.preferences.motion;
  root.style.setProperty("--ui-scale", `${Number(state.preferences.fontScale || 100) / 100}`);
  const themeToggle = $("#themeToggle span");
  if (themeToggle) themeToggle.textContent = root.dataset.theme === "dark" ? "☼" : "☾";
  const themeButton = $("#themeToggle");
  if (themeButton) themeButton.setAttribute("aria-label", root.dataset.theme === "dark" ? "切换到浅色主题" : "切换到深色主题");
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  if (themeMeta) themeMeta.setAttribute("content", root.dataset.theme === "dark" ? "#07111f" : "#eef2f6");
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "尚未安排";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDuration(milliseconds = 0) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function taskEstimate(task, type) {
  if (type === "active") return "继续完成";
  if (type === "retrieval") return "约 2–5 分钟";
  if (task?.objective_type === "表达型") return "约 12–18 分钟";
  return "约 8–12 分钟";
}

function toast(message, isError = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast is-visible${isError ? " error" : ""}`;
  clearTimeout(element._timer);
  element._timer = setTimeout(() => {
    element.className = "toast";
  }, 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `请求失败：${response.status}`;
    try {
      const body = await response.json();
      if (body.detail) {
        detail = Array.isArray(body.detail) ? body.detail.map((item) => item.msg || JSON.stringify(item)).join("；") : body.detail;
      }
    } catch (_) {}
    throw new Error(detail);
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response;
}

function renderLoadingState(label = "正在读取本地学习状态…") {
  return `<div class="loading-state"><div class="loading-orbit" aria-hidden="true"><span></span></div><p>${escapeHtml(label)}</p></div>`;
}

function updateShellUI() {
  document.body.dataset.view = state.view;
  document.querySelectorAll(".nav-item").forEach((item) => {
    const active = item.dataset.view === state.view;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });

  const today = state.today || { due: [], retrieval_due: [], attempts_today: 0, retrieval_attempts_today: 0, active: null };
  const completed = Number(today.attempts_today || 0) + Number(today.retrieval_attempts_today || 0);
  const remaining = Number(today.due?.length || 0) + Number(today.retrieval_due?.length || 0) + (today.active ? 1 : 0);
  const total = completed + remaining;
  const progress = total ? clamp(Math.round((completed / total) * 100), 0, 100) : 0;
  const pulse = $("#sidebarPulse");
  if (pulse) {
    pulse.innerHTML = `
      <div class="sidebar-pulse-head"><span>今日轨道</span><span class="pulse-mini">${remaining ? `${remaining} 项待完成` : "已清空"}</span></div>
      <div class="sidebar-pulse-value">${completed}<small> 次学习动作</small></div>
      <div class="sidebar-pulse-caption">${today.active ? "有一轮未完成闭卷，可从原位置继续" : remaining ? "优先处理到期任务，避免系统建设挤占学习" : "今日暂无到期任务，可开始新的知识单元"}</div>
      <div class="mini-progress" role="progressbar" aria-label="到期队列清理进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"><span style="width:${progress}%"></span></div>`;
  }
}

function setView(view, { focus = true } = {}) {
  state.view = view;
  const [eyebrow, title, description] = viewMeta[view];
  $("#viewEyebrow").textContent = eyebrow;
  $("#viewTitle").textContent = title;
  $("#viewDescription").textContent = description;
  updateShellUI();
  render();
  // 深链接：视图同步到 URL hash。刷新保持视图、浏览器后退/前进回到上一个视图、
  // 具体页面可收藏（#/today、#/library、#/retrieval…）。
  const targetHash = `#/${view}`;
  if (location.hash !== targetHash) location.hash = targetHash;
  if (focus) {
    requestAnimationFrame(() => content?.focus({ preventScroll: true }));
    if (window.innerWidth < 820) window.scrollTo({ top: 0, behavior: document.documentElement.dataset.motion === "reduced" ? "auto" : "smooth" });
  }
}

// 浏览器后退/前进/直接输入 hash：把 URL 恢复成对应视图（hashchange 在 setView
// 写回同一 hash 时不会再次触发，无循环）。
window.addEventListener("hashchange", () => {
  const match = location.hash.match(/^#\/([a-z]+)/);
  const view = match ? match[1] : "today";
  if (viewMeta[view] && view !== state.view) setView(view, { focus: false });
});

async function loadCore({ silent = false } = {}) {
  if (!silent) content.innerHTML = renderLoadingState();
  try {
    const [info, today, sources, active, model, retrievalSummary, retrievalDue, retrievalAll] = await Promise.all([
      api("/api/app-info"),
      api("/api/today"),
      api("/api/sources"),
      api("/api/sessions/active"),
      api("/api/learning-model"),
      api("/api/retrieval/summary"),
      api("/api/retrieval-items?due_only=true&limit=100"),
      api("/api/retrieval-items?include_answer=true&limit=100"),
    ]);
    state.info = info;
    state.today = today;
    state.sources = sources;
    state.activeSession = active;
    state.learningModel = model;
    state.retrievalSummary = retrievalSummary;
    state.retrievalDue = retrievalDue;
    state.retrievalAll = retrievalAll;
    if (active && !state.startedAtMs) state.startedAtMs = new Date(active.started_at).getTime();
    if (!state.selectedSourceId && sources.length) state.selectedSourceId = sources[0].id;
    if (state.selectedSourceId) await loadUnits(state.selectedSourceId, { renderAfter: false });
    updateProviderUI();
    updateShellUI();
    manageImportPolling();
    render();
  } catch (error) {
    content.innerHTML = `<div class="empty-state error-state"><div class="empty-symbol">!</div><h2>无法读取本地服务</h2><p>${escapeHtml(error.message)}</p><button class="primary-button" onclick="loadCore()">重新连接</button></div>`;
  }
}

function updateProviderUI() {
  if (!state.info) return;
  const provider = state.info.provider;
  const chip = $("#providerChip");
  if (provider.sends_to_cloud) {
    chip.textContent = provider.configured ? "云端推理已配置 · 最小上下文" : "云端推理尚未完成配置";
    $("#privacyMode").textContent = "教材本地保存 · 当前任务片段可发送云端";
  } else {
    chip.textContent = "本地证据评分 · 零云端发送";
    $("#privacyMode").textContent = "教材、答案与学习记录仅存本机";
  }
}

async function loadUnits(sourceId, { renderAfter = true } = {}) {
  try {
    state.units = await api(`/api/sources/${sourceId}/units`);
    if (renderAfter) render();
  } catch (error) {
    toast(error.message, true);
  }
}

function manageImportPolling() {
  const hasPending = state.sources.some((source) => ["queued", "parsing"].includes(source.status));
  if (hasPending && !state.importPolling) {
    state.importPolling = setInterval(() => loadCore({ silent: true }), 1800);
  }
  if (!hasPending && state.importPolling) {
    clearInterval(state.importPolling);
    state.importPolling = null;
  }
}

function render() {
  stopTimer();
  setPageKeyHandler(null);
  updateShellUI();
  if (state.view === "today") renderToday();
  if (state.view === "library") renderLibrary();
  if (state.view === "study") renderStudy();
  if (state.view === "retrieval") renderRetrieval();
  if (state.view === "model") renderModel();
  if (state.view === "settings") renderSettings();
}

function deriveTodayFocus(today, retrieval, hasData) {
  if (today.active) {
    return {
      type: "active",
      kicker: "继续未完成会话",
      title: today.active.title,
      description: "草稿、计时和提示使用已经保留。回到同一知识单元完成真实闭卷，不需要从头整理。",
      meta: [today.active.original_name, `第 ${today.active.page_start}-${today.active.page_end} 页`, taskEstimate(today.active, "active")],
      action: `<button class="primary-button" data-action="resume-session">继续上次学习</button>`,
    };
  }
  if (today.due?.length) {
    const task = today.due[0];
    return {
      type: "review",
      kicker: "到期完整复测",
      title: task.title,
      description: "它已经到达下一次完整提取时间。先闭卷恢复规则和边界，再回到教材核验。",
      meta: [task.original_name, `第 ${task.page_start}-${task.page_end} 页`, taskEstimate(task, "review")],
      action: `<button class="primary-button" data-action="start-unit" data-unit-id="${task.id}">开始完整复测</button>`,
    };
  }
  if (today.retrieval_due?.length) {
    const item = today.retrieval_due[0];
    return {
      type: "retrieval",
      kicker: "到期短提取",
      title: item.prompt,
      description: "先把已经到期的术语、条件和规则节点提取出来，避免短期熟悉感被误判为长期掌握。",
      meta: [item.item_type === "cloze" ? "挖空" : "闪卡", item.unit_title, taskEstimate(item, "retrieval")],
      action: `<button class="primary-button" data-action="start-retrieval-item" data-item-id="${item.id}">开始这张卡片</button>`,
    };
  }
  if (today.suggested?.length) {
    const task = today.suggested[0];
    return {
      type: "new",
      kicker: "建议开始",
      title: task.title,
      description: "当前没有更高优先级的到期任务。用一次无提示闭卷建立这个知识单元的第一条真实证据。",
      meta: [task.original_name, `第 ${task.page_start}-${task.page_end} 页`, taskEstimate(task, "new")],
      action: `<button class="primary-button" data-action="start-unit" data-unit-id="${task.id}">开始新的知识单元</button>`,
    };
  }
  return {
    type: hasData ? "clear" : "import",
    kicker: hasData ? "今日轨道已清空" : "建立第一条学习链",
    title: hasData ? "今天没有到期任务，可以主动选择下一块知识。" : "导入第一本教材，完成一次从来源到复测的真实闭环。",
    description: hasData
      ? "可以继续新的知识单元，也可以回到教材库检查知识单元与卡片质量。"
      : "文件、索引和学习记录默认留在本机。第一版先用文字型 PDF 跑通导入、闭卷、反馈和复测。",
    meta: hasData ? ["无逾期任务", `${retrieval.total || 0} 张活动卡片`, "学习节奏可自行推进"] : ["本地导入", "页码可追溯", "零云端必选项"],
    action: `<button class="primary-button" data-action="go-library">${hasData ? "选择下一个知识单元" : "导入第一本教材"}</button>`,
  };
}

function renderToday() {
  const today = state.today || { due: [], suggested: [], active: null, attempts_today: 0, retrieval_due: [], retrieval_attempts_today: 0 };
  const retrieval = state.retrievalSummary || { due: 0, total: 0, reviewed_today: 0 };
  const sourceCount = state.info?.source_count || 0;
  const unitCount = state.info?.unit_count || 0;
  const hasData = sourceCount > 0;
  const focus = deriveTodayFocus(today, retrieval, hasData);
  const completed = Number(today.attempts_today || 0) + Number(today.retrieval_attempts_today || 0);
  const remaining = Number(today.due?.length || 0) + Number(today.retrieval_due?.length || 0) + (today.active ? 1 : 0);
  const total = completed + remaining;
  const progress = total ? clamp(Math.round((completed / total) * 100), 0, 100) : 0;

  content.innerHTML = `
    <section class="focus-stage" data-focus-type="${focus.type}">
      <div class="focus-copy">
        <div class="focus-kicker"><span class="evidence-dot"></span>${escapeHtml(focus.kicker)}</div>
        <h2>${escapeHtml(focus.title)}</h2>
        <p>${escapeHtml(focus.description)}</p>
        <div class="focus-meta">${focus.meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
        <div class="focus-actions">
          ${focus.action}
          ${retrieval.total ? `<button class="secondary-button" data-action="start-retrieval-queue" data-due-only="true">${retrieval.due ? `复习 ${retrieval.due} 张到期卡片` : "打开挖空与闪卡"}</button>` : ""}
          <button class="ghost-button" data-action="go-library">查看教材库</button>
        </div>
      </div>
      <aside class="focus-progress" aria-label="到期队列清理进度">
        <div class="progress-orbit" style="--progress:${progress * 3.6}deg" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}">
          <div><strong>${progress}%</strong><span>今日轨道</span></div>
        </div>
        <dl class="progress-ledger">
          <div><dt>已完成</dt><dd>${completed}</dd></div>
          <div><dt>待完成</dt><dd>${remaining}</dd></div>
          <div><dt>知识单元</dt><dd>${unitCount}</dd></div>
        </dl>
      </aside>
    </section>

    <section class="today-ledger" aria-label="今日证据概况">
      <article><span class="ledger-index">01</span><div><strong>${today.attempts_today || 0}</strong><span>完整闭卷</span></div><p>有提交、有来源对照的整段复现</p></article>
      <article><span class="ledger-index">02</span><div><strong>${today.retrieval_attempts_today || 0}</strong><span>短提取</span></div><p>挖空与闪卡的真实作答</p></article>
      <article><span class="ledger-index">03</span><div><strong>${retrieval.due || 0}</strong><span>到期卡片</span></div><p>需要优先处理的复测节点</p></article>
      <article><span class="ledger-index">04</span><div><strong>${sourceCount}</strong><span>本地教材</span></div><p>共沉淀 ${unitCount} 个知识单元</p></article>
    </section>

    <section class="section plan-section">
      <div class="section-head">
        <div><div class="section-kicker">TODAY PLAN</div><h2>今天按这条轨道推进</h2><p>先完成到期任务，再开始新知识；系统功能不应抢走学习时间。</p></div>
      </div>
      <div class="plan-track">
        <article class="plan-node ${today.active || today.due?.length || today.retrieval_due?.length ? "is-current" : "is-done"}"><span>1</span><div><strong>清理到期</strong><p>${remaining ? `仍有 ${remaining} 项高优先级任务` : "当前没有到期任务"}</p></div></article>
        <article class="plan-node ${!remaining && today.suggested?.length ? "is-current" : completed ? "is-ready" : ""}"><span>2</span><div><strong>建立新证据</strong><p>${today.suggested?.length ? `${today.suggested.length} 个知识单元可开始` : "等待新的知识单元"}</p></div></article>
        <article class="plan-node ${completed ? "is-ready" : ""}"><span>3</span><div><strong>回看错误</strong><p>${state.learningModel?.recurring_errors?.length ? `${state.learningModel.recurring_errors.length} 类反复错误待修复` : "暂无反复错误记录"}</p></div></article>
      </div>
    </section>

    ${today.active ? renderActiveTask(today.active) : ""}
    ${renderRetrievalTaskSection(today.retrieval_due || [])}
    ${renderTaskSection("今日到期完整复测", "这些知识已经到达下一次完整提取时间。", today.due, "review")}
    ${renderTaskSection("建议开始", "没有更高优先级任务时，从这里建立新的闭卷证据。", today.suggested, "new")}
  `;
  bindCommonActions();
}

function renderActiveTask(active) {
  return `
    <section class="section">
      <div class="section-head"><div><div class="section-kicker">RESUME</div><h2>未完成会话</h2><p>草稿与提示使用已经本地保存，继续即可。</p></div><span class="count-chip">1 项</span></div>
      <div class="task-lane">
        <article class="task-row is-priority">
          <span class="task-sequence">续</span>
          <div class="task-main">
            <div class="task-title">${escapeHtml(active.title)}</div>
            <div class="task-meta"><span>${escapeHtml(active.original_name)}</span><span>第 ${active.page_start}-${active.page_end} 页</span><span>开始于 ${formatDate(active.started_at)}</span></div>
          </div>
          <div class="task-actions"><button class="primary-button small-button" data-action="resume-session">继续回答</button></div>
        </article>
      </div>
    </section>`;
}

function renderTaskSection(title, description, tasks, mode) {
  if (!tasks?.length) return "";
  return `
    <section class="section">
      <div class="section-head"><div><div class="section-kicker">${mode === "review" ? "FULL RECALL" : "NEW UNIT"}</div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div><span class="count-chip">${tasks.length} 项</span></div>
      <div class="task-lane">
        ${tasks.map((task, index) => `
          <article class="task-row ${mode === "review" ? "is-priority" : ""}">
            <span class="task-sequence">${String(index + 1).padStart(2, "0")}</span>
            <div class="task-main">
              <div class="task-title">${escapeHtml(task.title)}</div>
              <div class="task-meta">
                <span>${escapeHtml(task.original_name)}</span>
                <span>第 ${task.page_start}-${task.page_end} 页</span>
                ${task.objective_type ? `<span>${escapeHtml(task.objective_type)}</span>` : ""}
                ${task.mastery_status ? `<span>${escapeHtml(task.mastery_status)} · 上次 ${Number(task.last_score || 0).toFixed(0)} 分</span>` : ""}
                ${task.due_at ? `<span>到期 ${formatDate(task.due_at)}</span>` : ""}
              </div>
            </div>
            <span class="task-estimate">${taskEstimate(task, mode)}</span>
            <div class="task-actions"><button class="${mode === "review" ? "primary-button" : "secondary-button"} small-button" data-action="start-unit" data-unit-id="${task.id}">${mode === "review" ? "开始复测" : "开始学习"}</button></div>
          </article>`).join("")}
      </div>
    </section>`;
}

function renderRetrievalTaskSection(items) {
  if (!items?.length) return "";
  return `
    <section class="section">
      <div class="section-head"><div><div class="section-kicker">SHORT RETRIEVAL</div><h2>今日到期挖空与闪卡</h2><p>短提取用于巩固关键词、条件、术语与规则节点。</p></div><span class="count-chip">${items.length} 项</span></div>
      <div class="task-lane compact-lane">
        ${items.map((item, index) => `
          <article class="task-row">
            <span class="task-sequence">${String(index + 1).padStart(2, "0")}</span>
            <div class="task-main">
              <div class="task-title">${escapeHtml(item.prompt)}</div>
              <div class="task-meta"><span>${item.item_type === "cloze" ? "挖空" : "闪卡"}</span><span>${escapeHtml(item.unit_title)}</span><span>${escapeHtml(item.original_name)}</span><span>第 ${item.page_start}-${item.page_end} 页</span></div>
            </div>
            <span class="task-estimate">约 2–5 分钟</span>
            <div class="task-actions"><button class="secondary-button small-button" data-action="start-retrieval-item" data-item-id="${item.id}">开始提取</button></div>
          </article>`).join("")}
      </div>
    </section>`;
}

function renderLibrary() {
  const selected = state.sources.find((source) => source.id === state.selectedSourceId);
  content.innerHTML = `
    <div class="library-workspace">
      <aside class="library-rail">
        <article class="import-panel" id="importZone">
          <input id="pdfInput" type="file" accept="application/pdf,.pdf">
          <div class="import-symbol" aria-hidden="true">＋</div>
          <div>
            <div class="section-kicker">LOCAL IMPORT</div>
            <h2>添加本地教材</h2>
            <p>原文件、索引和学习记录默认留在本机。文字型 PDF 可先开始，低文本页面会单独标记。</p>
          </div>
          <label class="primary-button" for="pdfInput">选择 PDF</label>
          <span class="import-hint">也可以把文件拖到这里</span>
        </article>

        <section class="source-rail-section">
          <div class="rail-heading"><div><span>教材文件</span><small>${state.sources.length} 份本地资料</small></div><span class="count-chip">${state.sources.length}</span></div>
          <div class="source-list">
            ${state.sources.length ? state.sources.map(renderSourceCard).join("") : `<div class="rail-empty">尚未导入教材</div>`}
          </div>
        </section>
      </aside>

      <section class="library-canvas">
        ${selected ? renderSelectedSource(selected) : `
          <div class="empty-state source-empty">
            <div class="empty-symbol">书</div>
            <h2>先选择一份教材</h2>
            <p>解析完成后，这里会显示来源质量、知识单元、卡片数量和可执行学习动作。</p>
          </div>`}
      </section>
    </div>`;
  bindLibraryActions();
}

function sourceStatus(source) {
  const map = {
    queued: ["等待解析", "warn"],
    parsing: ["正在解析", "warn"],
    ready: ["可以学习", "good"],
    needs_attention: ["需要检查", "danger"],
    failed: ["解析失败", "danger"],
  };
  return map[source.status] || [source.status, ""];
}

function renderSourceCard(source) {
  const [label, tone] = sourceStatus(source);
  return `
    <button class="source-rail-item ${source.id === state.selectedSourceId ? "is-selected" : ""}" data-action="select-source" data-source-id="${source.id}" type="button">
      <span class="source-file-mark" aria-hidden="true">PDF</span>
      <span class="source-rail-copy">
        <strong>${escapeHtml(source.original_name)}</strong>
        <small>${source.page_count || "?"} 页 · ${source.unit_count || 0} 个单元 · ${formatBytes(source.file_size)}</small>
        ${["queued", "parsing"].includes(source.status) ? `<span class="progress-track"><span class="progress-bar" style="width:${source.progress}%"></span></span>` : ""}
      </span>
      <span class="status-dot ${tone}" title="${label}" aria-label="${label}"></span>
    </button>`;
}

function filteredUnits() {
  const query = state.unitQuery.trim().toLowerCase();
  const units = state.units.filter((unit) => {
    const matchesQuery = !query || `${unit.title} ${unit.body} ${unit.objective_type}`.toLowerCase().includes(query);
    const matchesFilter = state.unitFilter === "all"
      || (state.unitFilter === "approved" && unit.status === "approved")
      || (state.unitFilter === "pending" && unit.status !== "approved")
      || (state.unitFilter === "learned" && Boolean(unit.mastery_status))
      || (state.unitFilter === "cards" && Number(unit.retrieval_count || 0) > 0);
    return matchesQuery && matchesFilter;
  });
  const sorted = [...units];
  if (state.unitSort === "title") {
    sorted.sort((a, b) => a.title.localeCompare(b.title, "zh") || a.page_start - b.page_start);
  } else if (state.unitSort === "status") {
    sorted.sort((a, b) => Number(a.status !== "approved") - Number(b.status !== "approved") || a.page_start - b.page_start);
  } else if (state.unitSort === "cards") {
    sorted.sort((a, b) => Number(b.retrieval_count || 0) - Number(a.retrieval_count || 0) || a.page_start - b.page_start);
  } else {
    sorted.sort((a, b) => a.page_start - b.page_start);
  }
  return sorted;
}

function unitSortLabel() {
  return { page: "按教材页码", title: "按标题", status: "按确认状态", cards: "按卡片数" }[state.unitSort] || "按教材页码";
}

function renderSelectedSource(source) {
  const [label, tone] = sourceStatus(source);
  const lowText = Number(source.quality?.low_text_pages || 0);
  const units = filteredUnits();
  const approvedCount = state.units.filter((unit) => unit.status === "approved").length;
  const cardCount = state.units.reduce((sum, unit) => sum + Number(unit.retrieval_count || 0), 0);
  return `
    <header class="source-overview">
      <div class="source-overview-main">
        <div class="inline-meta"><span class="status-pill ${tone}">${label}</span><span class="source-path">本地文件 · ${formatBytes(source.file_size)}</span></div>
        <h2>${escapeHtml(source.original_name)}</h2>
        <p>页面、知识单元、卡片和真实作答都通过稳定来源锚点关联。</p>
      </div>
      <a class="secondary-button" href="/api/source-files/${source.id}" target="_blank" rel="noopener">打开原 PDF</a>
    </header>

    <div class="source-facts" aria-label="教材概况">
      <article><span>页数</span><strong>${source.page_count || 0}</strong><small>已处理 ${source.processed_pages || 0} 页</small></article>
      <article><span>知识单元</span><strong>${state.units.length}</strong><small>${approvedCount} 个已确认</small></article>
      <article><span>提取卡片</span><strong>${cardCount}</strong><small>闪卡与挖空合计</small></article>
      <article class="${lowText ? "has-warning" : ""}"><span>低文本页面</span><strong>${lowText}</strong><small>${lowText ? "建议人工核验" : "当前未发现异常"}</small></article>
    </div>

    ${source.error_message ? `<div class="notice warn">${escapeHtml(source.error_message)}</div>` : ""}
    ${source.status === "ready" ? `
      <section class="unit-workbench">
        <div class="unit-toolbar">
          <div>
            <div class="section-kicker">KNOWLEDGE UNITS</div>
            <h3>知识单元</h3>
            <p>先确认来源和颗粒度，再进入闭卷、挖空与闪卡。</p>
          </div>
          <div class="unit-toolbar-controls">
            <label class="search-field"><span aria-hidden="true">⌕</span><input id="unitSearch" type="search" value="${escapeHtml(state.unitQuery)}" placeholder="搜索标题、规则或术语" autocomplete="off"></label>
            <select id="unitSort" aria-label="排序知识单元">
              <option value="page" ${state.unitSort === "page" ? "selected" : ""}>按教材页码</option>
              <option value="title" ${state.unitSort === "title" ? "selected" : ""}>按标题</option>
              <option value="status" ${state.unitSort === "status" ? "selected" : ""}>按确认状态</option>
              <option value="cards" ${state.unitSort === "cards" ? "selected" : ""}>按卡片数</option>
            </select>
            <select id="unitFilter" aria-label="筛选知识单元">
              <option value="all" ${state.unitFilter === "all" ? "selected" : ""}>全部单元</option>
              <option value="approved" ${state.unitFilter === "approved" ? "selected" : ""}>已确认</option>
              <option value="pending" ${state.unitFilter === "pending" ? "selected" : ""}>待确认</option>
              <option value="learned" ${state.unitFilter === "learned" ? "selected" : ""}>已有作答</option>
              <option value="cards" ${state.unitFilter === "cards" ? "selected" : ""}>已有卡片</option>
            </select>
          </div>
        </div>
        <div class="unit-result-meta" id="unitResultMeta"><span>显示 ${Math.min(units.length, state.unitVisibleCount)} / ${state.units.length} 个单元</span><span>${unitSortLabel()}</span></div>
        <div class="unit-list" id="unitList">
          ${units.length ? units.slice(0, state.unitVisibleCount).map(renderUnitCard).join("") : `<div class="empty-state inline-empty"><div class="empty-symbol">⌕</div><h3>没有匹配的知识单元</h3><p>调整搜索词或筛选条件后再试。</p></div>`}
          ${units.length > state.unitVisibleCount ? `<button class="ghost-button load-more-button" data-action="show-more-units" type="button">显示更多单元（还有 ${units.length - state.unitVisibleCount} 个）</button>` : ""}
        </div>
      </section>` : `
      <div class="processing-panel">
        <div class="loading-orbit" aria-hidden="true"><span></span></div>
        <div><h3>教材正在本地解析</h3><p>已处理 ${source.processed_pages || 0} / ${source.page_count || "?"} 页。已完成页面会优先进入后续处理。</p></div>
      </div>`}
  `;
}

function renderUnitCard(unit, index = 0) {
  const tone = unit.status === "approved" ? "good" : "warn";
  const status = unit.status === "approved" ? "已确认" : "待确认";
  const retrievalCount = Number(unit.retrieval_count || 0);
  // 正文超过约 5 行（按行宽 40 字估算）才折叠并给出“展开全文”，短单元直接完整显示
  const longBody = unit.body.length > 200;
  return `
    <article class="unit-card">
      <div class="unit-index">${String(index + 1).padStart(2, "0")}</div>
      <div class="unit-card-body">
        <header class="unit-card-head">
          <div>
            <div class="inline-meta"><span class="status-pill ${tone}">${status}</span><span>第 ${unit.page_start}-${unit.page_end} 页</span><span>${escapeHtml(unit.objective_type)}</span></div>
            <h3>${escapeHtml(unit.title)}</h3>
          </div>
          ${unit.mastery_status ? `<span class="mastery-badge">${escapeHtml(unit.mastery_status)}</span>` : ""}
        </header>
        <div class="unit-body-clamp ${longBody ? "is-clamped" : ""}">
          <p>${escapeHtml(unit.body)}</p>
          ${longBody ? `<button class="body-expand-toggle" data-action="toggle-unit-body" data-unit-id="${unit.id}" type="button">展开全文</button>` : ""}
        </div>
        <div class="unit-evidence-strip">
          <span><strong>${Number(unit.flashcard_count || 0)}</strong> 闪卡</span>
          <span><strong>${Number(unit.cloze_count || 0)}</strong> 挖空</span>
          <span><strong>${unit.version}</strong> 当前版本</span>
          ${unit.last_score != null ? `<span><strong>${Number(unit.last_score).toFixed(0)}</strong> 上次闭卷</span>` : ""}
        </div>
        <footer class="unit-card-foot">
          <div class="unit-card-actions">
            <button class="ghost-button small-button" data-action="review-unit" data-unit-id="${unit.id}">审核 / 编辑</button>
            <button class="ghost-button small-button" data-action="generate-retrieval" data-unit-id="${unit.id}">${retrievalCount ? "补充卡片" : "生成挖空与闪卡"}</button>
            <button class="ghost-button small-button" data-action="create-retrieval" data-unit-id="${unit.id}">手动建卡</button>
            ${retrievalCount ? `<button class="secondary-button small-button" data-action="start-unit-retrieval" data-unit-id="${unit.id}">练习 ${retrievalCount} 张</button>` : ""}
          </div>
          <div class="unit-primary-actions">
            ${(() => { const idx = state.units.findIndex((candidate) => candidate.id === unit.id); const next = idx >= 0 ? state.units[idx + 1] : null; return next ? `<button class="ghost-button small-button" data-action="merge-next-unit" data-unit-id="${unit.id}" data-other-unit-id="${next.id}">与下一单元合并</button>` : ""; })()}
            <button class="primary-button small-button" data-action="start-unit" data-unit-id="${unit.id}">${unit.status !== "approved" ? "先审核再学习" : unit.mastery_status ? "再次完整复测" : "开始完整闭卷"}</button>
          </div>
        </footer>
      </div>
    </article>`;
}

function methodPackFor(session = {}) {
  if (session.method_pack?.training_dimensions?.length) return session.method_pack;
  const fallbackDimensions = [
    ["core_question", "核心设问", "先回答本单元究竟要求解释、辨析或适用什么。"],
    ["rule_elements", "规则与要件", "恢复一般规则、启动条件和构成要件。"],
    ["exceptions_boundaries", "例外与边界", "检查例外、限制、阻断条件和相邻制度。"],
    ["legal_effect", "法律效果", "明确权利、义务、效力、责任或程序后果。"],
    ["terminology_expression", "术语与规范表达", "使用来源内术语，按规则、条件、结论组织答案。"],
  ];
  return {
    id: "law_full_recall_v1",
    version: "0.3.0",
    name: "法学完整闭卷方法包",
    focus_label: session.objective_type || "综合闭卷",
    selection_reason: "使用五维完整闭卷检查；旧会话未保存方法快照，当前按兼容规则显示。",
    runtime_status: "selected",
    training_dimensions: fallbackDimensions.map(([id, label, instruction], index) => ({ id, label, instruction, emphasized: index < 3 })),
  };
}

function studyChecklistFor(session) {
  return methodPackFor(session).training_dimensions || [];
}

function dimensionStatusLabel(status = "") {
  return { strong: "高目标覆盖", partial: "部分目标恢复", missing: "低目标恢复", critical_conflict: "关键冲突", uncertain: "待语义核对", not_applicable: "目标未列明", unavailable: "诊断降级" }[status] || "待核对";
}

function dimensionTone(status = "") {
  if (status === "strong") return "good";
  if (status === "partial" || status === "not_applicable" || status === "uncertain") return "warn";
  if (status === "missing" || status === "unavailable" || status === "critical_conflict") return "danger";
  return "info";
}

function renderMethodDiagnostics(methodPack, dimensions = []) {
  if (!dimensions.length) return "";
  const runtimeLabel = methodPack?.runtime_status === "degraded" ? "已降级" : "学习目标恢复信号";
  const flags = methodPack?.generated_flags || {};
  const provenance = flags.learning_target_provenance || "source_basis_pending";
  const provenanceLabel = {
    source_exact: "目标=教材来源原样",
    edited_learning_text: "目标=人工改写学习文本",
    legacy_unverified: "目标=迁移历史文本（待核对来源）",
    source_basis_pending: "目标来源待校准",
  }[provenance] || "目标来源待校准";
  return `
    <section class="section method-diagnostic-section">
      <div class="section-head"><div><div class="section-kicker">METHOD PACK · ${escapeHtml(methodPack?.id || "law_full_recall_v1")}</div><h2>五维学习目标恢复检查</h2><p>${escapeHtml(methodPack?.selection_reason || "按知识单元类型选择训练重点，并只依据本轮冻结学习目标给出诊断。")}</p></div><span class="count-chip">v${escapeHtml(methodPack?.version || "0.3.0")} · ${runtimeLabel}</span></div>
      <div class="method-boundary-note"><strong>目标身份</strong><span>${escapeHtml(provenanceLabel)}。评分与冲突检查针对本轮冻结学习目标；教材来源快照用于回源核对。</span></div>
      <div class="dimension-grid">
        ${dimensions.map((item, index) => {
          const score = item.score == null ? "—" : Number(item.score).toFixed(0);
          return `<article class="dimension-card ${dimensionTone(item.status)}">
            <header><span>${String(index + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(item.label)}</strong><small>${dimensionStatusLabel(item.status)}</small></div><b>${score}</b></header>
            <p>${escapeHtml(item.summary || "本轮没有生成该维度说明。")}</p>
            <footer><span>${escapeHtml(item.next_action || "回到来源核对后重新提取。")}</span>${item.atom_refs?.length ? `<small>${item.atom_refs.map(escapeHtml).join(" · ")}</small>` : ""}</footer>
          </article>`;
        }).join("")}
      </div>
      <div class="method-boundary-note"><strong>边界</strong><span>分数只代表本地学习目标恢复信号。若目标经过人工改写，系统不会把它冒充教材原文。关键冲突会直接阻断；同义改写可能进入“待语义核对”。这里不等同于正式法学评分。</span></div>
    </section>`;
}

function renderProcessStepper(activeStep = 1) {
  const steps = [
    [1, "闭卷提取", "暴露真实记忆"],
    [2, "来源对照", "核对规则与遗漏"],
    [3, "修复复测", "生成下一次任务"],
  ];
  return `<div class="process-stepper">${steps.map(([step, title, note]) => `
    <div class="process-step ${step === activeStep ? "is-active" : step < activeStep ? "is-done" : ""}">
      <span>${step < activeStep ? "✓" : step}</span><div><strong>${title}</strong><small>${note}</small></div>
    </div>`).join("")}</div>`;
}

function countAnswerUnits(value = "") {
  const compact = value.trim().replace(/\s+/g, "");
  return compact.length;
}

function renderStudy() {
  const session = state.activeSession;
  if (!session && !state.feedback) {
    content.innerHTML = `
      <div class="empty-state study-empty">
        <div class="empty-symbol">答</div>
        <div class="section-kicker">ACTIVE RECALL FIRST</div>
        <h2>当前没有进行中的闭卷会话</h2>
        <p>从今日任务或教材知识单元开始。系统会先隐藏原文，再记录真实回答、提示使用、置信度和用时。</p>
        <div class="empty-actions"><button class="primary-button" data-action="go-library">选择知识单元</button><button class="secondary-button" data-action="go-today">返回今日学习</button></div>
      </div>`;
    bindCommonActions();
    return;
  }
  if (state.feedback) {
    renderFeedback();
    return;
  }

  const hintLevel = Number(session.hint_level || 0);
  const sourceVisible = hintLevel > 0;
  const sourceText = hintLevel === 1 ? `${session.body.slice(0, 220)}${session.body.length > 220 ? "……" : ""}` : session.body;
  const methodPack = methodPackFor(session);
  const checklist = studyChecklistFor(session);
  const draftText = session.draft_text || "";
  const confidenceValue = Number(session.draft_confidence ?? 70);

  content.innerHTML = `
    ${renderProcessStepper(1)}
    <div class="study-workspace ${state.sourcePaneCollapsed ? "source-collapsed" : ""}">
      <aside class="study-source-rail">
        <header class="study-panel-head">
          <div>
            <div class="inline-meta"><span class="status-pill warn">来源受控</span><span>${escapeHtml(session.original_name)}</span></div>
            <h2>${escapeHtml(session.title)}</h2>
            <p>第 ${session.page_start}-${session.page_end} 页 · ${escapeHtml(session.objective_type)} · ${escapeHtml(methodPack.focus_label || "综合闭卷")}</p>
          </div>
          <button class="icon-button compact-icon" data-action="toggle-source-pane" title="收起来源栏" aria-label="收起来源栏">‹</button>
        </header>

        <div class="source-gate ${sourceVisible ? "is-revealed" : ""}">
          ${sourceVisible ? `
            <div class="source-paper">
              <div class="paper-label">${hintLevel === 1 ? "一级提示 · 原文节选" : "完整原文"}</div>
              <div class="source-text">${escapeHtml(sourceText)}</div>
            </div>` : `
            <div class="source-hidden">
              <div class="source-seal" aria-hidden="true">封</div>
              <h3>先暴露你的大脑</h3>
              <p>闭卷写出规则、条件、例外、易混淆点与规范表达。查看提示会降低本次证据权重。</p>
            </div>`}
        </div>

        <div class="hint-controls">
          <button class="ghost-button small-button" data-action="hint" data-level="1" ${hintLevel >= 1 ? "disabled" : ""}>一级提示</button>
          <button class="ghost-button small-button" data-action="hint" data-level="2" ${hintLevel >= 2 ? "disabled" : ""}>查看完整原文</button>
        </div>
      </aside>

      <main class="study-editor-panel">
        <header class="study-editor-head">
          <div><div class="section-kicker">YOUR ANSWER</div><h2>闭卷回答</h2><p>先恢复能够独立调用的内容，暂时不要追求语言漂亮。</p></div>
          <div class="editor-status"><span id="draftStatus">${state.draftStatus === "saving" ? "保存中" : "草稿已保存"}</span><span id="answerCount">${countAnswerUnits(draftText)} 字</span></div>
        </header>
        <textarea id="answerText" placeholder="按“考点定位 → 规则与要件 → 例外与边界 → 规范结论”写下你当前能够独立恢复的内容……" autofocus>${escapeHtml(draftText)}</textarea>
        <footer class="editor-footnote">
          <span>草稿每次停顿后自动保存到本机</span>
          <span><kbd>Ctrl / ⌘</kbd> + <kbd>Enter</kbd> 提交</span>
        </footer>
      </main>

      <aside class="study-session-rail">
        <section class="session-clock">
          <span>本轮用时</span>
          <strong class="timer" id="timer">00:00</strong>
          <small>计时只用于观察提取速度</small>
        </section>

        <section class="session-block">
          <div class="session-block-head"><strong>作答置信度</strong><span id="confidenceLabel">${confidenceValue}%</span></div>
          <div class="confidence-scale"><span>猜测</span><span>确定</span></div>
          <div class="range-row"><input id="confidence" type="range" min="0" max="100" value="${confidenceValue}" aria-label="作答置信度"><span class="range-value" id="confidenceValue">${confidenceValue}</span></div>
        </section>

        <section class="session-block method-pack-block">
          <div class="session-block-head"><strong>${escapeHtml(methodPack.name || "法学完整闭卷方法包")}</strong><span>v${escapeHtml(methodPack.version || "0.3.0")}</span></div>
          <p class="method-pack-reason">${escapeHtml(methodPack.selection_reason || "使用五维检查形成可追溯闭卷证据。")}</p>
          <ul class="study-checklist">${checklist.map((item) => `<li class="${item.emphasized ? "is-emphasized" : ""}"><span></span><div><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.instruction || "")}</small></div></li>`).join("")}</ul>
        </section>

        <div class="evidence-notice ${hintLevel ? "is-warning" : "is-clean"}">
          <span class="evidence-mark" aria-hidden="true">${hintLevel ? "!" : "✓"}</span>
          <div><strong>${hintLevel === 0 ? "无提示证据" : `${hintLevel} 级提示已使用`}</strong><p>${hintLevel === 0 ? "本轮可以形成完整的独立提取证据。" : "系统会降低证据权重，但仍保留真实学习过程。"}</p></div>
        </div>

        <div class="session-actions">
          <button class="primary-button" data-action="submit-attempt">提交并对照来源</button>
          <button class="ghost-button" data-action="cancel-session">结束本轮</button>
        </div>
      </aside>
    </div>
    <button class="source-restore-tab ${state.sourcePaneCollapsed ? "is-visible" : ""}" data-action="toggle-source-pane" type="button">展开教材来源</button>`;

  bindStudyActions();
  const answerBox = $("#answerText");
  if (answerBox) answerBox.value = draftText;
  startTimer();
}

function renderFeedback() {
  const result = state.feedback;
  const feedback = result.feedback;
  const methodPack = result.method_pack || feedback.method_pack || null;
  const dimensionResults = result.dimension_results || feedback.dimension_results || [];
  const scoreTone = result.score >= 82 ? "good" : result.score >= 60 ? "warn" : "danger";
  const evidencePercent = Math.round(result.evidence_weight * 100);
  content.innerHTML = `
    ${renderProcessStepper(2)}
    <section class="result-hero">
      <div class="result-score-block">
        <span class="result-label">有效学习证据分</span>
        <strong>${Number(result.score).toFixed(0)}</strong>
        <span>证据权重 ${evidencePercent}%${Number.isFinite(Number(result.provider_score)) && Math.abs(Number(result.provider_score) - Number(result.score)) >= 0.1 ? ` · 原始覆盖 ${Number(result.provider_score).toFixed(0)}` : ""}</span>
      </div>
      <div class="result-summary">
        <div class="inline-meta"><span class="status-pill ${scoreTone}">${escapeHtml(result.review.mastery_status)}</span><span>下次复测 ${formatDate(result.review.due_at)}</span>${methodPack ? `<span>${escapeHtml(methodPack.focus_label || methodPack.name)} · v${escapeHtml(methodPack.version || "0.3.0")}</span>` : ""}</div>
        <h2>${result.score >= 82 ? "本轮已经形成可用证据，下一步进入延迟保持。" : result.score >= 60 ? "核心框架存在，但仍有关键缺口需要立即修复。" : "当前提取还不稳定，先修复规则骨架再安排复测。"}</h2>
        <p>${escapeHtml(feedback.next_action)}</p>
        <div class="result-actions"><button class="primary-button" data-action="retest-unit" data-unit-id="${result.knowledge_unit_id}">立即重新闭卷</button><button class="secondary-button" data-action="go-today">返回今日任务</button></div>
      </div>
    </section>

    ${feedback.warning ? `<div class="notice warn result-warning">${escapeHtml(feedback.warning)}</div>` : ""}

    ${renderMethodDiagnostics(methodPack, dimensionResults)}

    <section class="feedback-board">
      ${feedbackCard("已稳定覆盖", feedback.matched_points, "good", "✓")}
      ${feedbackCard("本轮遗漏", feedback.missing_points, "warn", "−")}
      ${feedbackCard("需要复核", feedback.incorrect_points, "danger", "!")}
      ${feedbackCard("表达与证据", feedback.expression_issues, "info", "文")}
    </section>

    <section class="section evidence-section">
      <div class="section-head"><div><div class="section-kicker">SOURCE EVIDENCE</div><h2>教材来源</h2><p>反馈中的关键判断应当能够回到具体页码核验。</p></div><span class="count-chip">${Math.min((feedback.evidence || []).length, 5)} 条</span></div>
      <div class="evidence-ledger">
        ${(feedback.evidence || []).slice(0, 5).map((item, index) => `<article><span class="evidence-number">${String(index + 1).padStart(2, "0")}</span><div><strong>第 ${item.page_start}-${item.page_end} 页 · 覆盖 ${(Number(item.coverage) * 100).toFixed(0)}%</strong><p>${escapeHtml(item.text)}</p></div></article>`).join("")}
      </div>
    </section>

    <section class="review-ticket">
      <div><span>下一次复测</span><strong>${formatDate(result.review.due_at)}</strong><p>${escapeHtml(result.review.reason)}</p></div>
      <div class="review-ticket-meta"><span>${result.errors_created} 条错因记录</span><span>评分器 ${escapeHtml(result.provider)}</span>${methodPack ? `<span>方法包 ${escapeHtml(methodPack.id)}@${escapeHtml(methodPack.version)}</span>` : ""}</div>
    </section>`;
  bindCommonActions();
}

function feedbackCard(title, items = [], tone = "", mark = "") {
  const safeItems = items?.length ? items : ["本轮没有记录到这一类问题"];
  return `<article class="feedback-column ${tone}"><header><span>${mark}</span><h3>${title}</h3><small>${items?.length || 0} 项</small></header><ul>${safeItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></article>`;
}

function renderRetrieval() {
  if (state.retrievalResult) {
    renderRetrievalResult();
    return;
  }
  if (state.retrievalActive) {
    renderRetrievalPractice();
    return;
  }
  renderRetrievalDashboard();
}

function filteredRetrievalItems() {
  const query = state.retrievalQuery.trim().toLowerCase();
  const filtered = state.retrievalAll.filter((item) => {
    const matchesQuery = !query || `${item.prompt} ${item.answer || ""} ${item.unit_title} ${item.original_name}`.toLowerCase().includes(query);
    const dueNow = item.due_at ? new Date(item.due_at).getTime() <= Date.now() : true;
    const matchesFilter = state.retrievalFilter === "all"
      || (state.retrievalFilter === "due" && dueNow)
      || (state.retrievalFilter === "flashcard" && item.item_type === "flashcard")
      || (state.retrievalFilter === "cloze" && item.item_type === "cloze")
      || (state.retrievalFilter === "new" && Boolean(item.is_new));
    return matchesQuery && matchesFilter;
  });
  const sorted = [...filtered];
  if (state.retrievalSort === "title") {
    sorted.sort((a, b) => a.unit_title.localeCompare(b.unit_title, "zh") || a.prompt.localeCompare(b.prompt, "zh"));
  } else if (state.retrievalSort === "created") {
    sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  } else {
    // 默认：到期优先，同到期按创建时间（新卡先看）
    sorted.sort((a, b) => (a.due_at ? new Date(a.due_at).getTime() : 0) - (b.due_at ? new Date(b.due_at).getTime() : 0)
      || new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  }
  return sorted;
}

function retrievalSortLabel() {
  return { due: "到期优先", created: "按创建时间", title: "按单元标题" }[state.retrievalSort] || "到期优先";
}

function renderRetrievalDashboard() {
  const summary = state.retrievalSummary || { total: 0, flashcards: 0, clozes: 0, due: 0, new: 0, reviewed_today: 0, average_score: 0 };
  const visibleItems = filteredRetrievalItems();
  const reviewed = Number(summary.reviewed_today || 0);
  const due = Number(summary.due || 0);
  const queueProgress = reviewed + due ? clamp(Math.round((reviewed / (reviewed + due)) * 100), 0, 100) : 0;

  content.innerHTML = `
    <section class="retrieval-command">
      <div class="retrieval-command-copy">
        <div class="focus-kicker"><span class="evidence-dot"></span>主动提取队列</div>
        <h2>${summary.due ? `今天有 ${summary.due} 张卡片需要被重新提取。` : summary.total ? "到期队列已经清空，可以继续巩固或管理卡片。" : "从一个知识单元生成第一组可复测卡片。"}</h2>
        <p>闪卡先回忆再显示答案；挖空先提交再核对。每张卡片独立记录版本、用时、遗忘和下一次复测。</p>
        <div class="focus-actions">
          ${summary.due ? `<button class="primary-button" data-action="start-retrieval-queue" data-due-only="true">开始 ${summary.due} 张到期复习</button>` : ""}
          ${summary.total ? `<button class="secondary-button" data-action="start-retrieval-queue" data-due-only="false">练习全部活动卡片</button>` : `<button class="primary-button" data-action="go-library">去教材库生成</button>`}
          <button class="ghost-button" data-action="go-library">查看知识单元</button>
        </div>
      </div>
      <aside class="retrieval-queue-card">
        <div class="queue-card-head"><span>今日队列</span><strong>${queueProgress}%</strong></div>
        <div class="queue-track"><span style="width:${queueProgress}%"></span></div>
        <dl>
          <div><dt>已提取</dt><dd>${reviewed}</dd></div>
          <div><dt>仍到期</dt><dd>${due}</dd></div>
          <div><dt>平均分</dt><dd>${Number(summary.average_score || 0).toFixed(0)}</dd></div>
        </dl>
      </aside>
    </section>

    <section class="retrieval-ledger" aria-label="卡片概况">
      <article><span>闪卡</span><strong>${summary.flashcards || 0}</strong><small>先回忆，后自评</small></article>
      <article><span>挖空</span><strong>${summary.clozes || 0}</strong><small>关键词与规则节点</small></article>
      <article><span>新卡</span><strong>${summary.new || 0}</strong><small>尚未形成提取证据</small></article>
      <article><span>今日提取</span><strong>${summary.reviewed_today || 0}</strong><small>真实作答次数</small></article>
    </section>

    ${renderRetrievalTaskSection(state.retrievalDue || [])}

    <section class="section card-management-section">
      <div class="section-head"><div><div class="section-kicker">CARD LIBRARY</div><h2>卡片管理</h2><p>自动生成只是初稿。核对题面、答案与教材来源后再长期使用。</p></div><span class="count-chip" id="retrievalResultCount">${visibleItems.length} / ${summary.total || 0} 张</span></div>
      <div class="card-toolbar">
        <div class="segmented-control" role="group" aria-label="筛选卡片">
          ${[
            ["all", "全部"],
            ["due", "到期"],
            ["flashcard", "闪卡"],
            ["cloze", "挖空"],
            ["new", "新卡"],
          ].map(([value, label]) => `<button class="segment ${state.retrievalFilter === value ? "is-active" : ""}" data-action="filter-retrieval" data-filter="${value}" type="button">${label}</button>`).join("")}
        </div>
        <label class="search-field card-search"><span aria-hidden="true">⌕</span><input id="retrievalSearch" type="search" value="${escapeHtml(state.retrievalQuery)}" placeholder="搜索题面、答案或教材" autocomplete="off"></label>
        <select id="retrievalSort" aria-label="排序卡片">
          <option value="due" ${state.retrievalSort === "due" ? "selected" : ""}>到期优先</option>
          <option value="created" ${state.retrievalSort === "created" ? "selected" : ""}>按创建时间</option>
          <option value="title" ${state.retrievalSort === "title" ? "selected" : ""}>按单元标题</option>
        </select>
      </div>
      <div class="retrieval-manage-list" id="retrievalManageList">
        ${visibleItems.length ? visibleItems.slice(0, state.retrievalVisibleCount).map(renderRetrievalManageItem).join("") : `<div class="empty-state inline-empty"><div class="empty-symbol">卡</div><h3>没有匹配的卡片</h3><p>调整筛选条件，或前往教材库生成新的挖空与闪卡。</p></div>`}
        ${visibleItems.length > state.retrievalVisibleCount ? `<button class="ghost-button load-more-button" data-action="show-more-retrieval" type="button">显示更多卡片（还有 ${visibleItems.length - state.retrievalVisibleCount} 张）</button>` : ""}
      </div>
    </section>`;
  bindRetrievalActions();
}

function renderRetrievalManageItem(item, index = 0) {
  const typeLabel = item.item_type === "cloze" ? "挖空" : "闪卡";
  return `
    <article class="retrieval-manage-card">
      <span class="card-number">${String(index + 1).padStart(2, "0")}</span>
      <div class="retrieval-manage-main">
        <header class="retrieval-manage-head">
          <div>
            <div class="inline-meta"><span class="status-pill ${item.item_type === "cloze" ? "warn" : "good"}">${typeLabel}</span><span>${escapeHtml(item.unit_title)}</span><span>第 ${item.page_start}-${item.page_end} 页</span><a class="pdf-jump" href="${pdfJumpHref(item.source_id, item.page_start)}" data-locate="${escapeHtml((item.answer || "").split("\x1f")[0])}" target="_blank" rel="noopener">在 PDF 中查看</a></div>
            <div class="task-title">${escapeHtml(item.prompt)}</div>
          </div>
          <span class="mastery-badge">${escapeHtml(item.mastery_status || "新卡")}</span>
        </header>
        <details class="retrieval-answer-details">
          <summary>查看答案与来源</summary>
          <div class="retrieval-answer"><strong>标准答案</strong><p>${escapeHtml(item.answer || "")}</p><strong>来源原文</strong><p>${escapeHtml(item.source_excerpt || "")}</p></div>
        </details>
        <footer class="retrieval-manage-foot">
          <div class="card-history"><span>${item.attempt_count || 0} 次提取</span><span>${item.due_at ? `下次 ${formatDate(item.due_at)}` : "尚未安排"}</span><span>连续成功 ${item.streak || 0} 次</span></div>
          <div class="unit-card-actions"><button class="ghost-button small-button" data-action="edit-retrieval" data-item-id="${item.id}">编辑</button><button class="ghost-button small-button" data-action="archive-retrieval" data-item-id="${item.id}">停用</button><button class="secondary-button small-button" data-action="start-retrieval-item" data-item-id="${item.id}">练习</button></div>
        </footer>
      </div>
    </article>`;
}

function renderRetrievalPractice() {
  const item = state.retrievalActive;
  const reveal = state.retrievalReveal;
  const total = state.retrievalCompleted + state.retrievalQueue.length;
  const currentNumber = state.retrievalCompleted + 1;
  const progress = total ? clamp(Math.round((state.retrievalCompleted / total) * 100), 0, 100) : 0;
  const isFlashcard = item.item_type === "flashcard";
  content.innerHTML = `
    <div class="practice-shell">
      <header class="practice-topline">
        <div>
          <div class="inline-meta"><span class="status-pill ${isFlashcard ? "good" : "warn"}">${isFlashcard ? "闪卡" : "挖空"}</span><span>${escapeHtml(state.retrievalQueueLabel)}</span></div>
          <h2>${escapeHtml(item.unit_title)}</h2>
          <p>${escapeHtml(item.original_name)} · 第 ${item.page_start}-${item.page_end} 页 · <a class="pdf-jump" href="${pdfJumpHref(item.source_id, item.page_start)}" data-locate="${escapeHtml((item.answer || "").split("\x1f")[0])}" target="_blank" rel="noopener">打开教材原文</a></p>
        </div>
        <div class="practice-counter"><strong>${currentNumber}</strong><span>/ ${Math.max(total, 1)}</span></div>
      </header>
      <div class="practice-progress" role="progressbar" aria-label="本轮卡片进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"><span style="width:${progress}%"></span></div>

      <div class="practice-grid">
        <main class="practice-card" data-card-type="${item.item_type}">
          <div class="practice-card-label">${isFlashcard ? "请先在脑中完整回答" : "请填写被挖空的规则节点"}</div>
          <div class="retrieval-prompt">${escapeHtml(item.prompt)}</div>
          ${isFlashcard ? `
            ${reveal ? `
              <div class="answer-reveal">
                <section><span>标准答案</span><div class="retrieval-answer-text">${escapeHtml(reveal.answer).split("\x1f").join("<br>")}</div></section>
                <section class="source-quote">
                  <span>教材来源 · 第 ${item.page_start}-${item.page_end} 页 · <a class="pdf-jump" href="${pdfJumpHref(item.source_id, item.page_start)}" target="_blank" rel="noopener">在 PDF 中查看</a></span>
                  <details><summary>展开原文片段</summary><p>${highlightInExcerpt(reveal.source_excerpt, reveal.answer)}</p></details>
                </section>
              </div>` : `
              <div class="retrieval-hidden-answer">
                <div class="recall-pulse" aria-hidden="true"><span></span></div>
                <h3>确认自己已经尝试回忆</h3>
                <p>答案显示后，请按真实提取质量评分。系统会拒绝未显示答案就提交自评。</p>
                <button class="primary-button" data-action="reveal-retrieval">显示答案</button>
                <small><kbd>Space</kbd> 也可以显示</small>
              </div>`}
          ` : `
            <div class="cloze-answer-area">
              <label>你的答案（共 ${(item.prompt.match(/____/g) || []).length || 1} 个空）</label>
              <div class="cloze-inputs">${Array.from({ length: (item.prompt.match(/____/g) || []).length || 1 }, (_, i) => `<input class="cloze-input" data-cloze-index="${i}" autocomplete="off" placeholder="${i === 0 ? "输入关键词或规则片段" : `第 ${i + 1} 个空`}" ${i === 0 ? "autofocus" : ""}>`).join("")}</div>
              <div class="action-row"><button class="ghost-button" data-action="give-up-cloze">暂时想不起</button><button class="primary-button" data-action="submit-cloze">提交填空</button></div>
              <small>按 Enter 提交，系统会忽略空格和常见标点；多个空按顺序填写。</small>
            </div>`}
        </main>

        <aside class="practice-control-rail">
          <section class="session-clock"><span>本卡用时</span><strong class="timer" id="retrievalTimer">00:00</strong><small>只用于观察提取速度</small></section>
          <div class="evidence-notice is-clean"><span class="evidence-mark" aria-hidden="true">证</span><div><strong>卡片级证据</strong><p>这次结果独立于完整闭卷，不会覆盖知识单元历史。</p></div></div>
          ${isFlashcard && reveal ? `
            <section class="rating-section">
              <div class="session-block-head"><strong>这次提取得怎么样？</strong><span>按 1–4</span></div>
              <div class="rating-grid">
                <button class="rating-button again" data-action="rate-flashcard" data-rating="again"><i>1</i><strong>忘记</strong><span>10 分钟</span></button>
                <button class="rating-button hard" data-action="rate-flashcard" data-rating="hard"><i>2</i><strong>困难</strong><span>约 1 天</span></button>
                <button class="rating-button good" data-action="rate-flashcard" data-rating="good"><i>3</i><strong>记得</strong><span>约 3 天</span></button>
                <button class="rating-button easy" data-action="rate-flashcard" data-rating="easy"><i>4</i><strong>轻松</strong><span>约 7 天</span></button>
              </div>
            </section>` : `
            <section class="session-block shortcut-panel"><strong>本页快捷键</strong><p>${isFlashcard ? "Space 显示答案，显示后按 1–4 自评。" : "Enter 提交填空；输入法组合输入不会误触。"}</p></section>`}
          <button class="ghost-button full-width" data-action="exit-retrieval">结束本轮卡片练习</button>
        </aside>
      </div>
    </div>`;
  bindRetrievalActions();
  startRetrievalTimer();
}

function renderRetrievalResult() {
  const result = state.retrievalResult;
  const tone = result.score >= 85 ? "good" : result.score >= 60 ? "warn" : "danger";
  const ratingLabels = { again: "需要重学", hard: "仍不稳定", good: "成功提取", easy: "轻松提取" };
  const hasNext = state.retrievalQueue.length > 1;
  content.innerHTML = `
    <section class="retrieval-result-hero">
      <div class="result-score-block compact-score"><span class="result-label">${result.item_type === "cloze" ? "本地挖空核对" : "闪卡自评证据"}</span><strong>${Number(result.score).toFixed(0)}</strong><span>${escapeHtml(result.review.mastery_status)}</span></div>
      <div class="result-summary">
        <div class="inline-meta"><span class="status-pill ${tone}">${ratingLabels[result.rating] || result.rating}</span><span>下次 ${formatDate(result.review.due_at)}</span></div>
        <h2>${escapeHtml(result.note)}</h2>
        <p>连续成功 ${result.review.streak} 次 · 遗忘 ${result.review.lapses} 次。当前结果已写入本地卡片历史。</p>
        <div class="result-actions"><button class="secondary-button" data-action="exit-retrieval">返回卡片中心</button><button class="primary-button" data-action="next-retrieval">${hasNext ? "下一张" : "完成本轮"}</button></div>
      </div>
    </section>

    ${result.critical_mismatches?.length ? `<section class="notice critical-mismatch"><strong>关键限定冲突</strong><ul>${result.critical_mismatches.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul><p>这类错误会直接进入“立即重做”，不会被字符串相似度当成普通困难。</p></section>` : ""}

    <section class="answer-comparison">
      <article><div class="section-kicker">EXPECTED ANSWER</div><h3>标准答案</h3><p>${escapeHtml(result.expected_answer).split("\x1f").join("<br>")}</p></article>
      <article class="source-answer"><div class="section-kicker">SOURCE</div><h3>教材来源</h3><p><strong>第 ${result.page_start}-${result.page_end} 页</strong> · <a class="pdf-jump" href="${pdfJumpHref(result.source_id, result.page_start)}" data-locate="${escapeHtml((result.expected_answer || "").split("\x1f")[0])}" target="_blank" rel="noopener">在 PDF 中查看原文</a></p><details class="source-excerpt-details"><summary>展开原文片段</summary>${highlightInExcerpt(result.source_excerpt, result.expected_answer)}</details></article>
    </section>

    <section class="review-ticket">
      <div><span>下一次复测</span><strong>${formatDate(result.review.due_at)}</strong><p>${escapeHtml(result.review.reason)}</p></div>
      <div class="review-ticket-meta"><span>${escapeHtml(result.review.mastery_status)}</span><span>间隔 ${result.review.interval_minutes} 分钟</span></div>
    </section>`;
  bindRetrievalActions();
}

function calibrationSummary(metrics = {}) {
  const score = Number(metrics.average_score || 0);
  const confidence = Number(metrics.average_confidence || 0);
  const gap = Math.round(confidence - score);
  if (!metrics.attempts) return { gap: 0, label: "等待数据", note: "完成第一次真实闭卷后，系统才会评估置信度校准。", tone: "" };
  if (gap >= 15) return { gap, label: "偏高估", note: `平均置信度比覆盖分高 ${gap} 分，需要重点识别高置信度错误。`, tone: "danger" };
  if (gap <= -15) return { gap, label: "偏低估", note: `平均置信度比覆盖分低 ${Math.abs(gap)} 分，可能存在掌握后仍不敢确认。`, tone: "warn" };
  return { gap, label: "较校准", note: `平均置信度与覆盖分相差 ${Math.abs(gap)} 分，当前判断相对稳定。`, tone: "good" };
}

function renderModel() {
  const model = state.learningModel || { mastery: [], recurring_errors: [], repair_queue: [], metrics: {}, retrieval_metrics: {}, latest_attempts: [] };
  const metrics = model.metrics || {};
  const retrievalMetrics = model.retrieval_metrics || {};
  const total = model.mastery.reduce((sum, item) => sum + Number(item.count), 0) || 1;
  const calibration = calibrationSummary(metrics);
  const dominantError = model.recurring_errors?.[0];

  content.innerHTML = `
    <section class="model-brief">
      <div class="model-brief-copy">
        <div class="focus-kicker"><span class="evidence-dot"></span>本地学习证据画像</div>
        <h2>${metrics.attempts ? `当前画像来自 ${metrics.attempts} 次完整闭卷和 ${retrievalMetrics.attempts || 0} 次卡片作答。` : "当前还没有足够的真实作答证据。"}</h2>
        <p>${escapeHtml(model.model_note || "系统只依据真实作答、提示使用、置信度和复测记录更新。")}</p>
      </div>
      <aside class="calibration-card ${calibration.tone}">
        <span>置信度校准</span>
        <strong>${calibration.label}</strong>
        <p>${calibration.note}</p>
      </aside>
    </section>

    <section class="evidence-metrics">
      <article><span>完整闭卷</span><strong>${metrics.attempts || 0}</strong><small>真实提交次数</small></article>
      <article><span>平均覆盖</span><strong>${Number(metrics.average_score || 0).toFixed(0)}</strong><small>当前本地评分结果</small></article>
      <article><span>平均置信度</span><strong>${Number(metrics.average_confidence || 0).toFixed(0)}%</strong><small>用于识别高置信度错误</small></article>
      <article><span>平均用时</span><strong>${formatDuration(metrics.average_elapsed_ms || 0)}</strong><small>观察提取速度变化</small></article>
      <article><span>卡片作答</span><strong>${retrievalMetrics.attempts || 0}</strong><small>共 ${state.retrievalSummary?.total || 0} 张活动卡 · 独立记录</small></article>
      <article><span>卡片平均分</span><strong>${Number(retrievalMetrics.average_score || 0).toFixed(0)}</strong><small>成功 ${retrievalMetrics.successful_count || 0} · 遗忘 ${retrievalMetrics.again_count || 0}</small></article>
    </section>

    <div class="model-grid">
      <section class="model-panel mastery-panel">
        <div class="section-head"><div><div class="section-kicker">MASTERY</div><h2>掌握状态</h2><p>一个知识单元只能由真实作答证据推动状态变化。</p></div></div>
        <div class="mastery-distribution">
          ${model.mastery.length ? model.mastery.map((item) => `
            <div class="mastery-row">
              <div><strong>${escapeHtml(item.mastery_status)}</strong><span>${item.count} 个单元</span></div>
              <div class="mastery-track"><span style="width:${Math.max(5, Number(item.count) / total * 100)}%"></span></div>
              <b>${Math.round(Number(item.count) / total * 100)}%</b>
            </div>`).join("") : `<div class="inline-empty compact-empty"><p>完成第一次闭卷作答后，系统才会建立掌握状态。</p></div>`}
        </div>
      </section>

      <section class="model-panel diagnosis-panel">
        <div class="section-head"><div><div class="section-kicker">DIAGNOSIS</div><h2>当前最值得修复</h2><p>只展示有真实作答证据支撑的开放错误。</p></div></div>
        ${dominantError ? `
          <div class="diagnosis-focus"><span>${escapeHtml(dominantError.error_type)}</span><h3>${escapeHtml(dominantError.detail)}</h3><p>这一错误已经出现 ${dominantError.count} 次。下一轮应优先生成对比、边界或规范表达任务。</p></div>` : `
          <div class="inline-empty compact-empty"><p>尚无反复错误。继续完成闭卷和延迟复测后，这里会形成可执行诊断。</p></div>`}
        ${model.recurring_errors?.length > 1 ? `<div class="diagnosis-list">${model.recurring_errors.slice(1, 5).map((item) => `<article><span>${escapeHtml(item.error_type)}</span><strong>${escapeHtml(item.detail)}</strong><small>${item.count} 次</small></article>`).join("")}</div>` : ""}
      </section>
    </div>

    <section class="section repair-queue-section">
      <div class="section-head"><div><div class="section-kicker">ERROR REPAIR LOOP</div><h2>错因修复队列</h2><p>错误只有经过新的无提示闭卷，并由你人工确认后才会关闭。</p></div><span class="count-chip">${model.repair_queue?.length || 0} 条</span></div>
      <div class="repair-queue">
        ${model.repair_queue?.length ? model.repair_queue.map((item) => `
          <article class="repair-card ${item.status === "repairing" ? "is-repairing" : ""}">
            <div class="repair-card-main">
              <div class="inline-meta"><span class="status-pill ${item.can_resolve ? "good" : item.status === "repairing" ? "warn" : "danger"}">${item.can_resolve ? "已完成复测 · 待确认" : item.status === "repairing" ? "修复中" : "待修复"}</span><span>${escapeHtml(item.unit_title)}</span><span>${escapeHtml(item.original_name)}</span></div>
              <h3>${escapeHtml(item.detail)}</h3>
              <p>${item.can_resolve ? `后续无提示闭卷已达到当前证据门槛（有效分 ${Number(item.retest_score || 0).toFixed(0)}）。是否真正修复仍由你确认。` : item.status === "repairing" ? escapeHtml(item.resolution_gate_reason || "完成当前针对性闭卷后，回到这里确认是否解决。") : "启动修复会进入同一知识单元的完整闭卷，并冻结这次修复事件。"}</p>
            </div>
            <div class="repair-card-actions">
              ${item.can_resolve ? `<button class="primary-button small-button" data-action="resolve-error" data-error-id="${item.id}">确认已修复</button>` : `<button class="secondary-button small-button" data-action="repair-error" data-error-id="${item.id}">${item.status === "repairing" ? "继续 / 再测" : "开始针对性复测"}</button>`}
            </div>
          </article>`).join("") : `<div class="inline-empty compact-empty"><p>当前没有开放的错因修复任务。</p></div>`}
      </div>
    </section>

    <section class="section">
      <div class="section-head"><div><div class="section-kicker">RECENT EVIDENCE</div><h2>最近作答</h2><p>原始证据不会被一段模糊的 AI 总结覆盖。</p></div><span class="count-chip">${model.latest_attempts?.length || 0} 条</span></div>
      <div class="attempt-timeline">
        ${model.latest_attempts?.length ? model.latest_attempts.map((item, index) => `
          <article>
            <span class="timeline-dot">${String(index + 1).padStart(2, "0")}</span>
            <div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.original_name)} · ${formatDate(item.created_at)} · 提示级别 ${item.hint_level}</p></div>
            <span class="status-pill ${item.score >= 82 ? "good" : item.score >= 60 ? "warn" : "danger"}">${Number(item.score).toFixed(0)} 分 · 置信 ${item.confidence}%</span>
          </article>`).join("") : `<div class="inline-empty compact-empty"><p>尚无作答记录。</p></div>`}
      </div>
    </section>`;
  bindModelActions();
}

async function startErrorRepair(errorId) {
  try {
    const result = await api(`/api/errors/${errorId}/repair`, { method: "POST" });
    state.activeSession = { ...result.unit, ...result.session, original_name: result.error?.original_name || "本地教材" };
    state.startedAtMs = new Date(result.session.started_at).getTime();
    state.feedback = null;
    state.sourcePaneCollapsed = false;
    setView("study");
    toast("已进入针对性修复闭卷；完成后回到学习证据确认是否解决");
  } catch (error) {
    toast(error.message, true);
  }
}

async function resolveError(errorId) {
  if (!window.confirm("确认这条错因已经通过后续无提示复测修复？系统会保留完整历史。")) return;
  try {
    await api(`/api/errors/${errorId}/resolve`, { method: "POST" });
    await loadCore({ silent: true });
    state.view = "model";
    renderModel();
    toast("错因已关闭，历史记录和复测证据仍保留");
  } catch (error) {
    toast(error.message, true);
  }
}

function bindModelActions() {
  document.querySelectorAll('[data-action="repair-error"]').forEach((button) => button.addEventListener("click", () => startErrorRepair(button.dataset.errorId)));
  document.querySelectorAll('[data-action="resolve-error"]').forEach((button) => button.addEventListener("click", () => resolveError(button.dataset.errorId)));
}

function renderSettings() {
  const profile = state.info?.profile || { exam_name: "法学考研", exam_date: "", daily_minutes: 90 };
  const provider = state.info?.provider || {};
  const prefs = state.preferences;
  content.innerHTML = `
    <div class="settings-grid">
      <section class="settings-panel">
        <div class="section-head"><div><div class="section-kicker">LEARNING TARGET</div><h2>学习目标</h2><p>这里只保存用户明确确认的稳定事实。</p></div></div>
        <form id="profileForm" class="settings-form">
          <div class="field full-field"><label for="examName">考试或项目名称</label><input id="examName" value="${escapeHtml(profile.exam_name || "法学考研")}" required></div>
          <div class="field"><label for="examDate">考试日期</label><input id="examDate" type="date" value="${escapeHtml(profile.exam_date || "")}"><small>当前仅记录，尚未参与任务排程。</small></div>
          <div class="field"><label for="dailyMinutes">每日可投入分钟</label><input id="dailyMinutes" type="number" min="10" max="720" value="${profile.daily_minutes || 90}"><small>当前仅记录，尚未约束今日容量。</small></div>
          <div class="form-actions"><button class="primary-button" type="submit">保存本地目标</button></div>
        </form>
      </section>

      <section class="settings-panel">
        <div class="section-head"><div><div class="section-kicker">INTERFACE</div><h2>界面与阅读</h2><p>偏好只保存在当前浏览器，不进入学习证据画像。</p></div></div>
        <form id="uiPrefsForm" class="settings-form">
          <div class="field"><label for="themePreference">主题</label><select id="themePreference"><option value="dark" ${prefs.theme === "dark" ? "selected" : ""}>深色</option><option value="light" ${prefs.theme === "light" ? "selected" : ""}>浅色</option><option value="system" ${prefs.theme === "system" ? "selected" : ""}>跟随系统</option></select></div>
          <div class="field"><label for="densityPreference">信息密度</label><select id="densityPreference"><option value="comfortable" ${prefs.density === "comfortable" ? "selected" : ""}>舒展</option><option value="compact" ${prefs.density === "compact" ? "selected" : ""}>紧凑</option></select></div>
          <div class="field"><label for="motionPreference">动效</label><select id="motionPreference"><option value="full" ${prefs.motion === "full" ? "selected" : ""}>完整反馈</option><option value="reduced" ${prefs.motion === "reduced" ? "selected" : ""}>减少动效</option></select></div>
          <div class="field"><label for="fontScalePreference">文字比例</label><select id="fontScalePreference"><option value="90" ${prefs.fontScale === "90" ? "selected" : ""}>90%</option><option value="100" ${prefs.fontScale === "100" ? "selected" : ""}>100%</option><option value="110" ${prefs.fontScale === "110" ? "selected" : ""}>110%</option><option value="120" ${prefs.fontScale === "120" ? "selected" : ""}>120%</option></select></div>
          <div class="form-actions"><button class="secondary-button" type="submit">应用界面偏好</button></div>
        </form>
      </section>
    </div>

    <section class="section settings-panel provider-panel">
      <div class="section-head"><div><div class="section-kicker">MODEL & PRIVACY</div><h2>模型与隐私</h2><p>智能供应商可以替换，学习记忆归本地产品所有。</p></div><span class="status-pill ${provider.sends_to_cloud ? "warn" : "good"}">${provider.sends_to_cloud ? "云端最小上下文" : "纯本地评分"}</span></div>
      <div class="privacy-contract">
        <article><span>教材文件</span><strong>默认留在本地</strong><p>不会为了问答反复上传整本 PDF。</p></article>
        <article><span>学习证据</span><strong>本地结构化保存</strong><p>作答、错因、提示和复测状态归用户所有。</p></article>
        <article><span>当前模式</span><strong>${escapeHtml(provider.mode || "local")}</strong><p>${provider.sends_to_cloud ? "只发送当前任务所需的知识片段与回答。" : "当前不发送教材、回答或学习记录到云端。"}</p></article>
      </div>
    </section>

    <section class="section settings-panel export-panel">
      <div><div class="section-kicker">PORTABLE REVIEW · V0.1</div><h2>随身复习实验</h2><p>把到期闪卡与挖空导出为 StudyPack，在独立移动复习器完成训练后，再把 StudyEvents 导回桌面。只同步学习行为，不互拷数据库状态。</p></div>
      <div class="action-row">
        <button class="primary-button" data-action="export-study-pack" data-mode="due" data-limit="50">导出今日 StudyPack</button>
        <button class="secondary-button" data-action="export-study-pack" data-mode="all" data-limit="200">导出全部卡片</button>
        <label class="secondary-button file-inline-button" for="studyEventsInput">导入 StudyEvents</label>
        <input id="studyEventsInput" type="file" accept="application/json,.json" hidden>
      </div>
      <p class="settings-note">移动端挖空只做临时字面核对；导回桌面后会使用当前正式规则重新评分。若桌面在离线期间已经学习了同一张卡，导入会返回冲突，不会静默覆盖。</p>
      ${state.portableImportResult ? `
        <div class="portable-import-receipt">
          <strong>最近一次导入回执</strong>
          <span>导入 ${state.portableImportResult.summary?.imported || 0} · 重复 ${state.portableImportResult.summary?.duplicates || 0} · 冲突 ${state.portableImportResult.summary?.conflicts || 0}</span>
          ${state.portableImportResult.summary?.conflicts ? `<details><summary>查看冲突</summary><ul>${state.portableImportResult.results.filter((item) => item.status === "conflict").map((item) => `<li>${escapeHtml(item.item_id || item.event_id)} · ${escapeHtml(portableImportReasonLabel(item.reason))}</li>`).join("")}</ul></details>` : ""}
        </div>` : ""}
    </section>

    <section class="section settings-panel export-panel">
      <div><div class="section-kicker">DATA SOVEREIGNTY</div><h2>数据主权</h2><p>完整备份包含结构化学习状态和事件日志，不包含原 PDF 二进制副本。</p></div>
      <div class="action-row"><a class="primary-button" href="/api/export">导出全部学习数据</a><button class="secondary-button" data-action="go-library">查看本地教材</button></div>
    </section>`;
  bindSettingsActions();
  bindCommonActions();
}

function bindCommonActions() {
  document.querySelectorAll('[data-action="go-library"]').forEach((button) => button.addEventListener("click", () => setView("library")));
  document.querySelectorAll('[data-action="go-retrieval"]').forEach((button) => button.addEventListener("click", () => setView("retrieval")));
  document.querySelectorAll('[data-action="go-today"]').forEach((button) => button.addEventListener("click", () => { state.feedback = null; setView("today"); loadCore({ silent: true }); }));
  document.querySelectorAll('[data-action="resume-session"]').forEach((button) => button.addEventListener("click", () => { state.feedback = null; setView("study"); }));
  document.querySelectorAll('[data-action="start-unit"]').forEach((button) => button.addEventListener("click", () => startUnit(button.dataset.unitId)));
  document.querySelectorAll('[data-action="review-unit"]').forEach((button) => button.addEventListener("click", () => openUnitDialog(button.dataset.unitId)));
  document.querySelectorAll('[data-action="merge-next-unit"]').forEach((button) => button.addEventListener("click", () => mergeNextUnit(button.dataset.unitId, button.dataset.otherUnitId)));
  document.querySelectorAll('[data-action="retest-unit"]').forEach((button) => button.addEventListener("click", async () => {
    state.feedback = null;
    await startUnit(button.dataset.unitId);
  }));
  document.querySelectorAll('[data-action="generate-retrieval"]').forEach((button) => button.addEventListener("click", () => generateRetrieval(button.dataset.unitId, button)));
  document.querySelectorAll('[data-action="create-retrieval"]').forEach((button) => button.addEventListener("click", () => createManualRetrieval(button.dataset.unitId)));
  document.querySelectorAll('[data-action="start-unit-retrieval"]').forEach((button) => button.addEventListener("click", () => startRetrievalQueue({ dueOnly: false, unitId: button.dataset.unitId, label: "知识单元练习" })));
  document.querySelectorAll('[data-action="start-retrieval-queue"]').forEach((button) => button.addEventListener("click", () => startRetrievalQueue({ dueOnly: button.dataset.dueOnly !== "false", label: button.dataset.dueOnly === "false" ? "全部卡片练习" : "到期复习" })));
  document.querySelectorAll('[data-action="start-retrieval-item"]').forEach((button) => button.addEventListener("click", () => startRetrievalItem(button.dataset.itemId)));
  document.querySelectorAll('[data-action="toggle-source-pane"]').forEach((button) => button.addEventListener("click", () => {
    state.sourcePaneCollapsed = !state.sourcePaneCollapsed;
    renderStudy();
  }));
  document.querySelectorAll('[data-action="show-more-units"]').forEach((button) => button.addEventListener("click", () => {
    state.unitVisibleCount += 25;
    updateUnitListView();
  }));
  document.querySelectorAll('[data-action="toggle-unit-body"]').forEach((button) => button.addEventListener("click", () => {
    const clamp = button.closest(".unit-body-clamp");
    if (!clamp) return;
    const expanded = clamp.classList.toggle("is-expanded");
    button.textContent = expanded ? "收起全文" : "展开全文";
  }));
  document.querySelectorAll('[data-action="show-more-retrieval"]').forEach((button) => button.addEventListener("click", () => {
    state.retrievalVisibleCount += 20;
    updateRetrievalListView();
  }));
}

function updateUnitListView() {
  const units = filteredUnits();
  const list = $("#unitList");
  const meta = $("#unitResultMeta");
  if (list) {
    list.innerHTML = (units.length ? units.slice(0, state.unitVisibleCount).map(renderUnitCard).join("") : `<div class="empty-state inline-empty"><div class="empty-symbol">⌕</div><h3>没有匹配的知识单元</h3><p>调整搜索词或筛选条件后再试。</p></div>`)
      + (units.length > state.unitVisibleCount ? `<button class="ghost-button load-more-button" data-action="show-more-units" type="button">显示更多单元（还有 ${units.length - state.unitVisibleCount} 个）</button>` : "");
  }
  if (meta) meta.innerHTML = `<span>显示 ${Math.min(units.length, state.unitVisibleCount)} / ${state.units.length} 个单元</span><span>${unitSortLabel()}</span>`;
  bindCommonActions();
}

function bindLibraryActions() {
  bindCommonActions();
  const input = $("#pdfInput");
  const zone = $("#importZone");
  input?.addEventListener("change", () => input.files?.[0] && importPdf(input.files[0]));
  ["dragenter", "dragover"].forEach((eventName) => zone?.addEventListener(eventName, (event) => { event.preventDefault(); zone.classList.add("is-dragging"); }));
  ["dragleave", "drop"].forEach((eventName) => zone?.addEventListener(eventName, (event) => { event.preventDefault(); zone.classList.remove("is-dragging"); }));
  zone?.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) importPdf(file);
  });
  document.querySelectorAll('[data-action="select-source"]').forEach((card) => card.addEventListener("click", async () => {
    state.selectedSourceId = card.dataset.sourceId;
    state.unitQuery = "";
    state.unitFilter = "all";
    await loadUnits(state.selectedSourceId);
  }));

  $("#unitSearch")?.addEventListener("input", (event) => {
    state.unitQuery = event.target.value;
    state.unitVisibleCount = 25;
    updateUnitListView();
  });
  $("#unitFilter")?.addEventListener("change", (event) => {
    state.unitFilter = event.target.value;
    state.unitVisibleCount = 25;
    updateUnitListView();
  });
  $("#unitSort")?.addEventListener("change", (event) => {
    state.unitSort = event.target.value;
    state.unitVisibleCount = 25;
    updateUnitListView();
  });

  setPageKeyHandler((event) => {
    if (event.key === "/" && !isEditableTarget(event.target)) {
      event.preventDefault();
      $("#unitSearch")?.focus();
    }
  });
}

async function importPdf(file) {
  if (!file.name.toLowerCase().endsWith(".pdf")) return toast("请选择 PDF 文件", true);
  const form = new FormData();
  form.append("file", file);
  try {
    toast("教材已进入本地导入队列");
    const result = await api("/api/sources/import", { method: "POST", body: form });
    state.selectedSourceId = result.source.id;
    await loadCore({ silent: true });
    setView("library");
    toast(result.deduplicated ? "检测到相同教材，已复用现有索引" : "文件已保存到本地，正在解析");
  } catch (error) {
    toast(error.message, true);
  }
}

async function startUnit(unitId) {
  if (!unitId) return;
  const unit = state.units.find((item) => item.id === unitId);
  if (unit && unit.status !== "approved") {
    openUnitDialog(unitId);
    toast("先核对来源与学习文本，再确认这个知识单元后开始闭卷");
    return;
  }
  try {
    const result = await api(`/api/units/${unitId}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approve_unit: false }),
    });
    state.activeSession = { ...result.unit, ...result.session, original_name: state.sources.find((s) => s.id === result.unit.source_id)?.original_name || "本地教材" };
    state.startedAtMs = new Date(result.session.started_at).getTime();
    state.feedback = null;
    state.sourcePaneCollapsed = false;
    state.draftStatus = "saved";
    setView("study");
    toast(result.resumed ? "已恢复未完成会话" : "已开始闭卷会话");
  } catch (error) {
    toast(error.message, true);
  }
}


function closeUnitDialog() {
  const dialog = $("#unitDialog");
  if (dialog?.open && typeof dialog.close === "function") dialog.close();
  else dialog?.removeAttribute("open");
  state.unitDialogContext = null;
}

function openUnitDialog(unitId) {
  const unit = state.units.find((candidate) => candidate.id === unitId);
  const dialog = $("#unitDialog");
  const body = $("#unitDialogBody");
  if (!unit || !dialog || !body) return toast("未找到知识单元", true);
  state.unitDialogContext = { unitId };
  const objectiveTypes = ["精确复现型", "辨析型", "适用型", "理解解释型", "表达型", "综合型"];
  body.innerHTML = `
    <div class="unit-review-meta">
      <span class="status-pill ${unit.status === "approved" ? "good" : "warn"}">${unit.status === "approved" ? "已确认" : "待确认"}</span>
      <span>第 ${unit.page_start}-${unit.page_end} 页</span><span>版本 ${unit.version}</span>
    </div>
    <div class="dialog-field-grid unit-review-grid">
      <div class="field full-field"><label for="unitDialogTitleInput">知识单元标题</label><input id="unitDialogTitleInput" value="${escapeHtml(unit.title)}" maxlength="160"></div>
      <div class="field"><label for="unitDialogObjective">学习材质</label><select id="unitDialogObjective">${objectiveTypes.map((item) => `<option value="${item}" ${item === unit.objective_type ? "selected" : ""}>${item}</option>`).join("")}</select></div>
      <div class="field"><label>来源范围</label><div class="field-readonly">第 ${unit.page_start}-${unit.page_end} 页 · <a class="pdf-jump" href="${pdfJumpHref(unit.source_id, unit.page_start)}" target="_blank" rel="noopener">在 PDF 中打开本单元</a></div></div>
      <div class="field full-field"><label>教材来源快照（只读）</label><textarea rows="9" readonly aria-readonly="true">${escapeHtml(unit.source_basis_text || "当前单元缺少可验证的来源快照，请回到原 PDF 核对。")}</textarea><small>来源状态：${escapeHtml(unit.source_basis_status || "unknown")} · 这一层不随学习笔记编辑而改变。</small></div>
      <div class="field full-field"><label for="unitDialogText">学习单元文本（可编辑）</label><textarea id="unitDialogText" rows="16">${escapeHtml(unit.body)}</textarea><small>修改这里会形成新的学习材料版本，当前掌握状态失效、活动卡片进入 stale，并要求重新确认。拆分时把光标放在新单元开始处。</small>
        <div class="selection-builder" id="unitSelectionBuilder" hidden>
          <div class="selection-head"><strong>划选建卡</strong><span>在正文中划选一段文字（2–80 字），即可直接建立挖空或闪卡，不修改单元正文</span></div>
          <div class="selection-preview" id="unitSelectionPreview"></div>
          <div class="selection-actions">
            <label class="selection-template-label" for="unitFlashTemplate">闪卡提问方式</label>
            <select id="unitFlashTemplate">
              <option value="recall">用自己的话复述</option>
              <option value="define">什么是{主题}？</option>
              <option value="require">的构成要件有哪些？</option>
              <option value="condition">的适用条件是什么？</option>
              <option value="classify">分为哪几类？</option>
              <option value="distinguish">与相近概念有何区别？</option>
              <option value="exception">的例外或限制情形有哪些？</option>
              <option value="basis">的法律依据是什么？</option>
              <option value="meaning">的意义是什么？</option>
            </select>
            <button type="button" class="secondary-button small-button" data-action="selection-cloze">挖空</button>
            <button type="button" class="secondary-button small-button" data-action="selection-flashcard">闪卡</button>
            <button type="button" class="ghost-button small-button" data-action="selection-clear">清除</button>
          </div>
          <small>进阶：在正文里用 <code>==内容==</code> 标记多个空，保存时自动生成一张多空挖空卡，标记随后自动清除。</small>
        </div>
      </div>
    </div>
    <div class="notice warn"><strong>证据保护</strong>：教材来源快照保持只读；学习文本编辑只产生新版本。拆分/合并会归档旧单元并新建单元，历史闭卷和卡片作答继续指向当时版本。</div>`;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  requestAnimationFrame(() => $("#unitDialogTitleInput")?.focus());
  bindUnitSelection();
  $("#unitDialogText")?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      saveUnitDialog();
    }
  });
  document.querySelector('[data-action="selection-cloze"]')?.addEventListener("click", selectionBuildCloze);
  document.querySelector('[data-action="selection-flashcard"]')?.addEventListener("click", selectionBuildFlashcard);
  document.querySelector('[data-action="selection-clear"]')?.addEventListener("click", hideUnitSelection);
}

function bindUnitSelection() {
  const area = $("#unitDialogText");
  const builder = $("#unitSelectionBuilder");
  if (!area || !builder) return;
  const update = () => {
    if (document.activeElement !== area) {
      builder.hidden = true;
      state.unitSelection = null;
      return;
    }
    const start = area.selectionStart ?? 0;
    const end = area.selectionEnd ?? 0;
    if (start === end) {
      builder.hidden = true;
      state.unitSelection = null;
      return;
    }
    const selected = area.value.slice(start, end).replace(/\s+/g, " ").trim();
    if (selected.length < 2 || selected.length > 80) {
      builder.hidden = true;
      state.unitSelection = null;
      return;
    }
    state.unitSelection = { start, end, text: selected };
    const preview = $("#unitSelectionPreview");
    if (preview) preview.textContent = `已划选：…${selected.slice(0, 64)}${selected.length > 64 ? "…" : ""}…`;
    builder.hidden = false;
  };
  ["mouseup", "keyup"].forEach((eventName) => area.addEventListener(eventName, () => setTimeout(update, 0)));
}

function buildSelectionContext(body, selected) {
  const index = body.indexOf(selected);
  if (index < 0) return { text: selected };
  const window = 90;
  const start = Math.max(0, index - window);
  const end = Math.min(body.length, index + selected.length + window);
  const prefix = start > 0 ? "……" : "";
  const suffix = end < body.length ? "……" : "";
  return { text: prefix + body.slice(start, end).replace(/\r/g, "").trim() + suffix };
}

function hideUnitSelection() {
  state.unitSelection = null;
  const builder = $("#unitSelectionBuilder");
  if (builder) builder.hidden = true;
}

function refreshRetrievalAfterCreate() {
  if (state.view === "retrieval") {
    loadRetrievalSummary();
    renderRetrieval();
  }
}

async function selectionBuildCloze() {
  const selection = state.unitSelection;
  const unitId = state.unitDialogContext?.unitId;
  if (!selection || !unitId) return toast("请先在正文中划选一段文字", true);
  const unit = state.units.find((candidate) => candidate.id === unitId);
  const context = buildSelectionContext(unit?.body || "", selection.text);
  const clozeText = context.text.replace(selection.text, "____");
  if (clozeText === context.text) return toast("未能在教材正文中定位到该片段", true);
  try {
    await api(`/api/units/${unitId}/retrieval-items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_type: "cloze", prompt: clozeText, answer: selection.text, cloze_text: clozeText, source_excerpt: context.text }),
    });
    toast("已建立挖空卡（来源保留上下文）");
    hideUnitSelection();
    refreshRetrievalAfterCreate();
  } catch (error) {
    toast(error.message, true);
  }
}

const UNIT_FLASHCARD_TEMPLATES = {
  recall: (topic) => `用自己的话复述：${topic}（注意规则、条件与例外）`,
  define: (topic) => `什么是${topic}？`,
  require: (topic) => `${topic}的构成要件有哪些？`,
  condition: (topic) => `${topic}的适用条件是什么？`,
  classify: (topic) => `${topic}分为哪几类？`,
  distinguish: (topic) => `${topic}与相近概念有何区别？`,
  exception: (topic) => `${topic}的例外或限制情形有哪些？`,
  basis: (topic) => `${topic}的法律依据是什么？`,
  meaning: (topic) => `${topic}的意义是什么？`,
};

async function selectionBuildFlashcard() {
  const selection = state.unitSelection;
  const unitId = state.unitDialogContext?.unitId;
  if (!selection || !unitId) return toast("请先在正文中划选一段文字", true);
  const unit = state.units.find((candidate) => candidate.id === unitId);
  const context = buildSelectionContext(unit?.body || "", selection.text);
  const template = $("#unitFlashTemplate")?.value || "recall";
  const formatter = UNIT_FLASHCARD_TEMPLATES[template] || UNIT_FLASHCARD_TEMPLATES.recall;
  const topic = selection.text.length > 16 ? `${selection.text.slice(0, 16)}…` : selection.text;
  try {
    await api(`/api/units/${unitId}/retrieval-items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_type: "flashcard", prompt: formatter(topic), answer: selection.text, source_excerpt: context.text }),
    });
    toast("已建立闪卡");
    hideUnitSelection();
    refreshRetrievalAfterCreate();
  } catch (error) {
    toast(error.message, true);
  }
}

const PdfReader = {
  lib: null,
  pdfDoc: null,
  sourceId: null,
  page: 1,
  scale: 1.3,
  locateRects: [],
  locatePage: null,

  async ensureLib() {
    if (this.lib) return this.lib;
    const lib = await import("/vendor/pdfjs/pdf.min.mjs");
    lib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.min.mjs";
    lib.GlobalWorkerOptions.cMapUrl = "/vendor/pdfjs/cmaps/";
    lib.GlobalWorkerOptions.cMapPacked = true;
    this.lib = lib;
    return lib;
  },

  status(text, isError = false) {
    const el = $("#pdfReaderStatus");
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("is-error", Boolean(isError));
    el.hidden = false;
  },

  async open({ sourceId, page, locateText, titleText }) {
    this.sourceId = sourceId;
    this.page = page || 1;
    this.locateRects = [];
    this.locatePage = null;
    const statusEl = $("#pdfReaderStatus");
    if (statusEl) statusEl.hidden = true;
    try {
      const lib = await this.ensureLib();
      this.status("正在加载教材（首次约数秒）……");
      this.pdfDoc = await lib.getDocument({
        url: `/api/source-files/${sourceId}`,
        cMapUrl: "/vendor/pdfjs/cmaps/",
        cMapPacked: true,
      }).promise;
      const title = $("#pdfViewerTitle");
      if (title) title.textContent = titleText || "教材原文";
      if (locateText) {
        this.status("正在定位原文句子……");
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 12000);
        try {
          const response = await fetch(`/api/locate?source_id=${encodeURIComponent(sourceId)}&text=${encodeURIComponent(locateText)}`, { signal: controller.signal });
          clearTimeout(timer);
          if (response.ok) {
            const located = await response.json();
            this.page = located.page;
            this.locatePage = located.page;
            this.locateRects = located.rects || [];
          }
        } catch (_) {
          /* 定位失败回退到页码 */
        }
      }
      await this.render();
      if (this.locateRects.length) {
        // 定位完成后滚动到高亮位置（显式计算，scrollIntoView 在 dialog 内不可靠）
        requestAnimationFrame(() => this.scrollToHighlight());
      }
      if (this.locatePage) {
        requestAnimationFrame(() => {
          const first = this.highlightEl()?.firstElementChild;
          if (first) first.scrollIntoView({ block: "center", behavior: "smooth" });
        });
      }
    } catch (error) {
      this.status(`无法打开教材：${error.message || error}`, true);
    }
  },

  highlightEl() {
    return $("#pdfReaderHighlights");
  },

  async render() {
    if (!this.pdfDoc) return;
    const pdfPage = await this.pdfDoc.getPage(this.page);
    const viewport = pdfPage.getViewport({ scale: this.scale });
    const canvas = $("#pdfReaderCanvas");
    if (!canvas) return;
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;
    const renderTask = pdfPage.render({ canvasContext: canvas.getContext("2d"), viewport });
    await renderTask.promise;
    this.lastViewport = viewport;
    const statusEl = $("#pdfReaderStatus");
    if (statusEl) statusEl.hidden = true;
    const host = $("#pdfReaderCanvasHost");
    if (host) host.style.width = `${Math.floor(viewport.width)}px`;
    const pageLabel = $("#pdfViewerPage");
    if (pageLabel) pageLabel.textContent = `第 ${this.page} / ${this.pdfDoc.numPages} 页`;
    this.applyHighlights(viewport);
  },

  applyHighlights(viewport) {
    const host = this.highlightEl();
    if (!host) return;
    host.innerHTML = "";
    if (!this.locateRects.length || this.locatePage !== this.page) return;
    const scale = viewport.scale;
    for (const rect of this.locateRects) {
      const div = document.createElement("div");
      div.className = "pdf-highlight";
      div.style.left = `${rect.x0 * scale}px`;
      div.style.top = `${rect.y0 * scale}px`;
      div.style.width = `${Math.max(2, (rect.x1 - rect.x0) * scale)}px`;
      div.style.height = `${Math.max(14, (rect.y1 - rect.y0) * scale)}px`;
      host.appendChild(div);
    }
  },

  scrollToHighlight() {
    const scroller = document.querySelector(".pdf-viewer-body");
    const first = this.highlightEl()?.firstElementChild;
    if (!scroller || !first) return;
    const rect = first.getBoundingClientRect();
    const bodyRect = scroller.getBoundingClientRect();
    const target = scroller.scrollTop + (rect.top - bodyRect.top) - scroller.clientHeight / 2 + rect.height / 2;
    scroller.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
  },

  async step(delta) {
    if (!this.pdfDoc) return;
    const next = this.page + delta;
    if (next < 1 || next > this.pdfDoc.numPages) return;
    this.page = next;
    this.locatePage = null;
    this.locateRects = [];
    await this.render();
  },

  async zoom(delta) {
    if (!this.pdfDoc) return;
    this.scale = Math.min(3, Math.max(0.6, this.scale + delta));
    await this.render();
  },

  async close() {
    if (this.pdfDoc) {
      try { await this.pdfDoc.destroy(); } catch (_) {}
    }
    this.pdfDoc = null;
    this.locateRects = [];
    this.locatePage = null;
    const dialog = $("#pdfViewerDialog");
    if (dialog?.open && typeof dialog.close === "function") dialog.close();
    else dialog?.removeAttribute("open");
    state.pdfViewer = null;
  },
};

window.PdfReader = PdfReader; // 调试与外部接入入口

function openPdf(sourceId, page, locateText) {
  const dialog = $("#pdfViewerDialog");
  if (!dialog) {
    window.open(pdfJumpHref(sourceId, page), "_blank", "noopener");
    return;
  }
  state.pdfViewer = { sourceId, page: page || 1, locateText: locateText || null };
  const source = Array.isArray(state.sources) ? state.sources.find((item) => item.id === sourceId) : null;
  const titleText = source?.original_name || "教材原文";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  PdfReader.open({ sourceId, page: page || 1, locateText: locateText || null, titleText });
}

function bindPdfViewerActions() {
  document.querySelector('[data-action="close-pdf-viewer"]')?.addEventListener("click", () => PdfReader.close());
  document.querySelector('[data-action="pdf-prev"]')?.addEventListener("click", () => PdfReader.step(-1));
  document.querySelector('[data-action="pdf-next"]')?.addEventListener("click", () => PdfReader.step(1));
  document.querySelector('[data-action="pdf-zoom-in"]')?.addEventListener("click", () => PdfReader.zoom(0.15));
  document.querySelector('[data-action="pdf-zoom-out"]')?.addEventListener("click", () => PdfReader.zoom(-0.15));
  document.querySelector('[data-action="pdf-external"]')?.addEventListener("click", () => {
    if (state.pdfViewer) window.open(pdfJumpHref(state.pdfViewer.sourceId, PdfReader.page), "_blank", "noopener");
  });
}

// 应用内查看：拦截所有“在 PDF 中查看 / 打开原 PDF”链接，改为自研阅读器
// （新标签打开会被浏览器扩展如 AIX Downloader 劫持成下载界面）。
// data-locate 为定位目标文本（原句/答案），命中后跳页并高亮。
document.addEventListener("click", (event) => {
  const link = event.target.closest?.("a.pdf-jump, a[href*='/api/source-files/']");
  if (!link) return;
  const href = link.getAttribute("href") || "";
  const match = href.match(/\/api\/source-files\/([^#?]+)(?:#page=(\d+))?/);
  if (!match) return;
  event.preventDefault();
  openPdf(match[1], match[2] ? Number(match[2]) : null, link.dataset.locate || null);
});

function pdfJumpHref(sourceId, page) {
  return page ? `/api/source-files/${sourceId}#page=${page}` : `/api/source-files/${sourceId}`;
}

function highlightInExcerpt(excerpt, answer) {
  if (!excerpt) return "";
  let html = escapeHtml(excerpt);
  if (!answer) return html;
  for (const part of answer.split("\x1f")) {
    const escaped = escapeHtml(part.trim());
    if (escaped && html.includes(escaped)) {
      html = html.split(escaped).join(`<mark class="excerpt-mark">${escaped}</mark>`);
    }
  }
  return html;
}

async function saveUnitDialog({ approve = false } = {}) {
  const unitId = state.unitDialogContext?.unitId;
  if (!unitId) return;
  const title = $("#unitDialogTitleInput")?.value.trim() || "";
  let body = $("#unitDialogText")?.value.trim() || "";
  const objectiveType = $("#unitDialogObjective")?.value || "综合型";
  if (!title || body.length < 20) return toast("标题不能为空，正文至少保留 20 个字符", true);
  // ==内容== 标记 → 生成一张多空挖空卡（取首个含标记的段落，最多 4 空），随后清除标记
  const markerParagraph = body.split(/\n\s*\n/).find((para) => para.includes("==")) || "";
  const markers = [...markerParagraph.matchAll(/==([^=]{1,40}?)==/g)]
    .map((match) => match[1].replace(/\s+/g, " ").trim())
    .filter((text) => text.length >= 2)
    .slice(0, 4);
  if (markers.length) {
    const unitId = state.unitDialogContext?.unitId;
    const clozeText = markerParagraph.replace(/==([^=]{1,40}?)==/g, "____");
    try {
      await api(`/api/units/${unitId}/retrieval-items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_type: "cloze", prompt: clozeText, answer: markers.join("\x1f"), cloze_text: clozeText, source_excerpt: markerParagraph }),
      });
      toast(`已从 ==标记== 生成 ${markers.length} 空挖空卡`);
      refreshRetrievalAfterCreate();
    } catch (error) {
      toast(error.message, true);
    }
    body = body.replace(/==([^=]{1,40}?)==/g, "$1");
  }
  try {
    const currentUnit = state.units.find((item) => item.id === unitId);
    const bodyChanged = Boolean(currentUnit && currentUnit.body !== body);
    const result = await api(`/api/units/${unitId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, body, objective_type: objectiveType, ...(approve && !bodyChanged ? { status: "approved" } : {}) }),
    });
    closeUnitDialog();
    await loadCore({ silent: true });
    state.view = "library";
    renderLibrary();
    if (bodyChanged) {
      toast("学习文本已形成新版本，旧掌握证据已失效；请重新审核后再确认");
    } else {
      toast(approve && result.status === "approved" ? "知识单元已确认" : "知识单元已保存");
    }
  } catch (error) {
    toast(error.message, true);
  }
}

async function splitUnitDialog() {
  const unitId = state.unitDialogContext?.unitId;
  const textarea = $("#unitDialogText");
  if (!unitId || !textarea) return;
  const splitAt = Number(textarea.selectionStart || 0);
  const body = textarea.value;
  if (splitAt < 20 || body.length - splitAt < 20) return toast("请把光标放在正文内部，拆分后两段都至少保留 20 个字符", true);
  const baseTitle = $("#unitDialogTitleInput")?.value.trim() || "知识单元";
  const objectiveType = $("#unitDialogObjective")?.value || "综合型";
  if (!window.confirm("拆分会归档当前知识单元并新建两个待确认单元；历史作答不会被改写。继续吗？")) return;
  try {
    await api(`/api/units/${unitId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        split_at: splitAt,
        body,
        left_title: `${baseTitle}（上）`,
        right_title: `${baseTitle}（下）`,
        left_objective_type: objectiveType,
        right_objective_type: objectiveType,
      }),
    });
    closeUnitDialog();
    await loadCore({ silent: true });
    state.view = "library";
    renderLibrary();
    toast("已拆分为两个待确认知识单元，旧证据已保留");
  } catch (error) {
    toast(error.message, true);
  }
}

async function mergeNextUnit(unitId, otherUnitId) {
  if (!unitId || !otherUnitId) return;
  const first = state.units.find((item) => item.id === unitId);
  const second = state.units.find((item) => item.id === otherUnitId);
  if (!first || !second) return toast("未找到相邻知识单元", true);
  if (!window.confirm(`将“${first.title}”与下一单元“${second.title}”合并为新的待确认单元？旧单元会归档，历史证据继续保留。`)) return;
  try {
    const result = await api(`/api/units/${unitId}/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ other_unit_id: otherUnitId }),
    });
    await loadCore({ silent: true });
    state.view = "library";
    renderLibrary();
    toast(`已合并为“${result.unit.title}”，请继续审核边界与标题`);
  } catch (error) {
    toast(error.message, true);
  }
}


function openRetrievalDialog({ mode, unitId = null, item = null } = {}) {
  const dialog = $("#retrievalDialog");
  const body = $("#retrievalDialogBody");
  const title = $("#retrievalDialogTitle");
  const description = $("#retrievalDialogDescription");
  const submit = $("#retrievalDialogSubmit");
  if (!dialog || !body) return;

  const itemType = item?.item_type || "flashcard";
  state.dialogContext = { mode, unitId, itemId: item?.id || null };
  title.textContent = mode === "edit" ? "编辑提取卡片" : "建立提取卡片";
  description.textContent = mode === "edit" ? "编辑会创建新的卡片版本，历史作答仍保留旧版本快照。" : "题面、答案和来源必须形成稳定的一一对应关系。";
  submit.textContent = mode === "edit" ? "保存新版本" : "建立卡片";
  body.innerHTML = `
    <div class="dialog-field-grid">
      <div class="field">
        <label for="dialogItemType">卡片类型</label>
        <select id="dialogItemType" ${mode === "edit" ? "disabled" : ""}>
          <option value="flashcard" ${itemType === "flashcard" ? "selected" : ""}>闪卡</option>
          <option value="cloze" ${itemType === "cloze" ? "selected" : ""}>挖空</option>
        </select>
      </div>
      <div class="field dialog-source-field">
        <label>关联知识单元</label>
        <div class="field-readonly">${escapeHtml(item?.unit_title || state.units.find((unit) => unit.id === unitId)?.title || "当前知识单元")}</div>
      </div>
    </div>
    <div class="field" id="dialogPromptField">
      <label for="dialogPrompt">闪卡问题</label>
      <input id="dialogPrompt" value="${escapeHtml(itemType === "flashcard" ? item?.prompt || "" : "")}" placeholder="例如：善意取得的构成要件是什么？">
      <small>问题应能独立触发一个明确知识节点。</small>
    </div>
    <div class="field" id="dialogClozeField">
      <label for="dialogCloze">挖空句</label>
      <input id="dialogCloze" value="${escapeHtml(itemType === "cloze" ? item?.cloze_text || item?.prompt?.replace(/^填空：/, "") || "" : "")}" placeholder="用 ____ 标出唯一空位">
      <small>当前版本只支持单空挖空，必须包含一个 ____。</small>
    </div>
    <div class="field">
      <label for="dialogAnswer">标准答案</label>
      <textarea id="dialogAnswer" rows="6" placeholder="写入可被来源支持的标准答案">${escapeHtml(item?.answer || "")}</textarea>
      <small>答案修改后，卡片会重置为新卡，避免新内容继承旧掌握状态。</small>
    </div>`;

  $("#dialogItemType")?.addEventListener("change", syncRetrievalDialogFields);
  syncRetrievalDialogFields();
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  requestAnimationFrame(() => (itemType === "cloze" ? $("#dialogCloze") : $("#dialogPrompt"))?.focus());
}

function syncRetrievalDialogFields() {
  const type = $("#dialogItemType")?.value || "flashcard";
  $("#dialogPromptField")?.classList.toggle("hidden", type !== "flashcard");
  $("#dialogClozeField")?.classList.toggle("hidden", type !== "cloze");
}

function closeRetrievalDialog() {
  const dialog = $("#retrievalDialog");
  state.dialogContext = null;
  if (dialog?.open && typeof dialog.close === "function") dialog.close();
  else dialog?.removeAttribute("open");
}

async function submitRetrievalDialog(event) {
  event.preventDefault();
  const context = state.dialogContext;
  if (!context) return closeRetrievalDialog();
  const itemType = $("#dialogItemType")?.value || "flashcard";
  const answer = $("#dialogAnswer")?.value.trim() || "";
  const clozeText = $("#dialogCloze")?.value.trim() || "";
  const promptText = itemType === "cloze" ? `填空：${clozeText}` : $("#dialogPrompt")?.value.trim() || "";
  if (!promptText || !answer) return toast("题面和答案不能为空", true);
  if (itemType === "cloze" && !clozeText.includes("____")) return toast("挖空句必须包含 ____", true);

  const button = $("#retrievalDialogSubmit");
  button.disabled = true;
  button.textContent = context.mode === "edit" ? "正在保存版本…" : "正在建立卡片…";
  try {
    if (context.mode === "edit") {
      const payload = { prompt: promptText, answer };
      if (itemType === "cloze") payload.cloze_text = clozeText;
      await api(`/api/retrieval-items/${context.itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      closeRetrievalDialog();
      await loadCore({ silent: true });
      state.view = "retrieval";
      renderRetrieval();
      toast("卡片已更新，旧复习状态已重置为新卡");
    } else {
      const created = await api(`/api/units/${context.unitId}/retrieval-items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_type: itemType, prompt: promptText, answer, cloze_text: itemType === "cloze" ? clozeText : null }),
      });
      closeRetrievalDialog();
      await loadCore({ silent: true });
      toast(itemType === "cloze" ? "手动挖空已建立并进入复习队列" : "手动闪卡已建立并进入复习队列");
      await startRetrievalItem(created.id);
    }
  } catch (error) {
    button.disabled = false;
    button.textContent = context.mode === "edit" ? "保存新版本" : "建立卡片";
    toast(error.message, true);
  }
}

async function createManualRetrieval(unitId) {
  if (!unitId) return;
  openRetrievalDialog({ mode: "create", unitId });
}

async function generateRetrieval(unitId, button) {
  if (!unitId) return;
  const originalText = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "正在本地生成…";
  }
  try {
    const result = await api(`/api/units/${unitId}/retrieval-items/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_types: ["flashcard", "cloze"], max_per_type: 3 }),
    });
    await loadCore({ silent: true });
    toast(result.created ? `已生成 ${result.created} 张卡片，重复内容已自动跳过` : result.reactivated ? `已重新启用 ${result.reactivated} 张与当前知识单元一致的卡片` : result.skipped_archived ? `已跳过 ${result.skipped_archived} 张用户主动停用的卡片` : "卡片已存在，直接进入练习");
    if (result.items?.length) await startRetrievalQueue({ dueOnly: false, unitId, label: "新生成卡片" });
  } catch (error) {
    toast(error.message, true);
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function startRetrievalQueue({ dueOnly = true, unitId = null, label = "到期复习" } = {}) {
  try {
    const params = new URLSearchParams({ due_only: String(dueOnly), limit: "100" });
    if (unitId) params.set("unit_id", unitId);
    const items = await api(`/api/retrieval-items?${params.toString()}`);
    if (!items.length) {
      setView("retrieval");
      return toast(dueOnly ? "当前没有到期卡片" : "当前范围没有可练习卡片");
    }
    state.retrievalQueue = items;
    state.retrievalActive = items[0];
    state.retrievalReveal = null;
    state.retrievalResult = null;
    state.retrievalStartedAtMs = Date.now();
    state.retrievalCompleted = 0;
    state.retrievalQueueLabel = label;
    state.retrievalSubmitting = false;
    setView("retrieval");
  } catch (error) {
    toast(error.message, true);
  }
}

async function startRetrievalItem(itemId) {
  if (!itemId) return;
  try {
    const item = await api(`/api/retrieval-items/${itemId}`);
    state.retrievalQueue = [item];
    state.retrievalActive = item;
    state.retrievalReveal = null;
    state.retrievalResult = null;
    state.retrievalStartedAtMs = Date.now();
    state.retrievalCompleted = 0;
    state.retrievalQueueLabel = "单卡练习";
    state.retrievalSubmitting = false;
    setView("retrieval");
  } catch (error) {
    toast(error.message, true);
  }
}

async function revealRetrieval() {
  if (!state.retrievalActive?.id) return;
  try {
    state.retrievalReveal = await api(`/api/retrieval-items/${state.retrievalActive.id}/reveal`, { method: "POST" });
    renderRetrieval();
  } catch (error) {
    toast(error.message, true);
  }
}

async function submitRetrievalAttempt({ rating = null, responseText = "" } = {}) {
  const item = state.retrievalActive;
  if (!item || state.retrievalSubmitting) return;
  state.retrievalSubmitting = true;
  document.querySelectorAll('[data-action="rate-flashcard"], [data-action="submit-cloze"], [data-action="give-up-cloze"]').forEach((button) => { button.disabled = true; });
  try {
    const elapsed = Date.now() - (state.retrievalStartedAtMs || Date.now());
    const result = await api(`/api/retrieval-items/${item.id}/attempts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        response_text: responseText,
        rating,
        elapsed_ms: elapsed,
        revealed_answer: item.item_type === "flashcard" ? Boolean(state.retrievalReveal) : true,
      }),
    });
    state.retrievalResult = result;
    stopTimer();
    renderRetrieval();
  } catch (error) {
    document.querySelectorAll('[data-action="rate-flashcard"], [data-action="submit-cloze"], [data-action="give-up-cloze"]').forEach((button) => { button.disabled = false; });
    toast(error.message, true);
  } finally {
    state.retrievalSubmitting = false;
  }
}

async function nextRetrieval() {
  const completedId = state.retrievalActive?.id;
  if (completedId) state.retrievalQueue = state.retrievalQueue.filter((item) => item.id !== completedId);
  state.retrievalCompleted += 1;
  state.retrievalResult = null;
  state.retrievalReveal = null;
  state.retrievalSubmitting = false;
  if (state.retrievalQueue.length) {
    state.retrievalActive = state.retrievalQueue[0];
    state.retrievalStartedAtMs = Date.now();
    renderRetrieval();
    return;
  }
  state.retrievalActive = null;
  state.retrievalStartedAtMs = null;
  state.retrievalCompleted = 0;
  await loadCore({ silent: true });
  state.view = "retrieval";
  renderRetrieval();
  toast("本轮卡片提取已完成");
}

async function exitRetrieval() {
  state.retrievalQueue = [];
  state.retrievalActive = null;
  state.retrievalReveal = null;
  state.retrievalResult = null;
  state.retrievalStartedAtMs = null;
  state.retrievalCompleted = 0;
  state.retrievalSubmitting = false;
  stopTimer();
  await loadCore({ silent: true });
  state.view = "retrieval";
  renderRetrieval();
}

async function editRetrievalItem(itemId) {
  const item = state.retrievalAll.find((candidate) => candidate.id === itemId);
  if (!item) return toast("未找到这张卡片", true);
  openRetrievalDialog({ mode: "edit", item });
}

async function archiveRetrievalItem(itemId) {
  if (!window.confirm("停用后不会再进入复习队列，历史作答仍会保留。确定继续吗？")) return;
  try {
    await api(`/api/retrieval-items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "archived" }),
    });
    await loadCore({ silent: true });
    state.view = "retrieval";
    renderRetrieval();
    toast("卡片已停用");
  } catch (error) {
    toast(error.message, true);
  }
}

function bindRetrievalManageActions({ includeStart = true } = {}) {
  if (includeStart) document.querySelectorAll('[data-action="start-retrieval-item"]').forEach((button) => button.addEventListener("click", () => startRetrievalItem(button.dataset.itemId)));
  document.querySelectorAll('[data-action="edit-retrieval"]').forEach((button) => button.addEventListener("click", () => editRetrievalItem(button.dataset.itemId)));
  document.querySelectorAll('[data-action="archive-retrieval"]').forEach((button) => button.addEventListener("click", () => archiveRetrievalItem(button.dataset.itemId)));
}

function updateRetrievalListView() {
  const items = filteredRetrievalItems();
  const list = $("#retrievalManageList");
  const count = $("#retrievalResultCount");
  if (list) {
    list.innerHTML = (items.length ? items.slice(0, state.retrievalVisibleCount).map(renderRetrievalManageItem).join("") : `<div class="empty-state inline-empty"><div class="empty-symbol">卡</div><h3>没有匹配的卡片</h3><p>调整筛选条件，或前往教材库生成新的挖空与闪卡。</p></div>`)
      + (items.length > state.retrievalVisibleCount ? `<button class="ghost-button load-more-button" data-action="show-more-retrieval" type="button">显示更多卡片（还有 ${items.length - state.retrievalVisibleCount} 张）</button>` : "");
  }
  if (count) count.textContent = `${Math.min(items.length, state.retrievalVisibleCount)} / ${state.retrievalSummary?.total || 0} 张`;
  bindRetrievalManageActions();
}

function bindRetrievalActions() {
  bindCommonActions();
  document.querySelector('[data-action="reveal-retrieval"]')?.addEventListener("click", revealRetrieval);
  document.querySelectorAll('[data-action="rate-flashcard"]').forEach((button) => button.addEventListener("click", () => submitRetrievalAttempt({ rating: button.dataset.rating })));
  document.querySelector('[data-action="submit-cloze"]')?.addEventListener("click", () => {
    const inputs = Array.from(document.querySelectorAll(".cloze-input"));
    const responses = inputs.map((input) => input.value.trim()).filter(Boolean);
    if (!responses.length) return toast("请先填写挖空答案", true);
    submitRetrievalAttempt({ responseText: responses.join("\x1f") });
  });
  document.querySelector('[data-action="give-up-cloze"]')?.addEventListener("click", () => submitRetrievalAttempt({ responseText: "（未能作答）" }));
  document.querySelectorAll(".cloze-input").forEach((input, index, all) => {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        if (index < all.length - 1) all[index + 1].focus();
        else document.querySelector('[data-action="submit-cloze"]')?.click();
      }
    });
  });
  document.querySelector('[data-action="next-retrieval"]')?.addEventListener("click", nextRetrieval);
  document.querySelectorAll('[data-action="exit-retrieval"]').forEach((button) => button.addEventListener("click", exitRetrieval));
  bindRetrievalManageActions({ includeStart: false });
  document.querySelectorAll('[data-action="filter-retrieval"]').forEach((button) => button.addEventListener("click", () => {
    state.retrievalFilter = button.dataset.filter;
    state.retrievalVisibleCount = 20;
    renderRetrievalDashboard();
  }));
  $("#retrievalSort")?.addEventListener("change", (event) => {
    state.retrievalSort = event.target.value;
    state.retrievalVisibleCount = 20;
    updateRetrievalListView();
  });
  $("#retrievalSearch")?.addEventListener("input", (event) => {
    state.retrievalQuery = event.target.value;
    state.retrievalVisibleCount = 20;
    updateRetrievalListView();
  });

  setPageKeyHandler((event) => {
    if (event.isComposing) return;
    if (!state.retrievalActive && event.key === "/" && !isEditableTarget(event.target)) {
      event.preventDefault();
      $("#retrievalSearch")?.focus();
      return;
    }
    if (!state.retrievalActive || isEditableTarget(event.target)) return;
    if (state.retrievalResult && event.key === "Enter") {
      event.preventDefault();
      document.querySelector('[data-action="next-retrieval"]')?.click();
      return;
    }
    if (state.retrievalActive.item_type === "flashcard" && !state.retrievalReveal && (event.key === " " || event.code === "Space")) {
      event.preventDefault();
      document.querySelector('[data-action="reveal-retrieval"]')?.click();
      return;
    }
    if (state.retrievalActive.item_type === "flashcard" && state.retrievalReveal) {
      const ratingMap = { "1": "again", "2": "hard", "3": "good", "4": "easy" };
      const rating = ratingMap[event.key];
      if (rating) {
        event.preventDefault();
        document.querySelector(`[data-action="rate-flashcard"][data-rating="${rating}"]`)?.click();
      }
    }
  });
}

function startRetrievalTimer() {
  stopTimer();
  const update = () => {
    const timer = $("#retrievalTimer");
    if (timer) timer.textContent = formatDuration(Date.now() - (state.retrievalStartedAtMs || Date.now()));
  };
  update();
  state.timerHandle = setInterval(update, 1000);
}

function updateAnswerTelemetry() {
  const answer = $("#answerText")?.value || "";
  const count = $("#answerCount");
  if (count) count.textContent = `${countAnswerUnits(answer)} 字`;
}

function bindStudyActions() {
  bindCommonActions();
  const slider = $("#confidence");
  const answer = $("#answerText");
  slider?.addEventListener("input", () => {
    $("#confidenceValue").textContent = slider.value;
    $("#confidenceLabel").textContent = `${slider.value}%`;
    scheduleDraftSave();
  });
  answer?.addEventListener("input", () => {
    updateAnswerTelemetry();
    scheduleDraftSave();
  });
  document.querySelectorAll('[data-action="hint"]').forEach((button) => button.addEventListener("click", () => useHint(Number(button.dataset.level))));
  document.querySelector('[data-action="submit-attempt"]')?.addEventListener("click", submitAttempt);
  document.querySelector('[data-action="cancel-session"]')?.addEventListener("click", cancelSession);

  setPageKeyHandler((event) => {
    if (event.isComposing) return;
    const modifier = event.ctrlKey || event.metaKey;
    if (modifier && event.key === "Enter") {
      event.preventDefault();
      document.querySelector('[data-action="submit-attempt"]')?.click();
      return;
    }
    if (modifier && event.key.toLowerCase() === "s") {
      event.preventDefault();
      clearTimeout(state.draftSaveTimer);
      saveDraft({ announce: true });
    }
  });
}

function scheduleDraftSave() {
  clearTimeout(state.draftSaveTimer);
  state.draftStatus = "saving";
  const status = $("#draftStatus");
  if (status) status.textContent = "等待保存";
  state.draftSaveTimer = setTimeout(() => saveDraft(), 650);
}

async function saveDraft({ announce = false } = {}) {
  if (!state.activeSession?.id) return;
  const answer = $("#answerText")?.value || "";
  const confidence = Number($("#confidence")?.value || 70);
  const status = $("#draftStatus");
  if (status) status.textContent = "保存中";
  try {
    await api(`/api/sessions/${state.activeSession.id}/draft`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: answer, confidence }),
    });
    state.activeSession.draft_text = answer;
    state.activeSession.draft_confidence = confidence;
    state.draftStatus = "saved";
    if (status) status.textContent = "草稿已保存";
    if (announce) toast("草稿已保存到本机");
  } catch (_) {
    state.draftStatus = "error";
    if (status) status.textContent = "自动保存失败，提交时仍会保存";
    if (announce) toast("草稿保存失败，请稍后重试", true);
  }
}

async function cancelSession() {
  if (!state.activeSession?.id) return;
  const confirmed = window.confirm("结束本轮后，未提交的草稿将保留在事件记录之外，但不会计入掌握证据。确定继续吗？");
  if (!confirmed) return;
  try {
    await api(`/api/sessions/${state.activeSession.id}/cancel`, { method: "POST" });
    clearTimeout(state.draftSaveTimer);
    state.activeSession = null;
    state.feedback = null;
    state.startedAtMs = null;
    await loadCore({ silent: true });
    setView("today");
    toast("本轮会话已结束，未生成掌握证据");
  } catch (error) {
    toast(error.message, true);
  }
}

async function useHint(level) {
  try {
    await api(`/api/sessions/${state.activeSession.id}/hint`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level }),
    });
    state.activeSession.hint_level = Math.max(Number(state.activeSession.hint_level || 0), level);
    renderStudy();
  } catch (error) {
    toast(error.message, true);
  }
}

async function submitAttempt() {
  const answer = $("#answerText")?.value.trim();
  if (!answer) return toast("请先写下当前能够独立恢复的内容", true);
  const button = document.querySelector('[data-action="submit-attempt"]');
  button.disabled = true;
  button.textContent = "正在对照来源…";
  try {
    const elapsed = Date.now() - (state.startedAtMs || Date.now());
    clearTimeout(state.draftSaveTimer);
    const result = await api(`/api/sessions/${state.activeSession.id}/attempts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        answer_text: answer,
        confidence: Number($("#confidence")?.value || 70),
        elapsed_ms: elapsed,
      }),
    });
    state.feedback = result;
    state.activeSession = null;
    stopTimer();
    renderStudy();
    await loadCore({ silent: true });
    state.view = "study";
    state.feedback = result;
    renderStudy();
  } catch (error) {
    button.disabled = false;
    button.textContent = "提交并对照来源";
    toast(error.message, true);
  }
}

function startTimer() {
  stopTimer();
  const update = () => {
    const timer = $("#timer");
    if (timer) timer.textContent = formatDuration(Date.now() - (state.startedAtMs || Date.now()));
  };
  update();
  state.timerHandle = setInterval(update, 1000);
}

function stopTimer() {
  if (state.timerHandle) clearInterval(state.timerHandle);
  state.timerHandle = null;
}

function portableImportReasonLabel(reason) {
  return ({
    duplicate_event_in_bundle: "同一文件里存在重复事件",
    invalid_event_time: "设备时间异常",
    item_missing: "卡片已不存在",
    item_inactive: "卡片或知识单元已停用",
    item_version_drift: "卡片内容已更新",
    history_advanced: "桌面端学习历史已经前进",
    event_predates_pack: "事件时间明显早于这个 StudyPack",
    base_attempt_missing: "导出时的基线作答已无法确认",
    event_predates_base: "事件时间明显早于导出时的学习基线",
    event_predates_item: "事件时间早于卡片创建时间",
    flashcard_requires_reveal_and_rating: "闪卡记录缺少揭示或自评",
    cloze_response_required: "挖空记录缺少实际答案",
  })[reason] || reason || "未知冲突";
}

async function downloadStudyPack(mode, limit, button) {
  if (button) button.disabled = true;
  try {
    const response = await fetch(`/api/study-pack/export?mode=${encodeURIComponent(mode)}&limit=${Number(limit) || 50}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `导出失败（${response.status}）`);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `study-pack-${mode}.json`;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
    toast(mode === "due" ? "今日 StudyPack 已导出" : "全部卡片 StudyPack 已导出");
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

function bindSettingsActions() {
  document.querySelectorAll('[data-action="export-study-pack"]').forEach((button) => button.addEventListener("click", () => downloadStudyPack(button.dataset.mode || "due", button.dataset.limit || "50", button)));

  $("#profileForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    if (button) button.disabled = true;
    try {
      await api("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          exam_name: $("#examName").value.trim(),
          exam_date: $("#examDate").value || null,
          daily_minutes: Number($("#dailyMinutes").value),
        }),
      });
      await loadCore({ silent: true });
      toast("学习目标已保存到本地");
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (button) button.disabled = false;
    }
  });

  $("#uiPrefsForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    state.preferences = {
      theme: $("#themePreference").value,
      density: $("#densityPreference").value,
      motion: $("#motionPreference").value,
      fontScale: $("#fontScalePreference").value,
    };
    saveUiPreferences();
    renderSettings();
    toast("界面偏好已应用并保存在本机");
  });

  $("#studyEventsInput")?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text());
      const result = await api("/api/study-events/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.portableImportResult = result;
      await loadCore({ silent: true });
      const summary = result.summary || {};
      toast(`StudyEvents 已处理：导入 ${summary.imported || 0}，重复 ${summary.duplicates || 0}，冲突 ${summary.conflicts || 0}`);
    } catch (error) {
      toast(`StudyEvents 导入失败：${error.message}`, true);
    } finally {
      event.target.value = "";
    }
  });
}

function openShortcutsDialog() {
  const dialog = $("#shortcutsDialog");
  if (!dialog) return;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function closeShortcutsDialog() {
  const dialog = $("#shortcutsDialog");
  if (dialog?.open && typeof dialog.close === "function") dialog.close();
  else dialog?.removeAttribute("open");
}

function toggleTheme() {
  const current = resolvedTheme();
  state.preferences.theme = current === "dark" ? "light" : "dark";
  saveUiPreferences();
  toast(state.preferences.theme === "dark" ? "已切换到深色主题" : "已切换到浅色主题");
}

function bindGlobalShellActions() {
  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#refreshButton")?.addEventListener("click", () => loadCore());
  $("#themeToggle")?.addEventListener("click", toggleTheme);
  $("#shortcutsButton")?.addEventListener("click", openShortcutsDialog);
  $("#retrievalDialogForm")?.addEventListener("submit", submitRetrievalDialog);
  $("#unitDialogForm")?.addEventListener("submit", (event) => { event.preventDefault(); saveUnitDialog(); });
  $("#unitDialogApprove")?.addEventListener("click", () => saveUnitDialog({ approve: true }));
  $("#unitDialogSplit")?.addEventListener("click", splitUnitDialog);
  document.querySelectorAll('[data-action="close-unit-dialog"]').forEach((button) => button.addEventListener("click", closeUnitDialog));
  document.querySelectorAll('[data-action="close-dialog"]').forEach((button) => button.addEventListener("click", closeRetrievalDialog));
  document.querySelectorAll('[data-action="close-shortcuts"]').forEach((button) => button.addEventListener("click", closeShortcutsDialog));

  $("#unitDialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeUnitDialog();
  });
  $("#retrievalDialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeRetrievalDialog();
  });
  $("#shortcutsDialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeShortcutsDialog();
  });

  document.addEventListener("keydown", (event) => {
    if (event.isComposing || isEditableTarget(event.target)) return;
    if (event.key === "?") {
      event.preventDefault();
      openShortcutsDialog();
    }
  });

  window.matchMedia?.("(prefers-color-scheme: light)").addEventListener?.("change", () => {
    if (state.preferences.theme === "system") applyUiPreferences();
  });
}

applyUiPreferences();
// 深链接：刷新/直接访问 #/xxx 时恢复对应视图（setView 会同步 banner 与导航高亮；
// 数据由随后的 loadCore 加载后再次渲染）
const initialHash = location.hash.match(/^#\/([a-z]+)/);
if (initialHash && viewMeta[initialHash[1]] && initialHash[1] !== "today") setView(initialHash[1], { focus: false });
bindGlobalShellActions();
bindPdfViewerActions();
window.loadCore = loadCore;
loadCore();
