from __future__ import annotations

import os

from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "app" / "static" / "index.html"
CSS = ROOT / "app" / "static" / "styles.css"
JS = ROOT / "app" / "static" / "app.js"
ARTIFACTS = ROOT / "artifacts"


MOCK_SCRIPT = r"""
(() => {
  const now = new Date().toISOString();
  const source = {
    id: 'source-1', original_name: '民法教材·演示版.pdf', file_size: 1823000,
    status: 'ready', page_count: 2, processed_pages: 2, progress: 100,
    unit_count: 2, quality: {low_text_pages: 0}, created_at: now
  };
  const units = [
    {
      id: 'unit-1', source_id: 'source-1', title: '善意取得的构成要件',
      body: '善意取得制度用于保护交易安全。受让人取得所有权，应当具备以下条件：处分人为无处分权人；受让人在受让该财产时为善意；以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。',
      page_start: 1, page_end: 1, objective_type: '精确复现型', status: 'approved', version: 1,
      mastery_status: '不稳定', last_score: 68, retrieval_count: 2, flashcard_count: 1, cloze_count: 1
    },
    {
      id: 'unit-2', source_id: 'source-1', title: '遗失物善意取得的特别规则',
      body: '所有权人有权自知道或者应当知道受让人之日起二年内向受让人请求返还原物，但通过拍卖或者向具有经营资格的经营者购得的，应当支付受让人所付费用。',
      page_start: 2, page_end: 2, objective_type: '辨析型', status: 'draft', version: 1,
      mastery_status: null, last_score: null, retrieval_count: 0, flashcard_count: 0, cloze_count: 0
    }
  ];
  const methodPack = {
    id:'law_full_recall_v1', version:'0.3.0', name:'法学完整闭卷方法包',
    objective_type:'精确复现型', focus_profile:'precision_recall', focus_label:'精确复现',
    selection_reason:'知识单元被标记为精确复现型，优先检查规则条件、限定语和法律效果是否完整恢复。',
    runtime_status:'selected',
    generated_flags:{learning_target_provenance:'source_exact',source_exact:true,source_bounded:true,learning_target_bounded:true},
    training_dimensions:[
      {id:'rule_elements',label:'规则与要件',instruction:'恢复一般规则、启动条件，并标明条件之间的并列或选择关系。',emphasized:true},
      {id:'exceptions_boundaries',label:'例外与边界',instruction:'检查原文是否存在例外、限制、阻断条件或相邻制度边界。',emphasized:true},
      {id:'legal_effect',label:'法律效果',instruction:'明确规则触发后产生的权利、义务、效力、责任或程序后果。',emphasized:true},
      {id:'core_question',label:'核心设问',instruction:'先用一句话回答本单元要求解释、辨析或适用什么。',emphasized:false},
      {id:'terminology_expression',label:'术语与规范表达',instruction:'使用来源内术语和限定词，按规则、条件、结论组织答案。',emphasized:false}
    ]
  };
  const dimensionResults = methodPack.training_dimensions.map((item, index) => ({
    ...item, status:index === 0 ? 'partial' : index === 1 ? 'missing' : 'strong',
    score:index === 0 ? 64 : index === 1 ? 32 : 82,
    summary:index === 0 ? '规则与要件已有部分恢复，仍存在来源要点或限定语缺口。' : index === 1 ? '例外与边界在本次答案中的来源覆盖较弱，尚不能形成稳定证据。' : `${item.label}已覆盖来源中的主要表达，但仍需通过延迟复测确认稳定性。`,
    next_action:'对照来源锚点补写一次，再关闭原文重新回答。',
    source_refs:[{page_start:1,page_end:1,coverage:.64,text:units[0].body}],
    atom_refs:index === 0 ? ['LAW-14','LAW-15','LAW-19'] : ['QUA-03']
  }));
  const flash = {
    id: 'flash-1', knowledge_unit_id: 'unit-1', item_type: 'flashcard',
    prompt: '请闭卷复述「善意取得的构成要件」的核心规则、条件与例外。',
    unit_title: units[0].title, original_name: source.original_name, page_start: 1, page_end: 1,
    mastery_status: '新卡', due_at: now, interval_minutes: 0, streak: 0, lapses: 0,
    last_score: 0, last_rating: 'new', last_attempt_id: null, attempt_count: 0, is_new: true
  };
  const cloze = {
    id: 'cloze-1', knowledge_unit_id: 'unit-1', item_type: 'cloze',
    prompt: '填空：受让人在受让该财产时为 ____。', cloze_text: '受让人在受让该财产时为 ____。',
    unit_title: units[0].title, original_name: source.original_name, page_start: 1, page_end: 1,
    mastery_status: '新卡', due_at: now, interval_minutes: 0, streak: 0, lapses: 0,
    last_score: 0, last_rating: 'new', last_attempt_id: null, attempt_count: 0, is_new: true
  };
  const all = [
    {...flash, answer: '处分人为无处分权人；受让人在受让财产时为善意；以合理价格转让；完成登记或交付。', source_excerpt: units[0].body, revealed: true},
    {...cloze, answer: '善意', source_excerpt: '受让人在受让该财产时为善意。', revealed: true}
  ];
  const hidden = [flash, cloze];
  let retrievalAttempts = 0;
  let activeSession = null;
  let sessionDraft = '';
  let failAppInfoOnce = Boolean(window.__FAIL_APP_INFO_ONCE);

  const jsonResponse = (value, status=200) => new Response(JSON.stringify(value), {status, headers: {'Content-Type':'application/json'}});
  window.fetch = async (url, options={}) => {
    const path = String(url);
    if (path === '/api/app-info') {
      if (failAppInfoOnce) { failAppInfoOnce = false; return jsonResponse({detail:'模拟本地服务暂不可用'}, 503); }
      return jsonResponse({product:'法学语义学习工作台', version:'0.8.0', profile:{exam_name:'法学考研', exam_date:null, daily_minutes:90}, source_count:1, unit_count:2, retrieval_item_count:2, provider:{mode:'local', configured:true, sends_to_cloud:false}});
    }
    if (path === '/api/today') return jsonResponse({active:activeSession ? {...activeSession, ...units[0], original_name: source.original_name} : null, due:[{...units[0], original_name:source.original_name, due_at:now}], suggested:[{...units[1], original_name:source.original_name}], attempts_today:1, retrieval_due:hidden, retrieval_attempts_today:retrievalAttempts});
    if (path === '/api/sources') return jsonResponse([source]);
    if (path === '/api/sessions/active') return jsonResponse(activeSession ? {...activeSession, ...units[0], original_name: source.original_name} : null);
    if (path === '/api/learning-model') return jsonResponse({
      mastery:[{mastery_status:'不稳定',count:1},{mastery_status:'未接触',count:1}],
      recurring_errors:[{error_type:'条件遗漏',detail:'反复遗漏善意判断的时间节点',count:3}],
      metrics:{attempts:4,average_score:72,average_confidence:84,average_elapsed_ms:286000},
      retrieval_metrics:{attempts:retrievalAttempts,average_score:70,again_count:0,successful_count:1},
      latest_attempts:[{title:units[0].title,original_name:source.original_name,created_at:now,hint_level:0,score:68,confidence:85}],
      model_note:'学习证据画像只汇总真实作答、提示、卡片与复测记录；当前不声称具有个体能力预测模型。',
      repair_queue:[{id:'error-1',knowledge_unit_id:'unit-1',unit_title:units[0].title,error_type:'条件遗漏',detail:'遗漏善意判断时间点',status:'repairing',created_at:now,can_resolve:true,retest_attempt_id:'attempt-retest-1',retest_score:78}]
    });
    if (path === '/api/retrieval/summary') return jsonResponse({total:2,flashcards:1,clozes:1,due:2,new:2,attempts:retrievalAttempts,average_score:70,reviewed_today:retrievalAttempts});
    if (path === '/api/retrieval-items?due_only=true&limit=100') return jsonResponse(hidden);
    if (path === '/api/retrieval-items?include_answer=true&limit=100') return jsonResponse(all);
    if (path.startsWith('/api/retrieval-items?')) return jsonResponse(hidden);
    if (path === '/api/sources/source-1/units') return jsonResponse(units);
    if (path === '/api/units/unit-1/sessions') {
      activeSession = {id:'session-1', knowledge_unit_id:'unit-1', started_at:now, hint_level:0, draft_text:sessionDraft, draft_confidence:70, method_pack:methodPack};
      return jsonResponse({unit:units[0],session:activeSession,resumed:false});
    }
    if (path === '/api/units/unit-2/sessions') {
      activeSession = {id:'session-2', knowledge_unit_id:'unit-2', started_at:now, hint_level:0, draft_text:'', draft_confidence:70, method_pack:{...methodPack, objective_type:'辨析型', focus_profile:'distinction', focus_label:'辨析边界'}};
      return jsonResponse({unit:units[1],session:activeSession,resumed:false});
    }
    if (path === '/api/sessions/session-1/draft' || path === '/api/sessions/session-2/draft') {
      sessionDraft = JSON.parse(options.body || '{}').text || '';
      return jsonResponse({saved:true});
    }
    if (path === '/api/sessions/session-1/hint' || path === '/api/sessions/session-2/hint') {
      const level = JSON.parse(options.body || '{}').level || 1;
      activeSession = {...activeSession, hint_level:level};
      return jsonResponse({hint_level:level});
    }
    if (path === '/api/sessions/session-1/attempts' || path === '/api/sessions/session-2/attempts') {
      activeSession = null;
      return jsonResponse({
        attempt_id:'attempt-1',knowledge_unit_id:'unit-1',score:72,evidence_weight:1,provider:'local-evidence',errors_created:2,
        method_pack:{...methodPack,runtime_status:'completed'},dimension_results:dimensionResults,
        review:{mastery_status:'不稳定',due_at:new Date(Date.now()+86400000).toISOString(),reason:'关键条件仍有遗漏，明日进行一次无提示复测。'},
        feedback:{matched_points:['识别了交易安全与无权处分结构','写出了善意和合理价格'],missing_points:['遗漏登记或交付条件'],incorrect_points:[],expression_issues:['结论缺少明确法律效果'],next_action:'补齐登记或交付条件后立即重新闭卷。',warning:null,evidence:[{page_start:1,page_end:1,coverage:.72,text:units[0].body}],method_pack:{...methodPack,runtime_status:'completed'},dimension_results:dimensionResults}
      });
    }
    if (path === '/api/retrieval-items/flash-1') return jsonResponse(flash);
    if (path === '/api/retrieval-items/cloze-1') return jsonResponse(cloze);
    if (path === '/api/retrieval-items/flash-1/reveal') return jsonResponse({id:'flash-1',answer:all[0].answer,source_excerpt:all[0].source_excerpt,page_start:1,page_end:1,unit_title:units[0].title});
    if (path === '/api/retrieval-items/flash-1/attempts') {
      retrievalAttempts += 1;
      return jsonResponse({id:'ra-1',retrieval_item_id:'flash-1',knowledge_unit_id:'unit-1',item_type:'flashcard',score:85,rating:'good',correct:true,note:'能够独立恢复，进入正常间隔。',expected_answer:all[0].answer,source_excerpt:all[0].source_excerpt,page_start:1,page_end:1,review:{mastery_status:'不稳定',due_at:new Date(Date.now()+259200000).toISOString(),interval_minutes:4320,streak:1,lapses:0,reason:'按正常间隔复测，并保留来源回指。'},created_at:now});
    }
    if (path === '/api/retrieval-items/cloze-1/attempts') {
      retrievalAttempts += 1;
      return jsonResponse({id:'ra-2',retrieval_item_id:'cloze-1',knowledge_unit_id:'unit-1',item_type:'cloze',score:100,rating:'good',correct:true,note:'答案与标准填空一致。',expected_answer:'善意',source_excerpt:'受让人在受让该财产时为善意。',page_start:1,page_end:1,review:{mastery_status:'不稳定',due_at:new Date(Date.now()+259200000).toISOString(),interval_minutes:4320,streak:1,lapses:0,reason:'按正常间隔复测，并保留来源回指。'},created_at:now});
    }
    if (path === '/api/units/unit-1/retrieval-items/generate') return jsonResponse({knowledge_unit_id:'unit-1',created:0,reused:2,items:all});
    if (path === '/api/profile') return jsonResponse({saved:true});
    return jsonResponse({detail:`unmocked ${path}`}, 404);
  };
})();
"""


def mount(page: Page, *, fail_once: bool = False, wait_ready: bool = True) -> None:
    html = INDEX.read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/styles.css">', "")
    html = html.replace('<script src="/app.js" defer></script>', "")
    page.set_content(html, wait_until="domcontentloaded")
    page.add_style_tag(path=str(CSS))
    if fail_once:
        page.add_script_tag(content="window.__FAIL_APP_INFO_ONCE = true;")
    page.add_script_tag(content=MOCK_SCRIPT)
    page.add_script_tag(path=str(JS))
    if wait_ready:
        page.get_by_role("heading", name="今日学习").wait_for(timeout=10_000)
    page.wait_for_timeout(250)


def assert_no_horizontal_overflow(page: Page) -> None:
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1, f"horizontal overflow: {overflow}px"


def track_browser_errors(page: Page, label: str, errors: list[str]) -> None:
    page.on("pageerror", lambda error: errors.append(f"{label} pageerror: {error}"))
    page.on("console", lambda message: errors.append(f"{label} console: {message.text}") if message.type == "error" else None)


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"), args=["--no-sandbox"])
        browser_errors: list[str] = []

        desktop = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        track_browser_errors(desktop, "desktop", browser_errors)
        mount(desktop)
        desktop.keyboard.press("Tab")
        assert desktop.locator(".skip-link").evaluate("el => el.matches(':focus-visible')")
        desktop.evaluate("document.activeElement?.blur()")
        assert_no_horizontal_overflow(desktop)
        desktop.screenshot(path=str(ARTIFACTS / "ui-round2-today-dark.png"), full_page=True)

        desktop.get_by_role("button", name="本地教材库").click()
        desktop.get_by_role("heading", name="添加本地教材").wait_for()
        assert_no_horizontal_overflow(desktop)
        desktop.screenshot(path=str(ARTIFACTS / "ui-round2-library-dark.png"), full_page=True)

        desktop.get_by_role("button", name="审核 / 编辑").first.click()
        desktop.get_by_role("heading", name="审核知识单元").wait_for(timeout=8_000)
        desktop.locator("#unitDialogText").wait_for(timeout=8_000)
        assert desktop.get_by_role("button", name="按光标拆分").is_visible()
        desktop.screenshot(path=str(ARTIFACTS / "ui-v060-unit-review.png"), full_page=True)
        desktop.get_by_role("button", name="取消").click()

        desktop.get_by_role("button", name="学习证据").click()
        desktop.get_by_role("heading", name="错因修复队列").wait_for(timeout=8_000)
        desktop.get_by_role("button", name="确认已修复").wait_for(timeout=8_000)
        desktop.screenshot(path=str(ARTIFACTS / "ui-v060-error-repair.png"), full_page=True)

        desktop.get_by_role("button", name="本地教材库").click()
        desktop.get_by_role("button", name="手动建卡").first.click()
        desktop.get_by_role("heading", name="建立提取卡片").wait_for()
        desktop.screenshot(path=str(ARTIFACTS / "ui-round2-card-dialog.png"), full_page=True)
        desktop.get_by_role("button", name="关闭").click()

        desktop.get_by_role("button", name="再次完整复测").first.click()
        desktop.get_by_role("heading", name="闭卷回答").wait_for()
        desktop.get_by_text("法学完整闭卷方法包", exact=True).wait_for()
        desktop.get_by_text("规则与要件", exact=True).wait_for()
        desktop.locator("#answerText").fill("善意取得要求处分人无权处分，受让人善意并支付合理价格。")
        desktop.keyboard.press("Control+s")
        desktop.get_by_text("草稿已保存到本机").wait_for()
        desktop.get_by_role("button", name="一级提示").click()
        desktop.get_by_text("一级提示 · 原文节选").wait_for()
        assert_no_horizontal_overflow(desktop)
        desktop.screenshot(path=str(ARTIFACTS / "ui-round2-study-dark.png"), full_page=True)

        desktop.get_by_role("button", name="切换到浅色主题").click()
        desktop.wait_for_timeout(150)
        assert desktop.locator("html").get_attribute("data-theme") == "light"
        desktop.screenshot(path=str(ARTIFACTS / "ui-round2-study-light.png"), full_page=True)

        desktop.keyboard.press("Control+Enter")
        desktop.get_by_text("教材来源", exact=True).wait_for()
        desktop.get_by_role("heading", name="五维学习目标恢复检查").wait_for()
        desktop.get_by_text("v0.3.0 · 学习目标恢复信号", exact=True).wait_for()
        desktop.screenshot(path=str(ARTIFACTS / "ui-round2-feedback-light.png"), full_page=True)

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        track_browser_errors(mobile, "mobile", browser_errors)
        mount(mobile)
        mobile.get_by_role("button", name="挖空与闪卡").click(timeout=8000)
        mobile.get_by_role("button", name="开始 2 张到期复习").click(timeout=8000)
        mobile.get_by_role("button", name="显示答案").click(timeout=8000)
        mobile.get_by_role("button", name="记得 约 3 天").wait_for(timeout=8000)
        mobile.keyboard.press("3")
        mobile.get_by_text("闪卡自评证据", exact=True).wait_for(timeout=8000)
        assert_no_horizontal_overflow(mobile)
        mobile.screenshot(path=str(ARTIFACTS / "ui-round2-mobile-retrieval.png"), full_page=True)

        mobile_method = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        track_browser_errors(mobile_method, "mobile-method", browser_errors)
        mount(mobile_method)
        mobile_method.get_by_role("button", name="本地教材库").click(timeout=8_000)
        mobile_method.get_by_role("button", name="再次完整复测").first.click(timeout=8_000)
        mobile_method.get_by_text("法学完整闭卷方法包", exact=True).wait_for(timeout=8_000)
        mobile_method.get_by_text("规则与要件", exact=True).wait_for(timeout=8_000)
        assert_no_horizontal_overflow(mobile_method)
        mobile_method.locator("#answerText").fill("善意取得要求处分人无处分权，受让人善意并支付合理价格。")
        mobile_method.keyboard.press("Control+Enter")
        mobile_method.get_by_role("heading", name="五维学习目标恢复检查").wait_for(timeout=8_000)
        mobile_method.get_by_text("v0.3.0 · 学习目标恢复信号", exact=True).wait_for(timeout=8_000)
        assert_no_horizontal_overflow(mobile_method)
        mobile_method.screenshot(path=str(ARTIFACTS / "ui-m3a-mobile-feedback.png"), full_page=True)

        narrow = browser.new_page(viewport={"width": 320, "height": 568}, device_scale_factor=1)
        track_browser_errors(narrow, "narrow", browser_errors)
        mount(narrow)
        assert_no_horizontal_overflow(narrow)
        narrow.get_by_role("button", name="设置与数据").click()
        narrow.get_by_role("heading", name="界面与阅读").wait_for(timeout=8_000)
        assert_no_horizontal_overflow(narrow)

        tablet = browser.new_page(viewport={"width": 1024, "height": 768}, device_scale_factor=1)
        track_browser_errors(tablet, "tablet", browser_errors)
        mount(tablet)
        tablet.get_by_role("button", name="本地教材库").click()
        tablet.get_by_role("heading", name="添加本地教材").wait_for(timeout=8_000)
        assert_no_horizontal_overflow(tablet)

        recovery = browser.new_page(viewport={"width": 1024, "height": 768}, device_scale_factor=1)
        track_browser_errors(recovery, "recovery", browser_errors)
        mount(recovery, fail_once=True, wait_ready=False)
        recovery.get_by_role("heading", name="无法读取本地服务").wait_for(timeout=8_000)
        recovery.get_by_role("button", name="重新连接").click()
        recovery.get_by_role("heading", name="今日学习").wait_for(timeout=8_000)
        assert_no_horizontal_overflow(recovery)
        assert not browser_errors, "\n".join(browser_errors)

        browser.close()

    for name in [
        "ui-round2-today-dark.png",
        "ui-round2-library-dark.png",
        "ui-v060-unit-review.png",
        "ui-v060-error-repair.png",
        "ui-round2-card-dialog.png",
        "ui-round2-study-dark.png",
        "ui-round2-study-light.png",
        "ui-round2-feedback-light.png",
        "ui-round2-mobile-retrieval.png",
        "ui-m3a-mobile-feedback.png",
    ]:
        print(ARTIFACTS / name)


if __name__ == "__main__":
    main()
