import { chromium } from 'playwright';
const B='http://127.0.0.1:8099';
const helpers=`
function _lin(c){c/=255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4);}
function _lum([r,g,b]){return 0.2126*_lin(r)+0.7152*_lin(g)+0.0722*_lin(b);}
function _parse(s){const m=s.match(/rgba?\\(([^)]+)\\)/);if(!m)return null;const p=m[1].split(',').map(x=>parseFloat(x));return {rgb:[p[0],p[1],p[2]],a:p.length>3?p[3]:1};}
function _effBg(el){let n=el;while(n){const st=getComputedStyle(n);const bg=_parse(st.backgroundColor);if(bg&&bg.a>0)return bg.rgb;n=n.parentElement;}return [255,255,255];}
window.ratio=function(sel){const el=document.querySelector(sel);if(!el)return null;const st=getComputedStyle(el);const fg=_parse(st.color);const bg=_effBg(el);if(!fg)return null;const l1=_lum(fg.rgb),l2=_lum(bg);return Math.round(((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05))*100)/100;};
`;
const br=await chromium.launch();const ct=await br.newContext();const p=await ct.newPage();
await p.addInitScript(helpers);
const errs=[];p.on('console',m=>{if(m.type()==='error')errs.push(m.text().slice(0,100));});
const out={fixes:{},regression:{}};

// ---- FIXES ----
// A11Y-002
await p.goto(`${B}/architektur.html`,{waitUntil:'networkidle'});await p.waitForTimeout(400);
await p.keyboard.press('Tab');await p.keyboard.press('Tab');await p.keyboard.press('Tab');await p.keyboard.press('Tab');
out.fixes['A11Y-002_archtab']=await p.evaluate(()=>{const e=document.activeElement;const s=getComputedStyle(e);return {cls:(e.className||'').toString().slice(0,20),outline:s.outlineStyle+' '+s.outlineWidth};});
await p.goto(`${B}/einreichen.html`,{waitUntil:'networkidle'});await p.waitForTimeout(300);await p.focus('#urlInput');
out.fixes['A11Y-002_input']=await p.evaluate(()=>{const s=getComputedStyle(document.querySelector('#urlInput'));return s.outlineStyle+' '+s.outlineWidth+' '+s.outlineColor;});
// A11Y-003
await p.goto(`${B}/architektur.html`,{waitUntil:'networkidle'});await p.waitForTimeout(300);
out.fixes['A11Y-003']=await p.evaluate(()=>({role:document.querySelector('#archSvg').getAttribute('role'),named:!!document.querySelector('#archSvg').getAttribute('aria-label'),nodes:document.querySelectorAll('#archSvg .arch-node[tabindex="0"]').length}));
// A11Y-004
const skip={};for(const pg of['index.html','einreichen.html','architektur.html']){await p.goto(`${B}/${pg}`,{waitUntil:'networkidle'});await p.waitForTimeout(150);skip[pg]=await p.evaluate(()=>{const s=document.querySelector('.skip-link');const t=s?document.querySelector(s.getAttribute('href')):null;return !!s&&!!t;});}
out.fixes['A11Y-004_skiplinks']=skip;
// A11Y-006 + USE-005
await p.goto(`${B}/einreichen.html`,{waitUntil:'networkidle'});await p.waitForTimeout(300);
out.fixes['A11Y-006']=await p.evaluate(()=>{const e=document.querySelector('#urlInput');return {req:e.getAttribute('aria-required'),desc:e.getAttribute('aria-describedby')};});
await p.evaluate(()=>document.querySelector('#submitBtn').click());
out.fixes['A11Y-006_err']=await p.evaluate(()=>({inv:document.querySelector('#urlInput').getAttribute('aria-invalid'),desc:document.querySelector('#urlInput').getAttribute('aria-describedby'),focus:document.activeElement?.id}));
await p.fill('#urlInput','https://ok.org/x.pdf');await p.fill('#yearInput','abcd');
out.fixes['USE-005_year']=await p.evaluate(()=>{document.querySelector('#submitBtn').click();return {hint:document.querySelector('#submitHint').textContent.slice(0,30),focus:document.activeElement?.id};});
// USE-005 happy path: valid url+year → should NOT block on validation (would try window.open)
await p.fill('#yearInput','2023');
out.fixes['USE-005_valid']=await p.evaluate(()=>{const before=document.querySelector('#submitHint').textContent;
  // stub window.open to avoid popup
  window.open=()=>({});document.querySelector('#submitBtn').click();
  const h=document.querySelector('#submitHint').textContent;return {changed:h!==before,hint:h.slice(0,40)};});
// USE-009
await p.goto(`${B}/404.html`,{waitUntil:'networkidle'});await p.waitForTimeout(150);
out.fixes['USE-009']=await p.evaluate(()=>({h1:document.querySelector('h1')?.textContent,home:!!document.querySelector('#homeLink')?.getAttribute('href')}));
// PERF-004
const reqs=[];p.on('request',r=>{if(r.url().includes('index.json'))reqs.push('i');if(r.url().includes('meta.json'))reqs.push('m');});
await p.goto(`${B}/index.html`,{waitUntil:'networkidle'});await p.waitForTimeout(400);
await p.evaluate(()=>{const d=document.querySelector('#pipelinePanel');if(d){d.open=true;d.dispatchEvent(new Event('toggle'));}});await p.waitForTimeout(600);
out.fixes['PERF-004_fetches']={index:reqs.filter(x=>x==='i').length,meta:reqs.filter(x=>x==='m').length};

// ---- REGRESSION SAMPLE (previously-passed checks in touched areas) ----
// A11Y-005 contrast (CSS touched)
await p.goto(`${B}/index.html`,{waitUntil:'networkidle'});await p.waitForTimeout(300);
out.regression['A11Y-005_contrast_light']=await p.evaluate(()=>({navLink:window.ratio('.nav-link'),muted:window.ratio('.skill-card p'),eyebrow:window.ratio('.eyebrow')}));
await p.evaluate(()=>document.documentElement.setAttribute('data-theme','dark'));await p.waitForTimeout(200);
out.regression['A11Y-005_contrast_dark']=await p.evaluate(()=>({navLink:window.ratio('.nav-link'),muted:window.ratio('.skill-card p')}));
await p.evaluate(()=>document.documentElement.setAttribute('data-theme','light'));
// A11Y-008 reflow + USE-008 topbar (nav min-height change)
const reflow={};for(const pg of['index.html','einreichen.html','architektur.html']){await p.setViewportSize({width:320,height:900});await p.goto(`${B}/${pg}`,{waitUntil:'networkidle'});await p.waitForTimeout(300);reflow[pg]=await p.evaluate(()=>({hScroll:document.documentElement.scrollWidth>document.documentElement.clientWidth+2,sw:document.documentElement.scrollWidth}));}
out.regression['A11Y-008_reflow']=reflow;await p.setViewportSize({width:1280,height:900});
// topbar not overflowing at desktop after nav flex change
await p.goto(`${B}/index.html`,{waitUntil:'networkidle'});await p.waitForTimeout(200);
out.regression['USE-008_topbar']=await p.evaluate(()=>{const tb=document.querySelector('.topbar');return {overflow:tb.scrollWidth>tb.clientWidth+2,navlinkH:Math.round(document.querySelector('.nav-link').getBoundingClientRect().height)};});
// A11Y-001 keyboard: skip link focus target + data hydrated
out.regression['A11Y-001_hydrate']=await p.evaluate(()=>({skillCards:document.querySelectorAll('.skill-card').length,lp21Rows:document.querySelectorAll('#lp21TableBody tr').length}));
// USE-001 status: filter summary aria-live + generated_at from meta
await p.evaluate(()=>{document.querySelector('#statusFilter').value='candidate';document.querySelector('#statusFilter').dispatchEvent(new Event('input'));});await p.waitForTimeout(200);
out.regression['USE-001_status']=await p.evaluate(()=>({summary:document.querySelector('#filterSummary').textContent.slice(0,40),live:document.querySelector('#filterSummary').getAttribute('aria-live')}));
out.regression['USE-001_generatedAt']=await p.evaluate(()=>document.querySelector('#dataGeneratedAt')?.textContent||'');
// PERF-002 CLS + PERF-001 LCP
await p.goto(`${B}/index.html`,{waitUntil:'load'});
await p.evaluate(()=>{window.__cls=0;window.__lcp=0;new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput)window.__cls+=e.value;}).observe({type:'layout-shift',buffered:true});new PerformanceObserver(l=>{for(const e of l.getEntries())window.__lcp=e.startTime;}).observe({type:'largest-contentful-paint',buffered:true});});
await p.waitForTimeout(2200);
out.regression['PERF_cwv']=await p.evaluate(()=>({cls:Math.round(window.__cls*1000)/1000,lcp:Math.round(window.__lcp)}));

out.consoleErrors=errs;
await br.close();console.log(JSON.stringify(out,null,1));
