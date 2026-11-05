import assert from 'node:assert/strict';
import {Client,LineDecoder,DEFAULTS,validate} from './protocol.mjs';
assert.equal(validate(structuredClone(DEFAULTS)).base_hz,1500);
for(const patch of [{filters:[]},{sounds:['unknown']},{volumes:[0,110,64]},{climb_off:.2},{sink_off:-1},{base_hz:NaN},{patterns:[]},{base_notes:[1500,1500]},{remote_hid:1}])assert.throws(()=>validate({...structuredClone(DEFAULTS),...patch}));
let emitted=[];const decoder=new LineDecoder(x=>emitted.push(x));const bytes=new TextEncoder().encode('@CFG {"id":1,"text":"città"}\nI,STAT,42\n');for(const byte of bytes)decoder.push(new Uint8Array([byte]));assert.deepEqual(emitted,['@CFG {"id":1,"text":"città"}','I,STAT,42']);
let sent=[];const c=new Client(async line=>sent.push(JSON.parse(line)),1000);
const a=c.request('get'),b=c.request('preview',{sound:'dolce'});await new Promise(r=>setTimeout(r,0));assert.equal(sent.length,2);
c.receive('@CFG '+JSON.stringify({v:1,id:sent[1].id,ok:true}));c.receive(JSON.stringify({v:1,id:sent[0].id,ok:true}));await Promise.all([a,b]);assert.equal(c.pending.size,0);
const rejected=c.request('set');await new Promise(r=>setTimeout(r,0));c.receive(JSON.stringify({v:1,id:sent.at(-1).id,ok:false,error:'invalid'}));await assert.rejects(rejected,/invalid/);
const framed=c.request('get');await new Promise(r=>setTimeout(r,0));const id=sent.at(-1).id;const data=Buffer.from(JSON.stringify({v:1,id,ok:true,config:DEFAULTS})).toString('base64');const chunks=data.match(/.{1,64}/g);for(let i=chunks.length-1;i>=0;i--)c.receive(`@CF1 ${id}:${i}:${chunks.length}:${chunks[i]}`);assert.deepEqual((await framed).config,DEFAULTS);
const pending=c.request('get');c.close();await assert.rejects(pending,/scollegato/);
const timeout=new Client(async()=>{},5);await assert.rejects(timeout.request('get'),/non risponde/);
console.log('PASS protocol validation, fragmented UTF8, IDs, errors, disconnect, timeout');

const old=structuredClone(DEFAULTS);delete old.base_notes;delete old.patterns;delete old.remote_hid;old.base_hz=1700;assert.equal(validate(old).base_hz,1700);assert.equal(old.remote_hid,false);
