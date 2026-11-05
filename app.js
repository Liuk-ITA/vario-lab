function drawText(canvas,text,...args){canvas.fillText(window.VarioI18n?window.VarioI18n.t(text):text,...args);}
'use strict';
(() => {
const $=id=>document.getElementById(id),V=Vario,fmt=(n,d=2)=>V.finite(n)?n.toLocaleString(document.documentElement?.lang==='it'?'it-IT':'en-US',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const seconds=t=>{t=Math.max(0,t||0);return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0');};
const S={mode:'replay',dataset:null,results:[],settings:{...V.defaults},kind:'pressure',basis:'nominal',hz:80,upstream:'raw',
  pos:0,playing:false,speed:1,visible:{lp:true,reg:true,kal:true,dual:true,hybrid:false,sky:false},channel:'height',audio:false,connected:false,recording:false,
  raw:[],recorded:null,lastRx:0,invalid:0,diagnostics:[],manualClock:false,manualKind:false,profileChanges:[]};
let slowAudioFilter;
let port,reader,bleDevice,bleCharacteristic,decoder,livePipeline,plotDirty=true,lastFrame=0,lastTick=performance.now(),lastStats=0;
let ctx,osc,gain,toneNode,audioStart=0,climbing=false;const beepClock=new V.BeepClock();
function notify(text,error=false){$('notice').textContent=text;$('notice').hidden=!text;$('notice').classList.toggle('error',error);}
function guard(fn){return async(...a)=>{try{await fn(...a);}catch(e){notify(e.message||String(e),true);console.error(e);}};}
function download(name,data,type='application/json'){
  const a=document.createElement('a'),url=URL.createObjectURL(new Blob([data],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
}
const audioOptions=()=>({preset:$('audio-preset').value,climb:Number($('climb-threshold').value),sink:Number($('sink-threshold').value),hysteresisEnabled:$('audio-hysteresis').checked,toneScale:Math.max(.2,Math.min(3,Number($('audio-tone-scale').value)||1)),pauseScale:Math.max(.2,Math.min(3,Number($('audio-pause-scale').value)||1)),weak:$('audio-weak').checked,slowTau:Math.max(.1,Math.min(10,Number($('audio-slow-tau').value)||1.5)),beepDuty:Math.max(.1,Math.min(.9,(Number($('audio-dual-duty').value)||50)/100)),splitFraction:Math.max(.1,Math.min(.9,(Number($('audio-dual-split').value)||50)/100))});
const options=()=>({settings:S.settings,hz:S.hz,kind:S.kind,basis:S.basis});
function phaseAt(t){let e=null;for(const x of S.dataset?.events||[]){if(x.t<=t)e=x;else break;}return e;}
function proxyAt(t,kind='velocity') {
  const e=S.dataset?.events||[];let i=-1;for(let j=0;j<e.length;j++)if(e[j].t<=t)i=j;else break;
  if(i<0)return null;const a=e[i],b=e[i+1];
  if(a.phase==='BASSO')return 0;if(a.phase==='ALTO')return kind==='velocity'?0:1.2;
  if(!b||b.t<=a.t)return null;const v=(a.phase==='SALITA'?1.2:-1.2)/(b.t-a.t);
  return kind==='velocity'?v:(a.phase==='SALITA'?0:1.2)+v*(t-a.t);
}
function indexAt(t){let lo=0,hi=S.results.length-1;while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(S.results[mid].timeline<=t)lo=mid;else hi=mid-1;}return lo;}
function current(){return S.results[indexAt(S.pos)];}
function duration(){return Math.max(0,S.results.at(-1)?.timeline||0);}
function inputUI(){
  for(const [id,key]of [['dual-fast','dualFast'],['dual-slow','dualSlow'],['dual-output','dualOutput'],['hybrid-input','hybridInput'],['hybrid-window','hybridWindow'],['hybrid-output','hybridOutput'],['sky-sigma','skySigma'],['sky-q','skyQ'],['sky-window','skyWindow']])$(id).value=S.settings[key];
  for(const id of ['dual-card','hybrid-card'])$(id).classList.toggle('disabled-card',S.kind==='velocity');
  $('time-basis').value=S.basis;$('sample-rate').value=S.hz;$('signal-kind').value=S.kind;$('upstream').value=S.upstream;
  if(S.kind!=='pressure'&&$('audio-source').value==='sky')$('audio-source').value=S.kind==='velocity'?'external':'reg';
  $('sky-card').classList.toggle('disabled-card',S.kind!=='pressure');
  const vel=S.kind==='velocity';$('reg-card').classList.toggle('disabled-card',vel);$('kal-card').classList.toggle('disabled-card',vel);
  $('reg-window').disabled=$('kal-sigma').disabled=$('kal-q').disabled=$('tau-height').disabled=vel;
  $('lp-description').textContent=vel?'Lissage della velocità ricevuta, senza derivarla.':'Due stadi, una risposta morbida.';
  for(const o of $('audio-source').options)o.disabled=vel&&(['reg','kal','dual','hybrid','sky'].includes(o.value))||o.value==='sky'&&S.kind!=='pressure';
  if(vel&&['reg','kal','dual','hybrid','sky'].includes($('audio-source').value))$('audio-source').value='external';
  $('upstream-tag').textContent=(vel?'Velocità':S.kind==='height'?'Quota':'Pressione')+' · '+({raw:'grezza dichiarata',filtered:'già filtrata',unknown:'filtro a monte ignoto'}[S.upstream]);
  $('clock-badge').textContent=({nominal:'TEMPO NOMINALE',device:'TEMPO DISPOSITIVO',batch:'ANCORAGGI FIFO',receive:'RICEZIONE PC'}[S.basis])+' · '+S.hz+' Hz';
  $('clock-hint').textContent=S.basis==='receive'?'I burst USB/BLE possono alterare molto la derivata. Intervalli uguali o non crescenti reinizializzano il filtro.':
    S.basis==='batch'?'Le ancore FIFO sono ricostruzioni locali, non timestamp hardware. Disponibili solo quando registrate.':
    'Tempi originali conservati. Nominale richiede una frequenza dichiarata corretta; i timestamp device possono essere ricostruiti.';
}
function stats(){
  for(const key of ['lp','reg','kal','dual','hybrid','sky']){
    const vv=S.results.filter(r=>r.ready&&V.finite(r[key])).map(r=>r[key]);
    const mean=vv.reduce((a,b)=>a+b,0)/vv.length,sd=vv.length>1?Math.sqrt(vv.reduce((a,x)=>a+(x-mean)**2,0)/(vv.length-1)):null;
    $(key+'-stat').textContent=fmt(sd,3);
  }
  $('segments').textContent=new Set(S.results.map(r=>r.segment)).size+' segmenti';
}
function recomputeSlowAudio(){slowAudioFilter=new V.SlowAudio(audioOptions().slowTau);S.slowAudio=S.results.map(r=>slowAudioFilter.update(r,$('audio-source').value));}
function recompute(){
  if(!S.dataset)return;S.results=V.run(S.dataset.samples,options());livePipeline=new V.Pipeline(options());
  if(S.connected)S.results=S.dataset.samples.map((r,i)=>livePipeline.update(r,i));
  const unavailable=S.results.filter(r=>r.invalidTime).length;
  if(unavailable)notify(`Base temporale non disponibile in ${unavailable.toLocaleString(document.documentElement?.lang==='it'?'it-IT':'en-US')} campioni: nessun tempo è stato inventato. Scegli una base presente nel file.`,true);
  stats();inputUI();recomputeSlowAudio();plotDirty=true;
}
function setData(data,position=0){
  if(!Array.isArray(data.samples)||!data.samples.length)throw Error('Nessun campione utilizzabile nel file.');
  if(data.samples.length>500000)throw Error('Questa versione gestisce al massimo 500.000 campioni per sessione.');
  S.profileChanges=data.experiment?.profileChanges||data.profileChanges||[];S.dataset=V.normalize(data);S.kind=data.kind||'pressure';S.upstream=data.upstream||'unknown';S.hz=data.hz||80;
  S.playing=false;mute();S.pos=position;S.raw=data.raw||[];recompute();
  $('dataset-name').textContent=data.name||'Registrazione importata';$('dataset-detail').textContent=data.source||'File locale';
  $('count-tag').textContent=data.samples.length.toLocaleString(document.documentElement?.lang==='it'?'it-IT':'en-US')+' campioni';
  $('quality-tag').textContent=data.events?.length?Math.floor((data.events.length-1)/4)+' cicli annotati':'Senza marcatori di moto';
  $('timeline-description').textContent=data.events?.length?'Marcatori manuali · 1,20 m dichiarati · riferimento interpolato (proxy)':'Nessun riferimento di movimento: non è un test di errore o latenza.';
  $('chart-clock').textContent='Asse del grafico: '+(V.finite(data.samples[0].tBatch)?'ricostruzione locale FIFO':V.finite(data.samples[0].tDevice)?'tempo dispositivo':'tempo di ricezione o indice nominale')+'.';
  $('session-summary').textContent=data.description||'Dati e tempi originali conservati. La velocità già filtrata resta separata dalla pressione. Tutti i calcoli avvengono nel browser.';
  updateConnection();plotDirty=true;
}
function demo(){S.basis='nominal';S.manualClock=S.manualKind=false;notify('');setData(V.demo(window.VARIO_DEMO),59);}
function mute(){toneNode?.port.postMessage({enabled:false});beepClock.reset();if(gain&&ctx)gain.gain.setTargetAtTime(0,ctx.currentTime,.01);climbing=false;}
async function audioToggle(){
  if(!S.audio){
    const C=window.AudioContext||window.webkitAudioContext;if(!C)throw Error('Web Audio non disponibile.');
    if(!ctx){ctx=new C();
      if(ctx.audioWorklet&&window.AudioWorkletNode){
        try{await ctx.audioWorklet.addModule('tone-worklet.js');toneNode=new AudioWorkletNode(ctx,'vario-tone');toneNode.connect(ctx.destination);}
        catch(e){notify('AudioWorklet non disponibile: audio di riserva sul timer. '+e.message);}
      }
      if(!toneNode){osc=ctx.createOscillator();gain=ctx.createGain();osc.type='sine';gain.gain.value=0;osc.connect(gain);gain.connect(ctx.destination);osc.start();}
    }
    await ctx.resume();S.audio=true;audioStart=performance.now()/1000;
  }else{S.audio=false;mute();}
  $('audio-toggle').textContent=S.audio?'♫ Audio attivo':'Audio disattivato';$('audio-toggle').setAttribute('aria-pressed',String(S.audio));$('audio-toggle').classList.toggle('audio-on',S.audio);
}
function audioTick(row,now){
  if(!S.audio||!ctx)return;
  if((!S.playing&&!S.connected)||document.hidden||(S.connected&&now-S.lastRx>1200)||!row?.ready){mute();return;}
  const source=$('audio-source').value,v=source==='external'?row.velocity:row[source];
  const a=V.audioState(v,{...audioOptions(),slowVelocity:S.slowAudio?.[indexAt(S.pos)]},climbing);
  climbing=a.mode==='climb';
  if(toneNode){toneNode.port.postMessage({...a,enabled:a.mode!=='silent',volume:Number($('volume').value)});return;}
  beepClock.update(ctx.currentTime,a);const tone=V.toneAtPhase(a,beepClock.phase),on=tone.on;
  if(tone.hz>0)osc.frequency.setTargetAtTime(tone.hz,ctx.currentTime,a.splitTone?.002:.035);
  gain.gain.setTargetAtTime(on?Number($('volume').value):0,ctx.currentTime,.008);
}
function chart(canvas,series,small=false){
  const ratio=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
  if(w<1)return;if(canvas.width!==Math.round(w*ratio)||canvas.height!==Math.round(h*ratio)){canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);}
  const c=canvas.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);c.clearRect(0,0,w,h);
  const left=43,right=w-12,top=10,bottom=h-25,lo=S.connected?Math.max(0,S.pos-30):0,hi=S.connected?Math.max(30,S.pos):Math.max(1,duration());
  const x=t=>left+(t-lo)/(hi-lo)*(right-left),values=[];
  for(const ss of series)for(let i=0;i<S.results.length;i++){const r=S.results[i];if(r.timeline>=lo&&r.timeline<=hi){const v=ss.get(r);if(V.finite(v))values.push(v);}}
  let min=Infinity,max=-Infinity;for(const value of values){if(value<min)min=value;if(value>max)max=value;}if(!values.length){min=-.5;max=.5;}
  if(!small){min=Math.min(min,-.3);max=Math.max(max,.3);}if(max-min<.1){min-=.1;max+=.1;}
  const pad=(max-min)*.12;min-=pad;max+=pad;const y=v=>bottom-(v-min)/(max-min)*(bottom-top);
  c.font='9px Segoe UI';c.lineWidth=1;
  for(let i=0;i<=4;i++){const v=min+(max-min)*i/4,yy=y(v);c.strokeStyle='#edf1f3';c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();c.fillStyle='#9aa7ae';c.textAlign='right';drawText(c,fmt(v,small&&S.channel==='pressure'?0:1),left-8,yy+3);}
  for(let i=0;i<=5;i++){const t=lo+(hi-lo)*i/5,xx=x(t);c.fillStyle='#9aa7ae';c.textAlign='center';drawText(c,seconds(t),xx,h-6);}
  for(const e of S.dataset?.events||[]){if(e.t<lo||e.t>hi)continue;c.fillStyle=e.phase==='SALITA'?'#157c7809':e.phase==='DISCESA'?'#d17b4907':'#00000000';const index=S.dataset.events.indexOf(e),end=S.dataset.events[index+1]?.t??hi;c.fillRect(x(e.t),top,Math.max(0,x(Math.min(hi,end))-x(e.t)),bottom-top);c.strokeStyle='#d8e2e5';c.setLineDash([2,4]);c.beginPath();c.moveTo(x(e.t),top);c.lineTo(x(e.t),bottom);c.stroke();c.setLineDash([]);}
  if(!small){c.strokeStyle='#b9c9ce';c.setLineDash([3,4]);c.beginPath();c.moveTo(left,y(0));c.lineTo(right,y(0));c.stroke();c.setLineDash([]);}
  c.save();c.beginPath();c.rect(left,top,right-left,bottom-top);c.clip();
  for(const ss of series){c.strokeStyle=ss.color;c.lineWidth=ss.dash?1.2:1.4;c.setLineDash(ss.dash?[5,4]:[]);c.beginPath();let started=false,lastPixel=-10,lastSegment=null;
    const stride=Math.max(1,Math.floor(S.results.length/Math.max(w*3,1)));
    for(let i=0;i<S.results.length;i+=stride){const r=S.results[i];if(r.timeline<lo||r.timeline>hi)continue;const v=ss.get(r);if(!V.finite(v)){started=false;continue;}const xx=x(r.timeline),yy=y(v);if(started&&r.segment===lastSegment)c.lineTo(xx,yy);else c.moveTo(xx,yy);started=true;lastPixel=xx;lastSegment=r.segment;}c.stroke();c.setLineDash([]);
  }
  c.restore();const xx=x(S.pos);if(xx>=left&&xx<=right){c.strokeStyle='#6a9595';c.lineWidth=1;c.beginPath();c.moveTo(xx,top);c.lineTo(xx,bottom);c.stroke();c.fillStyle='#157c78';c.beginPath();c.arc(xx,top+1,3,0,Math.PI*2);c.fill();}
}
function render(){
  const row=current(),key=$('audio-source').value,v=key==='external'?row?.velocity:row?.[key];
  $('speed-value').innerHTML=(V.finite(v)?(v>=0?'+':'')+fmt(v):'—')+'<small>m/s</small>';
  $('height-value').innerHTML=fmt(row?.z)+'<small>m</small>';
  $('readout-filter').textContent=({lp:S.kind==='velocity'?'LP SU V':'PASSA-BASSO',reg:'REGRESSIONE',kal:'KALMAN',dual:'RC ADATTATO',hybrid:'MINIVARIO ARCHIVIO',sky:'SKYBEAN ADATTATO',external:'RICEVUTO'})[key];
  $('audio-status').textContent=$('audio-preset').value==='dualmean'?'Doppia media / attuale '+fmt(v)+' m/s / lenta '+fmt(S.slowAudio?.[indexAt(S.pos)])+' m/s / tau '+audioOptions().slowTau+' s':'Audio su clic. Pausa e ricerca interrompono il tono.';
  $('readout-quality').textContent=!row?.ready?'Calibrazione / inizializzazione filtri':S.kind==='velocity'?'Velocità ricevuta · filtraggio a monte '+S.upstream:'Valore stimato · '+S.basis;
  const phase=phaseAt(S.pos);$('phase-value').textContent=phase?.phase||'NON MARCATO';$('phase-value').classList.toggle('moving',!!phase&&['SALITA','DISCESA'].includes(phase.phase));
  $('phase-detail').textContent=phase?`${phase.completed||0} / 5 cicli conclusi · riferimento manuale`:'Nessun riferimento di moto disponibile';
  $('position').textContent=seconds(S.pos);$('duration').textContent=seconds(duration());$('seek').value=duration()?Math.round(S.pos/duration()*1000):0;
  $('play').textContent=S.playing?'Ⅱ':'▶';$('play').setAttribute('aria-label',S.playing?'Metti in pausa':'Avvia replay');
  const colors={lp:'#3676bd',reg:'#d17b49',kal:'#16877b',dual:'#9756ae',hybrid:'#a49434',sky:'#b45669'};
  const series=Object.keys(colors).filter(k=>S.visible[k]).map(k=>({color:colors[k],get:r=>r[k]}));
  if(S.dataset?.samples.some(r=>V.finite(r.velocity)))series.push({color:'#83939e',dash:true,get:r=>r.velocity});
  if(S.dataset?.events?.length)series.push({color:'#9aa2a5',dash:true,get:r=>proxyAt(r.timeline)});
  chart($('velocity-chart'),series);
  chart($('height-chart'),[{color:'#628da6',get:r=>S.channel==='height'?r.z:r.pressure},...(S.channel==='height'&&S.dataset?.events?.length?[{color:'#a7b1b4',dash:true,get:r=>proxyAt(r.timeline,'height')}]:[])],true);
}
async function mode(mode){
  if(mode==='replay'&&S.connected)await disconnect();
  S.mode=mode;S.playing=false;mute();$('connection-panel').hidden=mode==='replay';
  document.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('selected',b.dataset.mode===mode);b.setAttribute('aria-selected',String(b.dataset.mode===mode));});
  $('mode-note').textContent=mode==='replay'?'Riascolta, confronta, modifica.':mode==='record'?'Registra oggi, confronta domani.':'Stessi algoritmi, dati in arrivo.';
  $('play').disabled=mode!=='replay';$('seek').disabled=mode!=='replay';updateConnection();plotDirty=true;
}
function updateConnection(){
  $('disconnect').disabled=!S.connected;$('usb').disabled=S.connected||!('serial'in navigator)||!window.isSecureContext;
  $('ble').disabled=S.connected||!('bluetooth'in navigator)||!window.isSecureContext;
  $('record').disabled=!S.connected;$('send-command').disabled=!port||!S.connected;
  $('record').textContent=S.recording?'■ Termina e rivedi':'● Avvia registrazione';
  $('connection-status').textContent=S.connected?(S.recording?'Registrazione attiva · ':'Live · ')+S.dataset.samples.length.toLocaleString(document.documentElement?.lang==='it'?'it-IT':'en-US')+' campioni · '+S.invalid+' righe scartate':
    'Non collegato. USB '+('serial'in navigator?'disponibile':'non disponibile')+' · BLE '+('bluetooth'in navigator?'disponibile':'non disponibile')+(window.isSecureContext?'':' · richiede HTTPS o localhost');
}
function prepareLive(label){
  S.profileChanges=[];
  S.playing=false;S.connected=true;S.invalid=0;S.raw=[];S.recorded=null;S.pos=0;S.receiveOrigin=null;S.deviceOrigin=null;S.batchOrigin=null;S.timelineOrigin=null;
  S.dataset={name:label,source:label,description:'Ingresso live · dati originali nel browser',samples:[],events:[],batches:[],hz:S.hz,kind:S.kind,upstream:'unknown'};
  S.results=[];recomputeSlowAudio();livePipeline=new V.Pipeline(options());S.batchMap=new Map();
  $('dataset-name').textContent=label;$('dataset-detail').textContent='Connessione locale · nessun invio a un server';$('quality-tag').textContent='Nessun riferimento indipendente';
  notify('');updateConnection();
}
function receive(line,rx,xctrack=false){
  if(!S.connected)return;if(S.raw.length>=500000){notify('Limite della registrazione raw raggiunto. Esporta i dati prima di continuare.',true);disconnect();return;}const raw={receive_s:rx,line};S.raw.push(raw);if(S.recording)S.recorded.raw.push(raw);
  try {
    const msg=V.parseLine(line,rx,S.dataset.samples.length);if(!msg)return;
    if(msg.type==='sample'){if(xctrack)msg.sample.upstream='filtered';sample(msg.sample);}
    else if(msg.type==='event'){
      const e={...msg.event,t:V.finite(S.timelineOrigin)?msg.event.deviceTick-S.timelineOrigin:S.pos};
      S.dataset.events.push(e);if(S.recording)S.recorded.events.push({...msg.event});plotDirty=true;
    } else if(msg.type==='batch'){
      const b=msg.batch;S.dataset.batches.push(b);if(S.recording)S.recorded.batches.push({...b});
      for(let i=0;i<b.n;i++)S.batchMap.set(b.seq+i,b.read-(b.n-1-i)/S.hz);
    } else if(line.startsWith('E,'))notify('Diagnostica dispositivo: '+line,true);
  }catch(e){S.invalid++;if(S.invalid<4)notify(e.message,true);}
}
function sample(r){
  if(S.dataset.samples.length>=500000){notify('Limite di 500.000 campioni raggiunto. Esporta la sessione prima di continuare.',true);disconnect();return;}
  const first=S.dataset.samples.length===0;
  if(first){
    if(r.hz>0){S.hz=r.hz;S.dataset.hz=r.hz;}
    if(!S.manualKind)S.kind=V.finite(r.pressure)?'pressure':V.finite(r.altitude)?'height':'velocity';
    if(!S.manualClock&&r.protocol!=='BMP581')S.basis=V.finite(r.tDevice)?'device':'receive';
    S.upstream=r.upstream||'unknown';S.dataset.kind=S.kind;S.dataset.upstream=S.upstream;
    if(S.recording){S.recorded.kind=S.kind;S.recorded.hz=S.hz;S.recorded.upstream=S.upstream;}
    livePipeline=new V.Pipeline(options());inputUI();
    if(r.protocol!=='BMP581'&&!r.hz)notify('Questo protocollo non dichiara la frequenza. Prima di usare il tempo nominale, imposta gli Hz reali. Filtraggio a monte: '+S.upstream+'.');
  }
  S.receiveOrigin??=r.tReceive;if(V.finite(r.tDevice))S.deviceOrigin??=r.tDevice;
  if(S.batchMap.has(r.seq))r.tBatch=S.batchMap.get(r.seq);
  if(first)S.timelineOrigin=V.finite(r.tBatch)?r.tBatch:V.finite(r.tDevice)?r.tDevice:r.tReceive;
  r.timeline=(V.finite(r.tBatch)?r.tBatch:V.finite(r.tDevice)?r.tDevice:r.tReceive)-S.timelineOrigin;
  if(first)for(const e of S.dataset.events)if(V.finite(e.deviceTick))e.t=e.deviceTick-S.timelineOrigin;
  S.dataset.samples.push({...r});if(S.recording)S.recorded.samples.push({...r});
  S.results.push(livePipeline.update(r,S.dataset.samples.length-1));S.slowAudio.push(slowAudioFilter.update(S.results.at(-1),$('audio-source').value));S.pos=Math.max(0,r.timeline);S.lastRx=performance.now();
  $('count-tag').textContent=(S.recording?S.recorded.samples.length:S.dataset.samples.length).toLocaleString(document.documentElement?.lang==='it'?'it-IT':'en-US')+' campioni';plotDirty=true;
}
async function connectUSB(){
  const selected=await navigator.serial.requestPort();await selected.open({baudRate:Number($('baud').value)});
  port=selected;try{await port.setSignals({dataTerminalReady:false,requestToSend:false});}catch{/* Some native USB transports have no line signals. */}
  prepareLive('Seriale · flusso seriale');decoder=new V.LineDecoder(receive);reader=port.readable.getReader();
  (async()=>{try{while(S.connected){const {value,done}=await reader.read();if(done)break;if(value)decoder.push(value,performance.now()/1000);}}catch(e){if(S.connected)notify('Connessione USB interrotta: '+e.message,true);}finally{try{reader?.releaseLock();}catch{}reader=null;if(S.connected){S.connected=false;S.recording=false;mute();updateConnection();}}})();
}
function uuid(value){const s=value.trim();return /^[a-f0-9]{4}$/i.test(s)?parseInt(s,16):s;}
async function connectBLE(){
  const kind=$('ble-profile').value,service=kind==='ess'?0x181a:['xctrack','nus'].includes(kind)?'6e400001-b5a3-f393-e0a9-e50e24dcca9e':uuid($('ble-service').value),characteristic=kind==='ess'?0x2a6d:['xctrack','nus'].includes(kind)?'6e400003-b5a3-f393-e0a9-e50e24dcca9e':uuid($('ble-characteristic').value);
  bleDevice=await navigator.bluetooth.requestDevice({acceptAllDevices:true,optionalServices:[service]});
  const server=await bleDevice.gatt.connect();
  try{const svc=await server.getPrimaryService(service);bleCharacteristic=await svc.getCharacteristic(characteristic);decoder=new V.LineDecoder((line,rx)=>receive(line,rx,kind==='xctrack'));
    prepareLive('BLE · '+(bleDevice.name||'strumento'));
    bleCharacteristic.addEventListener('characteristicvaluechanged',e=>{
      const value=e.target.value,rx=performance.now()/1000;
      if(kind==='ess'){
        if(value.byteLength!==4){S.invalid++;return;}
        const r={seq:S.dataset.samples.length+1,tReceive:rx,pressure:value.getUint32(0,true)*.1,protocol:'BLE ESS',upstream:'unknown',raw:'ESS:'+Array.from(new Uint8Array(value.buffer,value.byteOffset,value.byteLength)).map(x=>x.toString(16).padStart(2,'0')).join('')};
        const raw={receive_s:rx,line:r.raw};S.raw.push(raw);if(S.recording)S.recorded.raw.push(raw);sample(r);
      }else decoder.push(new Uint8Array(value.buffer,value.byteOffset,value.byteLength),rx);
    });
    await bleCharacteristic.startNotifications();
    bleDevice.addEventListener('gattserverdisconnected',()=>{S.connected=false;S.recording=false;mute();updateConnection();notify('Dispositivo BLE scollegato. I dati ricevuti restano esportabili.');},{once:true});
  }catch(e){bleDevice.gatt.disconnect();S.connected=false;updateConnection();throw e;}
}
async function disconnect(){
  S.connected=false;mute();if(reader){try{await reader.cancel();}catch{}}
  if(port){try{await port.close();}catch{}port=null;}
  if(bleDevice?.gatt?.connected)bleDevice.gatt.disconnect();bleCharacteristic=null;
  if(S.recording)S.recording=false;updateConnection();
}
async function toggleRecording(){
  if(!S.recording){S.recorded={profileChanges:S.profileChanges,samples:[],events:S.dataset.events.length?[{...S.dataset.events.at(-1),contextOnly:true}]:[],batches:[],raw:[],kind:S.kind,hz:S.hz,upstream:S.upstream,name:'Registrazione '+new Date().toLocaleTimeString(document.documentElement?.lang==='it'?'it-IT':'en-US'),source:S.dataset.source};S.recording=true;updateConnection();}
  else {S.recording=false;const copy=S.recorded;await disconnect();if(copy.samples.length){setData(copy);await mode('replay');notify('Registrazione conclusa. Puoi riprodurla, cambiare i filtri ed esportarla.');}else notify('Nessun campione ricevuto durante la registrazione.');}
}
async function importFiles(files){
  if(S.connected)await disconnect();let data=null,extras={events:[],batches:[]};notify('');S.invalid=0;
  for(const file of files){
    if(file.size>50*1024*1024)throw Error('File troppo grande: limite 50 MB.');
    const text=await file.text();
    if(file.name.toLowerCase().endsWith('.json')){
      const j=JSON.parse(text);if(!Array.isArray(j.samples))throw Error('Il JSON non è una sessione Vario Lab.');
      data=Array.isArray(j.samples[0])?V.demo(j):j;if(j.experiment){S.settings={...V.defaults,...j.experiment.settings};S.basis=j.experiment.basis||'nominal';data.kind=j.experiment.kind||j.kind;data.hz=j.experiment.hz||j.hz;data.upstream=j.experiment.upstream||j.upstream;applySettingValues();
        if(j.experiment.audio){$('audio-source').value=j.experiment.audio.source||'reg';$('audio-preset').value=j.experiment.audio.preset||'classic';$('climb-threshold').value=j.experiment.audio.climb??.1;$('sink-threshold').value=j.experiment.audio.sink??-.5;$('audio-hysteresis').checked=!!j.experiment.audio.hysteresisEnabled;$('audio-tone-scale').value=j.experiment.audio.toneScale??1;$('audio-pause-scale').value=j.experiment.audio.pauseScale??1;$('audio-weak').checked=!!j.experiment.audio.weak;$('audio-slow-tau').value=j.experiment.audio.slowTau??1.5;$('audio-dual-duty').value=(j.experiment.audio.beepDuty??.5)*100;$('audio-dual-split').value=(j.experiment.audio.splitFraction??.5)*100;}}continue;
    }
    if(file.name.match(/\.(jsonl|nmea|log|txt)$/i)){
      const records=[],events=[],batches=[],raw=[];let i=0;
      for(const line of text.split(/\r?\n/)){if(!line.trim())continue;let original=line,rx=i/(S.hz||80);
        if(file.name.endsWith('.jsonl')){const e=JSON.parse(line);if(!e.rx&&!e.line)continue;original=e.rx??e.line;rx=e.host_monotonic_s??e.receive_s??rx;}
        try{const p=V.parseLine(original,rx,records.length);raw.push({receive_s:rx,line:original});if(p?.type==='sample')records.push(p.sample);else if(p?.type==='event')events.push(p.event);else if(p?.type==='batch')batches.push(p.batch);}catch{S.invalid++;}i++;
      }
      if(records.length)data={name:file.name,samples:records,events,batches,raw,hz:records[0].hz||S.hz,kind:S.kind,upstream:records[0].upstream||'unknown'};continue;
    }
    const parsed=V.parseCSV(text,S.kind,S.hz);extras.events.push(...parsed.events);extras.batches.push(...parsed.batches);
    if(parsed.samples.length){data={name:file.name,source:'CSV importato · '+file.name,samples:parsed.samples,events:[],batches:[],hz:parsed.samples[0].hz||S.hz,kind:S.kind,upstream:'unknown'};
      if(!parsed.samples.some(r=>V.finite(r.pressure)))data.kind=parsed.samples.some(r=>V.finite(r.altitude))?'height':'velocity';}
  }
  if(!data)throw Error('Seleziona un file con campioni, eventualmente insieme a events.csv e batches.csv.');
  data.events=[...(data.events||[]),...extras.events];data.batches=[...(data.batches||[]),...extras.batches];
  if(!data.samples.some(r=>V.finite(r.tDevice))&&S.basis==='device')S.basis='nominal';
  setData(data);await mode('replay');
  if(S.invalid)notify('File importato. Righe non riconosciute o non valide: '+S.invalid+'.');
}
function session(){const data=S.recording&&S.recorded?.samples.length?S.recorded:S.dataset;return {...data,version:1,application:'Vario Lab',raw:S.recording?S.recorded.raw:S.raw,experiment:{...options(),profileChanges:S.profileChanges,upstream:S.upstream,visible:S.visible,audio:{source:$('audio-source').value,...audioOptions()}}};}
function applySettingValues(){
  for(const [id,key]of [['tau-height','tauHeight'],['tau-velocity','tauVelocity'],['reg-window','window'],['kal-sigma','sigma'],['kal-q','q']]){$(id).value=S.settings[key];if($(id+'-output'))$(id+'-output').textContent=fmt(S.settings[key],2)+' s';}
  $('temperature').value=S.settings.temperature-273.15;
}
let timer;
for(const [id,key]of [['tau-height','tauHeight'],['tau-velocity','tauVelocity'],['reg-window','window'],['kal-sigma','sigma'],['kal-q','q']])$(id).addEventListener('input',()=>{
  const value=Number($(id).value);if(!(value>0&&Number.isFinite(value))){notify('Inserisci un parametro positivo e finito.',true);return;}S.settings[key]=value;if($(id+'-output'))$(id+'-output').textContent=fmt(value,2)+' s';clearTimeout(timer);timer=setTimeout(guard(recompute),100);
});
$('time-basis').onchange=guard(()=>{S.basis=$('time-basis').value;S.manualClock=true;mute();notify('');recompute();});
$('sample-rate').onchange=guard(()=>{const n=Number($('sample-rate').value);if(!(n>0&&n<=1000))throw Error('Frequenza tra 0 e 1000 Hz richiesta.');S.hz=n;recompute();});
$('temperature').onchange=guard(()=>{const t=Number($('temperature').value);if(!Number.isFinite(t)||t< -40||t>50)throw Error('Temperatura di riferimento tra −40 e +50 °C.');S.settings.temperature=t+273.15;recompute();});
$('signal-kind').onchange=guard(()=>{S.kind=$('signal-kind').value;S.manualKind=true;recompute();});
$('upstream').onchange=()=>{S.upstream=$('upstream').value;inputUI();};
$('reset-settings').onclick=guard(()=>{S.settings={...V.defaults};S.hz=80;S.basis='nominal';applySettingValues();notify('');recompute();});
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=guard(()=>mode(b.dataset.mode)));
document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=guard(async()=>{document.querySelectorAll('[data-nav]').forEach(x=>x.classList.toggle('active',x===b));if(b.dataset.nav==='sources'){await mode('live');$('source-section').scrollIntoView({behavior:'smooth'});}else if(b.dataset.nav==='notes')$('notes-section').scrollIntoView({behavior:'smooth'});else window.scrollTo({top:0,behavior:'smooth'});}));
document.querySelectorAll('[data-visible]').forEach(b=>b.onchange=()=>{S.visible[b.dataset.visible]=b.checked;plotDirty=true;});
document.querySelectorAll('[data-channel]').forEach(b=>b.onclick=()=>{S.channel=b.dataset.channel;document.querySelectorAll('[data-channel]').forEach(x=>x.classList.toggle('selected',x===b));plotDirty=true;});
$('play').onclick=()=>{if(S.mode!=='replay')return;S.playing=!S.playing;if(S.pos>=duration())S.pos=0;mute();plotDirty=true;};
$('restart').onclick=()=>{S.pos=0;mute();plotDirty=true;};$('seek').oninput=()=>{S.pos=Number($('seek').value)/1000*duration();mute();plotDirty=true;};
$('playback-rate').onchange=()=>{S.speed=Number($('playback-rate').value);mute();};
const profiles={dualmean:{source:'kal',preset:'dualmean',description:'Bip doppia media: prima parte con la stima attuale, seconda parte con una EMA aggiuntiva lenta; nessuna pausa interna. Cadenza dalla stima attuale.'},rc:{source:'dual',preset:'classic',description:'RC: doppia EMA calibrata. Adattamento della famiglia Bakke.'},sky:{source:'sky',preset:'curves',description:'SkyBean: filtro scalare sulla pressione e differenza di quota. Parametri del laboratorio, non replica originale.'},kal:{source:'kal',preset:'classic',description:'Kalman barometrico quota/velocita; nessuna IMU in questa prova.'},reg:{source:'reg',preset:'classic',description:'Regressione causale sulla finestra passata.'},lp:{source:'lp',preset:'classic',description:'Passa-basso + derivata, con tau regolabili e suono classico.'},curves:{source:'kal',preset:'curves',description:'Kalman + curve sonore indipendenti per frequenza, durata e pausa. Curve del laboratorio, ispirate alla struttura SkyDrop.'},pair:{source:'kal',preset:'pair',description:'Kalman + coppie di toni, ispirate a BiBean. Secondo tono piu alto in salita, piu basso in discesa.'}};
function applyProfile(key){const p=profiles[key];if(!p)return;if(S.kind==='velocity'||key==='sky'&&S.kind!=='pressure'){notify('I profili barometrici richiedono pressione o quota, non sola velocit\u00e0 ricevuta.',true);$('lab-profile').value='custom';return;}mute();$('audio-source').value=p.source;$('audio-preset').value=p.preset;$('profile-description').textContent=p.description;recomputeSlowAudio();S.visible[p.source]=true;document.querySelectorAll('[data-visible]').forEach(b=>b.checked=!!S.visible[b.dataset.visible]);S.profileChanges.push({timeline_s:S.pos,receive_s:performance.now()/1000,profile:key,source:p.source,preset:p.preset,settings:{...S.settings},audio:audioOptions(),origin:'browser UI'});plotDirty=true;}
$('lab-profile').onchange=()=>applyProfile($('lab-profile').value);
$('next-profile').onclick=()=>{const keys=Object.keys(profiles),i=keys.indexOf($('lab-profile').value),key=keys[(i+1)%keys.length];$('lab-profile').value=key;applyProfile(key);};
for(const [id,key]of [['dual-fast','dualFast'],['dual-slow','dualSlow'],['dual-output','dualOutput'],['hybrid-input','hybridInput'],['hybrid-window','hybridWindow'],['hybrid-output','hybridOutput'],['sky-sigma','skySigma'],['sky-q','skyQ'],['sky-window','skyWindow']])$(id).onchange=()=>{const v=Number($(id).value),candidate={...S.settings,[key]:v};try{new V.Pipeline({settings:candidate});S.settings=candidate;mute();recompute();}catch(e){$(id).value=S.settings[key];notify(e.message,true);}};
for(const id of ['audio-hysteresis','audio-tone-scale','audio-pause-scale','audio-weak'])$(id).onchange=()=>{mute();$('lab-profile').value='custom';};
for(const id of ['audio-slow-tau','audio-dual-duty','audio-dual-split'])$(id).onchange=()=>{if(id==='audio-slow-tau')recomputeSlowAudio();$('lab-profile').value='custom';plotDirty=true;};
$('audio-toggle').onclick=guard(audioToggle);$('audio-source').onchange=()=>{$('lab-profile').value='custom';mute();recomputeSlowAudio();plotDirty=true;};$('audio-preset').onchange=()=>{$('lab-profile').value='custom';mute();};
$('import').onclick=()=>$('files').click();$('files').onchange=guard(async()=>{await importFiles([...$('files').files]);$('files').value='';});
$('demo').onclick=guard(async()=>{if(S.connected)await disconnect();await mode('replay');demo();});
$('usb').onclick=guard(connectUSB);$('ble').onclick=guard(connectBLE);$('disconnect').onclick=guard(disconnect);$('record').onclick=guard(toggleRecording);
$('ble-profile').onchange=()=>{if($('ble-profile').value==='ess'){$('ble-service').value='181a';$('ble-characteristic').value='2a6d';}else if(['nus','xctrack'].includes($('ble-profile').value)){$('ble-service').value='6e400001-b5a3-f393-e0a9-e50e24dcca9e';$('ble-characteristic').value='6e400003-b5a3-f393-e0a9-e50e24dcca9e';}};
$('send-command').onclick=guard(async()=>{if(!port?.writable)throw Error('Nessuna porta USB scrivibile.');const command=$('command').value.trim();if(!command||command.length>200)throw Error('Comando vuoto o troppo lungo.');const writer=port.writable.getWriter();try{await writer.write(new TextEncoder().encode(command+'\n'));S.raw.push({tx:command,receive_s:performance.now()/1000});notify('Comando inviato: '+command);}finally{writer.releaseLock();}});
$('export').onclick=()=>$('export-dialog').showModal();
$('save-session').onclick=()=>{download('vario-lab-session.json',JSON.stringify(session()));$('export-dialog').close();};
$('save-raw').onclick=()=>download('vario-lab-raw.jsonl',(S.recording?S.recorded.raw:S.raw).map(r=>JSON.stringify(r)).join('\n'),'application/x-ndjson');
$('download-csv').onclick=()=>download('vario-lab-samples.csv',V.csvExport(S.recording?S.recorded.samples:S.dataset.samples),'text/csv');
$('download-analysis').onclick=()=>download('vario-lab-results.csv',V.csvExport(S.results.map((r,i)=>({audio_slow_velocity_mps:S.slowAudio?.[i],audio_slow_tau_s:audioOptions().slowTau,audio_source:$('audio-source').value,seq:r.seq,device_s:r.tDevice,receive_s:r.tReceive,batch_s:r.tBatch,timeline_s:r.timeline,filter_time_s:r.tFilter,segment:r.segment,pressure_pa:r.pressure,relative_height_m:r.z,velocity_received_mps:r.velocity,v_lowpass_mps:r.lp,v_regression_mps:r.reg,v_kalman_mps:r.kal,v_dual_ema_mps:r.dual,v_hybrid_mps:r.hybrid,v_skybean_mps:r.sky,ready:r.ready,phase_annotation:phaseAt(r.timeline)?.phase||'',reference_velocity_average_proxy_mps:proxyAt(r.timeline),time_basis:S.basis,upstream:S.upstream}))), 'text/csv');
$('download-firmware').onclick=()=>{const a=document.createElement('a');a.href='install/firmware/stick_vario_ram.py';a.download='stick_vario_ram.py';a.click();};
window.addEventListener('resize',()=>plotDirty=true);
document.addEventListener('visibilitychange',()=>{if(document.hidden){S.playing=false;mute();}});
window.addEventListener('beforeunload',()=>{mute();if(bleDevice?.gatt?.connected)bleDevice.gatt.disconnect();});
function tick(now){
  const dt=Math.min((now-lastTick)/1000,.25);lastTick=now;
  if(S.playing){S.pos+=dt*S.speed;if(S.pos>=duration()){if($('loop').checked){S.pos=0;mute();}else{S.pos=duration();S.playing=false;mute();}}plotDirty=true;}

  if(plotDirty&&now-lastFrame>90){render();plotDirty=false;lastFrame=now;}
  if(S.connected&&now-lastStats>1000){stats();updateConnection();lastStats=now;}
  requestAnimationFrame(tick);
}
window.addEventListener('variolanguagechange',()=>{plotDirty=true;});
demo();applySettingValues();requestAnimationFrame(tick);
// Expose deterministic hooks for browser interaction tests, not remote control.
window.VarioApp={state:S,recompute,importFiles,setData,mode,render,disconnect,session};
const audioTimer=setInterval(()=>audioTick(current(),performance.now()),20);if(audioTimer?.unref)audioTimer.unref();
})();

