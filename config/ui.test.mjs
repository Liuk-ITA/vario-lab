import assert from 'node:assert/strict';
import {DEFAULTS,UUID} from './protocol.mjs';
class Element{
  constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.style={};this.value='';this.checked=false;this.disabled=false;this.events={};this.classList={toggle(){}};this.textContent='';}
  get value(){return this._value??'';}
  set value(v){this._value=String(v);}
  append(...items){for(const child of items)if(typeof child!=='string'){child.parent=this;this.children.push(child);}}
  replaceChildren(...items){this.children=[];this.append(...items);}
  querySelector(selector){return this.all().find(x=>x.tag===selector);}
  all(){return this.children.flatMap(c=>[c,...c.all()]);}
  addEventListener(event,handler){(this.events[event]??=[]).push(handler);}
  async fire(event){for(const fn of this.events[event]||[])await fn({target:this});await new Promise(r=>setTimeout(r,0));}
  get previousElementSibling(){return this.parent?.children[this.parent.children.indexOf(this)-1]||null;}
  get nextElementSibling(){return this.parent?.children[this.parent.children.indexOf(this)+1]||null;}
  insertBefore(item,reference){if(item.parent){const i=item.parent.children.indexOf(item);item.parent.children.splice(i,1);}this.children.splice(this.children.indexOf(reference),0,item);item.parent=this;}
}
const nodes=new Map();const ids=['state','notice','device','changes','support','cycle-frequency','cycle-pattern','filters','sounds','patterns','base-notes','remote-hid','grove-buttons','volumes','custom-volume','base','pattern','climb_on','climb_off','sink_on','sink_off','usb','ble','disconnect','apply','reset','read','save'];for(const id of ids)nodes.set(id,new Element());
globalThis.document={getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),createTextNode:t=>Object.assign(new Element('#text'),{textContent:t}),querySelectorAll:selector=>[...nodes.values()].flatMap(x=>x.all()).filter(x=>selector==='[data-preview]'?x.dataset.preview!==undefined:x.dataset.volume!==undefined&&x.checked)};
let current=structuredClone(DEFAULTS),saved=false,previews=[],writes=[],pendingRead=null,rxQueue=[],bleNotify=null,bleLine='';
function reply(request){writes.push(request);if(request.op==='set'){current=structuredClone(request.config);saved=false;}if(request.op==='reset'){current=structuredClone(DEFAULTS);saved=false;}if(request.op==='save')saved=true;if(request.op==='preview')previews.push(request.sound);return {v:1,id:request.id,ok:true,config:current,saved,firmware:'test-fixture'};}
function pushUSB(bytes){if(pendingRead){const resolve=pendingRead;pendingRead=null;resolve({value:bytes,done:false});}else rxQueue.push(bytes);}
const reader={async read(){if(rxQueue.length)return {value:rxQueue.shift(),done:false};return new Promise(r=>pendingRead=r);},releaseLock(){},async cancel(){if(pendingRead){pendingRead({done:true});pendingRead=null;}}};
const port={async open(){},async setSignals(v){assert.equal(v.dataTerminalReady,false);},async close(){},readable:{getReader:()=>reader},writable:{getWriter:()=>({async write(bytes){const text=new TextDecoder().decode(bytes);assert.ok(text.startsWith('@CFG '));const r=reply(JSON.parse(text.slice(5)));const data=Buffer.from(JSON.stringify(r)).toString('base64'),chunks=data.match(/.{1,64}/g);const all=chunks.map((c,i)=>`@CF1 ${r.id}:${i}:${chunks.length}:${c}\n`).join('');const b=new TextEncoder().encode(all);for(let i=0;i<b.length;i+=13)pushUSB(b.slice(i,i+13));},releaseLock(){}})}};
let disconnectBLE=null;
const tx={addEventListener(e,f){bleNotify=f;},async startNotifications(){}};
const rx={async writeValueWithResponse(bytes){
  assert.ok(bytes.length<=18);bleLine+=new TextDecoder().decode(bytes);
  if(bleLine.endsWith('\n')){
    const r=reply(JSON.parse(bleLine));bleLine='';
    const data=new TextEncoder().encode(JSON.stringify(r)+'\n');
    for(let i=0;i<data.length;i+=20){const part=data.slice(i,i+20);bleNotify({target:{value:new DataView(part.buffer)}});}
  }
}};
const service={async getCharacteristic(uuid){return uuid===UUID.tx?tx:rx;}};
const device={name:'StickVario',addEventListener(e,f){disconnectBLE=f;},gatt:{
  connected:false,
  async connect(){this.connected=true;return {async getPrimaryService(uuid){assert.equal(uuid,UUID.service);return service;}};},
  disconnect(){this.connected=false;disconnectBLE?.();}
}};
Object.defineProperty(globalThis,'navigator',{value:{serial:{requestPort:async()=>port},bluetooth:{requestDevice:async()=>device}},configurable:true});
await import('./app.js');const $=id=>nodes.get(id);
assert.equal($('save').disabled,true);await $('usb').fire('click');assert.equal($('state').textContent,'● Collegato');assert.equal($('filters').children.length,5);
$('filters').children[1].querySelector('input').checked=false;await $('filters').children[1].querySelector('input').fire('change');assert.equal($('save').disabled,true);
await $('apply').fire('click');assert.ok(!current.filters.includes('reg'));assert.equal($('save').disabled,false);
const before=JSON.stringify(current.sounds);await $('sounds').children[2].children.at(-1).fire('click');assert.equal(previews.at(-1),'dispari');assert.equal(JSON.stringify(current.sounds),before);
await $('save').fire('click');assert.equal(saved,true);assert.match($('changes').textContent,/salvata/);
const count=writes.length;for(const row of $('filters').children)row.querySelector('input').checked=false;await $('apply').fire('click');assert.equal(writes.length,count);assert.match($('notice').textContent,/almeno/);
await $('read').fire('click');await $('reset').fire('click');assert.deepEqual(current,DEFAULTS);assert.equal(saved,false);
$('base-notes').value='1500, 2000';await $('cycle-frequency').fire('click');assert.equal(current.base_hz,2000);
await $('cycle-frequency').fire('click');assert.equal(current.base_hz,1500);
await $('cycle-pattern').fire('click');assert.equal(current.pattern,'continuous');
$('remote-hid').checked=true;await $('apply').fire('click');assert.equal(current.remote_hid,true);
await $('disconnect').fire('click');assert.equal($('state').textContent,'● Scollegato');
await $('ble').fire('click');assert.equal($('state').textContent,'● Collegato');await $('read').fire('click');await $('disconnect').fire('click');
console.log('PASS simulated DOM + USB/BLE: load, edit, apply, preview, explicit save, invalid form, reset, disconnect');
