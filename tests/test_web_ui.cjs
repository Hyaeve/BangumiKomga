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
  metadata_fields: ['title', 'summary', 'numberSort'], match_source: '书名号内容', recorded_at: '2026-09-10T13:14:13', volume_count: 1,
  volumes: [{ id: 2, item_title: '第一卷', source_path: '/data/comics/万古之王/第一卷.cbz', metadata_fields: ['numberSort'], match_source: '卷号排序', recorded_at: '2026-09-10T13:14:13' }]
}];
const runtimeLogs = [{ id: 1, level: 'info', action: '计划任务：自动执行', detail: '按 Cron 0 6 * * * 执行计划任务 每日元数据补全', source: 'scheduler', recorded_at: '2026-09-10T06:00:00' }];
const libraries = state.KOMGA_LIBRARY_LIST.map((item, index) => ({
  id: item.LIBRARY, name: ['国漫', '轻小说', '日漫', '无封面书库'][index] || `媒体库 ${index + 1}`
}));
let covers = [fs.readFileSync(path.join(web, 'logo-icon.png'))];
const apiCalls = [];

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
      apiCalls.push([req.method, url.pathname]);
      res.setHeader('Content-Type', 'application/json');
      let body = {};
      if (req.method === 'POST') {
        let raw = '';
        for await (const chunk of req) raw += chunk;
        body = JSON.parse(raw || '{}');
      }
      let result = {};
      if (url.pathname === '/api/auth/session') result = { authenticated: true, username: 'fixture' };
      else if (url.pathname === '/api/config') {
        if (req.method === 'POST') state = body;
        result = state;
      } else if (url.pathname === '/api/komga/libraries') result = { items: libraries };
      else if (url.pathname === '/api/komga/previews') result = { items: url.searchParams.get('library_id') === 'lib-3' ? [] : Array.from({ length: 8 }, (_, index) => ({ id: index, url: `/test-cover/${index}` })) };
      else if (url.pathname === '/api/tasks') result = { items: tasks };
      else if (url.pathname === '/api/scrape-records') result = { items: scrapeRecords };
      else if (url.pathname === '/api/scrape-records/stats') result = { total: 1, today: 1, comic: 1, novel: 0 };
      else if (url.pathname === '/api/runtime-logs') result = { items: runtimeLogs };
      else if (url.pathname === '/api/runtime-logs/stats') result = { total: 1, today: 1, plans: 1, manual: 0 };
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
    const type = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.png': 'image/png', '.ico': 'image/x-icon' }[path.extname(target)] || 'text/plain';
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
    assert.equal(await page.locator('.card-setting-grid .field-label').allTextContents().then(values => values.join('|')), 'Komga 服务|媒体库');
    await page.screenshot({ path: path.join(output, 'card-editor-desktop.png') });
    await page.getByRole('button', { name: '功能选项', exact: true }).click();
    const features = page.getByRole('dialog', { name: '功能选项候选项' });
    await features.getByLabel('简介翻译').check();
    await features.getByLabel('AI 识别').check();
    await page.screenshot({ path: path.join(output, 'feature-picker-desktop.png') });
    assert.equal(await features.count(), 1);
    assert.equal(await page.locator('#card-features .tag-picker-chip').count(), 2);
    await page.getByRole('heading', { name: '配置媒体库' }).click();
    assert.equal(await page.locator('.tag-picker-panel').count(), 0);
    await page.getByRole('button', { name: '缺失元数据', exact: true }).click();
    await page.getByRole('dialog', { name: '缺失元数据候选项' }).getByLabel('简介', { exact: true }).check();
    await page.getByRole('dialog', { name: '缺失元数据候选项' }).getByLabel('简介', { exact: true }).press('Escape');
    await page.getByRole('button', { name: '元数据覆盖', exact: true }).click();
    assert.equal(await page.locator('.tag-picker-panel').count(), 1);
    const overwrite = page.getByRole('dialog', { name: '元数据覆盖候选项' });
    await overwrite.getByLabel('封面', { exact: true }).check();
    await page.screenshot({ path: path.join(output, 'card-picker-desktop.png') });
    await overwrite.getByLabel('封面', { exact: true }).press('Escape');
    assert.equal(await page.locator('.tag-picker-panel').count(), 0);
    assert.equal(await page.getByRole('button', { name: '元数据覆盖', exact: true }).evaluate(el => document.activeElement === el), true);
    await page.getByRole('button', { name: '确定', exact: true }).click();
    await page.locator('.card-settings-modal').waitFor({ state: 'hidden' });
    assert.equal(state.KOMGA_LIBRARY_LIST[0].TRANSLATE_SUMMARY_TO_ZH, true);
    assert.equal(state.KOMGA_LIBRARY_LIST[0].AI_RECOGNITION, true);
    assert(state.KOMGA_LIBRARY_LIST[0].REQUIRED_FIELDS.includes('summary'));
    assert(state.KOMGA_LIBRARY_LIST[0].OVERWRITE_FIELDS.includes('thumbnail'));
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
    await page.locator('.task-card').first().getByRole('button', { name: '删除' }).click();
    assert.equal(await page.getByRole('heading', { name: '删除计划任务？' }).count(), 1);
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await page.getByRole('button', { name: /新建任务/ }).click();
    assert.equal(await page.locator('.tag-picker-panel').count(), 0);
    await page.getByRole('button', { name: '任务功能', exact: true }).press('ArrowDown');
    const taskFunctions = page.getByRole('dialog', { name: '任务功能候选项' });
    assert.equal(await taskFunctions.getByLabel('卡片拼贴刷新', { exact: true }).count(), 1);
    await taskFunctions.getByLabel('卡片拼贴刷新', { exact: true }).check();
    await taskFunctions.getByLabel('元数据补全').check();
    assert.equal(await taskFunctions.getByLabel('卡片拼贴刷新', { exact: true }).isChecked(), false);
    assert.equal(await page.locator('#task-functions .tag-picker-chip').count(), 1);
    await taskFunctions.getByLabel('元数据补全').press('Escape');
    assert.equal(await page.locator('.cron-picker').count(), 1);
    assert.equal(await page.locator('.cron-picker input').inputValue(), '0 6 * * *');
    assert.equal(await page.getByText('五段格式：分 时 日 月 周，按本地时间执行').count(), 0);
    await page.locator('.cron-picker input').fill('0 3 * * *');
    assert.equal(await page.locator('#task-metadata .tag-picker-chip').count(), 0);
    const widths = await page.locator('.task-form-row').evaluate(row => [...row.children].map(el => el.getBoundingClientRect().width));
    assert(Math.abs(widths[0] - widths[1]) < 2);
    await page.getByRole('button', { name: '应用媒体库', exact: true }).click();
    const libraryPanel = page.getByRole('dialog', { name: '应用媒体库候选项' });
    await libraryPanel.getByRole('checkbox').last().check();
    await libraryPanel.getByRole('checkbox').first().check();
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
    assert.equal(await page.locator('.records-head > *').count(), 6);
    assert.equal(await page.locator('.time-sort .sort-arrows i').count(), 2);
    await page.locator('.record-expand').click();
    assert.equal(await page.locator('.record-volume-head > *').count(), 6);
    assert.match(await page.locator('.record-path').innerText(), /第一卷\.cbz/);
    await page.locator('.nav-item').nth(3).click();
    await page.locator('.runtime-log-row').first().waitFor();
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
    assert.equal(await page.locator('.bangumi-card > label > .field-label').innerText(), '访问密钥');
    assert.equal(await page.locator('.strategy-card').getByText('轮询间隔（秒）').count(), 0);
    await page.locator('.strategy-card select').selectOption('poll');
    await page.locator('.strategy-card input[type=number]').first().waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('.strategy-card .field-label')].some(node => node.textContent === '轮询间隔（秒）'));
    assert.equal(await page.locator('.strategy-card .field-label').allTextContents().then(values => values.includes('轮询间隔（秒）')), true);
    await page.screenshot({ path: path.join(output, 'settings-desktop.png') });
    assert.deepEqual(errors, []);
    // Empty selections must remain empty when configuration is reloaded.
    const context = { Vue: { createApp: options => ({ mount: () => { context.options = options; } }) }, TagPicker: {} };
    vm.runInNewContext(fs.readFileSync(path.join(web, 'config.js'), 'utf8'), context);
    const card = context.options.methods.makeCard.call({ overwriteFieldOptions: [{ value: 'title' }], cardHues: [105] }, { OVERWRITE_FIELDS: [] });
    assert.equal(card.overwriteFields.length, 0);
    console.log(JSON.stringify({ result: 'PASS', cardLayout, screenshots: output, checks: 'chip selection, persistence, outside click, Escape, keyboard, scrolling, narrow/landscape viewports, empty covers, empty overwrite reload', apiCalls: apiCalls.length }, null, 2));
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
