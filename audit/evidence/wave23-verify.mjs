import { chromium } from 'playwright';
const B='http://127.0.0.1:8099';
const br=await chromium.launch();const ct=await br.newContext();const p=await ct.newPage();
const out={};

// A11Y-003: svg aria-label per view
await p.goto(`${B}/architektur.html`,{waitUntil:'networkidle'});await p.waitForTimeout(400);
out.svgFlow=await p.evaluate(()=>({role:document.querySelector('#archSvg').getAttribute('role'),aria:(document.querySelector('#archSvg').getAttribute('aria-label')||'').slice(0,55),nodesReachable:document.querySelectorAll('#archSvg .arch-node[tabindex="0"]').length}));
await p.click('#tabModel');await p.waitForTimeout(200);
out.svgModel=await p.evaluate(()=>({aria:(document.querySelector('#archSvg').getAttribute('aria-label')||'').slice(0,40)}));

// A11Y-010: nav-link height at 375
await p.setViewportSize({width:375,height:812});
await p.goto(`${B}/index.html`,{waitUntil:'networkidle'});await p.waitForTimeout(400);
out.navHeights=await p.evaluate(()=>[...document.querySelectorAll('.nav-link')].map(a=>({t:a.textContent.trim().slice(0,18),h:Math.round(a.getBoundingClientRect().height)})));
await p.setViewportSize({width:1280,height:900});

// USE-005: year + url validation + enter
await p.goto(`${B}/einreichen.html`,{waitUntil:'networkidle'});await p.waitForTimeout(300);
out.yearAttrs=await p.evaluate(()=>{const y=document.querySelector('#yearInput');return {pattern:y.getAttribute('pattern'),maxlength:y.getAttribute('maxlength'),describedby:y.getAttribute('aria-describedby')};});
// bad year
await p.fill('#urlInput','https://example.org/report.pdf');
await p.fill('#yearInput','19');
out.badYear=await p.evaluate(()=>{document.querySelector('#submitBtn').click();return {hint:document.querySelector('#submitHint').textContent,focused:document.activeElement?.id};});
// bad url
await p.fill('#yearInput','2023');await p.fill('#urlInput','nicht eine url');
out.badUrl=await p.evaluate(()=>{document.querySelector('#submitBtn').click();return {hint:document.querySelector('#submitHint').textContent.slice(0,40),ariaInvalid:document.querySelector('#urlInput').getAttribute('aria-invalid'),focused:document.activeElement?.id};});
// enter-to-submit fires validation (empty url)
await p.fill('#urlInput','');
out.enterSubmit=await p.evaluate(()=>{const e=new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true});document.querySelector('#urlInput').dispatchEvent(e);return {hint:document.querySelector('#submitHint').textContent.slice(0,40),ariaInvalid:document.querySelector('#urlInput').getAttribute('aria-invalid')};});

// USE-009: 404 renders + home link
await p.goto(`${B}/404.html`,{waitUntil:'networkidle'});await p.waitForTimeout(200);
out.notfound=await p.evaluate(()=>({h1:document.querySelector('h1')?.textContent,homeHref:document.querySelector('#homeLink')?.getAttribute('href'),styled:getComputedStyle(document.querySelector('main')).borderTopWidth}));

// PERF-004: index.json fetched once on index; meta.json fetched
const reqs=[];
p.on('request',r=>{const u=r.url();if(u.includes('index.json'))reqs.push('index.json');if(u.includes('meta.json'))reqs.push('meta.json');});
await p.goto(`${B}/index.html`,{waitUntil:'networkidle'});await p.waitForTimeout(500);
// open ops panel to trigger status.js loadPipeline (won't fetch index.json for generated anymore)
await p.evaluate(()=>{const d=document.querySelector('#pipelinePanel');if(d){d.open=true;d.dispatchEvent(new Event('toggle'));}});
await p.waitForTimeout(800);
out.fetches={indexJson:reqs.filter(x=>x==='index.json').length, metaJson:reqs.filter(x=>x==='meta.json').length};

await br.close();console.log(JSON.stringify(out,null,1));
