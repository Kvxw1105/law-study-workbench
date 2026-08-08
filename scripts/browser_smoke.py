from __future__ import annotations

import os

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "app" / "static" / "index.html"
CSS = ROOT / "app" / "static" / "styles.css"
JS = ROOT / "app" / "static" / "app.js"
DASHBOARD_SCREENSHOT = ROOT / "artifacts" / "ui-retrieval-dashboard.png"
SCREENSHOT = ROOT / "artifacts" / "ui-retrieval-smoke.png"


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/styles.css">', "")
    html = html.replace('<script src="/app.js" defer></script>', "")

    mock_script = r"""
    (() => {
      const now = new Date().toISOString();
      const source = {
        id: 'source-1', original_name: '民法教材·演示版.pdf', file_size: 1823000,
        status: 'ready', page_count: 2, processed_pages: 2, progress: 100,
        unit_count: 1, quality: {low_text_pages: 0}, created_at: now
      };
      const unit = {
        id: 'unit-1', source_id: 'source-1', title: '善意取得的构成要件',
        body: '善意取得制度用于保护交易安全。受让人取得所有权，应当具备以下条件：处分人为无处分权人；受让人在受让该财产时为善意；以合理价格转让；依法应当登记的已经登记，不需要登记的已经交付。',
        page_start: 1, page_end: 1, objective_type: '精确复现型', status: 'approved', version: 1,
        mastery_status: '不稳定', last_score: 68, retrieval_count: 2, flashcard_count: 1, cloze_count: 1
      };
      const flash = {
        id: 'flash-1', knowledge_unit_id: 'unit-1', item_type: 'flashcard',
        prompt: '请闭卷复述「善意取得的构成要件」的核心规则、条件与例外。',
        unit_title: unit.title, original_name: source.original_name, page_start: 1, page_end: 1,
        mastery_status: '新卡', due_at: now, interval_minutes: 0, streak: 0, lapses: 0,
        last_score: 0, last_rating: 'new', last_attempt_id: null, attempt_count: 0, is_new: true
      };
      const cloze = {
        id: 'cloze-1', knowledge_unit_id: 'unit-1', item_type: 'cloze',
        prompt: '填空：受让人在受让该财产时为 ____。', cloze_text: '受让人在受让该财产时为 ____。',
        unit_title: unit.title, original_name: source.original_name, page_start: 1, page_end: 1,
        mastery_status: '新卡', due_at: now, interval_minutes: 0, streak: 0, lapses: 0,
        last_score: 0, last_rating: 'new', last_attempt_id: null, attempt_count: 0, is_new: true
      };
      const all = [
        {...flash, answer: '处分人为无处分权人；受让人在受让财产时为善意；以合理价格转让；完成登记或交付。', source_excerpt: unit.body, revealed: true},
        {...cloze, answer: '善意', source_excerpt: '受让人在受让该财产时为善意。', revealed: true}
      ];
      const hidden = [flash, cloze];
      let retrievalAttempts = 0;

      const jsonResponse = (value, status=200) => new Response(JSON.stringify(value), {status, headers: {'Content-Type':'application/json'}});
      window.fetch = async (url, options={}) => {
        const path = String(url);
        if (path === '/api/app-info') return jsonResponse({product:'法学语义学习工作台', version:'0.8.0', profile:{exam_name:'法学考研', exam_date:null, daily_minutes:90}, source_count:1, unit_count:1, retrieval_item_count:2, provider:{mode:'local', configured:true, sends_to_cloud:false}});
        if (path === '/api/today') return jsonResponse({active:null, due:[], suggested:[], attempts_today:0, retrieval_due:hidden, retrieval_attempts_today:retrievalAttempts});
        if (path === '/api/sources') return jsonResponse([source]);
        if (path === '/api/sessions/active') return jsonResponse(null);
        if (path === '/api/learning-model') return jsonResponse({mastery:[], recurring_errors:[], metrics:{attempts:0,average_score:0,average_confidence:0,average_elapsed_ms:0}, retrieval_metrics:{attempts:retrievalAttempts,average_score:70,again_count:0,successful_count:1}, latest_attempts:[],model_note:'学习证据画像只汇总真实作答、提示、卡片与复测记录；当前不声称具有个体能力预测模型。', repair_queue:[]});
        if (path === '/api/retrieval/summary') return jsonResponse({total:2,flashcards:1,clozes:1,due:2,new:2,attempts:retrievalAttempts,average_score:70,reviewed_today:retrievalAttempts});
        if (path === '/api/retrieval-items?due_only=true&limit=100') return jsonResponse(hidden);
        if (path === '/api/retrieval-items?include_answer=true&limit=100') return jsonResponse(all);
        if (path.startsWith('/api/retrieval-items?')) return jsonResponse(hidden);
        if (path === '/api/sources/source-1/units') return jsonResponse([unit]);
        if (path === '/api/retrieval-items/flash-1') return jsonResponse(flash);
        if (path === '/api/retrieval-items/cloze-1') return jsonResponse(cloze);
        if (path === '/api/retrieval-items/flash-1/reveal') return jsonResponse({id:'flash-1',answer:all[0].answer,source_excerpt:all[0].source_excerpt,page_start:1,page_end:1,unit_title:unit.title});
        if (path === '/api/retrieval-items/flash-1/attempts') {
          retrievalAttempts += 1;
          return jsonResponse({id:'ra-1',retrieval_item_id:'flash-1',knowledge_unit_id:'unit-1',item_type:'flashcard',score:85,rating:'good',correct:true,note:'能够独立恢复，进入正常间隔。',expected_answer:all[0].answer,source_excerpt:all[0].source_excerpt,page_start:1,page_end:1,review:{mastery_status:'不稳定',due_at:new Date(Date.now()+259200000).toISOString(),interval_minutes:4320,streak:1,lapses:0,reason:'按正常间隔复测，并保留来源回指。'},created_at:now});
        }
        if (path === '/api/retrieval-items/cloze-1/attempts') {
          retrievalAttempts += 1;
          return jsonResponse({id:'ra-2',retrieval_item_id:'cloze-1',knowledge_unit_id:'unit-1',item_type:'cloze',score:100,rating:'good',correct:true,note:'答案与标准填空一致。',expected_answer:'善意',source_excerpt:'受让人在受让该财产时为善意。',page_start:1,page_end:1,review:{mastery_status:'不稳定',due_at:new Date(Date.now()+259200000).toISOString(),interval_minutes:4320,streak:1,lapses:0,reason:'按正常间隔复测，并保留来源回指。'},created_at:now});
        }
        if (path === '/api/units/unit-1/retrieval-items/generate') return jsonResponse({knowledge_unit_id:'unit-1',created:0,reused:2,items:all});
        return jsonResponse({detail:`unmocked ${path}`}, 404);
      };
    })();
    """

    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"),
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.set_content(html, wait_until="domcontentloaded")
        page.add_style_tag(path=str(CSS))
        page.add_script_tag(content=mock_script)
        page.add_script_tag(path=str(JS))
        page.get_by_text("今日到期挖空与闪卡").wait_for(timeout=10_000)
        page.get_by_role("button", name="本地教材库").click()
        page.get_by_role("button", name="手动建卡").wait_for(timeout=10_000)
        page.get_by_role("button", name="挖空与闪卡").click()
        page.get_by_text("卡片管理", exact=True).wait_for(timeout=10_000)
        page.screenshot(path=str(DASHBOARD_SCREENSHOT), full_page=True)
        page.get_by_role("button", name="开始 2 张到期复习").click()
        page.get_by_role("button", name="显示答案").click()
        page.get_by_role("button", name="记得 约 3 天").click()
        page.get_by_text("闪卡自评证据", exact=True).wait_for(timeout=10_000)
        page.get_by_role("button", name="下一张").click()
        page.locator("#clozeResponse").fill("善意")
        page.get_by_role("button", name="提交填空").click()
        page.get_by_text("本地挖空核对", exact=True).wait_for(timeout=10_000)
        assert page.get_by_text("教材来源", exact=True).is_visible()
        page.screenshot(path=str(SCREENSHOT), full_page=True)
        browser.close()
    print(DASHBOARD_SCREENSHOT)
    print(SCREENSHOT)


if __name__ == "__main__":
    main()
