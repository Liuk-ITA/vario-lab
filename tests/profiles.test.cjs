'use strict';
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');vm.runInThisContext(fs.readFileSync(path.join(root,'engine.js'),'utf8'));const V=Vario;
for(const hz of [40,80,120]){
 const f=new V.Filters();let r;
 for(let i=0;i<=hz*20;i++)r=f.update(i/hz,2*i/hz);
 assert.ok(Math.abs(r.dual-2)<1e-8,'double EMA ramp gain');assert.ok(Math.abs(r.hybrid-2)<1e-8,'hybrid ramp gain');
}
const f=new V.Filters();for(let i=0;i<1000;i++){const r=f.update(i/80,17);assert.equal(r.dual,0);assert.equal(r.hybrid,0);}
assert.throws(()=>new V.Pipeline({settings:{dualFast:.4,dualSlow:.2}}));
const miniSlow=V.audioState(.5,{preset:'mini'}),miniFast=V.audioState(2,{preset:'mini'});assert.ok(miniFast.hz>miniSlow.hz);assert.ok(miniFast.period<miniSlow.period);
const clock=new V.BeepClock(),a={mode:'climb',period:1,duty:.45};assert.equal(clock.update(0,a),true);clock.update(.2,a);const before=clock.phase;clock.update(.2,{...a,period:.2});assert.equal(clock.phase,before);clock.update(.22,{...a,period:.2});assert.ok(Math.abs(clock.phase-.3)<1e-10);
let Renderer;global.sampleRate=48000;global.AudioWorkletProcessor=class{constructor(){this.port={};}};global.registerProcessor=(name,cls)=>{Renderer=cls;};vm.runInThisContext(fs.readFileSync(path.join(root,'tone-worklet.js'),'utf8'));
const node=new Renderer(),block=new Float32Array(128);const render=()=>node.process([],[[block]]);
node.port.onmessage({data:{enabled:true,mode:'climb',hz:700,period:.5,duty:.45,volume:.08}});
for(let i=0;i<30;i++)render();assert.ok(block.some(x=>Math.abs(x)>.001));const phase=node.beat;
node.port.onmessage({data:{enabled:true,mode:'climb',hz:900,period:.2,duty:.45,volume:.08}});assert.equal(node.beat,phase);
for(let i=0;i<300;i++)render();assert.ok(block.every(x=>Number.isFinite(x)&&Math.abs(x)<1e-8),'stale control mutes worklet');
// Scalar pressure filter: constant pressure, causality, and exact time-window slope.
const scalar=new V.ScalarPressureLag();let scalarV;
for(let i=0;i<1600;i++){scalarV=scalar.update(i/80,100000,100000);if(i>50)assert.equal(scalarV,0);}
const ramp=new V.ScalarPressureLag({skySigma:.00001,skyQ:1});let vr;
for(let i=0;i<1600;i++){const z=i/80,p=100000*Math.pow(1-z*.0065/288.15,9.80665/(287.05287*.0065));vr=ramp.update(i/80,p,100000);}
assert.ok(Math.abs(vr-1)<1e-5);
assert.equal(V.audioState(.08,{preset:'classic'}).mode,'silent');assert.equal(V.audioState(.08,{preset:'classic',hysteresisEnabled:true},true).mode,'climb');assert.equal(V.audioState(.05,{preset:'classic',hysteresisEnabled:true},true).mode,'silent');
const cv=V.audioState(1,{preset:'curves'}),longTone=V.audioState(1,{preset:'curves',toneScale:2}),longPause=V.audioState(1,{preset:'curves',pauseScale:2});
assert.equal(cv.hz,longTone.hz);assert.equal(cv.hz,longPause.hz);assert.ok(longTone.duty>cv.duty);assert.ok(longPause.duty<cv.duty);
assert.equal(V.audioState(0,{preset:'curves'}).mode,'silent');assert.equal(V.audioState(0,{preset:'curves',weak:true}).mode,'weak');
const pair=V.audioState(1,{preset:'pair'});assert.ok(pair.secondHz>pair.hz);assert.ok(V.audioState(-1,{preset:'pair'}).secondHz<V.audioState(-1,{preset:'pair'}).hz);
assert.equal(V.toneAtPhase(pair,.01).on,true);assert.equal(V.toneAtPhase(pair,(pair.toneLength+.02)/pair.period).on,false);assert.equal(V.toneAtPhase(pair,(pair.toneLength+pair.gap+.02)/pair.period).hz,pair.secondHz);
const pairNode=new Renderer();pairNode.port.onmessage({data:{...pair,enabled:true,volume:.08}});
const pairBlock=new Float32Array(1),frames=Math.round((pair.toneLength+pair.gap+.06)*sampleRate);
for(let i=0;i<frames;i++){if(i%960===0)pairNode.port.onmessage({data:{...pair,enabled:true,volume:.08}});pairNode.process([],[[pairBlock]]);assert.ok(Number.isFinite(pairBlock[0]));}
assert.ok(Math.abs(pairNode.frequency-pair.secondHz)<25,'worklet follows second pitch');
const slow=new V.SlowAudio(1.5);slow.update({tFilter:0,segment:0,kal:0},'kal');assert.ok(Math.abs(slow.update({tFilter:1.5,segment:0,kal:1},'kal')-(1-Math.exp(-1)))<1e-12);
assert.equal(slow.update({tFilter:0,segment:1,kal:-1},'kal'),-1);
const ds=V.audioState(1,{preset:'dualmean',slowVelocity:.5}),classic=V.audioState(1);
assert.equal(ds.period,classic.period);assert.equal(classic.duty,.45);assert.equal(ds.duty,.5);assert.equal(ds.splitFraction,.5);assert.equal(ds.hz,730);assert.equal(ds.secondHz,640);
for(let i=0;i<1000;i++){const phase=i/1000,tone=V.toneAtPhase(ds,phase);assert.equal(tone.on,phase<.5);if(phase<.5)assert.equal(tone.hz,phase<.25?730:640);}
const changed=V.audioState(1,{preset:'dualmean',slowVelocity:.5,beepDuty:.7,splitFraction:.3});assert.equal(changed.duty,.7);assert.equal(V.toneAtPhase(changed,.22).hz,640);
assert.equal(V.audioState(-1,{preset:'dualmean',slowVelocity:1}).mode,'sink');
const shortNode=new Renderer();shortNode.port.onmessage({data:{enabled:true,mode:'climb',hz:900,secondHz:600,splitTone:true,splitFraction:.5,period:.02,duty:.5,volume:.08}});
let oldEnv=0;for(let i=0;i<470;i++){shortNode.process([],[[new Float32Array(1)]]);if(i>245)assert.ok(shortNode.envelope>=oldEnv,'no envelope gap between the two halves');oldEnv=shortNode.envelope;}
assert.ok(Math.abs(shortNode.frequency-600)<90);assert.ok(shortNode.envelope>.07);
console.log(JSON.stringify({status:'PASS',checks:['new filters constant/ramp at 40/80/120 Hz','scalar pressure filter/lag','independent audio curves','hysteresis thresholds','weak lift opt-in','paired tones and worklet second pitch','dual mean causal EMA and reset','split beep 45/50 percent duty, pitch and no gap','10ms worklet tone continuity','invalid parameters','beep phase continuity','actual worklet DSP in VM: tone/phase/stale mute'],physical_audio:'not listened automatically'}));
