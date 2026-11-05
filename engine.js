/* Vario Lab: pure numerical core. No network, DOM or device dependencies. */
'use strict';
globalThis.Vario = (() => {
  const defaults = Object.freeze({reference:2,temperature:288.15,tauHeight:.25,tauVelocity:.20,window:.60,sigma:.020,q:.020,dualFast:.19,dualSlow:.39,dualOutput:.19,hybridInput:.15654,hybridWindow:.875,hybridOutput:.35046,skySigma:.20,skyQ:.01,skyWindow:.50});
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  const number = x => x === '' || x == null || !Number.isFinite(Number(x)) ? null : Number(x);
  const height = (p,p0,T=288.15) => {
    if (!(p>0 && p0>0 && T>0)) throw Error('Pressione e riferimento devono essere positivi.');
    return T/.0065*(1-Math.pow(p/p0,287.05287*.0065/9.80665));
  };
  class Filters {
    constructor(settings={}) {this.s={...defaults,...settings};this.last=null;this.w=[];}
    update(t,z) {
      const s=this.s;
      if(!finite(t)||!finite(z)) throw Error('Campione non finito.');
      if(this.last===null) {
        this.last=this.start=t;this.z=z;this.v=0;this.x=z;this.kv=0;
        this.P=[s.sigma**2,0,0,1];this.w=[[t,z]];this.fast=this.slow=this.lastRaw=z;this.dual=this.hybrid=this.hybridEMA=0;this.hybridRows=[];
        return {lp:0,reg:null,kal:0,dual:0,hybrid:0};
      }
      const dt=t-this.last;if(!(dt>0)) throw Error('Il tempo deve crescere.');this.last=t;
      const old=this.z;this.z+=-Math.expm1(-dt/s.tauHeight)*(z-this.z);
      this.v+=-Math.expm1(-dt/s.tauVelocity)*((this.z-old)/dt-this.v);
      this.w.push([t,z]);while(this.w.length&&this.w[0][0]<t-s.window-1e-9)this.w.shift();
      let reg=null;
      if(t-this.start>=s.window-1e-9&&this.w.length>=3) {
        const n=this.w.length,mt=this.w.reduce((a,r)=>a+r[0],0)/n,mz=this.w.reduce((a,r)=>a+r[1],0)/n;
        let num=0,den=0;for(const [tt,zz]of this.w){num+=(tt-mt)*(zz-mz);den+=(tt-mt)**2;}reg=num/den;
      }
      const [a,b,c,d]=this.P;
      const p00=a+dt*(b+c)+dt*dt*d+s.q*dt**3/3;
      const p01=b+dt*d+s.q*dt*dt/2,p10=c+dt*d+s.q*dt*dt/2,p11=d+s.q*dt;
      const R=s.sigma**2,k0=p00/(p00+R),k1=p10/(p00+R),prediction=this.x+dt*this.kv,residual=z-prediction;
      this.x=prediction+k0*residual;this.kv+=k1*residual;
      // Joseph covariance update, matching the Python reference implementation.
      this.P=[(1-k0)**2*p00+k0*k0*R,(1-k0)*(p01-k1*p00)+k0*k1*R,
        (1-k0)*(p10-k1*p00)+k1*k0*R,p11-k1*(p01+p10)+k1*k1*p00+k1*k1*R];
      // Difference of two exponential averages, calibrated to unit ramp gain.
      this.fast+=-Math.expm1(-dt/s.dualFast)*(z-this.fast);
      this.slow+=-Math.expm1(-dt/s.dualSlow)*(z-this.slow);
      const lag=dt/Math.expm1(dt/s.dualSlow)-dt/Math.expm1(dt/s.dualFast);
      this.dual+=-Math.expm1(-dt/s.dualOutput)*((this.fast-this.slow)/lag-this.dual);
      const raw=(z-this.lastRaw)/dt;this.lastRaw=z;
      this.hybridEMA+=-Math.expm1(-dt/s.hybridInput)*(raw-this.hybridEMA);
      this.hybridRows.push([t,dt,this.hybridEMA]);
      while(this.hybridRows.length&&this.hybridRows[0][0]<=t-s.hybridWindow)this.hybridRows.shift();
      let weighted=0,span=0;
      for(const [end,width,v] of this.hybridRows){const overlap=Math.min(width,end-(t-s.hybridWindow));weighted+=overlap*v;span+=overlap;}
      this.hybrid+=-Math.expm1(-dt/s.hybridOutput)*(weighted/span-this.hybrid);
      return {lp:this.v,reg,kal:this.kv,dual:this.dual,hybrid:this.hybrid};
    }
  }
  // SkyBean-family adaptation: scalar pressure random walk, then altitude lag difference.
  class ScalarPressureLag {
    constructor(settings={}){this.s={...defaults,...settings};this.last=null;this.rows=[];}
    update(t,p,p0,T=288.15){
      const s=this.s,R=s.skySigma**2;
      if(this.last===null){this.x=p;this.P=R;this.start=t;}
      else{const dt=t-this.last;if(!(dt>0))throw Error('Il tempo deve crescere.');this.P+=s.skyQ*dt;const k=this.P/(this.P+R);this.x+=k*(p-this.x);this.P=(1-k)*this.P;}
      this.last=t;const z=height(this.x,p0,T);this.rows.push([t,z]);const target=t-s.skyWindow;
      while(this.rows.length>2&&this.rows[1][0]<=target)this.rows.shift();
      if(target<this.start-1e-9||this.rows.length<2)return null;
      const [a,b]=this.rows,fraction=Math.max(0,Math.min(1,(target-a[0])/(b[0]-a[0]))),old=a[1]+fraction*(b[1]-a[1]);
      return (z-old)/s.skyWindow;
    }
  }
  class Pipeline {
    constructor(options={}) {
      this.s={...defaults,...options.settings};this.hz=options.hz||80;this.kind=options.kind||'pressure';
      this.basis=options.basis||'nominal';this.ref=null;this.prev=null;this.segment=-1;
      for(const v of Object.values(this.s))if(!(finite(v)&&v>0))throw Error('Parametri dei filtri non validi.');
      if(!(this.s.dualSlow>this.s.dualFast))throw Error('Tau lenta deve essere maggiore di tau veloce.');
      if(!(this.hz>0&&this.hz<=1000))throw Error('Frequenza nominale non valida.');
    }
    update(r,index=0) {
      const seq=finite(r.seq)?r.seq:index+1;
      const clock=this.basis==='device'?r.tDevice:this.basis==='receive'?r.tReceive:this.basis==='batch'?r.tBatch:null;
      if(this.basis!=='nominal'&&!finite(clock))return {...r,lp:null,reg:null,kal:null,dual:null,hybrid:null,sky:null,z:null,ready:false,invalidTime:true,segment:this.segment};
      const broken=!this.prev||seq!==this.prev.seq+1||
        (finite(r.tDevice)&&finite(this.prev.tDevice)&&r.tDevice<=this.prev.tDevice)||
        (this.basis!=='nominal'&&clock<=this.prev.clock);
      if(broken){this.segment++;this.originSeq=seq;this.originClock=clock;this.cal=[];this.f=new Filters(this.s);this.sf=new ScalarPressureLag(this.s);this.start=null;this.velocityLP=null;}
      const t=this.basis==='nominal'?(seq-this.originSeq)/this.hz:clock-this.originClock;
      this.prev={seq,tDevice:r.tDevice,clock};
      const result={...r,tFilter:t,segment:this.segment,discontinuity:broken,reference:this.ref,z:null,lp:null,reg:null,kal:null,dual:null,hybrid:null,sky:null,ready:false};
      if(this.kind==='velocity') {
        if(!finite(r.velocity))return result;
        if(this.start===null){this.start=t;this.velocityLP=r.velocity;this.velocityTime=t;}
        else {this.velocityLP+=-Math.expm1(-(t-this.velocityTime)/this.s.tauVelocity)*(r.velocity-this.velocityLP);this.velocityTime=t;}
        return {...result,lp:this.velocityLP,ready:t-this.start>=3};
      }
      const value=this.kind==='pressure'?r.pressure:r.altitude;
      if(!finite(value)||(this.kind==='pressure'&&(value<=30000||value>=125000)))return result;
      if(this.ref===null) {
        this.cal.push(value);if(t<this.s.reference)return result;
        this.ref=this.cal.reduce((a,b)=>a+b,0)/this.cal.length;
      }
      const z=this.kind==='pressure'?height(value,this.ref,this.s.temperature):value-this.ref;
      if(this.start===null)this.start=t;
      return {...result,...this.f.update(t,z),sky:this.kind==='pressure'?this.sf.update(t,value,this.ref,this.s.temperature):null,z,reference:this.ref,ready:t-this.start>=3};
    }
  }
  function run(samples,options={}) {const p=new Pipeline(options);return samples.map((r,i)=>p.update(r,i));}
  function checksum(body) {let n=0;for(const c of body)n^=c.charCodeAt(0);return n.toString(16).toUpperCase().padStart(2,'0');}
  function nmea(line) {
    const m=line.trim().match(/^\$([^*]+)\*([0-9a-f]{2})$/i);
    if(!m||checksum(m[1])!==m[2].toUpperCase())throw Error('Checksum NMEA assente o non valido.');
    return m[1].split(',');
  }
  function parseLine(line,rx=0,index=0) {
    line=line.trim();if(!line)return null;
    const f=line.split(',');
    if(f[0]==='S'&&f.length===9) {
      const r={seq:number(f[1]),tDevice:number(f[2])/1000,pressure:number(f[3]),temperature:number(f[4]),
        osrP:number(f[5]),osrT:number(f[6]),hz:number(f[7]),mode:f[8],tReceive:rx,raw:line,protocol:'BMP581',upstream:'raw'};
      if(!finite(r.seq)||!finite(number(f[2]))||!(r.hz>0)||!finite(r.pressure))throw Error('Campione BMP581 malformato.');
      return {type:'sample',sample:r};
    }
    if(f[0]==='M'&&f.length===8) {
      if(!['BASSO','SALITA','ALTO','DISCESA'].includes(f[3]))throw Error('Fase non riconosciuta.');
      if(![1,2,4,5,6].every(i=>finite(number(f[i])))||number(f[1])<1||number(f[4])<0)throw Error('Marcatore di fase malformato.');
      return {type:'event',event:{id:number(f[1]),deviceTick:number(f[2])/1000,phase:f[3],completed:number(f[4]),seqSnapshot:number(f[5]),fifo:number(f[6]),source:f[7],tReceive:rx,raw:line}};
    }
    if(f[0]==='F'&&f.length===4){
      const seq=number(f[1]),n=number(f[2]),read=number(f[3]);
      if(!Number.isInteger(seq)||seq<1||!Number.isInteger(n)||n<1||n>16||!finite(read))throw Error('Marcatore FIFO malformato.');
      return {type:'batch',batch:{seq,n,read:read/1000}};
    }
    if(line.startsWith('$XCTOD,'))return {type:'diagnostic',line};
    if(line.startsWith('$')) {
      const a=nmea(line);let r={seq:index+1,tReceive:rx,tDevice:null,protocol:a[0],raw:line,upstream:'unknown'};
      if(a[0]==='VARIO') {
        // Flymaster-style pressure in hPa. Never guess units from magnitude.
        const p=number(a[1]);
        if(!(p>300&&p<1250))throw Error('VARIO: pressione attesa in hPa (300..1250). Conservato il raw; verificare il formato del firmware.');
        r.pressure=p*100;r.velocity=number(a[2]);
      } else if(a[0]==='LK8EX1') {
        // Pressure Pa, altitude m, climb cm/s. Missing-value sentinels never become measurements.
        const p=number(a[1]),h=number(a[2]),v=number(a[3]);
        r.pressure=p>30000&&p<125000?p:null;r.altitude=h!==99999?h:null;
        r.velocity=v!==9999&&finite(v)?v/100:null;r.temperature=number(a[4])===99?null:number(a[4]);
      } else if(a[0]==='XCTRC') {
        const fields=a.map(number);
        r.altitude=fields[10];r.velocity=fields[13];r.pressure=finite(fields[17])?fields[17]*100:null;
        if(fields.slice(1,8).every(finite)) {
          const [y,mo,day,hh,mm,ss,cs]=fields.slice(1,8);
          if(y>=1800&&y<=2500&&mo>=1&&mo<=12&&day>=1&&day<=31&&hh>=0&&hh<24&&mm>=0&&mm<60&&ss>=0&&ss<60&&cs>=0&&cs<100)
            r.tDevice=Date.UTC(y,mo-1,day,hh,mm,ss,cs*10)/1000;
        }
      } else return {type:'diagnostic',line};
      if(![r.pressure,r.altitude,r.velocity].some(finite))throw Error('La sentenza non contiene misure utilizzabili.');
      return {type:'sample',sample:r};
    }
    if(/^(?:_?PRS)\s+[0-9a-f]+$/i.test(line)) {
      return {type:'sample',sample:{seq:index+1,tReceive:rx,pressure:parseInt(line.split(/\s+/)[1],16),raw:line,protocol:line.startsWith('_')?'_PRS':'PRS',upstream:line.startsWith('_')?'filtered':'raw'}};
    }
    return {type:'diagnostic',line};
  }
  class LineDecoder {
    constructor(callback){this.callback=callback;this.decoder=new TextDecoder();this.pending='';}
    push(bytes,rx) {
      this.pending+=typeof bytes==='string'?bytes:this.decoder.decode(bytes,{stream:true});
      if(this.pending.length>1000000)throw Error('Flusso senza fine riga: controlla protocollo e caratteristica BLE.');
      let n;while((n=this.pending.indexOf('\n'))>=0){const line=this.pending.slice(0,n).replace(/\r/g,'');this.pending=this.pending.slice(n+1);if(line.trim())this.callback(line,rx);}
    }
  }
  function csvRows(text) {
    const rows=[];let row=[],field='',quoted=false;
    text=text.replace(/^\uFEFF/,'');
    for(let i=0;i<text.length;i++) {
      const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}
      else if(c===','&&!quoted){row.push(field);field='';}
      else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(v=>v!==''))rows.push(row);row=[];field='';}
      else field+=c;
    }
    if(quoted)throw Error('CSV con virgolette non chiuse.');
    if(field||row.length){row.push(field);rows.push(row);}return rows;
  }
  function parseCSV(text,kind='pressure',hz=80) {
    const rows=csvRows(text);if(rows.length<2)throw Error('CSV vuoto.');
    const header=rows.shift().map(h=>h.trim().toLowerCase());
    const pick=(obj,keys)=>{for(const k of keys)if(obj[k]!==undefined&&obj[k]!=='')return number(obj[k]);return null;};
    const samples=[],events=[],batches=[];
    for(const row of rows) {
      const o=Object.fromEntries(header.map((h,i)=>[h,row[i]??'']));
      if(o.phase&&o.device_button_tick_ms){events.push({deviceTick:number(o.device_button_tick_ms)/1000,phase:o.phase,completed:number(o.completed_cycles),source:o.source});continue;}
      if(o.first_seq&&o.device_read_start_ms){batches.push({seq:number(o.first_seq),n:number(o.frame_count),read:number(o.device_read_start_ms)/1000});continue;}
      const pressure=pick(o,['pressure_pa','pressure']),altitude=pick(o,['relative_height_m','altitude_m','height_m','altitude']),velocity=pick(o,['velocity_mps','vertical_speed_mps','vario_mps','velocity']);
      if([pressure,altitude,velocity].every(x=>x===null))continue;
      const ms=pick(o,['device_estimated_ms','device_ms']),ds=pick(o,['device_s','t_device_s','tdevice','time_s','sample_time_s']);
      samples.push({seq:pick(o,['seq'])??samples.length+1,tDevice:ms!==null?ms/1000:ds,
        tReceive:pick(o,['host_receive_monotonic_s','host_monotonic_s','host_receive_epoch_s','host_epoch_s','receive_s','treceive']),
        tBatch:pick(o,['device_batch_estimated_ms'])!==null?pick(o,['device_batch_estimated_ms'])/1000:pick(o,['batch_s','tbatch']),
        pressure,altitude,velocity,temperature:pick(o,['temp_c','temperature']),hz:pick(o,['odr_hz'])??hz,raw:JSON.stringify(o)});
    }
    return {samples,events,batches,kind};
  }
  function normalize(data) {
    const samples=data.samples.map(r=>({...r}));const events=(data.events||[]).map(e=>({...e}));
    const hz=data.hz||80;const map=new Map();
    for(const b of data.batches||[]){
      if(!Number.isInteger(b.n)||b.n<1||b.n>32||!finite(b.read)||!finite(b.seq))throw Error('Ancoraggio FIFO non valido.');
      for(let i=0;i<b.n;i++)map.set(b.seq+i,b.read-(b.n-1-i)/hz);
    }
    for(const r of samples)if(map.has(r.seq))r.tBatch=map.get(r.seq);
    const first=samples[0]||{},base=finite(first.tBatch)?first.tBatch:finite(first.tDevice)?first.tDevice:finite(first.tReceive)?first.tReceive:0;
    for(let i=0;i<samples.length;i++){
      const r=samples[i];r.timeline=(finite(r.tBatch)?r.tBatch:finite(r.tDevice)?r.tDevice:finite(r.tReceive)?r.tReceive:base+i/hz)-base;
    }
    for(const e of events)if(finite(e.deviceTick))e.t=e.deviceTick-base;
    return {...data,samples,events,hz};
  }
  function demo(data) {
    return normalize({...data,samples:data.samples.map(r=>({seq:r[0],tDevice:r[1],tReceive:r[2],tBatch:r[3],pressure:r[4],temperature:r[5]}))});
  }
  function csvExport(rows) {
    if(!rows.length)return '';
    const keys=[...new Set(rows.flatMap(r=>Object.keys(r)))];
    const esc=v=>v==null||typeof v==='number'&&!Number.isFinite(v)?'':'"'+String(v).replace(/"/g,'""')+'"';
    return keys.map(esc).join(',')+'\r\n'+rows.map(r=>keys.map(k=>esc(r[k])).join(',')).join('\r\n');
  }
  // Original lab curves inspired by configurable SkyDrop audio; not factory tables.
  const curvePoints=[[-5,150,.30,.20],[-1,250,.30,.20],[0,500,.24,.40],[.2,560,.22,.34],[.5,660,.18,.27],[1,800,.15,.20],[2,1030,.12,.13],[4,1350,.08,.08],[6,1600,.06,.05]];
  function curveAt(v){
    let i=0;while(i<curvePoints.length-2&&v>curvePoints[i+1][0])i++;
    const a=curvePoints[i],b=curvePoints[i+1],x=Math.max(0,Math.min(1,(v-a[0])/(b[0]-a[0])));
    return {hz:a[1]+x*(b[1]-a[1]),length:a[2]+x*(b[2]-a[2]),pause:a[3]+x*(b[3]-a[3])};
  }
  class SlowAudio {
    constructor(tau=1.5){if(!(finite(tau)&&tau>0))throw Error('Tau audio non valido.');this.tau=tau;this.last=null;}
    update(r,source){
      const v=source==='external'?r.velocity:r[source],t=r.tFilter;
      if(!finite(v)||!finite(t)){this.last=null;return null;}
      if(this.last===null||r.segment!==this.segment||t<=this.last)this.value=v;
      else this.value+=-Math.expm1(-(t-this.last)/this.tau)*(v-this.value);
      this.last=t;this.segment=r.segment;return this.value;
    }
  }
  function toneAtPhase(a,phase){
    if(a.mode==='silent')return {on:false,hz:0};
    if(a.splitTone)return {on:phase<a.duty,hz:phase<a.duty*a.splitFraction?a.hz:a.secondHz};
    if(!a.secondHz)return {on:a.duty===1||phase<a.duty,hz:a.hz};
    const t=phase*a.period;
    if(t<a.toneLength)return {on:true,hz:a.hz};
    if(t<a.toneLength+a.gap)return {on:false,hz:a.hz};
    return {on:t<2*a.toneLength+a.gap,hz:a.secondHz};
  }
  function audioState(v,options={},wasClimbing=false) {
    const o={climb:.1,sink:-.5,hysteresis:.04,base:550,slope:180,preset:'classic',hysteresisEnabled:false,toneScale:1,pauseScale:1,weak:false,weakWidth:.3,...options};
    if(!finite(v))return {mode:'silent',hz:0,period:0,duty:0};
    const threshold=(o.preset==='soft'||o.hysteresisEnabled)&&wasClimbing?o.climb-o.hysteresis:o.climb;
    const isClimb=v>=threshold,isSink=v<=o.sink,isWeak=o.weak&&!isClimb&&!isSink&&v>=o.climb-o.weakWidth;
    if(['curves','pair'].includes(o.preset)&&(isClimb||isSink||isWeak)){
      const mode=isClimb?'climb':isSink?'sink':'weak',c=curveAt(v);
      if(o.preset==='curves'&&isWeak)return {mode,hz:220+160*Math.max(0,Math.min(1,(v-o.climb+o.weakWidth)/o.weakWidth)),period:1,duty:1};
      if(o.preset==='curves'&&isSink)return {mode,hz:c.hz,period:1,duty:1};
      const length=c.length*o.toneScale,pause=c.pause*o.pauseScale;
      if(o.preset==='pair'){const secondHz=curveAt(v+(isClimb?.5:isSink?-.5:0)).hz,gap=.04,period=2*length+gap+pause;return {mode,hz:c.hz,secondHz,toneLength:length,gap,period,duty:(2*length+gap)/period};}
      return {mode,hz:c.hz,period:length+pause,duty:length/(length+pause)};
    }
    if(v>=threshold&&o.preset==='dualmean'){
      const hz=x=>Math.max(150,Math.min(1800,o.base+o.slope*x));
      return {mode:'climb',hz:hz(v),secondHz:hz(finite(o.slowVelocity)?o.slowVelocity:v),splitTone:true,splitFraction:Math.max(.1,Math.min(.9,o.splitFraction??.5)),period:Math.max(.12,.65/(1+Math.max(v,0)*1.4)),duty:Math.max(.1,Math.min(.9,o.beepDuty??.5))};
    }
    if(v>=threshold&&o.preset==='mini'){
      const x=Math.max(0,Math.min(10,v));
      const hz=Math.max(100,Math.min(2000,((-.33332*x+9.54324)*x-102.64693)*x*x+512.227*x+84.38465));
      const duration=Math.max(.06,Math.min(.6,(1.6478887*x*x-38.2889*x+341.275253)/1000));
      return {mode:'climb',hz,period:2*duration,duty:.5};
    }
    if(v>=threshold)return {mode:'climb',hz:Math.max(150,Math.min(1800,o.base+o.slope*v)),period:Math.max(.12,.65/(1+Math.max(v,0)*1.4)),duty:o.preset==='continuous'?1:.45};
    if(v<=o.sink)return {mode:'sink',hz:Math.max(120,Math.min(400,300+v*45)),period:1,duty:1};
    return {mode:'silent',hz:0,period:0,duty:0};
  }
  class BeepClock {
    constructor(){this.reset();}
    reset(){this.phase=0;this.last=null;this.mode='silent';}
    update(t,a){
      if(!finite(t)||a.mode==='silent'){this.reset();return false;}
      if(this.last===null||this.mode!==a.mode){this.phase=0;this.last=t;this.mode=a.mode;}
      const dt=Math.max(0,t-this.last);this.last=t;
      if(a.period>0)this.phase=(this.phase+dt/a.period)%1;
      return a.duty===1||this.phase<a.duty;
    }
  }
  return {defaults,finite,number,height,Filters,ScalarPressureLag,Pipeline,run,checksum,nmea,parseLine,LineDecoder,csvRows,parseCSV,normalize,demo,csvExport,audioState,curveAt,toneAtPhase,SlowAudio,BeepClock};
})();
