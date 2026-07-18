import { chromium } from 'playwright';
const B='http://127.0.0.1:8099';
const br=await chromium.launch();const ct=await br.newContext();const p=await ct.newPage();
const out={};

// A11Y-004: skip links present
for(const pg of ['einreichen.html','architektur.html','index.html']){
  await p.goto(`${B}/${pg}`,{waitUntil:'networkidle'});await p.waitForTimeout(300);
  const r=await p.evaluate(()=>{const s=document.querySelector('.skip-link');const target=s?document.querySelector(s.getAttribute('href')):null;return {skip:!!s, href:s?.getAttribute('href'), targetExists:!!target, targetTabindex:target?.getAttribute('tabindex')};});
  out[`skip_${pg}`]=r;
}

// A11Y-002a: architektur tab focus outline
await p.goto(`${B}/architektur.html`,{waitUntil:'networkidle'});await p.waitForTimeout(400);
await p.keyboard.press('Tab');await p.keyboard.press('Tab');await p.keyboard.press('Tab'); // -> first tab
out.archTabFocus=await p.evaluate(()=>{const e=document.activeElement;const s=getComputedStyle(e);return {cls:e.className,tag:e.tagName,outlineStyle:s.outlineStyle,outlineWidth:s.outlineWidth,outlineColor:s.outlineColor};});
await p.keyboard.press('Tab'); // second tab
out.archTab2Focus=await p.evaluate(()=>{const e=document.activeElement;const s=getComputedStyle(e);return {cls:e.className,outlineStyle:s.outlineStyle,outlineWidth:s.outlineWidth};});

// A11Y-002b: einreichen input focus outline
await p.goto(`${B}/einreichen.html`,{waitUntil:'networkidle'});await p.waitForTimeout(300);
await p.focus('#urlInput');
out.inputFocus=await p.evaluate(()=>{const e=document.querySelector('#urlInput');const s=getComputedStyle(e);return {outlineStyle:s.outlineStyle,outlineWidth:s.outlineWidth,outlineColor:s.outlineColor,offset:s.outlineOffset};});

// A11Y-006: aria attributes + submit empty
out.urlAria=await p.evaluate(()=>{const e=document.querySelector('#urlInput');return {ariaRequired:e.getAttribute('aria-required'),ariaDescribedby:e.getAttribute('aria-describedby'),required:e.hasAttribute('required')};});
out.submitEmpty=await p.evaluate(()=>{document.querySelector('#submitBtn').click();const e=document.querySelector('#urlInput');return {ariaInvalid:e.getAttribute('aria-invalid'),ariaDescribedby:e.getAttribute('aria-describedby'),hint:document.querySelector('#submitHint')?.textContent,hintId:document.querySelector('#submitHint')?.id,focused:document.activeElement?.id};});
// then fill valid and re-check reset
await p.fill('#urlInput','https://example.org/report.pdf');
out.submitValidReset=await p.evaluate(()=>{document.querySelector('#submitBtn').click();const e=document.querySelector('#urlInput');return {ariaInvalid:e.getAttribute('aria-invalid'),ariaDescribedby:e.getAttribute('aria-describedby')};});

await br.close();console.log(JSON.stringify(out,null,1));
