const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const requests=[],errors=[];
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/')) {
    requests.push(url.pathname+url.search);
    let result={};
    if(url.pathname==='/api/auth/session') {
      setTimeout(()=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({authenticated:true,username:'admin'}));},400);
      return;
    }
    if(url.pathname==='/api/config') result={KOMGA_SERVERS:[{id:'test',name:'测试',base_url:'http://fixture.invalid'}],KOMGA_LIBRARY_LIST:[{SERVER_ID:'test',LIBRARY:'books'}],METADATA_TASKS:[]};
    if(url.pathname==='/api/workbench/items') {
      const offset=Number(url.searchParams.get('page')||0)*48;
      result={total:10000,library_total:10000,items:Array.from({length:48},(_,i)=>({id:String(offset+i),title:'作品 '+(offset+i),cover:'/logo-icon.png'}))};
    }
    if(url.pathname==='/api/status') result={tasks:{}};
    if(url.pathname.endsWith('/stats')) result={total:10000,today:4,comic:5000,novel:5000,success:9000,failed:1000};
    if(url.pathname==='/api/runtime-logs') {
      const offset=Number(url.searchParams.get('offset')||0);
      result={total:10000,items:Array.from({length:100},(_,i)=>({id:offset+i,action:'执行任务',detail:'详细记录\n'+('测试日志 '.repeat((i%5)+1)),level:i%3?'info':'error',recorded_at:'2026-09-29 12:00:00'}))};
    }
    if(url.pathname==='/api/scrape-records') {
      const offset=Number(url.searchParams.get('offset')||0);
      result={total:10000,items:Array.from({length:50},(_,i)=>({id:offset+i,item_title:'作品 '+(offset+i),source_title:'作品 '+(offset+i),recorded_at:'2026-09-29 12:00:00',metadata_fields:['title'],volume_count:0}))};
    }
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify(result));return;
  }
  const file=path.join(root,'web',url.pathname==='/'?'index.html':url.pathname);
  if(!fs.existsSync(file)) {res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':'text/html');
  res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,channel:process.env.BK_BROWSER_CHANNEL||'msedge'});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/#records`);
    assert.equal(await page.locator('.login-card').count(),0);
    await page.locator('.record-item').first().waitFor();
    assert.ok(await page.locator('.record-item').count()<40);
    await page.evaluate(()=>window.scrollTo(0,8400));
    await page.waitForTimeout(600);
    assert.ok(requests.some(url=>url.includes('scrape-records?') && /offset=[1-9]/.test(url)));
    assert.ok(await page.locator('.record-item').count()<40);
    await page.getByRole('button',{name:'回到顶部',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollbarWidth),'none');
    await page.getByRole('button',{name:'回到顶部',exact:true}).click();
    await page.waitForFunction(()=>window.scrollY<2);
    assert.equal(await page.locator('[aria-label="刮削记录分页"]').count(),0);
    await page.locator('.nav-item').filter({hasText:'运行日志'}).click();
    await page.locator('.runtime-log-row').first().waitFor();
    await page.evaluate(()=>window.scrollTo(0,12000));
    await page.waitForTimeout(600);
    assert.ok(requests.some(url=>url.includes('runtime-logs?') && /offset=[1-9]/.test(url)));
    assert.ok(await page.locator('.runtime-log-row').count()<40);
    fs.mkdirSync(path.join(root,'test_results/web-ui'),{recursive:true});
    await page.screenshot({path:path.join(root,'test_results/web-ui/virtual-logs.png')});
    await page.locator('.nav-item').filter({hasText:'工作平台'}).click();
    await page.locator('.work-book').first().waitFor();
    await page.evaluate(()=>window.scrollTo(0,12000));
    await page.waitForTimeout(800);
    assert.ok(requests.some(url=>url.includes('/api/workbench/items?') && /page=[1-9]/.test(url)));
    assert.ok(await page.locator('.work-book').count()<120);
    await page.getByRole('button',{name:'回到顶部',exact:true}).waitFor();
    await page.screenshot({path:path.join(root,'test_results/web-ui/virtual-workbench.png')});
    await page.setViewportSize({width:390,height:844});
    await page.waitForTimeout(400);
    assert.ok(await page.locator('.work-book').count()<40);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(root,'test_results/web-ui/virtual-workbench-mobile.png')});
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('.nav-item').filter({hasText:'系统设置'}).click();
    await page.locator('.bangumi-card').waitFor();
    const actions=await page.locator('.bangumi-test-row > button').evaluateAll(items=>items.map(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,right:r.right};}));
    assert.ok(Math.abs(actions[0].width-actions[1].width)<1);
    assert.ok(Math.abs(actions[0].y-actions[1].y)<1);
    const cardBox=await page.locator('.bangumi-card').boundingBox();
    assert.ok(actions[1].right<=cardBox.x+cardBox.width);
    assert.equal(await page.locator('.archive-toggle').count(),0);
    await page.locator('.bangumi-card input').first().fill('test-token');
    await page.locator('.bangumi-card h3').click();
    await page.waitForTimeout(150);
    assert.ok(requests.includes('/api/bangumi/token'));
    fs.mkdirSync(path.join(root,'test_results/web-ui'),{recursive:true});
    await page.screenshot({path:path.join(root,'test_results/web-ui/new-settings.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(root,'test_results/web-ui/new-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('Virtual list, session gate, token autosave and responsive checks passed');
  } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
