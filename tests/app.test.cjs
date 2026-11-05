'use strict';
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
class Element extends EventTarget{
 constructor(id,attrs=''){super();this.id=id;this.attrs=attrs;this._value='';this.checked=/\bchecked\b/.test(attrs);this.disabled=/\bdisabled\b/.test(attrs);this.hidden=/\bhidden\b/.test(attrs);this.dataset={};this.options=[];this.textContent='';this.innerHTML='';this.clientWidth=800;this.clientHeight=id==='height-chart'?115:235;this.classes=new Set();this.classList={toggle:(x,v)=>v?this.classes.add(x):this.classes.delete(x)};}
 get value(){return this._value;}set value(v){this._value=String(v);}
 setAttribute(k,v){this[k]=v;}getAttribute(k){return this[k];}
 getContext(){return new Proxy({},{get:(_,key)=>()=>{}});}scrollIntoView(){}showModal(){this.open=true;}close(){this.open=false;}
 click(){return this.onclick?.({target:this});}
}
const els=new Map(),dataElements=[];
for(const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/gi)){
 const attrs=match[2],id=attrs.match(/\bid="([^"]+)"/)?.[1];const el=new Element(id,attrs);el.value=attrs.match(/\bvalue="([^"]*)"/)?.[1]??'';
 for(const d of attrs.matchAll(/data-([\w-]+)="([^"]*)"/g))el.dataset[d[1]]=d[2];
 if(id)els.set(id,el);if(Object.keys(el.dataset).length)dataElements.push(el);
}
for(const match of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/gi)){
 const id=match[1].match(/id="([^"]+)"/)[1],el=els.get(id);el.options=[...match[2].matchAll(/<option\b([^>]*)>([^<]*)<\/option>/g)].map(m=>({value:m[1].match(/value="([^"]*)"/)?.[1]??m[2],disabled:false,selected:m[1].includes('selected')}));el.value=(el.options.find(o=>o.selected)||el.options[0]).value;
}
global.window=globalThis;global.document={getElementById:id=>{return els.get(id)||null;},querySelectorAll:q=>{const key=q.match(/\[data-([\w-]+)\]/)?.[1];return dataElements.filter(x=>key in x.dataset);},createElement:()=>new Element('download'),addEventListener(){},hidden:false};
global.addEventListener=()=>{};global.scrollTo=()=>{};global.devicePixelRatio=1;global.isSecureContext=true;let frame;global.requestAnimationFrame=fn=>{frame=fn;};
class MockPort{
 constructor(){this.queue=[];this.waiter=null;const p=this;this.r={read:()=>new Promise(resolve=>{if(p.queue.length)resolve({value:p.queue.shift(),done:false});else p.waiter=resolve;}),cancel:async()=>{p.waiter?.({done:true});p.waiter=null;},releaseLock(){}};this.readable={getReader:()=>this.r};this.writable={getWriter:()=>({write:async bytes=>{this.tx=new TextDecoder().decode(bytes);},releaseLock(){}})};}
 async open(o){this.config=o;}async close(){this.closed=true;}async setSignals(s){this.signals=s;}
 push(text){const value=new TextEncoder().encode(text);if(this.waiter){this.waiter({value,done:false});this.waiter=null;}else this.queue.push(value);}
}
const port=new MockPort();Object.defineProperty(global,'navigator',{value:{serial:{requestPort:async()=>port}},configurable:true});
const fakeGain={value:0,setTargetAtTime(v){this.value=v;}};
global.AudioContext=class{constructor(){this.currentTime=0;this.destination={};}createOscillator(){return {type:'',frequency:{setTargetAtTime(){}},connect(){},start(){}};}createGain(){return {gain:fakeGain,connect(){}};}async resume(){}};
vm.runInThisContext(fs.readFileSync(path.join(root,'engine.js'),'utf8'));vm.runInThisContext(fs.readFileSync(path.join(root,'data/demo.js'),'utf8'));vm.runInThisContext(fs.readFileSync(path.join(root,'app.js'),'utf8'));
const ui=id=>els.get(id),app=global.VarioApp,delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 assert.equal(app.state.results.length,12610);app.render();assert.ok(ui('speed-value').innerHTML.includes('m/s'));assert.equal(ui('phase-value').textContent,'SALITA');
 ui('play').onclick();assert.equal(app.state.playing,true);frame(performance.now()+100);ui('play').onclick();assert.equal(app.state.playing,false);
 ui('seek').value='500';ui('seek').oninput();assert.ok(app.state.pos>70&&app.state.pos<90);
 ui('tau-height').value='.4';ui('tau-height').dispatchEvent(new Event('input'));await delay(130);assert.equal(app.state.settings.tauHeight,.4);
 ui('time-basis').value='receive';await ui('time-basis').onchange();assert.equal(app.state.basis,'receive');
 ui('reset-settings').onclick();assert.equal(app.state.basis,'nominal');
 const csv='seq,device_estimated_ms,pressure_pa,host_receive_monotonic_s\n1,0,100000,10\n2,13,100001,10.001\n3,25,100000,10.002\n';
 await app.importFiles([{name:'my-test.csv',size:csv.length,text:async()=>csv}]);assert.equal(app.state.dataset.samples.length,3);assert.equal(ui('dataset-name').textContent,'my-test.csv');
 const saved={...app.session(),experiment:{settings:{...Vario.defaults,tauHeight:.33},basis:'receive',kind:'pressure',hz:70,audio:{source:'lp',preset:'soft',climb:.2,sink:-1}}};
 const j=JSON.stringify(saved);await app.importFiles([{name:'session.json',size:j.length,text:async()=>j}]);assert.equal(app.state.hz,70);assert.equal(app.state.basis,'receive');assert.equal(app.state.settings.tauHeight,.33);assert.equal(ui('audio-preset').value,'soft');
 await app.mode('live');assert.equal(ui('connection-panel').hidden,false);await ui('usb').onclick();assert.equal(app.state.connected,true);assert.deepEqual(port.signals,{dataTerminalReady:false,requestToSend:false});
 const block=(start)=>'F,'+start+',4,'+(1000+start*12.5)+'\n'+Array.from({length:4},(_,i)=>`S,${start+i},${1000+(start+i)*12.5},100000,20,16,4,80,FIFO\n`).join('');
 port.push('M,1,1000,BASSO,0,0,0,ARM\n'+block(1));await delay(10);assert.equal(app.state.dataset.samples.length,4);assert.equal(app.state.dataset.events.length,1);
 await ui('record').onclick();assert.equal(app.state.recording,true);port.push(block(5));await delay(10);assert.equal(app.state.recorded.samples.length,4);
 await ui('record').onclick();assert.equal(app.state.connected,false);assert.equal(app.state.mode,'replay');assert.equal(app.state.dataset.samples.length,4);assert.equal(port.closed,true);
 await ui('demo').onclick();ui('audio-preset').value='continuous';await ui('audio-toggle').onclick();assert.equal(app.state.audio,true);ui('play').onclick();frame(performance.now()+20);assert.ok(fakeGain.value>=0);ui('play').onclick();assert.equal(fakeGain.value,0);
 await ui('audio-toggle').onclick();assert.equal(app.state.audio,false);
 ui('lab-profile').value='rc';ui('lab-profile').onchange();assert.equal(ui('audio-source').value,'dual');ui('next-profile').onclick();assert.equal(ui('audio-source').value,'sky');assert.equal(ui('lab-profile').value,'sky');assert.equal(ui('audio-preset').value,'curves');assert.equal(app.session().experiment.profileChanges.at(-1).profile,'sky');assert.ok(app.state.results.some(r=>Vario.finite(r.sky)));for(let i=0;i<12;i++){ui('next-profile').onclick();assert.notEqual(ui('lab-profile').value,'mini');}


 ui('audio-tone-scale').value='1.8';ui('audio-pause-scale').value='.6';ui('audio-hysteresis').checked=true;ui('audio-weak').checked=true;
 const newSession=JSON.stringify(app.session());ui('audio-tone-scale').value='1';ui('audio-pause-scale').value='1';ui('audio-hysteresis').checked=false;ui('audio-weak').checked=false;
 await app.importFiles([{name:'new-session.json',size:newSession.length,text:async()=>newSession}]);assert.equal(Number(ui('audio-tone-scale').value),1.8);assert.equal(Number(ui('audio-pause-scale').value),.6);assert.equal(ui('audio-hysteresis').checked,true);assert.equal(ui('audio-weak').checked,true);

 ui('lab-profile').value='dualmean';ui('lab-profile').onchange();assert.equal(ui('audio-preset').value,'dualmean');assert.equal(app.state.slowAudio.length,app.state.results.length);assert.ok(app.state.slowAudio.some(Vario.finite));
 const meanBefore=app.state.slowAudio[500];ui('seek').value='700';ui('seek').oninput();assert.equal(app.state.slowAudio[500],meanBefore);
 ui('audio-slow-tau').value='2.4';ui('audio-slow-tau').onchange();ui('audio-dual-duty').value='65';ui('audio-dual-split').value='35';const dualSession=JSON.stringify(app.session());
 ui('audio-slow-tau').value='1';ui('audio-dual-duty').value='50';ui('audio-dual-split').value='50';await app.importFiles([{name:'dual.json',size:dualSession.length,text:async()=>dualSession}]);assert.equal(Number(ui('audio-slow-tau').value),2.4);assert.equal(Number(ui('audio-dual-duty').value),65);assert.equal(Number(ui('audio-dual-split').value),35);

 class Characteristic extends EventTarget{async startNotifications(){return this;}emit(value){this.value=value;this.dispatchEvent(new Event('characteristicvaluechanged'));}}
 const ch=new Characteristic(),dev=new EventTarget();let requestedService,requestedCharacteristic;
 dev.name='Mock ESS';dev.gatt={connected:false,connect:async()=>{dev.gatt.connected=true;return {getPrimaryService:async id=>{requestedService=id;return {getCharacteristic:async c=>{requestedCharacteristic=c;return ch;}};}};},disconnect:()=>{dev.gatt.connected=false;dev.dispatchEvent(new Event('gattserverdisconnected'));}};
 navigator.bluetooth={requestDevice:async()=>dev};ui('ble-profile').value='ess';await app.mode('live');await ui('ble').onclick();
 const buffer=new ArrayBuffer(4),view=new DataView(buffer);view.setUint32(0,1000000,true);ch.emit(view);assert.equal(requestedService,0x181a);assert.equal(requestedCharacteristic,0x2a6d);assert.equal(app.state.dataset.samples[0].pressure,100000);
 await app.disconnect();assert.equal(app.state.connected,false);assert.equal(dev.gatt.connected,false);
 ui('ble-profile').value='xctrack';ui('ble-profile').onchange();dev.name='XCTRACK_BLE';await ui('ble').onclick();
 assert.equal(requestedService,'6e400001-b5a3-f393-e0a9-e50e24dcca9e');assert.equal(requestedCharacteristic,'6e400003-b5a3-f393-e0a9-e50e24dcca9e');
 const nmeaBody='VARIO,1013.25,,',wire='$'+nmeaBody+'*'+Vario.checksum(nmeaBody)+'\r\n';
 for(const fragment of [wire.slice(0,12),wire.slice(12)]){const bytes=new TextEncoder().encode(fragment);ch.emit(new DataView(bytes.buffer));}
 assert.equal(app.state.dataset.samples.length,1);assert.equal(app.state.dataset.samples[0].pressure,101325);assert.equal(app.state.upstream,'filtered');assert.equal(app.state.basis,'receive');
 await app.disconnect();
 console.log(JSON.stringify({status:'PASS',environment:'DOM/USB/Audio API doubles, NOT real browser hardware',checks:['demo render hooks','play/pause/seek','filter slider','time base','CSV import','JSON settings restore','dual mean profile, seek invariance and JSON settings round-trip','new audio settings JSON round-trip','profile cycle without MiniVario','SkyBean scalar output','mode switch','USB fragmented data','record stop/replay','audio explicit consent/mute','BLE ESS notification units and disconnect','XCTRACK NUS fragmented VARIO pressure and receive clock']},null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
