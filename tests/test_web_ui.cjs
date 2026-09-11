const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const vm = require('node:vm');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const output = path.join(root, 'test_results', 'web-ui');
fs.mkdirSync(output, { recursive: true });
const web = path.join(root, 'web');
const errors = [];
let state = {
  KOMGA_BASE_URL: 'http://fixture.invalid', KOMGA_EMAIL: 'fixture', KOMGA_EMAIL_PASSWORD: 'fixture',
  KOMGA_SERVERS: [{ id: 'fixture', name: '家庭书库', base_url: 'http://fixture.invalid', auth_mode: 'password', email: 'fixture', password: 'fixture' }],
  KOMGA_LIBRARY_LIST: Array.from({ length: 26 }, (_, index) => ({
    SERVER_ID: 'fixture', LIBRARY: `lib-${index}`, IS_NOVEL_ONLY: index % 2 === 1,
    REQUIRED_FIELDS: [], OVERWRITE_FIELDS: ['title', 'summary']
  }))
};
const tasks = [
  { id: 'task-a', name: '每日元数据补全', functions: ['metadata_completion'], fields: ['title', 'summary'], card_ids: ['lib-0'], cron: '0 6 * * *', enabled: true },
  { id: 'task-b', name: '封面拼贴刷新', functions: ['card_collage_refresh'], fields: [], card_ids: ['lib-1'], cron: '30 6 * * *', enabled: false }
];
const scrapeRecords = [{
  id: 'book:lib-0:1', item_type: '漫画', item_title: '万古之王', source_title: '《万古之王》[若鸿文化]', matched_title: '万古之王',
  library_id: 'lib-0', library_name: '国漫', server_id: 'fixture', server_name: '家庭书库', source_path: '/data/comics/万古之王/第一卷.cbz',
  metadata_fields: ['title', 'summary', 'numberSort', 'publisher', 'authors', 'tags', 'genres'], match_source: '书名号内容', recorded_at: '2026-09-10T13:14:13', volume_count: 1,
  volumes: [{ id: 2, item_title: '第一卷：用于验证省略显示与完整信息悬浮文本框的长标题', source_path: '/data/comics/万古之王/第一卷.cbz', metadata_fields: ['numberSort'], match_source: '卷号排序', recorded_at: '2026-09-10T13:14:13' }]
}];
const runtimeLogs = [{ id: 1, level: 'info', action: '计划任务：自动执行', detail: '触发方式：Cron 定时触发\n任务：每日元数据补全\n应用媒体库：家庭书库 / 国漫\n元数据：标题、简介\n包含锁定：关闭；完成锁定：开启\n' + '用于测试很长操作详情的自动换行，不应省略或撑出页面。'.repeat(8), source: 'web', recorded_at: '2026-09-10T06:00:00' }];
const libraries = state.KOMGA_LIBRARY_LIST.map((item, index) => ({
  id: item.LIBRARY, name: ['国漫', '轻小说', '日漫', '无封面书库'][index] || `媒体库 ${index + 1}`
}));
let covers = [fs.readFileSync(path.join(web, 'logo-icon.png'))];
const apiCalls = [];
const refreshRequests = [];
let executionStatus = { running: false, tasks: {} };
let sessionAuthenticated = true;

async function main() {
  if (process.env.BK_REFERENCE_IMAGE) {
    const sharp = require('sharp');
    const untilted = await sharp(process.env.BK_REFERENCE_IMAGE).rotate(-19).png().toBuffer();
    await sharp(untilted).toFile(path.join(output, 'reference-untilted.png'));
    // Temporary visual fixtures only; no covers are added to the application.
    covers = await Promise.all([
      [484, 240, 150, 240], [684, 240, 150, 240],
      [718, 122, 110, 72], [548, 157, 65, 40]
    ].map(([left, top, width, height]) => sharp(untilted).extract({ left, top, width, height }).png().toBuffer()));
  }
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname.startsWith('/api/')) {
      apiCalls.push([req.method, url.pathname, url.search]);
      res.setHeader('Content-Type', 'application/json');
      let body = {};
      if (req.method === 'POST') {
        let raw = '';
        for await (const chunk of req) raw += chunk;
        body = JSON.parse(raw || '{}');
      }
      let result = {};
      if (url.pathname === '/api/auth/session') result = { authenticated: sessionAuthenticated, username: 'fixture' };
      else if (url.pathname === '/api/auth/login') { sessionAuthenticated = true; result = {ok:true}; }
      else if (url.pathname === '/api/auth/logout') { sessionAuthenticated = false; result = {ok:true}; }
      else if (url.pathname === '/api/login-background') result = {items:state.KOMGA_LIBRARY_LIST.some(card=>card.LOGIN_BACKGROUND) ? Array.from({length:12}, (_,i)=>({url:`/test-cover/${i}`})) : []};
      else if (url.pathname === '/api/status') result = executionStatus;
      else if (url.pathname === '/api/proxy/test') result = {ok:true,message:'代理连接成功'};
      else if (url.pathname === '/api/proxy') { state.OUTBOUND_PROXY_URL = body.url; result = {url:body.url}; }
      else if (url.pathname === '/api/tasks/run') {
        executionStatus = { running: true, tasks: {...executionStatus.tasks,[body.id]:{state:'running',stopping:false}} };
        result = { started: true };
      }
      else if (url.pathname === '/api/tasks/stop') {
        assert(executionStatus.tasks[body.id]);
        delete executionStatus.tasks[body.id];
        executionStatus.running = Object.keys(executionStatus.tasks).length > 0;
        result = { stopping: true };
      }
      else if (url.pathname === '/api/bangumi/search') result = { items: [{ id: 123, name_cn: '测试漫画' }] };
      else if (url.pathname === '/api/bangumi/subject') result = { item: { id: 123, name_cn: '测试漫画', summary: '预览测试简介' } };
      else if (url.pathname === '/api/config') {
        if (req.method === 'POST') state = body;
        result = state;
      } else if (url.pathname === '/api/komga/libraries') result = { items: libraries };
      else if (url.pathname === '/api/komga/previews') result = { items: url.searchParams.get('library_id') === 'lib-3' ? [] : Array.from({ length: 8 }, (_, index) => ({ id: index, url: `/test-cover/${index}` })) };
      else if (url.pathname === '/api/tasks') {
        if (req.method === 'POST') {
          const existing = tasks.findIndex(task => task.id === body.id);
          if (existing >= 0) tasks.splice(existing, 1);
          tasks.push({ ...body, id: body.id || 'saved-task' });
        }
        result = { items: tasks };
      }
      else if (url.pathname === '/api/refresh') { refreshRequests.push(body); result = { started: true }; }
      else if (url.pathname === '/api/scrape-records') result = { items: scrapeRecords, total: 125 };
      else if (url.pathname === '/api/scrape-records/stats') result = { total: 1, today: 1, comic: 1, novel: 0 };
      else if (url.pathname === '/api/runtime-logs') result = { items: runtimeLogs, total: 230 };
      else if (url.pathname === '/api/runtime-logs/stats') result = { total: 230, today: 1, success: 12, failed: 3 };
      res.end(JSON.stringify(result));
      return;
    }
    if (url.pathname.startsWith('/test-cover/')) {
      res.setHeader('Content-Type', 'image/png');
      res.end(covers[Number(url.pathname.split('/').pop()) % covers.length]);
      return;
    }
    const relative = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
    const target = path.resolve(web, relative);
    if (!target.startsWith(web + path.sep) || !fs.existsSync(target)) {
      res.writeHead(404).end();
      return;
    }
    const type = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.png': 'image/png', '.ico': 'image/x-icon', '.svg': 'image/svg+xml' }[path.extname(target)] || 'text/plain';
    res.setHeader('Content-Type', type);
    res.end(fs.readFileSync(target));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: process.env.BK_BROWSER_CHANNEL || 'msedge' });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    page.on('pageerror', error => errors.push(error.message));
    const url = `http://127.0.0.1:${server.address().port}/`;
    await page.goto(url);
    await page.locator('.library-card').first().waitFor();
    assert.equal(await page.locator('.hero-head h1').innerText(), '媒体卡片');
    assert.equal(await page.locator('.nav-item').first().innerText(), '媒体卡片');
    assert.equal(await page.getByText('服务在线', { exact: true }).count(), 0);
    assert.match(await page.locator('.sidebar-logout').innerText(), /退出登录/);
    const navIcon = await page.locator('.nav-icon').first().boundingBox();
    const logoutIcon = await page.locator('.sidebar-logout svg').boundingBox();
    assert(Math.abs(navIcon.x-logoutIcon.x) < 1, 'logout icon aligns with navigation icons');
    const mediaAddRect = await page.locator('.hero-actions button').boundingBox();
    await page.waitForFunction(() => [...document.querySelectorAll('.library-card:first-child img')].every(img => img.complete && img.naturalWidth));
    await page.screenshot({ path: path.join(output, 'cards-desktop.png') });
    const cardLayout = await page.locator('.library-card').first().evaluate(card => {
      const rect = card.getBoundingClientRect(), collage = card.querySelector('.cover-collage');
      return { width: rect.width, height: rect.height, transform: getComputedStyle(collage).transform, images: [...collage.querySelectorAll('img')].map(img => getComputedStyle(img).transform) };
    });
    assert(cardLayout.images.every(value => value === 'none'));
    assert.notEqual(cardLayout.transform, 'none');
    assert.equal(await page.locator('.library-card').nth(3).locator('img').count(), 0);
    await page.locator('.library-card').first().click();
    assert.equal(await page.locator('.card-setting-grid legend').allTextContents().then(values => values.join('|')), 'Komga 服务|媒体库|媒体类型|功能选项');
    await page.getByRole('button', { name: 'Komga 服务', exact: true }).click();
    assert.equal(await page.getByRole('dialog', {name:'Komga 服务候选项'}).getByRole('radio').count(), 1);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.card-settings-modal').count(), 1);
    await page.screenshot({ path: path.join(output, 'card-editor-desktop.png') });
    await page.getByRole('button', { name: '功能选项', exact: true }).click();
    const features = page.getByRole('dialog', { name: '功能选项候选项' });
    assert.equal(await features.getByLabel('简介翻译').count(), 0);
    assert.equal(await features.getByLabel('仅匹配小说').count(), 0);
    assert.equal(await features.getByLabel('刮削匹配').isChecked(), true);
    assert.equal(await features.getByLabel('登录背景', {exact:false}).isChecked(), false);
    await features.getByLabel('AI 识别').check();
    await page.screenshot({ path: path.join(output, 'feature-picker-desktop.png') });
    assert.equal(await features.count(), 1);
    assert.equal(await page.locator('#card-features .tag-picker-chip').count(), 2);
    await features.getByLabel('刮削匹配').uncheck();
    await features.getByLabel('登录背景', {exact:false}).check();
    await features.getByLabel('AI 识别').press('Escape');
    await page.getByRole('button', { name: '媒体类型', exact: true }).click();
    const mediaTypes = page.getByRole('dialog', { name: '媒体类型候选项' });
    assert.equal(await mediaTypes.getByRole('radio').count(), 3);
    await mediaTypes.getByLabel('混合匹配', { exact: true }).click();
    assert.equal(await mediaTypes.count(), 0);
    await page.getByRole('heading', { name: '配置媒体库' }).click();
    assert.equal(await page.locator('.tag-picker-panel').count(), 0);
    await page.getByRole('button', { name: '缺失元数据', exact: true }).click();
    await page.getByRole('dialog', { name: '缺失元数据候选项' }).getByLabel('简介', { exact: true }).check();
    await page.getByRole('dialog', { name: '缺失元数据候选项' }).getByLabel('简介', { exact: true }).press('Escape');
    await page.getByRole('button', { name: '元数据覆盖', exact: true }).click();
    assert.equal(await page.locator('.tag-picker-panel').count(), 1);
    const overwrite = page.getByRole('dialog', { name: '元数据覆盖候选项' });
    await overwrite.getByLabel('全选', {exact:true}).check();
    assert.equal(await page.locator('#card-overwrite .tag-picker-chip').count(), 18);
    await overwrite.getByLabel('全选', {exact:true}).uncheck();
    assert.equal(await page.locator('#card-overwrite .tag-picker-chip').count(), 0);
    await overwrite.getByLabel('标题', {exact:true}).check();
    await overwrite.getByLabel('简介', {exact:true}).check();
    await overwrite.getByLabel('封面', { exact: true }).check();
    await page.screenshot({ path: path.join(output, 'card-picker-desktop.png') });
    await overwrite.getByLabel('封面', { exact: true }).press('Escape');
    assert.equal(await page.locator('.tag-picker-panel').count(), 0);
    assert.equal(await page.getByRole('button', { name: '元数据覆盖', exact: true }).evaluate(el => document.activeElement === el), true);
    await page.getByRole('button', { name: '确定', exact: true }).click();
    await page.locator('.card-settings-modal').waitFor({ state: 'hidden' });
    assert.equal(state.KOMGA_LIBRARY_LIST[0].TRANSLATE_SUMMARY_TO_ZH, false);
    assert.equal(state.KOMGA_LIBRARY_LIST[0].MEDIA_TYPE, 'mixed');
    assert.equal(state.KOMGA_LIBRARY_LIST[0].SCRAPE_ENABLED, false);
    assert.equal(state.KOMGA_LIBRARY_LIST[0].LOGIN_BACKGROUND, true);
    assert.equal(state.KOMGA_LIBRARY_LIST[0].AI_RECOGNITION, true);
    assert(state.KOMGA_LIBRARY_LIST[0].REQUIRED_FIELDS.includes('summary'));
    assert(state.KOMGA_LIBRARY_LIST[0].OVERWRITE_FIELDS.includes('thumbnail'));
    await page.locator('.library-card').first().click({ button: 'right' });
    assert.equal(await page.locator('.context-menu button').count(), 3);
    assert.equal(await page.locator('.context-menu button svg').count(), 3);
    assert.equal(await page.getByRole('button', { name: '刷新封面拼贴' }).count(), 0);
    await page.screenshot({ path: path.join(output, 'media-card-context-menu.png') });
    await page.getByRole('button', { name: '增量刮削', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.context-menu'));
    assert.deepEqual(refreshRequests.at(-1), { full: false, target_id: 'fixture::lib-0' });
    await page.locator('.library-card').first().click({ button: 'right' });
    await page.getByRole('button', { name: '全量刮削', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.context-menu'));
    assert.deepEqual(refreshRequests.at(-1), { full: true, target_id: 'fixture::lib-0' });
    await page.locator('.nav-item').nth(2).click();
    await page.locator('.task-card').first().waitFor();
    const taskCards = await page.locator('.task-card').evaluateAll(cards => cards.map(card => {
      const rect = card.getBoundingClientRect();
      return { left: rect.left, top: rect.top, width: rect.width };
    }));
    assert.equal(taskCards.length, 2);
    assert(Math.abs(taskCards[0].top - taskCards[1].top) < 2);
    assert(taskCards[1].left > taskCards[0].left);
    assert.match(await page.locator('.task-card').first().innerText(), /Cron 0 6 \* \* \*/);
    const taskAddRect = await page.locator('.hero-actions button').boundingBox();
    assert(Math.abs(mediaAddRect.y-taskAddRect.y) < 1);
    assert(Math.abs(mediaAddRect.x+mediaAddRect.width-taskAddRect.x-taskAddRect.width) < 1);
    assert.equal(mediaAddRect.height, taskAddRect.height);
    const firstTask = page.locator('.task-card').first();
    assert.equal(await firstTask.locator('.task-card-actions button').count(), 3);
    assert.equal(await firstTask.locator('[data-tooltip], [title]').count(), 0);
    await firstTask.getByRole('button', { name: '停用计划任务', exact: true }).click();
    assert.match(await firstTask.getAttribute('class'), /disabled/);
    assert.equal(await page.locator('.task-modal').count(), 0);
    await firstTask.getByRole('button', { name: '启用计划任务', exact: true }).click();
    await firstTask.getByRole('button', { name: '立即执行', exact: true }).click();
    await firstTask.getByRole('button', { name: '停止执行', exact: true }).waitFor();
    assert.equal(await firstTask.locator('.task-icon-button.running rect').count(), 1);
    await page.screenshot({ path: path.join(output, 'task-running.png') });
    await firstTask.getByRole('button', { name: '停止执行', exact: true }).click();
    await firstTask.getByRole('button', { name: '立即执行', exact: true }).waitFor();
    // Scheduler execution is observed via status polling, without clicking Run.
    executionStatus = { running: true, tasks: {'task-b':{state:'running',stopping:false}} };
    await page.locator('.task-card').nth(1).getByRole('button', { name: '停止执行', exact: true }).waitFor();
    assert.equal(await firstTask.getByRole('button', {name:'立即执行',exact:true}).isEnabled(), true);
    await firstTask.getByRole('button', {name:'立即执行',exact:true}).click();
    await firstTask.getByRole('button', {name:'停止执行',exact:true}).click();
    await page.locator('.task-card').nth(1).getByRole('button', { name: '停止执行', exact: true }).click();
    await page.locator('.task-card').first().getByRole('button', { name: '删除' }).click();
    assert.equal(await page.getByRole('heading', { name: '删除计划任务？' }).count(), 1);
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await page.getByRole('button', { name: /新建任务/ }).click();
    assert.equal(await page.locator('.tag-picker-panel').count(), 0);
    await page.getByRole('button', { name: '任务功能', exact: true }).press('ArrowDown');
    const taskFunctions = page.getByRole('dialog', { name: '任务功能候选项' });
    await taskFunctions.getByLabel('AI翻译', { exact: true }).click();
    assert.equal(await taskFunctions.count(), 0);
    await page.getByRole('button', { name: '元数据候选', exact: true }).click();
    const translationFields = page.getByRole('dialog', { name: '元数据候选候选项' });
    assert.equal(await translationFields.getByRole('checkbox').count(), 5);
    for (const label of ['标题', '简介', '出版商', '作者']) {
      assert.equal(await translationFields.getByLabel(label, { exact: true }).count(), 1);
    }
    await translationFields.getByLabel('全选', { exact: true }).check();
    await translationFields.getByLabel('标题', { exact: true }).press('Escape');
    assert.equal(await page.locator('#task-metadata .tag-picker-chip').count(), 4);
    await page.screenshot({ path: path.join(output, 'ai-translation-task.png') });
    await page.getByRole('button', { name: '任务功能', exact: true }).click();
    assert.equal(await taskFunctions.getByLabel('卡片拼贴刷新', { exact: true }).count(), 1);
    await taskFunctions.getByLabel('卡片拼贴刷新', { exact: true }).click();
    await page.getByRole('button', { name: '任务功能', exact: true }).click();
    await taskFunctions.getByLabel('元数据补全').click();
    assert.equal(await page.locator('#task-functions .tag-picker-chip').count(), 1);
    assert.match(await page.locator('#task-functions .tag-picker-chip').innerText(), /元数据补全/);
    assert.equal(await page.locator('.cron-picker').count(), 1);
    assert.equal(await page.locator('.cron-picker input').inputValue(), '0 6 * * *');
    const timeLimit = page.getByRole('spinbutton',{name:'时间限制',exact:true});
    assert.equal(await timeLimit.inputValue(),'0');
    assert.equal(await timeLimit.getAttribute('step'),'0.5');
    const scheduleFields = await page.locator('.task-schedule-row > fieldset').evaluateAll(elements=>elements.map(el=>{
      const box=el.getBoundingClientRect(), style=getComputedStyle(el), title=getComputedStyle(el.querySelector('legend'));
      return {y:box.y,height:box.height,width:box.width,border:style.borderColor,font:title.fontSize,color:title.color};
    }));
    assert.equal(scheduleFields.length,2);
    assert.deepEqual(scheduleFields[0],scheduleFields[1]);
    await page.locator('.task-time-limit').hover();
    assert.equal(await page.locator('.task-time-limit .day-unit').evaluate(el=>getComputedStyle(el).opacity),'0');
    await page.getByRole('button',{name:'增加时间限制',exact:true}).click();
    assert.equal(await timeLimit.inputValue(),'0.5');
    await page.getByRole('button',{name:'减少时间限制',exact:true}).click();
    assert.equal(await timeLimit.inputValue(),'0');
    await page.getByRole('button',{name:'减少时间限制',exact:true}).evaluate(el=>el.blur());
    await page.locator('.task-modal h2').hover();
    assert.equal(await page.locator('.task-time-limit .day-unit').evaluate(el=>getComputedStyle(el).opacity),'1');
    await page.screenshot({path:path.join(output,'task-time-limit.png')});
    assert.equal(await page.getByText('五段格式：分 时 日 月 周，按本地时间执行').count(), 0);
    await page.locator('.cron-picker input').fill('0 3 * * *');
    assert.equal(await page.locator('#task-metadata .tag-picker-chip').count(), 0);
    const widths = await page.locator('.task-form-row').evaluate(row => [...row.children].map(el => el.getBoundingClientRect().width));
    assert(Math.abs(widths[0] - widths[1]) < 2);
    await page.getByRole('button', { name: '应用媒体库', exact: true }).click();
    const libraryPanel = page.getByRole('dialog', { name: '应用媒体库候选项' });
    await libraryPanel.getByRole('checkbox').last().check();
    await libraryPanel.getByLabel('国漫', {exact:false}).check();
    assert.equal(await page.locator('#task-libraries .tag-picker-chip').count(), 2);
    const panelRect = await libraryPanel.boundingBox();
    assert(panelRect.y >= 0 && panelRect.y + panelRect.height <= 1000);
    await page.screenshot({ path: path.join(output, 'task-picker-desktop.png') });
    await page.getByRole('heading', { name: '新建计划任务' }).click();
    for (const viewport of [{ width: 390, height: 844 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport);
      await page.getByRole('button', { name: '应用媒体库', exact: true }).click();
      await page.getByRole('dialog', { name: '应用媒体库候选项' }).getByRole('checkbox').last().uncheck();
      const rect = await page.locator('.tag-picker-panel').boundingBox();
      assert(rect.x >= 0 && rect.x + rect.width <= viewport.width);
      assert(rect.y >= 0 && rect.y + rect.height <= viewport.height);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(output, `task-picker-${viewport.width}.png`) });
      await page.getByRole('dialog', { name: '应用媒体库候选项' }).getByRole('checkbox').last().press('Escape');
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.task-modal').getByRole('button', { name: '取消', exact: true }).click();
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('.nav-item').nth(1).click();
    await page.locator('.record-item').first().waitFor();
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/api/scrape-records?') && response.url().includes('offset=50')),
      page.getByRole('navigation', { name: '刮削记录分页' }).getByRole('button', { name: '下一页', exact: true }).click()
    ]);
    assert.match(apiCalls.filter(call => call[1] === '/api/scrape-records').at(-1)[2], /limit=50&offset=50/);
    await page.getByRole('navigation', { name: '刮削记录分页' }).getByRole('button', { name: '上一页', exact: true }).click();
    assert.equal(await page.locator('.records-head > *').count(), 6);
    assert.equal(await page.locator('.time-sort .sort-arrows i').count(), 2);
    const sortDecoration = await page.locator('.sort-arrows').evaluate(element => ({
      width: element.getBoundingClientRect().width,
      content: [element, ...element.children].flatMap(node =>
        ['::before', '::after'].map(pseudo => getComputedStyle(node, pseudo).content))
    }));
    assert.equal(sortDecoration.width, 20);
    assert(sortDecoration.content.every(content => content === 'none' || content === 'normal'));
    const initialColors = await page.locator('.sort-arrows i').evaluateAll(items => items.map(item => getComputedStyle(item).color));
    assert.notEqual(initialColors[0], initialColors[1]);
    await page.locator('.time-sort').click();
    await page.waitForFunction(colors => {
      const arrows = [...document.querySelectorAll('.sort-arrows i')];
      return arrows.every((arrow, index) => getComputedStyle(arrow).color === colors[1 - index]);
    }, initialColors);
    const nextColors = await page.locator('.sort-arrows i').evaluateAll(items => items.map(item => getComputedStyle(item).color));
    assert.deepEqual(nextColors, [...initialColors].reverse());
    assert.equal(await page.locator('.record-title-row > small').isVisible(), false);
    await page.locator('.record-expand').click();
    assert.equal(await page.locator('.record-volume-head > *').count(), 6);
    assert.match(await page.locator('.record-path').innerText(), /第一卷\.cbz/);
    await page.locator('.record-fields').hover();
    await page.locator('.floating-tooltip:not([hidden])').waitFor();
    assert.match(await page.locator('.floating-tooltip').innerText(), /简介/);
    await page.screenshot({path:path.join(output,'records-tooltip.png')});
    await page.locator('.record-volume:not(.record-volume-head) b').hover();
    assert.equal(await page.locator('.floating-tooltip').isVisible(), false);
    await page.locator('.record-volume:not(.record-volume-head) > span').first().hover();
    await page.locator('.floating-tooltip:not([hidden])').waitFor();
    assert.match(await page.locator('.floating-tooltip').innerText(), /长标题/);
    await page.locator('.nav-item').nth(3).click();
    await page.locator('.runtime-log-row').first().waitFor();
    assert.equal(await page.locator('.runtime-log-row > small').count(), 0);
    assert.equal(await page.locator('.runtime-log-row').getByText('web', {exact:true}).count(), 0);
    const logLayout = await page.locator('.runtime-log-detail').first().evaluate(element=>({
      whiteSpace:getComputedStyle(element).whiteSpace,
      height:element.getBoundingClientRect().height,
      overflow:element.scrollWidth>element.clientWidth+1
    }));
    assert.equal(logLayout.whiteSpace,'pre-wrap');
    assert(logLayout.height>100 && !logLayout.overflow);
    const shortLogHeight = await page.locator('.runtime-log-board').evaluate(el=>el.getBoundingClientRect().height);
    runtimeLogs.push(...Array.from({length:99},(_,index)=>({...runtimeLogs[0],id:index+2,detail:'操作详情\n执行完成'})));
    await page.getByRole('button',{name:'刷新运行日志',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.runtime-log-row').length===100);
    const fullLogLayout = await page.locator('.runtime-log-board').evaluate(el=>({
      height:el.getBoundingClientRect().height,viewport:innerHeight,
      overflow:getComputedStyle(el).overflowY,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight
    }));
    assert(fullLogLayout.height>fullLogLayout.viewport && fullLogLayout.height>shortLogHeight);
    assert.equal(fullLogLayout.overflow,'visible');
    assert(Math.abs(fullLogLayout.scrollHeight-fullLogLayout.clientHeight)<=1);
    await page.screenshot({path:path.join(output,'logs-natural-height.png')});
    runtimeLogs.splice(1);
    await page.getByRole('button',{name:'刷新运行日志',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.runtime-log-row').length===1);
    assert(Math.abs(await page.locator('.runtime-log-board').evaluate(el=>el.getBoundingClientRect().height)-shortLogHeight)<1);
    assert.match(await page.locator('.log-hero-controls').innerText(), /成功/);
    assert.match(await page.locator('.log-hero-controls').innerText(), /失败/);
    assert.equal(await page.locator('.stat-icon-success svg').count(), 1);
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/api/runtime-logs?') && response.url().includes('offset=100')),
      page.getByRole('navigation', { name: '运行日志分页' }).getByRole('button', { name: '下一页', exact: true }).click()
    ]);
    assert.match(apiCalls.filter(call => call[1] === '/api/runtime-logs').at(-1)[2], /limit=100&offset=100/);
    await page.screenshot({ path: path.join(output, 'logs-paged.png') });
    assert.equal(await page.locator('.hero-head .log-hero-controls').count(), 1);
    assert.equal(await page.locator('.view-stack .log-toolbar').count(), 0);
    await page.locator('.nav-item').first().click();
    await page.screenshot({ path: path.join(output, 'cards-mobile.png') });
    await page.locator('.library-card').first().click();
    await page.getByRole('button', { name: '元数据覆盖', exact: true }).click();
    await page.getByRole('dialog', { name: '元数据覆盖候选项' }).getByLabel('封面', { exact: true }).uncheck();
    await page.screenshot({ path: path.join(output, 'card-picker-mobile.png') });
    await page.getByRole('dialog', { name: '元数据覆盖候选项' }).getByLabel('封面', { exact: true }).press('Escape');
    await page.locator('.card-settings-modal').getByRole('button', { name: '取消', exact: true }).click();
    await page.locator('.nav-item').nth(4).click();
    await page.setViewportSize({ width: 1440, height: 1000 });
    assert.equal(await page.locator('.bangumi-card-head a').innerText(), '创建令牌 ↗');
    const backupRect = await page.locator('.settings-hero-actions').boundingBox();
    assert(Math.abs(backupRect.y-taskAddRect.y) < 1, 'settings actions align with task actions');
    const serverForm = page.locator('.server-form');
    await serverForm.getByRole('button', {name:'API 密钥',exact:true}).click();
    assert.equal(await serverForm.locator(':scope > label > .field-label').innerText(), 'API 密钥');
    await serverForm.getByRole('button', {name:'账号密码',exact:true}).click();
    assert.equal(await serverForm.locator('.server-form-grid').last().locator(':scope > label > .field-label').count(), 2);
    assert.deepEqual(await page.locator('.retention-fields .field-label').allTextContents(), ['记录保留','日志保留']);
    await page.locator('.retention-fields label').first().hover();
    assert.equal(await page.locator('.retention-fields .day-unit').first().evaluate(el=>getComputedStyle(el).opacity), '0');
    await page.getByRole('button', {name:'增加记录保留天数',exact:true}).click();
    assert.equal(await page.locator('.retention-fields input').first().inputValue(), '31');
    await page.getByRole('button', {name:'减少记录保留天数',exact:true}).click();
    await page.getByRole('button', {name:'减少记录保留天数',exact:true}).evaluate(el=>el.blur());
    await page.locator('.hero-head h1').hover();
    assert.equal(await page.locator('.retention-fields .day-unit').first().evaluate(el=>getComputedStyle(el).opacity), '1');
    await page.locator('.bangumi-card input[placeholder="漫画&小说"]').fill('测试漫画');
    await page.locator('.bangumi-card').getByRole('button', { name: '搜索', exact: true }).click();
    await page.locator('.bangumi-card').getByRole('button', { name: '预览', exact: true }).click();
    const previewAlignment = await page.locator('.bangumi-preview-heading').evaluate(element => {
      const [title, link] = [...element.children].map(child => child.getBoundingClientRect());
      return { titleCenter: title.y+title.height/2, linkCenter: link.y+link.height/2, fontSize: getComputedStyle(element.firstElementChild).fontSize };
    });
    assert(Math.abs(previewAlignment.titleCenter-previewAlignment.linkCenter)<1);
    assert.equal(previewAlignment.fontSize, '18px');
    await page.screenshot({ path: path.join(output, 'bangumi-preview.png') });
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.bangumi-card > label > .field-label').innerText(), '访问密钥');
    assert.equal(await page.locator('.strategy-card').getByText('轮询间隔（秒）').count(), 0);
    await page.getByRole('button', {name:'运行模式',exact:true}).click();
    await page.getByRole('dialog', {name:'运行模式候选项'}).getByLabel('定时轮询增量').click();
    assert.equal(await page.getByRole('dialog', {name:'运行模式候选项'}).count(), 0);
    await page.locator('.strategy-card input[type=number]').first().waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('.strategy-card .field-label')].some(node => node.textContent === '轮询间隔（秒）'));
    assert.equal(await page.locator('.strategy-card .field-label').allTextContents().then(values => values.includes('轮询间隔（秒）')), true);
    await page.locator('.proxy-card input').fill('http://127.0.0.1:7890');
    await page.locator('.proxy-card').getByRole('button', {name:'测试',exact:true}).click();
    await page.getByText('代理连接成功', {exact:true}).waitFor();
    await page.locator('.proxy-card').getByRole('button', {name:'保存',exact:true}).click();
    await page.getByText('代理配置已保存', {exact:true}).waitFor();
    assert.equal(state.OUTBOUND_PROXY_URL, 'http://127.0.0.1:7890');
    const aiBox = await page.locator('.ai-card').boundingBox();
    const proxyBox = await page.locator('.proxy-card').boundingBox();
    assert(Math.abs(aiBox.width-proxyBox.width)<1 && Math.abs(aiBox.y-proxyBox.y)<1, 'AI and proxy share equal-width columns');
    await page.screenshot({ path: path.join(output, 'settings-desktop.png') });
    await page.setViewportSize({width:390,height:844});
    await page.locator('.proxy-card').scrollIntoViewIfNeeded();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const mobileProxy = await page.locator('.proxy-card').boundingBox();
    const mobileAi = await page.locator('.ai-card').boundingBox();
    assert(mobileProxy.y>=mobileAi.y+mobileAi.height && mobileProxy.width<=390);
    await page.screenshot({path:path.join(output,'settings-proxy-mobile.png')});
    await page.setViewportSize({width:1440,height:1000});
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.evaluate(()=>Promise.all(document.getAnimations()
      .filter(animation=>animation.effect.getTiming().iterations!==Infinity)
      .map(animation=>animation.finished.catch(()=>{}))));
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const motion = await page.evaluate(async () => {
      const sidebar = document.querySelector('.sidebar');
      const main = document.querySelector('.main');
      const icon = document.querySelector('.nav-icon');
      const frames = [];
      document.querySelector('.collapse-btn').click();
      const start = performance.now();
      while (performance.now() - start < 550) {
        await new Promise(requestAnimationFrame);
        frames.push([sidebar.getBoundingClientRect().width, main.getBoundingClientRect().left, icon.getBoundingClientRect().left]);
      }
      return frames;
    });
    assert(motion.some(([width]) => width > 80 && width < 230), 'collapse has intermediate frames');
    assert(motion.every(([width, left]) => Math.abs(width - left) < 2), 'sidebar and main stay synchronized');
    assert(Math.max(...motion.map(frame => frame[2])) - Math.min(...motion.map(frame => frame[2])) < 1, 'icons stay anchored');
    await page.screenshot({ path: path.join(output, 'sidebar-collapsed.png') });
    await page.locator('.collapse-btn').click();
    await page.waitForFunction(() => document.querySelector('.sidebar').getBoundingClientRect().width > 235);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.locator('.nav-item').nth(2).click();
    await page.getByRole('button', { name: /新建任务/ }).click();
    await page.getByRole('button', { name: '任务功能', exact: true }).click();
    assert.match(await page.getByRole('dialog', {name:'任务功能候选项'}).locator('.tag-picker-option').first().innerText(), /元数据修正/);
    await page.getByRole('dialog', { name: '任务功能候选项' }).getByLabel('元数据修正', { exact: true }).click();
    assert.equal(await page.getByRole('switch').count(), 4);
    const switchRows = await page.locator('.task-option-switches > button').evaluateAll(elements=>elements.map(element=>{
      const box=element.getBoundingClientRect(); return {x:box.x,y:box.y};
    }));
    assert(switchRows.slice(0,3).every(box=>Math.abs(box.y-switchRows[0].y)<1));
    assert(switchRows[3].y>switchRows[0].y && Math.abs(switchRows[3].x-switchRows[0].x)<1);
    assert.equal(await page.getByRole('switch', {name:'包含锁定',exact:true}).getAttribute('aria-checked'), 'false');
    assert.equal(await page.getByRole('switch', {name:'完成锁定',exact:true}).getAttribute('aria-checked'), 'false');
    await page.getByRole('switch', {name:'繁转简',exact:true}).click();
    await page.getByRole('switch', {name:'标题提取',exact:true}).click();
    await page.getByRole('switch', {name:'包含锁定',exact:true}).click();
    await page.getByRole('switch', {name:'完成锁定',exact:true}).click();
    await page.getByRole('button', { name: '元数据候选', exact: true }).click();
    await page.getByRole('dialog', { name: '元数据候选候选项' }).getByLabel('全选', { exact: true }).check();
    await page.getByRole('dialog', { name: '元数据候选候选项' }).getByLabel('标题', { exact: true }).press('Escape');
    await page.getByRole('button', { name: '应用媒体库', exact: true }).click();
    await page.getByRole('dialog', { name: '应用媒体库候选项' }).getByLabel('国漫', { exact: false }).check();
    await page.getByRole('dialog', { name: '应用媒体库候选项' }).getByLabel('国漫', { exact: false }).press('Escape');
    await page.screenshot({ path: path.join(output, 'metadata-correction-editor.png') });
    await page.locator('.task-modal').getByRole('button', { name: '保存', exact: true }).click();
    await page.locator('.task-card.metadata_correction').waitFor();
    assert.deepEqual(tasks.at(-1).operations, ['simplify', 'extract_title']);
    assert.equal(tasks.at(-1).include_locked, true);
    assert.equal(tasks.at(-1).lock_completed, true);
    assert.deepEqual(tasks.at(-1).fields, ['title', 'summary', 'publisher', 'authors']);
    assert(tasks.at(-1).card_ids[0].includes('::'));
    assert.equal(tasks.at(-1).name, '元数据修正');
    const correctionMask = await page.locator('.task-card.metadata_correction .task-card-icon').evaluate(el => getComputedStyle(el, '::after').maskImage);
    assert(correctionMask.includes('metadata-correction.svg'));
    assert(await page.evaluate(async () => {
      const image = new Image();
      image.src = '/metadata-correction.svg';
      await image.decode();
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 24;
      const context = canvas.getContext('2d');
      context.drawImage(image, 0, 0, 24, 24);
      const pixels = context.getImageData(0, 0, 24, 24).data;
      return pixels.filter((value, index) => index % 4 === 3 && value > 0).length > 30;
    }));
    await page.screenshot({ path: path.join(output, 'correction-task-cards.png') });
    await page.locator('.task-card.metadata_correction').click();
    assert.equal(await page.getByRole('switch', {name:'繁转简',exact:true}).getAttribute('aria-checked'), 'true');
    assert.equal(await page.getByRole('switch', {name:'完成锁定',exact:true}).getAttribute('aria-checked'), 'true');
    await page.getByRole('button', { name: '任务功能', exact: true }).click();
    await page.getByRole('dialog', { name: '任务功能候选项' }).getByLabel('元数据补全').click();
    assert.equal(await page.getByRole('switch').count(), 2);
    assert.equal(await page.getByRole('switch', {name:'包含锁定',exact:true}).getAttribute('aria-checked'), 'false');
    const aiCompletion = page.getByRole('button', { name: 'AI补全', exact: true });
    assert.deepEqual(await page.locator('.completion-switches > button').allTextContents().then(values=>values.map(value=>value.trim())),
      ['AI补全','包含锁定','完成锁定']);
    const completionBoxes = await page.locator('.completion-switches > button').evaluateAll(elements=>elements.map(element=>{
      const box=element.getBoundingClientRect(); return {top:box.top,height:box.height,width:box.width};
    }));
    assert(completionBoxes.every(box=>Math.abs(box.top-completionBoxes[0].top)<1 &&
      Math.abs(box.height-completionBoxes[0].height)<1 && Math.abs(box.width-completionBoxes[0].width)<1));
    assert.equal(await aiCompletion.getAttribute('aria-pressed'), 'false');
    await aiCompletion.click();
    assert.equal(await aiCompletion.getAttribute('aria-pressed'), 'true');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(output, 'ai-completion-mobile.png') });
    const mobileSwitches = await page.locator('.completion-switches > button').evaluateAll(elements=>elements.map(element=>{
      const box=element.getBoundingClientRect(); return {y:box.y,right:box.right,overflow:element.scrollWidth>element.clientWidth+1};
    }));
    assert.equal(mobileSwitches.length,3);
    assert(mobileSwitches.every(box=>Math.abs(box.y-mobileSwitches[0].y)<1 && box.right<=390 && !box.overflow));
    await page.locator('.task-modal').getByRole('button', { name: '取消', exact: true }).click();
    await page.locator('.sidebar-logout').click();
    await page.locator('.login-card').waitFor();
    assert.equal(await page.getByRole('textbox', {name:'用户名',exact:true}).inputValue(), '');
    assert.equal(await page.locator('.login-input input').last().inputValue(), '');
    await page.waitForFunction(() => [...document.querySelectorAll('.login-backdrop img')].length > 0 &&
      [...document.querySelectorAll('.login-backdrop img')].every(img=>img.complete&&img.naturalWidth));
    assert.equal(await page.locator('.login-cover-column').count(), 8);
    assert.equal(await page.locator('.login-backdrop img').count(), 64);
    assert.equal(await page.locator('.login-backdrop').evaluate(el=>getComputedStyle(el,'::after').content), 'none');
    assert.equal(await page.locator('.login-input').first().evaluate(el=>getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)');
    assert.equal(await page.locator('.login-button > svg:first-child').count(), 1);
    assert.equal(await page.locator('.login-card').evaluate(el=>getComputedStyle(el).backgroundColor), 'rgba(255, 255, 255, 0.62)');
    const backgroundCover = page.locator('.login-backdrop img').first();
    await backgroundCover.dispatchEvent('error');
    assert.equal(await backgroundCover.evaluate(img=>img.style.visibility), 'hidden');
    await backgroundCover.dispatchEvent('load');
    assert.equal(await backgroundCover.evaluate(img=>img.style.visibility), 'visible');
    assert.equal(await page.locator('.login-input > svg').count(), 2);
    assert.equal(await page.locator('.login-input input').last().getAttribute('type'), 'password');
    await page.getByRole('button', {name:'显示密码',exact:true}).click();
    assert.equal(await page.locator('.login-input input').last().getAttribute('type'), 'text');
    await page.getByRole('button', {name:'隐藏密码',exact:true}).click();
    await page.screenshot({path:path.join(output,'login-mobile.png')});
    await page.setViewportSize({width:1440,height:1000});
    await page.screenshot({path:path.join(output,'login-desktop.png')});
    await page.emulateMedia({reducedMotion:'no-preference'});
    const driftStart = await page.locator('.login-cover-column').first().evaluate(el=>getComputedStyle(el).transform);
    await page.waitForTimeout(300);
    const driftEnd = await page.locator('.login-cover-column').first().evaluate(el=>getComputedStyle(el).transform);
    assert.notEqual(driftStart, driftEnd);
    assert.deepEqual(errors, []);
    // Empty selections must remain empty when configuration is reloaded.
    const context = { Vue: { createApp: options => ({ mount: () => { context.options = options; } }) }, TagPicker: {} };
    vm.runInNewContext(fs.readFileSync(path.join(web, 'config.js'), 'utf8'), context);
    const card = context.options.methods.makeCard.call({ overwriteFieldOptions: [{ value: 'title' }], cardHues: [105] }, { OVERWRITE_FIELDS: [] });
    const timeState = {editingTask:{time_limit_hours:0}};
    context.options.methods.stepTaskTime.call(timeState,0.5);
    assert.equal(timeState.editingTask.time_limit_hours,0.5);
    context.options.methods.stepTaskTime.call(timeState,-0.5);
    context.options.methods.stepTaskTime.call(timeState,-0.5);
    assert.equal(timeState.editingTask.time_limit_hours,0);
    assert.equal(card.overwriteFields.length, 0);
    assert.equal(context.options.methods.metadataText({ metadata_fields: ['summaryLock', 'authorsLock', 'summary'] }), '简介锁定、作者锁定、简介');
    context.clearInterval = () => {};
    context.setInterval = () => 1;
    const coverUrl = '/api/login-background/cover?token=fixture';
    const backgroundState = {authenticated:false,loginBackground:[{url:coverUrl,failed:true}],
      api:async()=>({items:[{url:coverUrl}]}),loadLoginBackground:()=>{}};
    await context.options.methods.loadLoginBackground.call(backgroundState);
    assert.match(backgroundState.loginBackground[0].url, /&retry=\d+$/);
    const recoveredUrl = backgroundState.loginBackground[0].url;
    await context.options.methods.loadLoginBackground.call(backgroundState);
    assert.equal(backgroundState.loginBackground[0].url, recoveredUrl);
    backgroundState.api = async()=>{throw new Error('temporary failure');};
    await context.options.methods.loadLoginBackground.call(backgroundState);
    assert.equal(backgroundState.loginBackground[0].url, recoveredUrl);
    backgroundState.api = async()=>({items:[]});
    await context.options.methods.loadLoginBackground.call(backgroundState);
    assert.equal(backgroundState.loginBackground.length, 0);
    console.log(JSON.stringify({ result: 'PASS', cardLayout, screenshots: output, checks: 'chip selection, persistence, outside click, Escape, keyboard, scrolling, narrow/landscape viewports, empty covers, empty overwrite reload', apiCalls: apiCalls.length }, null, 2));
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
