// Keep the persistence/autorun sequence explicit and independently testable.
export async function installAndStart(repl,bytes,sha256,autorun,onBoot=()=>{},log=()=>{}){
  await repl.installFile(bytes,sha256);
  log('File app verificato sul dispositivo.');
  let boot=null,menuSelected=false;
  if(autorun){
    boot=await repl.bootControl('enable');onBoot(boot);
    log('Launcher con backup installato; avvio automatico abilitato.');
  }else{
    try{boot=await repl.bootControl('read');}catch(e){log('Impostazioni di avvio non modificate: '+e.message);}
    if(boot?.main_owned){boot=await repl.bootControl('mode',1);menuSelected=true;}
    if(boot)onBoot(boot);
  }
  await repl.runInstalled();
  return {autorunEnabled:autorun,menuSelected,boot};
}
