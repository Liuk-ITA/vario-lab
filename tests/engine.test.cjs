'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
vm.runInThisContext(fs.readFileSync(path.join(root,'engine.js'),'utf8'));
global.window={};vm.runInThisContext(fs.readFileSync(path.join(root,'data/demo.js'),'utf8'));
const V=global.Vario,ds=V.demo(window.VARIO_DEMO),expected=JSON.parse(fs.readFileSync(path.join(__dirname,'python-reference.json'),'utf8'));
const out=V.run(ds.samples.slice(0,1000));let max=0,checked=0;
for(let i=0;i<expected.length;i++)for(const [js,py] of [['lp','v_lowpass_mps'],['reg','v_regression_mps'],['kal','v_kalman_mps'],['z','relative_height_m'],['reference','reference_pa'],['tFilter','sample_time_nominal_s']]){
 const a=out[i][js],b=expected[i][py];if(b===null)assert.equal(a,null,`${i} ${js}`);else{const err=Math.abs(a-b);max=Math.max(max,err);assert.ok(err<1e-8,`${i} ${js}: ${a} != ${b}`);}checked++;
}
assert.equal(ds.samples.length,12610);assert.equal(ds.events.length,21);assert.equal(V.height(100000,100000),0);
assert.ok(V.height(99900,100000)>8);assert.ok(V.height(99900,100000)<9);
const prefix=V.run(ds.samples.slice(0,700));assert.deepEqual(prefix,out.slice(0,700));
const missing=ds.samples.slice(0,500).filter((_,i)=>i!==420);assert.equal(V.run(missing).at(-1).segment,1);
const rx=V.run([{seq:1,tReceive:1,pressure:100000},{seq:2,tReceive:1,pressure:100000}],{basis:'receive'});assert.equal(rx[1].segment,1);
const nod=V.run([{seq:1,pressure:100000}],{basis:'device'});assert.equal(nod[0].invalidTime,true);
const vv=V.run(Array.from({length:300},(_,i)=>({seq:i+1,velocity:.7,tDevice:i/80})),{kind:'velocity'});assert.equal(vv.at(-1).lp,.7);assert.equal(vv.at(-1).reg,null);assert.equal(vv.at(-1).kal,null);
const sentence=body=>'$'+body+'*'+V.checksum(body);
let r=V.parseLine(sentence('LK8EX1,100000,99999,150,20,4.1,'),7,0).sample;
assert.equal(r.pressure,100000);assert.equal(r.altitude,null);assert.equal(r.velocity,1.5);assert.equal(r.tDevice,null);
assert.throws(()=>V.parseLine('$LK8EX1,100000,99999,150,20,4.1,*00'));
r=V.parseLine('$XCTRC,2015,8,11,10,56,23,80,48.62825,8.104885,129.4,0.01,322.76,-0.05,,,,997.79,77*66',0,0).sample;
assert.equal(r.pressure,99779);assert.equal(r.velocity,-.05);assert.equal(r.altitude,129.4);assert.ok(r.tDevice>1e9);
assert.equal(V.parseLine('PRS 186A0',0).sample.pressure,100000);assert.equal(V.parseLine('_PRS 186A0',0).sample.upstream,'filtered');
const lines=[];let decoder=new V.LineDecoder(line=>lines.push(line));decoder.push('S,1,10,100000,20,16,4,80,F');decoder.push('IFO\r\r\nM,1,10,BASSO,0,1,0,ARM\n');assert.equal(lines.length,2);
assert.equal(V.parseLine(lines[1]).event.phase,'BASSO');assert.equal(V.parseLine('F,1,4,1000').batch.n,4);
const csv='seq,device_estimated_ms,pressure_pa,host_receive_monotonic_s\r\n1,1000,100000,20\r\n2,1013,100001,20.001\r\n';
const imported=V.parseCSV(csv);assert.equal(imported.samples[0].tDevice,1);assert.equal(imported.samples[1].tReceive,20.001);
const roundtrip=V.parseCSV(V.csvExport(ds.samples.slice(0,50)));
for(let i=0;i<50;i++){assert.equal(roundtrip.samples[i].pressure,ds.samples[i].pressure);assert.equal(roundtrip.samples[i].tDevice,ds.samples[i].tDevice);assert.equal(roundtrip.samples[i].tReceive,ds.samples[i].tReceive);assert.equal(roundtrip.samples[i].tBatch,ds.samples[i].tBatch);}
assert.deepEqual(V.csvRows('a,b\n"one,two","quote""x"\n'),[['a','b'],['one,two','quote"x']]);assert.throws(()=>V.csvRows('a\n"broken'));
assert.equal(V.audioState(null).mode,'silent');assert.equal(V.audioState(.2).mode,'climb');assert.equal(V.audioState(-1).mode,'sink');assert.equal(V.audioState(0).mode,'silent');
assert.equal(V.audioState(.08,{preset:'soft'},true).mode,'climb');assert.equal(V.audioState(.08,{preset:'classic'},true).mode,'silent');

r=V.parseLine(sentence('VARIO,1013.25,,'),7).sample;
assert.equal(r.pressure,101325);assert.equal(r.velocity,null);assert.equal(r.tDevice,null);assert.equal(r.tReceive,7);
assert.equal(V.parseLine(sentence('VARIO,1000,-1.25,')).sample.velocity,-1.25);
assert.throws(()=>V.parseLine(sentence('VARIO,101325,,')));
assert.throws(()=>V.parseLine('$VARIO,1013.25,,*00'));
assert.equal(V.parseLine('$XCTOD,1,99').type,'diagnostic');
assert.equal(V.parseLine(sentence('LK8EX1,101325,9,9999,99,999,')).sample.temperature,null);
console.log(JSON.stringify({status:'PASS',python_comparisons:checked,max_abs_error:max,demo_samples:ds.samples.length,checks:['causality','gaps','duplicate receive clock','missing timestamps','velocity-only semantics','NMEA checksums/units','XCTRC UTC','PRS','fragmented lines','CSV round-trip','audio gate/hysteresis']},null,2));
