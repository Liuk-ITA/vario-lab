import assert from 'node:assert/strict';import {installAndStart} from './install-plan.mjs';
for(const [autorun,owned,expected] of [[true,false,['install','enable','run']],[false,true,['install','read','mode1','run']],[false,false,['install','read','run']]]){
  const calls=[];const repl={async installFile(){calls.push('install');},async bootControl(action,value){calls.push(action+(value??''));return {main_owned:owned};},async runInstalled(){calls.push('run');}};
  const result=await installAndStart(repl,new Uint8Array([1]),'hash',autorun);assert.deepEqual(calls,expected);assert.equal(result.autorunEnabled,autorun);
}
const failed=[];const repl={async installFile(){failed.push('install');},async bootControl(){throw Error('NVS unsupported');},async runInstalled(){failed.push('run');}};
await assert.rejects(installAndStart(repl,new Uint8Array([1]),'hash',true),/NVS/);assert.deepEqual(failed,['install']);
await installAndStart(repl,new Uint8Array([1]),'hash',false);assert.equal(failed.at(-1),'run');
console.log('PASS install pipeline: explicit enable before start, disabling existing autorun, untouched foreign startup, failure does not claim success');
