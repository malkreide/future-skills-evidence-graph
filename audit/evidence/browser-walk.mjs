import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8099';
const out = {};

// WCAG contrast helper injected into the page.
const helpers = `
function _lin(c){c/=255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4);}
function _lum([r,g,b]){return 0.2126*_lin(r)+0.7152*_lin(g)+0.0722*_lin(b);}
function _parse(s){const m=s.match(/rgba?\\(([^)]+)\\)/);if(!m)return null;const p=m[1].split(',').map(x=>parseFloat(x));return {rgb:[p[0],p[1],p[2]],a:p.length>3?p[3]:1};}
function _effBg(el){let node=el;while(node){const st=getComputedStyle(node);const bg=_parse(st.backgroundColor);if(bg&&bg.a>0)return bg.rgb;node=node.parentElement;}return [255,255,255];}
window.ratio=function(el){const st=getComputedStyle(el);const fg=_parse(st.color);const bg=_effBg(el);if(!fg)return null;const l1=_lum(fg.rgb),l2=_lum(bg);const r=(Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);return {ratio:Math.round(r*100)/100,color:st.color,bg:'rgb('+bg.join(',')+')',size:st.fontSize,weight:st.fontWeight};};
`;
async function inject(page){await page.evaluate(helpers);}

async function setTheme(page, theme){
  await page.evaluate((t)=>{document.documentElement.setAttribute('data-theme',t);localStorage.setItem('fseg-theme',t);}, theme);
}

async function measureContrast(page, selectors){
  return await page.evaluate((sels)=>{
    const res=[];
    for(const s of sels){
      const el=document.querySelector(s);
      if(!el){res.push({sel:s,found:false});continue;}
      const r=window.ratio(el);
      res.push({sel:s,found:true,text:(el.textContent||'').trim().slice(0,40),...r});
    }
    return res;
  }, selectors);
}

async function pageStructure(page){
  return await page.evaluate(()=>{
    const headings=[...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h=>h.tagName+':'+(h.textContent||'').trim().slice(0,45));
    const landmarks={main:document.querySelectorAll('main,[role=main]').length,nav:document.querySelectorAll('nav,[role=navigation]').length,header:document.querySelectorAll('header').length,footer:document.querySelectorAll('footer').length};
    const skip=document.querySelector('.skip-link');
    // icon-only buttons: buttons whose text is empty but contain svg
    const iconBtns=[...document.querySelectorAll('button')].filter(b=>!(b.textContent||'').trim()&&b.querySelector('svg,img')).map(b=>({cls:b.className,name:b.getAttribute('aria-label')||b.getAttribute('title')||null}));
    const imgsNoAlt=[...document.querySelectorAll('img')].filter(i=>!i.hasAttribute('alt')).length;
    const canvasLabel=(()=>{const c=document.querySelector('canvas');return c?{ariaLabel:(c.getAttribute('aria-label')||'').slice(0,60),role:c.getAttribute('role'),tabindex:c.getAttribute('tabindex')}:null;})();
    return {lang:document.documentElement.lang,title:document.title,h1count:document.querySelectorAll('h1').length,headings,landmarks,hasSkipLink:!!skip,iconBtns,imgsNoAlt,canvasLabel};
  });
}

async function reflowCheck(page){
  await page.setViewportSize({width:320,height:900});
  await page.waitForTimeout(400);
  const r=await page.evaluate(()=>({scrollW:document.documentElement.scrollWidth,clientW:document.documentElement.clientWidth}));
  await page.setViewportSize({width:1280,height:900});
  return {...r,horizontalScroll:r.scrollW>r.clientW+2};
}

async function targetSizes(page, selectors){
  await page.setViewportSize({width:375,height:812});
  await page.waitForTimeout(300);
  const res=await page.evaluate((sels)=>{
    const out=[];
    for(const s of sels){
      document.querySelectorAll(s).forEach((el)=>{
        const r=el.getBoundingClientRect();
        if(r.width>0)out.push({sel:s,w:Math.round(r.width),h:Math.round(r.height),text:(el.textContent||'').trim().slice(0,20)});
      });
    }
    // dedupe by sel keeping smallest
    return out;
  }, selectors);
  await page.setViewportSize({width:1280,height:900});
  return res;
}

async function focusCheck(page){
  // Tab a few times and record the active element + its outline
  const res=[];
  for(let i=0;i<10;i++){
    await page.keyboard.press('Tab');
    const info=await page.evaluate(()=>{
      const el=document.activeElement;if(!el)return null;
      const st=getComputedStyle(el);
      return {tag:el.tagName,cls:(el.className||'').toString().slice(0,30),text:(el.textContent||'').trim().slice(0,25),outlineStyle:st.outlineStyle,outlineWidth:st.outlineWidth,outlineColor:st.outlineColor};
    });
    res.push(info);
  }
  return res;
}

async function cwv(page, url){
  await page.goto(url,{waitUntil:'load'});
  await page.evaluate(()=>{window.__lcp=0;window.__cls=0;
    new PerformanceObserver((l)=>{for(const e of l.getEntries())window.__lcp=e.startTime;}).observe({type:'largest-contentful-paint',buffered:true});
    new PerformanceObserver((l)=>{for(const e of l.getEntries()){if(!e.hadRecentInput)window.__cls+=e.value;}}).observe({type:'layout-shift',buffered:true});
  });
  await page.waitForTimeout(2500);
  return await page.evaluate(()=>{
    const nav=performance.getEntriesByType('navigation')[0]||{};
    const res=performance.getEntriesByType('resource');
    const total=res.reduce((s,r)=>s+(r.transferSize||r.encodedBodySize||0),0);
    const biggest=res.map(r=>({n:r.name.split('/').pop(),kb:Math.round((r.transferSize||r.encodedBodySize||0)/1024)})).sort((a,b)=>b.kb-a.kb).slice(0,6);
    return {lcp:Math.round(window.__lcp),cls:Math.round(window.__cls*1000)/1000,domContentLoaded:Math.round(nav.domContentLoadedEventEnd||0),transferKB:Math.round(total/1024),biggest,resourceCount:res.length};
  });
}

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
await page.addInitScript(helpers);
page.on('console', m=>{ if(m.type()==='error') (out.consoleErrors=out.consoleErrors||[]).push(m.text().slice(0,120)); });

// ---------- INDEX ----------
await page.goto(BASE+'/index.html',{waitUntil:'networkidle'});
await page.waitForTimeout(800);
out.index={};
out.index.hydration=await page.evaluate(()=>({
  visibility:document.visibilityState,
  skillCards:document.querySelectorAll('.skill-card').length,
  metricSkills:document.querySelector('#metricSkills')?.textContent,
  lp21Rows:document.querySelectorAll('#lp21TableBody tr').length,
  detailFilled:!!document.querySelector('#detailPane .detail-header'),
  radarLabel:(document.querySelector('#lp21Radar')?.getAttribute('aria-label')||'').slice(0,50),
}));
// hydration: click theme toggle
out.index.themeToggleWorks=await page.evaluate(()=>{const b=document.querySelector('#themeToggle');const before=document.documentElement.getAttribute('data-theme');b.click();const after=document.documentElement.getAttribute('data-theme');b.click();return before!==after;});
out.index.structure=await pageStructure(page);
const idxSel=['.eyebrow','.principle','.field-hint','.pill','.metrics p','.method-note','.filter-summary','.nav-link','.legend-note','.mapping-table th','.skill-card p','.definition','.intro-lead p','.chain-node','#scoreValue','.pipeline-hint','.coverage-bar'];
await setTheme(page,'light');await page.waitForTimeout(200);
out.index.contrastLight=await measureContrast(page, idxSel);
await setTheme(page,'dark');await page.waitForTimeout(200);
out.index.contrastDark=await measureContrast(page, idxSel);
await setTheme(page,'light');await page.waitForTimeout(200);
out.index.reflow=await reflowCheck(page);
out.index.targets=await targetSizes(page,['#themeToggle','.metric-filter','.ghost-button','.nav-link','select','.skill-card','input[type=search]','.theme-toggle']);
await page.goto(BASE+'/index.html',{waitUntil:'networkidle'});await page.waitForTimeout(500);
out.index.focus=await focusCheck(page);
out.index.cwv=await cwv(page, BASE+'/index.html');

// ---------- EINREICHEN ----------
await page.goto(BASE+'/einreichen.html',{waitUntil:'networkidle'});
await page.waitForTimeout(400);
out.einreichen={};
out.einreichen.structure=await pageStructure(page);
out.einreichen.formFields=await page.evaluate(()=>{
  return [...document.querySelectorAll('input,textarea')].map(f=>{
    const id=f.id;let labelled=false;
    // implicit label (wrapping) or explicit
    let p=f.closest('label');
    if(p)labelled=true;
    if(id&&document.querySelector('label[for="'+id+'"]'))labelled=true;
    if(f.getAttribute('aria-label')||f.getAttribute('aria-labelledby'))labelled=true;
    return {id:id||f.getAttribute('placeholder')||f.tagName,type:f.type,labelled,autocomplete:f.getAttribute('autocomplete')||null,ariaLabel:f.getAttribute('aria-label')||null};
  });
});
out.einreichen.dropzone=await page.evaluate(()=>{const d=document.querySelector('#dropzone');return d?{role:d.getAttribute('role'),tabindex:d.getAttribute('tabindex'),ariaLabel:d.getAttribute('aria-label')}:null;});
out.einreichen.isForm=await page.evaluate(()=>!!document.querySelector('form'));
out.einreichen.submitValidation=await page.evaluate(()=>{const b=document.querySelector('#submitBtn');b.click();return {hint:document.querySelector('#submitHint')?.textContent,hintLive:document.querySelector('#submitHint')?.getAttribute('aria-live'),focused:document.activeElement?.id};});
const subSel=['.field-hint','.submit-hint','.dropzone-sub','.submit-fineprint','.req','.submit-note li','.eyebrow'];
await setTheme(page,'light');await page.waitForTimeout(150);
out.einreichen.contrastLight=await measureContrast(page, subSel);
await setTheme(page,'dark');await page.waitForTimeout(150);
out.einreichen.contrastDark=await measureContrast(page, subSel);
await setTheme(page,'light');
out.einreichen.reflow=await reflowCheck(page);
await page.goto(BASE+'/einreichen.html',{waitUntil:'networkidle'});await page.waitForTimeout(300);
out.einreichen.focus=await focusCheck(page);

// ---------- ARCHITEKTUR ----------
await page.goto(BASE+'/architektur.html',{waitUntil:'networkidle'});
await page.waitForTimeout(600);
out.architektur={};
out.architektur.structure=await pageStructure(page);
out.architektur.hydration=await page.evaluate(()=>({
  svgNodes:document.querySelectorAll('#archSvg .arch-node').length,
  metricSkills:document.querySelector('#metricSkills')?.textContent,
  svgHasName:(()=>{const s=document.querySelector('#archSvg');return {role:s?.getAttribute('role'),ariaLabel:s?.getAttribute('aria-label'),title:!!s?.querySelector('title')};})(),
}));
out.architektur.tabs=await page.evaluate(()=>{
  const tabs=[...document.querySelectorAll('.arch-tab')].map(t=>({role:t.getAttribute('role'),selected:t.getAttribute('aria-selected'),controls:t.getAttribute('aria-controls')||null}));
  const tablist=document.querySelector('[role=tablist]');
  const panel=document.querySelectorAll('[role=tabpanel]').length;
  return {tabs,tablistFound:!!tablist,tabpanels:panel};
});
// keyboard: can we reach an svg node and activate?
out.architektur.svgNodeKeyboard=await page.evaluate(()=>{const n=document.querySelector('#archSvg .arch-node');return n?{tabindex:n.getAttribute('tabindex'),role:n.getAttribute('role'),ariaLabel:n.getAttribute('aria-label')}:null;});
const archSel=['.eyebrow','.arch-intro p','.arch-footnote','.metrics p'];
await setTheme(page,'light');await page.waitForTimeout(150);
out.architektur.contrastLight=await measureContrast(page, archSel);
await setTheme(page,'dark');await page.waitForTimeout(150);
out.architektur.contrastDark=await measureContrast(page, archSel);
await setTheme(page,'light');
out.architektur.reflow=await reflowCheck(page);
await page.goto(BASE+'/architektur.html',{waitUntil:'networkidle'});await page.waitForTimeout(300);
out.architektur.focus=await focusCheck(page);
// SVG text contrast (node titles) - measure a node-title and node-sub
out.architektur.svgTextContrast=await page.evaluate(()=>{
  const t=document.querySelector('.node-title');const s=document.querySelector('.node-sub');
  const rd=(el)=>el?{fill:getComputedStyle(el).fill}:null;
  return {title:rd(t),sub:rd(s)};
});

await browser.close();
console.log(JSON.stringify(out,null,1));
