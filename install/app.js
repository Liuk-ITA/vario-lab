import {validateManifest,loadManifest,checkedFetch,githubRelease,digest,checkPython,MAX_APP} from './releases.mjs?build=1.1.0';
import {SerialWire,RawRepl,REPL_BUILD} from './raw-repl.mjs?build=1.1.0';
import {installAndStart} from './install-plan.mjs?build=1.1.0';
const $=id=>document.getElementById(id);
const BUILD='1.1.0';
let manifest=null,app=null,wire=null,repl=null,busy=false,connected=false,localFiles=new Map(),blobURLs=[],bootInfo=null;
function message(s,error=false){$('notice').textContent=s;$('notice').classList.toggle('error',error);}
function log(s){$('log').textContent+=String(s)+'\n';$('log').scrollTop=$('log').scrollHeight;}
function state(){
  const isApp=manifest?.kind==='micropython-app';
  $('state').textContent=connected?'? USB collegata':'? Scollegato';
  $('connect').disabled=busy||connected||manifest?.kind==='esp32-image'||!navigator.serial;
  $('disconnect').disabled=busy||!connected;
  for(const id of ['ram','install'])$(id).disabled=busy||!connected||!isApp||!app;
  if(connected&&$('autorun').checked&&!bootInfo)$('install').disabled=true;
  $('run-installed').disabled=busy||!connected;
  $('prepare').disabled=busy||connected;$('source').disabled=busy||connected;
  $('flash-prepare').disabled=busy||connected||!$('flash-confirm').checked||manifest?.kind!=='esp32-image';
  $('app-actions').hidden=!!manifest&&!isApp;$('flash-actions').hidden=manifest?.kind!=='esp32-image';
  $('boot-read').disabled=busy||!connected;
  $('boot-apply').disabled=busy||!connected||!bootInfo;
  $('boot-enable').disabled=busy||!connected||!bootInfo?.app_exists;
  $('boot-restore').disabled=busy||!connected||!bootInfo?.restore_available;
}
function showBoot(info){
  bootInfo=info;
  const modes=['main.py diretto','menu UIFlow e rete','solo rete, poi main.py'];
  $('boot-state').textContent='Modalita: '+info.boot_option+' ? '+(modes[info.boot_option]||'non impostata')+'\nmain.py: '+(info.main_owned?'launcher Stick Vario':info.main_exists?'programma precedente':'assente')+'\nApp vario: '+(info.app_exists?'salvata':'non salvata')+'\nRipristino: '+(info.restore_available?'disponibile':'non necessario');
  $('boot-mode').value=String([0,1,2].includes(info.boot_option)?info.boot_option:1);
  state();
}
async function action(fn){if(busy)return;busy=true;state();try{await fn();}catch(e){message(e.message,true);log('ERRORE: '+e.message);}finally{busy=false;state();}}
function sourceFields(){for(const [id,kind] of [['github-fields','github'],['url-fields','url'],['file-fields','file']])$(id).hidden=$('source').value!==kind;manifest=null;app=null;$('release').hidden=true;$('download').hidden=true;state();}
function releaseURLs(){for(const u of blobURLs)URL.revokeObjectURL(u);blobURLs=[];$('flash-mount').replaceChildren();}
async function assetFetch(url,options){const file=localFiles.get(decodeURIComponent(new URL(url).pathname.split('/').pop()));if(file)return new Response(await file.arrayBuffer());if(localFiles.size)throw Error('Manca il file locale '+new URL(url).pathname.split('/').pop());return fetch(url,options);}
async function prepare(){releaseURLs();localFiles=new Map();app=null;manifest=null;const source=$('source').value;
  if(source==='file'){
    const files=[...$('files').files];if(!files.length)throw Error('Seleziona i file.');for(const f of files)localFiles.set(f.name,f);
    const meta=files.find(f=>f.name.endsWith('.json'));
    if(meta)manifest=validateManifest(JSON.parse(await meta.text()),new URL('local/'+encodeURIComponent(meta.name),location.href));
    else{const file=files.find(f=>f.name.endsWith('.py'));if(!file||files.length!==1||file.size>MAX_APP)throw Error('Seleziona un solo bundle .py oppure manifest e file.');app=new Uint8Array(await file.arrayBuffer());checkPython(app);manifest={schema:1,kind:'micropython-app',board:'M5StickS3',name:'Bundle locale',version:file.name,app:{url:'',bytes:app.length,sha256:await digest(app)}};}
  }else{
    let url=new URL('firmware/stick-vario.release.json',location.href).href;
    if(source==='url')url=$('manifest-url').value.trim();
    if(source==='github'){
      const release=await githubRelease($('repo').value.trim(),$('tag').value.trim()||'latest');url=release.url;log('GitHub: '+release.tag+' · '+release.page);
      const a=document.createElement('a');a.href=release.url;a.textContent='Scarica manifest da GitHub';$('release').replaceChildren(a);$('release').hidden=false;
    }
    try{manifest=await loadManifest(url);}catch(e){if(source==='github')throw Error('Release trovata, ma il browser non ha scaricato il manifest. Usa il mirror GitHub Pages o i file locali. '+e.message);throw e;}
  }
  if(manifest.kind==='micropython-app'){
    try{app??=await checkedFetch(manifest.app,assetFetch);}catch(e){throw Error(e.message+' Se il download remoto ? bloccato, usa il mirror GitHub Pages oppure scarica i file dalla release.');}checkPython(app);
    const url=URL.createObjectURL(new Blob([app],{type:'text/x-python'}));blobURLs.push(url);$('download').href=url;$('download').download='stick_vario_ram.py';$('download').hidden=false;
  }
  $('release').textContent=`${manifest.name||'Stick Vario'}\n${manifest.version}\n${manifest.kind==='micropython-app'?'App MicroPython / UIFlow2':'Immagine di sistema ESP32-S3'}${app?'\n'+app.length.toLocaleString('it-IT')+' byte · SHA-256 '+manifest.app.sha256:''}`;$('release').hidden=false;
  message('Versione pronta. '+(app?'Collega lo Stick per provarla o salvarla.':'Apri il flasher soltanto se vuoi sostituire il firmware di sistema.'));log('Manifest verificato: '+manifest.version);
}
let lastProgress=0;function progress(value){const now=Date.now();if(now-lastProgress<100&&value!==1)return;lastProgress=now;$('progress').hidden=false;$('progress').value=value;}
async function connect(){const port=await navigator.serial.requestPort();wire=new SerialWire(port);try{await wire.open();repl=new RawRepl(wire,progress);log('Ingresso REPL senza soft reset…');await repl.enter();const info=await repl.probe();connected=true;$('device').textContent=info.machine+' · MicroPython/UIFlow2 compatibile';message('Stick collegato. Il programma precedente è stato interrotto.');log(JSON.stringify(info));try{showBoot(await repl.bootControl());}catch(e){bootInfo=null;$('boot-state').textContent='Opzioni avvio non disponibili: '+e.message;log('Opzioni avvio non disponibili: '+e.message);}}catch(e){await wire.close();wire=null;repl=null;throw e;}}
async function disconnect(){if(repl)try{await repl.leave();}catch{}await wire?.close();wire=null;repl=null;connected=false;state();}
async function run(persist=false,existing=false){
  try{
    $('progress').hidden=false;$('progress').value=0;
    let installed=null;
    if(existing){log('Avvio app gia salvata...');await repl.runInstalled();}
    else if(persist){
      log('Scrittura app e verifica...');
      installed=await installAndStart(repl,app,manifest.app.sha256,$('autorun').checked,showBoot,log);
    }else{log('Caricamento in RAM...');await repl.runRAM(checkPython(app));}
    log('I,READY confermato: vario avviato.');
    await disconnect();$('progress').value=1;
    if(installed?.autorunEnabled)message('App installata e avviata. Avvio automatico del vario abilitato.');
    else if(installed?.menuSelected)message('App salvata e avviata. Al prossimo riavvio: menu UIFlow.');
    else if(persist)message('App salvata e avviata. Impostazioni di avvio non modificate.');
    else message('Variometro avviato. La porta USB e libera per il configuratore.');
  }catch(e){await disconnect();throw e;}
}
async function systemFlash(){
  if(!$('flash-confirm').checked||!manifest||manifest.kind!=='esp32-image')throw Error('Seleziona e conferma un’immagine di sistema.');
  const parts=[];for(const part of manifest.flash.parts){const bytes=await checkedFetch(part,assetFetch);const url=URL.createObjectURL(new Blob([bytes]));blobURLs.push(url);parts.push({path:url,offset:part.offset});log('Binario verificato a offset '+part.offset);}
  const doc={name:manifest.name||'Stick Vario',version:manifest.version,new_install_prompt_erase:true,new_install_improv_wait_time:0,builds:[{chipFamily:'ESP32-S3',parts}]};
  const url=URL.createObjectURL(new Blob([JSON.stringify(doc)],{type:'application/json'}));blobURLs.push(url);
  await import('https://unpkg.com/esp-web-tools@10/dist/web/install-button.js?module');
  const button=document.createElement('esp-web-install-button');button.manifest=url;const activate=document.createElement('button');activate.slot='activate';activate.textContent='Apri flasher ESP32-S3';button.append(activate);$('flash-mount').replaceChildren(button);message('Binari verificati. Il pulsante apre ESP Web Tools: la scrittura richiederà un’ulteriore azione esplicita.');
}
$('source').addEventListener('change',sourceFields);$('prepare').addEventListener('click',()=>action(prepare));$('connect').addEventListener('click',()=>action(connect));$('disconnect').addEventListener('click',()=>action(disconnect));$('ram').addEventListener('click',()=>action(()=>run()));$('install').addEventListener('click',()=>action(()=>run(true)));$('run-installed').addEventListener('click',()=>action(()=>run(false,true)));$('autorun').addEventListener('change',state);$('boot-read').addEventListener('click',()=>action(async()=>{showBoot(await repl.bootControl());message('Impostazioni di avvio lette.');}));$('boot-enable').addEventListener('click',()=>action(async()=>{showBoot(await repl.bootControl('enable'));message('Avvio automatico del vario abilitato. Tieni B all accensione per tornare al menu.');}));$('boot-restore').addEventListener('click',()=>action(async()=>{showBoot(await repl.bootControl('restore'));message('Programma di avvio e modalita precedenti ripristinati.');}));$('boot-apply').addEventListener('click',()=>action(async()=>{showBoot(await repl.bootControl('mode',Number($('boot-mode').value)));message('Modalita di avvio salvata, attiva al prossimo riavvio.');}));$('flash-confirm').addEventListener('change',state);$('flash-prepare').addEventListener('click',()=>action(systemFlash));
$('log').textContent='Installer '+BUILD+' ? '+REPL_BUILD+'\n';
const stamp=$('build');if(stamp)stamp.textContent='Installer '+BUILD+' ? '+REPL_BUILD;
sourceFields();if(!navigator.serial)message('Web Serial non disponibile. Usa un browser desktop compatibile su HTTPS o localhost.',true);
