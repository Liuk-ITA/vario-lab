// MicroPython raw/raw-paste protocol. No soft reset, bootloader or DTR reset.
import {BOOT_CODE} from './boot-control.mjs?build=1.1.0';
export const REPL_BUILD='native-probe-3';
export const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const encoder=new TextEncoder(),decoder=new TextDecoder();
export class SerialWire{
  constructor(port){this.port=port;this.buffer=[];this.waiters=[];this.closed=false;this.error=null;}
  async open(){await this.port.open({baudRate:115200});try{await this.port.setSignals({dataTerminalReady:false,requestToSend:false});}catch{}this.reader=this.port.readable.getReader();this.writer=this.port.writable.getWriter();this.readTask=this.readLoop();}
  async readLoop(){try{while(true){const {value,done}=await this.reader.read();if(done)break;for(const b of value)this.buffer.push(b);if(this.buffer.length>4*1024*1024)throw Error('Buffer seriale troppo grande.');this.wake();}}catch(e){this.error=e;}finally{this.closed=true;this.wake();}}
  wake(){for(const fn of this.waiters.splice(0))fn();}
  async read(n,timeout=10000){const end=Date.now()+timeout;while(this.buffer.length<n){if(this.closed)throw this.error||Error('Seriale scollegata.');const left=end-Date.now();if(left<=0)throw Error('Timeout seriale.');await new Promise(resolve=>{const done=()=>{clearTimeout(timer);const i=this.waiters.indexOf(done);if(i>=0)this.waiters.splice(i,1);resolve();};const timer=setTimeout(done,left);this.waiters.push(done);});}return new Uint8Array(this.buffer.splice(0,n));}
  async until(marker,timeout=10000,limit=1024*1024){const out=[];const end=Date.now()+timeout;while(out.length<limit){out.push((await this.read(1,Math.max(1,end-Date.now())))[0]);if(out.length>=marker.length&&marker.every((b,i)=>out[out.length-marker.length+i]===b))return new Uint8Array(out);}throw Error('Risposta seriale troppo lunga.');}
  async write(data){await this.writer.write(typeof data==='string'?encoder.encode(data):data);}
  async close(){try{await this.reader?.cancel();}catch{}try{await this.readTask;}catch{}try{this.reader?.releaseLock();this.writer?.releaseLock();}catch{}try{await this.port.close();}catch{}this.closed=true;this.wake();}
}
export class RawRepl{
  constructor(wire,progress=()=>{}){this.wire=wire;this.progress=progress;this.raw=false;}
  async enter(){await sleep(1200);this.wire.buffer.length=0;await this.wire.write(new Uint8Array([13,3,3]));await sleep(300);await this.wire.write(new Uint8Array([13,1]));await this.wire.until(encoder.encode('raw REPL; CTRL-B to exit\r\n>'));this.raw=true;}
  async start(code){if(!this.raw)throw Error('REPL non collegata.');const bytes=typeof code==='string'?encoder.encode(code):code;await this.wire.write(new Uint8Array([5,65,1]));const response=await this.wire.read(2);
    if(response[0]===82&&response[1]===1){
      const header=await this.wire.read(2);const window=header[0]+256*header[1];if(!window)throw Error('Finestra raw-paste non valida.');let remaining=window,index=0;
      while(index<bytes.length){while(remaining===0||this.wire.buffer.length){const b=(await this.wire.read(1,30000))[0];if(b===1)remaining+=window;else if(b===4){await this.wire.write(new Uint8Array([4]));const result=await this.follow();throw Error('Compilazione interrotta: '+result.stderr);}else throw Error('Controllo raw-paste inatteso: '+b);}
        const n=Math.min(remaining,bytes.length-index);await this.wire.write(bytes.slice(index,index+n));index+=n;remaining-=n;this.progress(index/bytes.length);
      }
      await this.wire.write(new Uint8Array([4]));await this.wire.until(new Uint8Array([4]),30000);
    }else{
      if(!(response[0]===82&&response[1]===0))await this.wire.until(encoder.encode('w REPL; CTRL-B to exit\r\n>'));
      for(let i=0;i<bytes.length;i+=256){await this.wire.write(bytes.slice(i,i+256));this.progress(Math.min(1,(i+256)/bytes.length));await sleep(10);}
      await this.wire.write(new Uint8Array([4]));const ok=decoder.decode(await this.wire.read(2));if(ok!=='OK')throw Error('Esecuzione raw REPL rifiutata.');
    }
  }
  async follow(timeout=30000){const stdout=await this.wire.until(new Uint8Array([4]),timeout);const stderr=await this.wire.until(new Uint8Array([4]),timeout);await this.wire.until(new Uint8Array([62]),timeout);return {stdout:decoder.decode(stdout.slice(0,-1)),stderr:decoder.decode(stderr.slice(0,-1))};}
  async exec(code){const progress=this.progress;this.progress=()=>{};try{await this.start(code);const r=await this.follow();if(r.stderr.trim())throw Error(r.stderr.trim());return r.stdout;}finally{this.progress=progress;}}
  async probe(){
    const code=[
      'import sys,os,json',
      'import M5,micropython',
      '_sv_viper_ok=False',
      "_sv_viper_error=''",
      'try:',
      " exec('@micropython.viper\\ndef _sv_native_probe(x:int)->int:\\n return x+1\\n')",
      ' _sv_viper_ok=_sv_native_probe(41)==42',
      'except Exception as _sv_error:',
      ' _sv_viper_error=str(_sv_error)',
      "print('SV_PROBE '+json.dumps({'machine':os.uname().machine,'runtime':sys.version,'speaker':hasattr(M5.Speaker,'playWav'),'viper':_sv_viper_ok,'viper_attribute':hasattr(micropython,'viper'),'viper_error':_sv_viper_error,'board':M5.getBoard() if hasattr(M5,'getBoard') else None}))"
    ].join('\n');
    const text=await this.exec(code),line=text.split('\n').find(s=>s.startsWith('SV_PROBE '));
    if(!line)throw Error('Runtime non riconosciuto.');
    const info=JSON.parse(line.slice(9));
    if(!info.speaker)throw Error('Il runtime non espone M5.Speaker.playWav.');
    if(!info.viper)throw Error('Prova compilatore Viper fallita: '+(info.viper_error||'risultato inatteso')+' ? Dati: '+JSON.stringify(info));
    if(!/ESP32.?S3/i.test(info.machine)||!(/stick.*s3/i.test(info.machine)||info.board===26||/stick.*s3/i.test(String(info.board))))throw Error('Scheda diversa da M5StickS3: '+info.machine+' (board '+info.board+').');
    return info;
  }
  async waitReady(timeout=20000){const lines=[];const end=Date.now()+timeout;while(Date.now()<end){const line=decoder.decode(await this.wire.until(new Uint8Array([10]),Math.max(1,end-Date.now()),16384)).trim();lines.push(line);if(line.startsWith('I,READY,')&&line.includes('audio=1'))return lines;if(line.includes('Traceback')||line.startsWith('E,FATAL')||line.startsWith('E,AUDIO_INIT')||line.startsWith('E,BLE_INIT'))throw Error(line);}throw Error('Avvio non confermato.');}
  async runRAM(source){await this.start(source);return this.waitReady();}
  async installFile(bytes,expectedHash){
    const target='/flash/stick_vario_app.py',temp=target+'.new';
    await this.exec("import binascii,os,hashlib\n_sv_file=open('"+temp+"','wb')");
    try{
      for(let i=0;i<bytes.length;i+=768){const chunk=bytes.slice(i,i+768);let text='';for(const b of chunk)text+=String.fromCharCode(b);await this.exec("_sv_file.write(binascii.a2b_base64('"+btoa(text)+"'))");this.progress(Math.min(1,(i+chunk.length)/bytes.length));}
      await this.exec('_sv_file.close()');
      const verification=await this.exec("_sv_hash=hashlib.sha256()\nwith open('"+temp+"','rb') as _sv_read:\n while True:\n  _sv_data=_sv_read.read(1024)\n  if not _sv_data:break\n  _sv_hash.update(_sv_data)\nprint('SV_HASH '+binascii.hexlify(_sv_hash.digest()).decode())\nwith open('"+temp+"') as _sv_read:compile(_sv_read.read(),'stick_vario_app.py','exec')");
      if(!verification.includes('SV_HASH '+expectedHash))throw Error('Verifica SHA-256 sul dispositivo fallita.');
      await this.exec("try:os.stat('"+target+"')\nexcept OSError as _sv_e:\n if _sv_e.args[0]!=2:raise\nelse:\n with open('"+target+"','rb') as _sv_old,open('"+target+".previous','wb') as _sv_backup:\n  while True:\n   _sv_data=_sv_old.read(1024)\n   if not _sv_data:break\n   _sv_backup.write(_sv_data)\nos.rename('"+temp+"','"+target+"')\nprint('SV_INSTALLED')");
    }catch(e){try{await this.exec('try:_sv_file.close()\nexcept Exception:pass');}catch{}throw e;}
    return target;
  }
  async runInstalled(){await this.start("exec(open('/flash/stick_vario_app.py').read(),globals())");return this.waitReady();}
  async bootControl(action='read',value=null){
    await this.exec(BOOT_CODE);
    const code="print('SV_BOOT '+json.dumps(sv_boot("+JSON.stringify(action)+","+(value===null?'None':JSON.stringify(value))+")))";
    const text=await this.exec(code),line=text.split('\n').find(s=>s.startsWith('SV_BOOT '));
    if(!line)throw Error('Risposta impostazioni di avvio assente.');
    return JSON.parse(line.slice(8));
  }
  async leave(){if(this.raw){await this.wire.write(new Uint8Array([13,2]));this.raw=false;}}
}
