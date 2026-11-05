import assert from 'node:assert/strict';import {webcrypto,createHash} from 'node:crypto';import {readFile} from 'node:fs/promises';
import {safeURL,validateManifest,checkedFetch,digest,githubRelease,checkPython} from './releases.mjs';import {RawRepl} from './raw-repl.mjs';
if(!globalThis.crypto)globalThis.crypto=webcrypto;globalThis.location={href:'http://127.0.0.1:8765/install/'};
const payload=new TextEncoder().encode('import M5\nclass StickVarioApp:pass\n');const sha=await digest(payload);
const doc={schema:1,kind:'micropython-app',board:'M5StickS3',version:'test',app:{url:'app.py',bytes:payload.length,sha256:sha}};
const m=validateManifest(doc,location.href);assert.equal(m.app.url,'http://127.0.0.1:8765/install/app.py');assert.match(checkPython(payload),/StickVarioApp/);
for(const patch of [{schema:2},{board:'ESP32'},{app:{...doc.app,bytes:0}},{app:{...doc.app,url:'javascript:alert(1)'}},{app:{...doc.app,sha256:'bad'}}])assert.throws(()=>validateManifest({...doc,...patch},location.href));
assert.throws(()=>safeURL('http://example.com/a'));assert.throws(()=>checkPython(new Uint8Array([0,1])));
await checkedFetch(m.app,async()=>new Response(payload));await assert.rejects(checkedFetch({...m.app,sha256:'0'.repeat(64)},async()=>new Response(payload)),/SHA/);
const flash={schema:1,kind:'esp32-image',board:'M5StickS3',version:'test',flash:{parts:[{url:'full.bin',offset:0,bytes:4096,sha256:sha}]}};assert.equal(validateManifest(flash,location.href).flash.parts.length,1);
assert.throws(()=>validateManifest({...flash,flash:{parts:[...flash.flash.parts,{url:'bad.bin',offset:0,bytes:1,sha256:sha}]}},location.href),/sovrapposte/);
assert.throws(()=>validateManifest({...flash,flash:{parts:[{url:'bad.bin',offset:1,bytes:1,sha256:sha}]}},location.href));
const gh=await githubRelease('owner/repo','v0.5',async url=>{assert.match(url,/releases\/tags\/v0.5/);return new Response(JSON.stringify({tag_name:'v0.5',html_url:'https://github.com/owner/repo/releases/tag/v0.5',assets:[{name:'stick-vario.release.json',browser_download_url:'https://github.com/owner/repo/releases/download/v0.5/stick-vario.release.json'}]}));});assert.equal(gh.tag,'v0.5');await assert.rejects(githubRelease('../bad repo'),/Repository/);

class FakeWire{
  constructor(paste=true){this.buffer=[];this.paste=paste;this.mode='idle';this.commands=[];this.file=[];this.installed=false;}
  push(b){this.buffer.push(...(typeof b==='string'?new TextEncoder().encode(b):b));}
  async read(n){if(this.buffer.length<n)throw Error('test underrun '+n);return new Uint8Array(this.buffer.splice(0,n));}
  async until(marker){const out=[];while(this.buffer.length){out.push(this.buffer.shift());if(out.length>=marker.length&&marker.every((b,i)=>out[out.length-marker.length+i]===b))return new Uint8Array(out);}throw Error('test marker missing '+marker);}
  async write(bytes){if(typeof bytes==='string')bytes=new TextEncoder().encode(bytes);const a=[...bytes];
    if(a.join()==='13,3,3')return;
    if(a.join()==='13,1'){this.push('raw REPL; CTRL-B to exit\r\n>');return;}
    if(a.join()==='13,2')return;
    if(a.join()==='5,65,1'){this.mode='code';this.code=[];this.push(this.paste?[82,1,32,0,1]:[82,0]);return;}
    if(this.mode==='code'){
      if(a.length===1&&a[0]===4){
        const code=new TextDecoder().decode(new Uint8Array(this.code));this.commands.push(code);this.push(this.paste?[4]:'OK');this.mode='idle';let out='',err='';
        if(code.includes("print('SV_BOOT '"))out='SV_BOOT '+JSON.stringify({boot_option:1,main_exists:true,main_owned:false,app_exists:true,restore_available:false})+'\n';
        if(code.includes('SV_PROBE '))out='SV_PROBE '+JSON.stringify({machine:'M5StickS3 with ESP32S3',speaker:true,viper:true,viper_attribute:false,board:26,runtime:'test'})+'\n';
        if(code.startsWith('raise ValueError'))err='ValueError: EXPECTED';
        if(code.includes("_sv_file=open"))this.file=[];
        const match=/_sv_file\.write\(binascii.a2b_base64\('([^']+)'\)\)/.exec(code);if(match)this.file.push(Buffer.from(match[1],'base64'));
        if(code.includes('SV_HASH '))out='SV_HASH '+(this.badHash?'bad':createHash('sha256').update(Buffer.concat(this.file)).digest('hex'))+'\n';
        if(code.includes('SV_INSTALLED')){this.installed=true;out='SV_INSTALLED\n';}
        if(code.includes('LONG_RUNNING')||code.startsWith("exec(open('/flash/stick_vario_app.py')")){this.push('I,BOOT,test\nI,READY,ble=1,audio=1,profile=KALMAN,raw=0\n');return;}
        this.push(out);this.push([4]);this.push(err);this.push([4,62]);return;
      }
      this.code.push(...a);if(this.paste)this.push([1]);return;
    }
    throw Error('unexpected test write '+a);
  }
}
for(const paste of [true,false]){
  const wire=new FakeWire(paste),repl=new RawRepl(wire);await repl.enter();const info=await repl.probe();assert.ok(info.speaker&&info.viper);assert.equal(info.viper_attribute,false);assert.equal((await repl.bootControl()).boot_option,1);
  await assert.rejects(repl.exec("raise ValueError('EXPECTED')"),/EXPECTED/);await repl.exec('print(123)');
  await repl.installFile(payload,sha);assert.equal(wire.installed,true);assert.deepEqual(Buffer.concat(wire.file),Buffer.from(payload));
  assert.ok(!wire.commands.some(c=>c.includes("open('/flash/main.py")||c.includes("open('/flash/boot.py")));
  const lines=await repl.runRAM('LONG_RUNNING');assert.match(lines.at(-1),/I,READY/);await repl.leave();
}
const bad=new FakeWire();const repl=new RawRepl(bad);await repl.enter();bad.badHash=true;await assert.rejects(repl.installFile(payload,sha),/SHA/);assert.equal(bad.installed,false);
const release=JSON.parse(await readFile(new URL('./firmware/stick-vario.release.json',import.meta.url)));const actual=await readFile(new URL('./firmware/stick_vario_ram.py',import.meta.url));assert.equal(await digest(actual),release.app.sha256);assert.equal(actual.length,release.app.bytes);
console.log('PASS manifests, GitHub release lookup, integrity, flash offsets, raw-paste/fallback, probe, app file install, SHA failure, RAM start; system flash never invoked');
