const { chromium } = require('playwright');
const DH = process.env.AEGIS_DEMO_HOME || '/tmp/dh';
const fs = require('fs');
const url = process.argv[2];
const log = (ok, msg) => console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`);
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await p.goto(url); await p.waitForTimeout(1500);
  // re-resolve the element on every click: the page may redraw between looking and clicking
  const $loc = async (sel) => ((await p.locator(sel).count()) ? { click: () => p.locator(sel).first().click() } : null);
  const toast = async () => { await p.waitForTimeout(700); return (await p.textContent('#toast')) || ''; };
  const go = async (h) => { await p.evaluate(x => location.hash = x, h); await p.waitForTimeout(900); };
  const openCount = async () => p.evaluate(async () => (await (await fetch('/api/state')).json()).counts.open);

  // hostile text in an event must be shown as text, never run
  fs.appendFileSync(DH + '/.aegis/events.jsonl', JSON.stringify({ id: 'xss000000001', kind: 'autopilot', severity: 'info', time: Date.now() / 1000,
    title: '<img src=x onerror="window.__xss=1"> &lt;b&gt;', detail: '<script>window.__xss=1</script>', source: 'test', data: {}, actions: [] }) + '\n');
  await p.evaluate(() => refresh()); await go('activity'); await p.waitForTimeout(600);
  const xss = await p.evaluate(() => ({ ran: window.__xss === 1, imgs: document.querySelectorAll('#act-list img').length, shown: document.querySelector('#act-list').textContent.includes('<img src=x') }));
  log(!xss.ran && xss.imgs === 0 && xss.shown, `Hostile event text is shown as text (script ran: ${xss.ran}, injected <img>: ${xss.imgs}, visible as text: ${xss.shown})`);
  await p.click('#act-list .event:has-text("<img") >> text=Ignore'); await toast();
  // activity: mark handled
  await go('activity');
  let before = await openCount();
  await p.click('#act-list .event >> text=Mark handled');
  let t = await toast(); let after = await openCount();
  log(after === before - 1, `Mark handled: open ${before} -> ${after}, toast "${t}"`);
  // ignore (text button or outline)
  before = after;
  await p.click('#act-list .event >> text=Ignore');
  t = await toast(); after = await openCount();
  log(after === before - 1, `Ignore: open ${before} -> ${after}, toast "${t}"`);
  // filter all + reopen
  await p.click('.filter button[data-filter="all"]'); await p.waitForTimeout(400);
  const reopenCount = await p.locator('#act-list .event >> text=Reopen').count();
  log(reopenCount >= 2, `All filter shows handled events with Reopen (${reopenCount})`);
  await p.locator('#act-list .event >> text=Reopen').first().click(); t = await toast();
  log((await openCount()) === after + 1, `Reopen: toast "${t}"`);
  await p.click('.filter button[data-filter="high"]'); await p.waitForTimeout(400);
  const sevs = await p.$$eval('#act-list .sev', els => els.map(e => e.textContent.trim().toLowerCase()));
  log(sevs.length > 0 && sevs.every(s => s === 'high'), `High filter shows only high (${sevs.length})`);
  await p.click('.filter button[data-filter="open"]');
  // jail from activity
  const jailBtn = await $loc('#act-list .event:has-text("github") >> text=Jail it');
  if (jailBtn) { await jailBtn.click(); t = await toast(); const cfg = fs.readFileSync(DH + '/.claude.json', 'utf8'); log(cfg.includes('"mcp-jail"') && /github[\s\S]*mcp-jail/.test(cfg), `Jail it (github) rewrote config, toast "${t}"`); }
  else log(false, 'Jail it button for github not found');
  // review pins drawer
  const rev = await $loc('#act-list .event >> text=How to review');
  if (rev) { await rev.click(); await p.waitForTimeout(500); const txt = await p.textContent('#drawer-body'); log(!(await p.isHidden('#drawer')) && txt.includes('aegis mcp-pins weather'), 'How to review opens drawer with mcp-pins commands'); await p.keyboard.press('Escape'); await p.waitForTimeout(300); log(await p.isHidden('#drawer'), 'Escape closes drawer'); }
  // mcp page: undo
  await go('mcp');
  const undo = await $loc('.srv-row:has-text("github") >> text=Undo');
  if (undo) { await undo.click(); t = await toast(); const cfg = JSON.parse(fs.readFileSync(DH + '/.claude.json', 'utf8')); const gh = cfg.projects['/home/user/shop2'].mcpServers.github; log(gh.command === 'npx', `Undo restored github, toast "${t}"`); }
  else log(false, 'Undo button for github not found on MCP page');
  const pre = await $loc('.srv-row:has-text("filesystem") >> text=Undo');
  if (pre) { await pre.click(); await toast(); await p.waitForTimeout(800); }  // start from "full rights"
  const jail2 = await $loc('.srv-row:has-text("filesystem") >> text=Jail it');
  if (jail2) { await jail2.click(); t = await toast(); await p.waitForTimeout(800); const st = await p.textContent('.srv-row:has-text("filesystem")'); log(st.includes('Jailed'), `MCP page Jail it -> row shows Jailed, toast "${t}"`); }
  else log(false, 'Jail it for filesystem not found');
  // autopilot settings
  await go('autopilot');
  const cfg0 = (fs.existsSync(DH + '/.aegis/watch/config.json') ? JSON.parse(fs.readFileSync(DH + '/.aegis/watch/config.json', 'utf8')) : {auto_jail:false,interval:5});
  await p.click('label[for="set-auto_jail"] .switch'); t = await toast();
  const cfg1 = (fs.existsSync(DH + '/.aegis/watch/config.json') ? JSON.parse(fs.readFileSync(DH + '/.aegis/watch/config.json', 'utf8')) : {auto_jail:false,interval:5});
  log(cfg1.auto_jail === !cfg0.auto_jail, `Auto-jail toggle saved (${cfg0.auto_jail} -> ${cfg1.auto_jail}), toast "${t}"`);
  await p.click('label[for="set-auto_jail"] .switch'); await toast();
  await p.selectOption('#set-interval', '15'); await toast();
  log((fs.existsSync(DH + '/.aegis/watch/config.json') ? JSON.parse(fs.readFileSync(DH + '/.aegis/watch/config.json', 'utf8')) : {auto_jail:false,interval:5}).interval === 15, 'Interval select saved');
  await p.selectOption('#set-interval', '5'); await toast();
  // run drawer with diff
  await go('agents');
  await p.click('#ag-table tbody tr'); await p.waitForTimeout(1200);
  const diff = await p.textContent('#drawer-body .diff');
  log(diff && !diff.includes('Loading'), `Run drawer loads changes: "${(diff||'').slice(0,60).replace(/\n/g,' ')}"`);
  await p.click('#drawer-close'); await p.waitForTimeout(300);
  // run bar
  await go('overview');
  await p.fill('#page-overview [data-prompt] input', 'Fix the failing test');
  await p.click('#page-overview [data-prompt] .send'); t = await toast();
  log(/Started/.test(t), `Run bar starts a sandboxed run, toast "${t}"`);
  const active = JSON.parse(fs.readFileSync(DH + '/.aegis/watch/active.json', 'utf8'));
  log(active.length >= 1, `active.json lists the run (${active.length})`);
  await go('agents'); await p.waitForTimeout(500);
  const cur = await p.textContent('#ag-current');
  log(/Current agent run|Latest agent run/.test(cur), `Agents page shows the run: "${cur.slice(0, 70)}"`);
  // empty prompt
  await go('overview'); await p.click('#page-overview [data-prompt] .send'); t = await toast();
  log(/Describe/.test(t), `Empty prompt is refused with a hint: "${t}"`);
  // palette
  await p.keyboard.press('Control+k'); await p.waitForTimeout(300);
  await p.keyboard.type('bound'); await p.keyboard.press('Enter'); await p.waitForTimeout(600);
  log(await p.evaluate(() => location.hash) === '#boundaries', 'Ctrl+K palette navigates');
  // refresh + copy
  await p.click('#btn-refresh'); t = await toast(); log(/Checked/.test(t), `Check now: "${t}"`);
  await p.click('#page-boundaries .copy'); t = await toast(); log(/Copied|aegis probe/.test(t), `Copy button: "${t}"`);
  log(errors.length === 0, `No console errors ${errors.length ? errors.join(' | ') : ''}`);
  await b.close();
})();
