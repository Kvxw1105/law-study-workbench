(() => {
  const PACK_PROTOCOL = "study-pack/0.1";
  const EVENT_PROTOCOL = "study-events/0.1";
  const CLIENT_VERSION = "portable-reviewer/0.1";
  const SESSION_KEY = "study-protocol-session-v01";
  const state = { pack: null, items: [], index: 0, events: [], startedAt: 0, currentRevealed: false, currentResponse: "", savedSession: null };

  const $ = (selector) => document.querySelector(selector);
  const show = (selector, visible) => $(selector)?.classList.toggle("hidden", !visible);
  const uuid = () => globalThis.crypto?.randomUUID?.() || `evt-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const nowIso = () => new Date().toISOString();
  const normalize = (value) => String(value || "").normalize("NFKC").replace(/[\s，。；;：:、,.!?！？“”'"（）()\[\]{}]/g, "").toLowerCase();
  const storageGet = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
  const storageSet = (key, value) => { try { localStorage.setItem(key, value); return true; } catch { return false; } };
  const softHaptic = (pattern = 8) => { try { navigator.vibrate?.(pattern); } catch {} };

  function updateEventCount() {
    const target = $("#sessionEventCount");
    if (target) target.textContent = `${state.events.length} 条待同步`;
  }

  function canonicalJson(value) {
    if (value === null || typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }

  function sha256Fallback(bytes) {
    const K = [
      0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
    ];
    const H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
    const padded = new Uint8Array(paddedLength);
    padded.set(bytes);
    padded[bytes.length] = 0x80;
    const bitLength = bytes.length * 8;
    const high = Math.floor(bitLength / 0x100000000);
    const low = bitLength >>> 0;
    for (let i = 0; i < 4; i += 1) {
      padded[paddedLength - 8 + i] = (high >>> (24 - i * 8)) & 0xff;
      padded[paddedLength - 4 + i] = (low >>> (24 - i * 8)) & 0xff;
    }
    const rotr = (x, n) => (x >>> n) | (x << (32 - n));
    const w = new Uint32Array(64);
    for (let offset = 0; offset < paddedLength; offset += 64) {
      for (let i = 0; i < 16; i += 1) {
        const j = offset + i * 4;
        w[i] = ((padded[j] << 24) | (padded[j + 1] << 16) | (padded[j + 2] << 8) | padded[j + 3]) >>> 0;
      }
      for (let i = 16; i < 64; i += 1) {
        const s0 = (rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3)) >>> 0;
        const s1 = (rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10)) >>> 0;
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }
      let [a,b,c,d,e,f,g,h] = H;
      for (let i = 0; i < 64; i += 1) {
        const S1 = (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) >>> 0;
        const ch = ((e & f) ^ (~e & g)) >>> 0;
        const temp1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
        const S0 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) >>> 0;
        const maj = ((a & b) ^ (a & c) ^ (b & c)) >>> 0;
        const temp2 = (S0 + maj) >>> 0;
        h=g; g=f; f=e; e=(d + temp1) >>> 0; d=c; c=b; b=a; a=(temp1 + temp2) >>> 0;
      }
      H[0]=(H[0]+a)>>>0; H[1]=(H[1]+b)>>>0; H[2]=(H[2]+c)>>>0; H[3]=(H[3]+d)>>>0;
      H[4]=(H[4]+e)>>>0; H[5]=(H[5]+f)>>>0; H[6]=(H[6]+g)>>>0; H[7]=(H[7]+h)>>>0;
    }
    return H.map((value) => value.toString(16).padStart(8, "0")).join("");
  }

  async function sha256Hex(text) {
    const bytes = new TextEncoder().encode(text);
    if (globalThis.crypto?.subtle) {
      const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
      return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    }
    return sha256Fallback(bytes);
  }

  async function verifyPackIntegrity(pack) {
    if (!pack?.pack_hash || !/^[0-9a-f]{64}$/i.test(pack.pack_hash)) throw new Error("StudyPack 缺少有效的完整性校验值");
    const payload = { ...pack };
    delete payload.pack_hash;
    const actual = await sha256Hex(canonicalJson(payload));
    if (actual.toLowerCase() !== pack.pack_hash.toLowerCase()) throw new Error("StudyPack 完整性校验失败：文件可能已被修改或损坏");
  }

  function persistSession() {
    if (!state.pack) return;
    storageSet(SESSION_KEY, JSON.stringify({
      pack: state.pack,
      items: state.items,
      index: state.index,
      events: state.events,
    }));
  }

  async function discoverSavedSession() {
    const raw = storageGet(SESSION_KEY);
    if (!raw) return;
    try {
      const saved = JSON.parse(raw);
      validatePack(saved.pack);
      await verifyPackIntegrity(saved.pack);
      if (!Array.isArray(saved.items) || !Array.isArray(saved.events)) return;
      state.savedSession = saved;
      updateEventCount();
      $("#resumeButton").classList.remove("hidden");
      $("#resumeButton").textContent = saved.index >= saved.items.length
        ? `恢复上次记录（${saved.events.length} 条待导出）`
        : `继续上次复习（${Math.min(saved.index + 1, saved.items.length)} / ${saved.items.length}）`;
    } catch {}
  }

  function resumeSavedSession() {
    const saved = state.savedSession;
    if (!saved) return;
    state.pack = saved.pack;
    state.items = saved.items;
    state.events = saved.events;
    state.index = saved.index || 0;
    updateEventCount();
    show("#importPanel", false);
    if (state.index >= state.items.length) finish();
    else { show("#donePanel", false); show("#sessionPanel", true); renderCurrent(); }
  }

  function deviceId() {
    let value = storageGet("study-protocol-device-id");
    if (!value) {
      value = `portable-${uuid()}`;
      storageSet("study-protocol-device-id", value);
    }
    return value;
  }

  function validatePack(pack) {
    if (!pack || pack.protocol !== PACK_PROTOCOL || !Array.isArray(pack.items)) throw new Error("不是可识别的 StudyPack v0.1");
    for (const item of pack.items) {
      if (!item.id || !item.version || !item.content_hash || !["flashcard", "cloze"].includes(item.type)) throw new Error("StudyPack 中存在不完整的学习对象");
      if (!item.content?.prompt || !item.content?.answer) throw new Error("StudyPack 中存在缺少题面或答案的对象");
    }
  }

  async function loadPack(file) {
    const pack = JSON.parse(await file.text());
    validatePack(pack);
    await verifyPackIntegrity(pack);
    state.pack = pack;
    state.items = pack.items.map((item) => ({ ...item, localBaseAttemptId: item.review_base?.last_attempt_id || null }));
    state.events = [];
    state.index = 0;
    updateEventCount();
    storageSet("study-protocol-last-pack", JSON.stringify(pack));
    state.savedSession = null;
    persistSession();
    show("#importPanel", false);
    show("#donePanel", false);
    show("#sessionPanel", true);
    renderCurrent();
  }

  function renderCurrent() {
    if (state.index >= state.items.length) return finish();
    const item = state.items[state.index];
    state.startedAt = performance.now();
    state.currentRevealed = false;
    state.currentResponse = "";
    $("#typeBadge").textContent = item.type === "cloze" ? "挖空" : "闪卡";
    $("#unitTitle").textContent = item.unit_title || "";
    $("#progressText").textContent = `${state.index + 1} / ${state.items.length}`;
    $("#progressBar").style.width = `${state.items.length ? (state.index / state.items.length) * 100 : 0}%`;
    $("#sourceMeta").textContent = `${item.source?.document_name || "本地教材"} · 第 ${item.source?.page_start || 1}-${item.source?.page_end || item.source?.page_start || 1} 页`;
    $("#promptText").textContent = item.content.prompt;
    $("#answerText").textContent = item.content.answer;
    $("#sourceExcerpt").textContent = item.source?.excerpt || "";
    $("#provisionalNote").textContent = "";
    $("#provisionalNote").classList.remove("is-match", "is-mismatch");
    $("#clozeInput").value = "";
    show("#answerArea", false);
    show("#ratingButtons", false);
    show("#nextClozeButton", false);
    show("#clozeArea", item.type === "cloze");
    show("#clozeCheckButton", item.type === "cloze");
    show("#flashArea", item.type === "flashcard");
    const card = $(".practice-card");
    card?.classList.remove("card-enter");
    requestAnimationFrame(() => card?.classList.add("card-enter"));
    document.body.dataset.itemType = item.type;
    if (item.type === "cloze") setTimeout(() => $("#clozeInput")?.focus(), 20);
  }

  function recordEvent({ rating = null, responseText = "", revealedAnswer = true }) {
    const item = state.items[state.index];
    const eventId = uuid();
    const event = {
      event_id: eventId,
      event_type: "retrieval_attempt",
      item_id: item.id,
      item_version: item.version,
      content_hash: item.content_hash,
      base_last_attempt_id: item.localBaseAttemptId,
      occurred_at: nowIso(),
      response_text: responseText,
      rating,
      elapsed_ms: Math.max(0, Math.round(performance.now() - state.startedAt)),
      revealed_answer: Boolean(revealedAnswer),
    };
    state.events.push(event);
    item.localBaseAttemptId = eventId;
    updateEventCount();
  }

  function revealFlashcard() {
    state.currentRevealed = true;
    show("#answerArea", true);
    show("#ratingButtons", true);
    show("#flashArea", false);
    $("#provisionalNote").textContent = "闪卡采用你的自评作为学习证据；桌面端导入后重新计算复习计划。";
    softHaptic(6);
  }

  function checkCloze() {
    const response = $("#clozeInput").value.trim();
    if (!response) return alert("请先填写答案");
    state.currentResponse = response;
    state.currentRevealed = true;
    show("#answerArea", true);
    show("#nextClozeButton", true);
    $("#clozeCheckButton").disabled = true;
    $("#clozeInput").disabled = true;
    show("#clozeCheckButton", false);
    const item = state.items[state.index];
    const same = normalize(response) === normalize(item.content.answer);
    $("#provisionalNote").classList.toggle("is-match", same);
    $("#provisionalNote").classList.toggle("is-mismatch", !same);
    softHaptic(same ? 8 : [7, 40, 7]);
    $("#provisionalNote").textContent = same
      ? "离线字面核对：一致。最终分数仍由桌面端使用正式挖空规则重算。"
      : "离线字面核对：不完全一致。最终判断仍由桌面端使用正式挖空规则重算。";
  }

  function nextAfterCloze() {
    recordEvent({ responseText: state.currentResponse, revealedAnswer: true });
    state.index += 1;
    softHaptic(5);
    persistSession();
    $("#clozeCheckButton").disabled = false;
    $("#clozeInput").disabled = false;
    renderCurrent();
  }

  function rateFlashcard(rating) {
    if (!state.currentRevealed) return;
    recordEvent({ rating, revealedAnswer: true });
    state.index += 1;
    softHaptic(rating === "again" ? [7, 35, 7] : 6);
    persistSession();
    renderCurrent();
  }

  function eventBundle() {
    return {
      protocol: EVENT_PROTOCOL,
      bundle_id: uuid(),
      pack_id: state.pack?.pack_id || "unknown",
      pack_hash: state.pack?.pack_hash || "unknown",
      exported_at: nowIso(),
      device: { id: deviceId(), label: $("#deviceLabel")?.value.trim() || "手机复习器", client: CLIENT_VERSION },
      events: state.events,
    };
  }

  function downloadJson(payload, filename) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
  }

  function exportEvents() {
    if (!state.events.length) return alert("当前还没有学习记录可导出");
    downloadJson(eventBundle(), `study-events-${new Date().toISOString().replace(/[:.]/g, "-")}.json`);
  }

  function finish() {
    persistSession();
    show("#sessionPanel", false);
    show("#donePanel", true);
    updateEventCount();
    $("#doneText").textContent = `已记录 ${state.events.length} 次学习行为。导出后回到桌面工作台的“设置与数据”导入即可同步进度。`;
  }

  function leave() {
    if (state.events.length && !confirm("当前有尚未导出的学习记录。确定返回？记录已保存在本机浏览器，可稍后恢复或重复导出。")) return;
    show("#sessionPanel", false);
    show("#donePanel", false);
    show("#importPanel", true);
  }

  $(".file-button")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    $("#packInput")?.click();
  });

  $("#packInput").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try { await loadPack(file); } catch (error) { alert(error.message); }
    event.target.value = "";
  });
  $("#revealButton").addEventListener("click", revealFlashcard);
  $("#clozeCheckButton").addEventListener("click", checkCloze);
  $("#nextClozeButton").addEventListener("click", nextAfterCloze);
  $("#ratingButtons").addEventListener("click", (event) => {
    const button = event.target?.closest?.("button[data-rating]");
    const rating = button?.dataset?.rating;
    if (rating) rateFlashcard(rating);
  });
  $("#exportButton").addEventListener("click", exportEvents);
  $("#doneExportButton").addEventListener("click", exportEvents);
  $("#leaveButton").addEventListener("click", leave);
  $("#restartButton").addEventListener("click", () => { state.index = 0; state.events = []; updateEventCount(); state.items = state.pack.items.map((item) => ({ ...item, localBaseAttemptId: item.review_base?.last_attempt_id || null })); persistSession(); show("#donePanel", false); show("#sessionPanel", true); renderCurrent(); });
  $("#resumeButton").addEventListener("click", resumeSavedSession);
  discoverSavedSession();

  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) navigator.serviceWorker.register("./sw.js").catch(() => {});
})();
