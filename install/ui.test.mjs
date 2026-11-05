import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';import {webcrypto} from 'node:crypto';
if(!globalThis.crypto)globalThis.crypto=webcrypto;
class El{
  constructor(){this.value='';this.textContent='';this.events={};this.children=[];this.hidden=false;this.disabled=false;this.checked=false;this.files=[];this.classList={toggle(){}};}
  addEventListener(e,f){(this.events[e]??=[]).push(f);}
  append(...x){this.children.push(...x);}
  replaceChildren(...x){this.children=[...x];}
  async fire(e){for(const fn of this.events[e]||[])await fn({target:this});}
}
const ids=['state','notice','log','source','prepare','connect','disconnect','ram','install','run-installed','flash-prepare','flash-confirm','flash-mount','app-actions','flash-actions','github-fields','url-fields','file-fields','release','download','repo','tag','files','manifest-url','progress','device','autorun','boot-state','boot-mode','boot-read','boot-apply','boot-enable','boot-restore'];
const nodes=Object.fromEntries(ids.map(id=>[id,new El()]));nodes.source.value='bundled';nodes.tag.value='latest';
globalThis.document={getElementById:id=>nodes[id],createElement:()=>new El()};globalThis.location={href:'http://127.0.0.1:8765/install/'};
Object.defineProperty(globalThis,'navigator',{value:{serial:{async requestPort(){throw Error('Cancelled test chooser');}}},configurable:true});
const realManifest=JSON.parse(await readFile(new URL('./firmware/stick-vario.release.json',import.meta.url),'utf8'));const realApp=await readFile(new URL('./firmware/stick_vario_ram.py',import.meta.url));
globalThis.fetch=async url=>{
  if(String(url).endsWith('stick-vario.release.json'))return new Response(JSON.stringify(realManifest));
  if(String(url).endsWith('stick_vario_ram.py'))return new Response(realApp);
  if(String(url).includes('invalid'))return new Response('{"schema":2}');
  return new Response('',{status:404});
};
await import('./app.js');assert.equal(nodes.ram.disabled,true);await nodes.prepare.fire('click');assert.equal(nodes.connect.disabled,false);assert.equal(nodes.download.hidden,false);assert.match(nodes.release.textContent,/MicroPython/);
await nodes.connect.fire('click');assert.match(nodes.notice.textContent,/Cancelled/);assert.equal(nodes.install.disabled,true);
nodes.source.value='url';await nodes.source.fire('change');nodes['manifest-url'].value='https://example.com/invalid';await nodes.prepare.fire('click');assert.equal(nodes.ram.disabled,true);assert.match(nodes.notice.textContent,/Manifest/);
nodes.source.value='file';await nodes.source.fire('change');const payload=new TextEncoder().encode('import M5\nclass StickVarioApp:pass\n');nodes.files.files=[{name:'local.py',size:payload.length,arrayBuffer:async()=>payload.buffer}];await nodes.prepare.fire('click');assert.equal(nodes.connect.disabled,false);assert.match(nodes.release.textContent,/local.py/);
const flash={schema:1,kind:'esp32-image',board:'M5StickS3',version:'local-image',flash:{parts:[{url:'full.bin',bytes:4096,offset:0,sha256:'0'.repeat(64)}]}};
nodes.files.files=[{name:'image.json',text:async()=>JSON.stringify(flash)}];await nodes.prepare.fire('click');assert.equal(nodes['flash-actions'].hidden,false);assert.equal(nodes['flash-prepare'].disabled,true);assert.equal(nodes.connect.disabled,true);nodes['flash-confirm'].checked=true;await nodes['flash-confirm'].fire('change');assert.equal(nodes['flash-prepare'].disabled,false);
// No click on the flash action: no remote script or system flash is performed.
console.log('PASS installer simulated DOM: bundled/local/invalid sources, chooser cancellation, ROM flash explicit gate; no system flash');
