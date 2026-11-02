const { chromium } = require('playwright');
const DH = process.env.AEGIS_DEMO_HOME || '/tmp/dh';
(async () => {
  const b = await chromium.launch();
  for (const [name, vp, scheme] of [['desktop-light', {width:1440,height:900}, 'light'], ['desktop-dark', {width:1440,height:900}, 'dark'], ['phone', {width:390,height:844}, 'light']]) {
    const p = await (await b.newContext({ viewport: vp, colorScheme: scheme })).newPage();
    await p.goto(process.argv[2]); await p.waitForTimeout(1500);
    for (const pg of ['overview','activity','agents','mcp','boundaries','autopilot','setup']) {
      await p.evaluate(h => location.hash = h, pg); await p.waitForTimeout(1100);
      const res = await p.evaluate(() => {
        const out = { small: [], contrast: [], overflow: [] };
        const parse = (c) => { const m = c.match(/[\d.]+/g); return m ? m.map(Number) : [0,0,0,0]; };
        const lum = ([r,g,b]) => { const f = (v) => { v/=255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); }; return .2126*f(r)+.7152*f(g)+.0722*f(b); };
        const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); const c = parse(cs.backgroundColor); if (cs.backgroundImage !== 'none' && e !== document.body) { const m = cs.backgroundImage.match(/rgba?\([^)]+\)|#[0-9a-f]{3,6}/i); if (m && m[0].startsWith('rgb')) return parse(m[0]); } if (e !== document.body && c.length >= 3 && (c.length < 4 || c[3] > .5)) return c; } return document.documentElement.matches(':root') && matchMedia('(prefers-color-scheme: dark)').matches ? [15,13,22] : [241,237,253]; };
        const page = document.querySelector('.page:not([hidden])');
        const walker = document.createTreeWalker(page, NodeFilter.SHOW_TEXT);
        const seen = new Set();
        while (walker.nextNode()) {
          const t = walker.currentNode; const el = t.parentElement; if (!t.textContent.trim() || seen.has(el)) continue; seen.add(el);
          if (el.closest('svg')) continue;
          const cs = getComputedStyle(el); const r = el.getBoundingClientRect(); if (!r.width || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
          const fs = parseFloat(cs.fontSize); if (fs < 12.5) out.small.push(`${fs}px "${t.textContent.trim().slice(0,30)}"`);
          const fg = parse(cs.color), bg = bgOf(el); const l1 = lum(fg), l2 = lum(bg); const ratio = (Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);
          const need = (fs >= 24 || (fs >= 18.6 && +cs.fontWeight >= 700)) ? 3 : 4.5;
          if (ratio < need) out.contrast.push(`${ratio.toFixed(2)} "${t.textContent.trim().slice(0,30)}"`);
          if (el.scrollWidth > el.clientWidth + 2 && cs.overflowX === 'visible' && cs.display !== 'inline' && !el.closest('.table-wrap,.terminal,.ev-code,.diff,pre')) out.overflow.push(`"${t.textContent.trim().slice(0,30)}"`);
        }
        out.pageOverflow = document.documentElement.scrollWidth > innerWidth;
        return out;
      });
      const issues = [...res.small.map(x=>'small '+x), ...res.contrast.map(x=>'contrast '+x), ...res.overflow.map(x=>'overflow '+x), ...(res.pageOverflow?['PAGE scrolls sideways']:[])];
      if (issues.length) console.log(`${name}/${pg}: ` + [...new Set(issues)].slice(0, 8).join(' | '));
    }
  }
  console.log('audit done'); await b.close();
})();
