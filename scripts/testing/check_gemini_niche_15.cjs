/* 15 real Gemini requests. The exact captured answer is replayed to /m/ to compare both clients.
   Actual /api/route and rendering are checked in each view. No application code/settings are changed.
   Requires a fresh backend on 8019, Playwright, Chrome, macOS say and ffmpeg (two audio cases).
   Outputs a generated JSON artifact under a unique temporary directory. */
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const cases = require('./gemini_niche_15.json');
const base = process.env.GEMINI_TEST_URL || 'http://127.0.0.1:8019';
const origin = new URL(base).origin;
const artifacts = fs.mkdtempSync(path.join(os.tmpdir(), 'bezna-niche-15-'));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const results = [];
const nowRo = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Europe/Bucharest',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date()).replace(' ', 'T');
const tomorrow = () => new Date(Date.parse(nowRo().slice(0, 10) + 'T12:00:00Z') + 86400000).toISOString().slice(0, 10);

const places = JSON.parse(execFileSync('.venv/bin/python', ['-c', "import gzip,json; print(json.dumps(json.load(gzip.open('data/out/city/places.json.gz','rt'))['entries']))"], {encoding:'utf8'}));
const byName = name => places.find(p => p.n === name);
let submitted = [];
async function rateWindow() {
  submitted = submitted.filter(t => Date.now() - t < 61000);
  if (submitted.length >= 6) {
    const ms = 61200 - (Date.now() - submitted[0]);
    console.log(JSON.stringify({stage:'rate_limit_pause',seconds:Math.ceil(ms/1000)}));
    for (let remaining=ms; remaining>0; remaining-=1000) await pause(Math.min(remaining,1000));
    submitted = submitted.filter(t => Date.now() - t < 61000);
  }
  submitted.push(Date.now());
}

async function runView(browser, c, replay, audio) {
  const mobile = replay !== undefined;
  const context = await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},permissions:['geolocation'],geolocation:{latitude:45.7531,longitude:21.2257}});
  const page = await context.newPage();
  const errors=[], issues=[], responses=[];
  const result={view:mobile?'mobile':'desktop',issues,errors};
  page.on('pageerror', e=>errors.push(e.message));
  page.on('response', r=>{if(new URL(r.url()).pathname==='/api/route')responses.push({url:r.url(),status:r.status()});});
  await page.route('**/*', async intercepted=>{
    const request=intercepted.request(),url=new URL(request.url());
    if(url.origin!==origin)return intercepted.abort();
    if(url.pathname==='/api/ask') {
      if(mobile)return intercepted.fulfill({status:replay.status,json:replay.body});
      if(audio){const body=request.postDataJSON();delete body.text;body.audio=audio;body.mime='audio/wav';return intercepted.continue({postData:JSON.stringify(body)});}
    }
    return intercepted.continue();
  });
  try {
    await page.goto(base+(mobile?'/m/':'/')+'?lang='+c.lang);
    if(mobile)await page.evaluate(()=>openSearch('B'));
    await page.locator('#ask-text').waitFor({state:'visible'});
    if(c.initial_from){const p=byName(c.initial_from);await page.evaluate(p=>setPoint('A',[p.lat,p.lon],p.n),p);}
    await page.locator('#ask-text').fill(c.text);
    if(!mobile)await rateWindow();
    const expectedDay=tomorrow();
    const answerPromise=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ask',{timeout:120000});
    const started=Date.now();
    await page.locator('#ask-go').click();
    const answer=await answerPromise,body=await answer.json();
    result.elapsed_s=+( (Date.now()-started)/1000).toFixed(2);
    result.response={status:answer.status(),body};
    await page.waitForFunction(()=>!document.getElementById('ask-go').disabled);
    result.note=await page.locator('#ask-note').innerText();
    if(answer.status()!==200){issues.push('HTTP '+answer.status());return result;}
    if(c.expect==='off_topic'){
      if(body.kind!=='off_topic')issues.push('Expected off_topic, got '+body.kind);
      if(responses.length)issues.push('Non-route request triggered routing');
      return result;
    }
    if(c.expect==='clarification'){
      if(!['clarify','unclear','not_found'].includes(body.kind))issues.push('Unspecified private places: '+body.kind);
      if(responses.length)issues.push('Invented route for unspecified places');
      return result;
    }
    if(body.kind!=='route'){
      result.clarification=true;
      for(const side of ['from','to']){
        if(!(body.missing||[]).includes(side)&&!(body.ambiguity||[]).includes(side))continue;
        const candidate=(body.candidates?.[side]||[]).find(p=>c[side]?.includes(p.name));
        if(!candidate){issues.push('No intended '+side+' candidate: '+JSON.stringify(body.candidates?.[side]||[]));return result;}
        await page.locator('#ask-choices button').filter({hasText:candidate.name}).click();
      }
    }
    await page.waitForFunction(()=>!!plan,{},{timeout:20000}).catch(()=>issues.push('No route plan after A/B'));
    const state=await page.evaluate(()=>({a:A&&[A.lat,A.lng],b:B&&[B.lat,B.lng],labels,mode:plan?.mode,at:plan?.at,meters:plan?.routes?.fastest?.length_m,minutes:plan?.routes?.fastest?.minutes,features:plan?.routes?.fastest?.geometry?.features?.length}));
    result.route=state;
    if(c.from&&!c.from.includes(state.labels.A))issues.push('Wrong A: '+state.labels.A);
    if(c.to&&!c.to.includes(state.labels.B))issues.push('Wrong B: '+state.labels.B);
    if(c.mode&&state.mode!==c.mode)issues.push('Wrong mode: '+state.mode);
    if(c.from_here&&JSON.stringify(state.a)!==JSON.stringify([45.7531,21.2257]))issues.push('Old A used instead of geolocation');
    if(c.tomorrow&&state.at?.slice(0,16)!==expectedDay+' '+c.tomorrow)issues.push('Wrong departure date/time: '+state.at);
    if(!state.features||!(state.meters>0))issues.push('No nonempty route geometry');
    result.routing_responses=responses;
    if(!responses.some(r=>r.status===200))issues.push('No HTTP 200 from /api/route');
    if(!issues.some(s=>s.startsWith('No route plan'))){
      await page.waitForFunction(isMobile=>{
        const visible=e=>e&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden'&&+getComputedStyle(e).opacity>0&&e.getBoundingClientRect().width+e.getBoundingClientRect().height>0;
        return [...document.querySelectorAll(isMobile?'#screen .rcard':'#cards .card')].some(visible)&&routeLayer.getLayers().some(l=>l.getLatLngs&&l.getLatLngs().length>=2&&l._map&&l.options.weight>=5&&visible(l._path||l._renderer?._container));
      },mobile,{timeout:15000}).then(()=>result.visible=true).catch(()=>issues.push('Route/card not visible'));
    }
    if(c.expect==='unsupported_warning'&&!body.unsupported?.length&&!/not supported|cannot guarantee|не поддерж|не могу гарант|nu pot garanta/i.test(result.note))issues.push('Stairs/darkness restrictions silently ignored; no limitation warning');
    if(errors.length)issues.push('Browser JS errors');
    return result;
  }catch(e){issues.push(e.message);return result;}finally{await context.close();}
}

(async()=>{
  console.log(JSON.stringify({stage:'start',artifacts,local_time:nowRo(),cases:cases.length,method:'15 real requests, exact answers replayed to mobile; real routing in both views'}));
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    for(const c of cases){
      let audio;
      if(c.audio){const name=path.join(artifacts,'voice-'+c.id);execFileSync('say',['-v','Milena','-r','205','-o',name+'.aiff',c.text]);execFileSync('ffmpeg',['-nostdin','-loglevel','error','-i',name+'.aiff','-ar','16000','-ac','1','-c:a','pcm_s16le',name+'.wav']);audio=fs.readFileSync(name+'.wav').toString('base64');}
      const desktop=await runView(browser,c,undefined,audio);
      const mobile=desktop.response?await runView(browser,c,desktop.response):{view:'mobile',issues:['No captured response']};
      const entry={...c,desktop,mobile,status:desktop.issues.length||mobile.issues.length?'FAIL':desktop.clarification?'PASS_WITH_CONFIRMATION':'PASS'};
      results.push(entry);
      fs.writeFileSync(path.join(artifacts,'results.json'),JSON.stringify(results,null,2));
      console.log(JSON.stringify({id:c.id,status:entry.status,kind:desktop.response?.body.kind,heard:desktop.response?.body.heard,from:desktop.route?.labels.A,to:desktop.route?.labels.B,mode:desktop.route?.mode,at:desktop.route?.at,meters:desktop.route?.meters,seconds:desktop.elapsed_s,desktop:desktop.issues,mobile:mobile.issues}));
    }
  }finally{await browser.close();}
  console.log(JSON.stringify({stage:'complete',results:path.join(artifacts,'results.json'),pass:results.filter(r=>r.status==='PASS').length,confirmation:results.filter(r=>r.status==='PASS_WITH_CONFIRMATION').length,fail:results.filter(r=>r.status==='FAIL').length}));
})().catch(e=>{console.error(e);process.exitCode=1});
