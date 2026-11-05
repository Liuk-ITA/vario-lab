export const MAX_APP=1024*1024;
export function safeURL(value,base=location.href){const u=new URL(value,base);if(!['https:','http:','blob:'].includes(u.protocol))throw Error('URL non supportato.');if(u.protocol==='http:'&&!['127.0.0.1','localhost','[::1]'].includes(u.hostname))throw Error('Usa HTTPS per i file remoti.');if(u.username||u.password)throw Error('Credenziali negli URL non consentite.');return u.href;}
export function validateManifest(m,base){
  if(!m||m.schema!==1||m.board!=='M5StickS3'||!['micropython-app','esp32-image'].includes(m.kind)||typeof m.version!=='string'||!m.version.length||m.version.length>100)throw Error('Manifest non compatibile con StickS3.');
  if(m.kind==='micropython-app'){
    if(!m.app||typeof m.app.url!=='string'||!m.app.url.length||!/^[a-f0-9]{64}$/i.test(m.app.sha256)||!Number.isInteger(m.app.bytes)||m.app.bytes<1||m.app.bytes>MAX_APP)throw Error('Dimensione o SHA-256 dell’app non validi.');
    return {...m,app:{...m.app,url:safeURL(m.app.url,base)}};
  }
  if(!m.flash||!Array.isArray(m.flash.parts)||!m.flash.parts.length||m.flash.parts.length>8)throw Error('Parti flash mancanti.');
  const parts=m.flash.parts.map(p=>{if(!Number.isInteger(p.offset)||p.offset<0||p.offset%4096||!Number.isInteger(p.bytes)||p.bytes<1||p.bytes>16*1024*1024||p.offset+p.bytes>8*1024*1024||!/^[a-f0-9]{64}$/i.test(p.sha256))throw Error('Parte flash non valida per StickS3 8 MB.');return {...p,url:safeURL(p.url,base)};}).sort((a,b)=>a.offset-b.offset);
  for(let i=1;i<parts.length;i++)if(parts[i].offset<parts[i-1].offset+parts[i-1].bytes)throw Error('Parti flash sovrapposte.');
  return {...m,flash:{parts}};
}
export async function digest(data){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(x=>x.toString(16).padStart(2,'0')).join('');}
export async function checkedFetch(asset,fetcher=fetch){const r=await fetcher(asset.url,{cache:'no-store'});if(!r.ok)throw Error('Download fallito: HTTP '+r.status);const data=new Uint8Array(await r.arrayBuffer());if(data.length!==asset.bytes||await digest(data)!==asset.sha256.toLowerCase())throw Error('Integrità non valida: dimensione o SHA-256 non corrispondono.');return data;}
export async function loadManifest(url,fetcher=fetch){url=safeURL(url);const r=await fetcher(url,{cache:'no-store'});if(!r.ok)throw Error('Manifest: HTTP '+r.status);return validateManifest(await r.json(),r.url||url);}
export async function githubRelease(repo,tag='latest',fetcher=fetch){
  if(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo))throw Error('Repository nel formato proprietario/nome.');
  const endpoint='https://api.github.com/repos/'+repo+'/releases/'+(tag==='latest'?'latest':'tags/'+encodeURIComponent(tag));
  const r=await fetcher(endpoint,{headers:{Accept:'application/vnd.github+json'}});if(!r.ok)throw Error('Release GitHub non disponibile: HTTP '+r.status);
  const release=await r.json();const asset=release.assets?.find(a=>a.name==='stick-vario.release.json')||release.assets?.find(a=>a.name==='stick-vario-system.release.json');if(!asset)throw Error('La release non contiene stick-vario.release.json.');
  return {url:safeURL(asset.browser_download_url),tag:release.tag_name,page:release.html_url};
}
export function checkPython(data){if(!data.length||data.length>MAX_APP||data.includes(0))throw Error('Seleziona uno script Python UTF-8, non un file binario.');const source=new TextDecoder('utf-8',{fatal:true}).decode(data);if(!source.includes('M5')||!source.includes('StickVarioApp'))throw Error('Il file non sembra il bundle Stick Vario.');return source;}
