export const UUID={service:'a50e0001-2d94-4c9a-983d-1abf4300c001',tx:'a50e0002-2d94-4c9a-983d-1abf4300c001',rx:'a50e0003-2d94-4c9a-983d-1abf4300c001'};
export const DEFAULTS={filters:['kal','reg','lp','dual','sky'],sounds:['dolce','ricco','dispari','fm_ferma'],volumes:[0,64,110,160,190,220,255],base_notes:[1000,1250,1500,1750,2000,2250,2500],patterns:['classic','continuous','dualmean','curves','pair'],remote_hid:false,grove_buttons:false,base_hz:1500,pattern:'classic',climb_on:.1,climb_off:.06,sink_on:-.5,sink_off:-.3};
export function validate(c){
  if(c&&typeof c==='object')for(const k of ['base_notes','patterns','remote_hid','grove_buttons'])if(!(k in c))c[k]=structuredClone(DEFAULTS[k]);
  if(!c||typeof c!=='object'||Object.keys(c).sort().join()!=Object.keys(DEFAULTS).sort().join())throw Error('Campi di configurazione non validi.');
  for(const key of ['filters','sounds','patterns'])if(!Array.isArray(c[key])||!c[key].length||new Set(c[key]).size!==c[key].length||c[key].some(x=>!DEFAULTS[key].includes(x)))throw Error('Seleziona almeno una voce valida per '+key+'.');
  if(!Array.isArray(c.volumes)||!c.volumes.length||c.volumes.length>12||c.volumes[0]!==0||c.volumes.some((x,i)=>!Number.isInteger(x)||x<0||x>255||(i&&x<=c.volumes[i-1])))throw Error('Volumi: valori interi unici da 0 a 255, incluso muto.');
  if(!Array.isArray(c.base_notes)||!c.base_notes.length||c.base_notes.length>16||new Set(c.base_notes).size!==c.base_notes.length||c.base_notes.some(x=>!Number.isInteger(x)||x<550||x>2500))throw Error('Frequenze del ciclo: da 550 a 2500 Hz, uniche e almeno una.');
  if(typeof c.grove_buttons!=='boolean')throw Error('Opzione pulsanti Grove non valida.');
  if(typeof c.remote_hid!=='boolean')throw Error('Opzione telecomando non valida.');
  if(!Number.isInteger(c.base_hz)||c.base_hz<550||c.base_hz>2500)throw Error('Frequenza: da 550 a 2500 Hz.');
  if(!DEFAULTS.patterns.includes(c.pattern))throw Error('Andamento non valido.');
  for(const key of ['climb_on','climb_off','sink_on','sink_off'])if(typeof c[key]!=='number'||!Number.isFinite(c[key])||Math.abs(c[key])>10)throw Error('Soglia non valida.');
  if(!(0<=c.climb_off&&c.climb_off<c.climb_on&&c.climb_on<=5))throw Error('La soglia di disattivazione salita deve essere inferiore a quella di attivazione.');
  if(!(-10<=c.sink_on&&c.sink_on<c.sink_off&&c.sink_off<=0))throw Error('La soglia di disattivazione discesa deve essere superiore a quella di attivazione.');
  return c;
}
export class LineDecoder{
  constructor(onLine){this.buffer='';this.decoder=new TextDecoder();this.onLine=onLine;}
  push(bytes){this.buffer+=this.decoder.decode(bytes,{stream:true});let end;while((end=this.buffer.indexOf('\n'))>=0){const line=this.buffer.slice(0,end).replace(/\r$/,'');this.buffer=this.buffer.slice(end+1);this.onLine(line);}if(this.buffer.length>8192)this.buffer='';}
}
export class Client{
  constructor(send,timeout=12000){this.send=send;this.timeout=timeout;this.next=0;this.pending=new Map();this.writes=Promise.resolve();this.fragments=new Map();}
  request(op,fields={}){const id=++this.next;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this.pending.delete(id);this.fragments.delete(id);reject(Error('Lo Stick non risponde. Verifica di avere il firmware configurabile e la connessione attiva.'));},this.timeout);this.pending.set(id,{resolve,reject,timer});const line=JSON.stringify({v:1,id,op,...fields})+'\n';this.writes=this.writes.catch(()=>{}).then(()=>this.send(line));this.writes.catch(e=>{const p=this.pending.get(id);if(p){clearTimeout(timer);this.pending.delete(id);reject(e);}});});}
  receive(line){
    if(line.startsWith('@CF1 ')){
      const match=/^@CF1 (\d+):(\d+):(\d+):([A-Za-z0-9+/=]*)$/.exec(line);if(!match)return;
      const [id,index,total]=match.slice(1,4).map(Number);if(!this.pending.has(id)||total<1||total>64||index>=total)return;
      let group=this.fragments.get(id);if(!group||group.total!==total){group={total,parts:new Map()};this.fragments.set(id,group);}
      group.parts.set(index,match[4]);if(group.parts.size!==total)return;
      try{const text=atob(Array.from({length:total},(_,i)=>group.parts.get(i)).join(''));line=new TextDecoder().decode(Uint8Array.from(text,c=>c.charCodeAt(0)));}catch{return;}finally{this.fragments.delete(id);}
    }
    if(line.startsWith('@CFG '))line=line.slice(5);if(!line.startsWith('{'))return;let r;try{r=JSON.parse(line);}catch{return;}if(r.v!==1)return;const p=this.pending.get(r.id);if(!p)return;this.pending.delete(r.id);this.fragments.delete(r.id);clearTimeout(p.timer);if(r.ok)p.resolve(r);else p.reject(Error(r.error||'Configurazione rifiutata.'));
  }
  close(){for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(Error('Dispositivo scollegato.'));}this.pending.clear();this.fragments.clear();}
}
