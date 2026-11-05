'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
vm.runInThisContext(fs.readFileSync(path.join(root,'i18n/catalog.js'),'utf8'));
const {translate}=VarioTranslations;
assert.equal(translate('Collega USB'),'Connect USB');
assert.equal(translate('Nessun dispositivo collegato.'),'No device connected.');
assert.equal(translate('  Collega USB  '),'  Connect USB  ');
assert.equal(translate('12.610 campioni'),'12,610 samples');
assert.equal(translate('Collega USB','it'),'Collega USB');
assert.equal(translate('LK8EX1,100000,99999,150,20,1080,*AB'),'LK8EX1,100000,99999,150,20,1080,*AB');

// Exercise the real UI layer with a small DOM double: updates, round trips and
// excluded technical logs must preserve their source rather than retranslate English.
let observer,languageEvent;
class Text {
  constructor(value,parent){this.nodeType=3;this.nodeValue=value;this.parentElement=parent;}
}
class Element {
  constructor(tag){this.nodeType=1;this.tag=tag;this.childNodes=[];this.attrs={};this.dataset={};this.listeners={};}
  append(node){this.childNodes.push(node);if(node.nodeType===3)node.parentElement=this;else node.parent=this;}
  closest(){return ['pre','code','script','style','textarea'].includes(this.tag)||this.dataset.i18nOwned!==undefined||this.parent?.closest()?this:null;}
  hasAttribute(name){return name in this.attrs;}
  getAttribute(name){return this.attrs[name];}
  setAttribute(name,value){this.attrs[name]=value;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  set textContent(value){this.childNodes=[new Text(value,this)];}
}
const html=new Element('html'),header=new Element('header'),body=new Element('body');
const button=new Element('button'),input=new Element('input'),log=new Element('pre');
button.textContent='Collega USB';input.value='1500';input.setAttribute('placeholder','Es. 80, 140');
log.textContent='Ingresso REPL senza soft reset…';body.append(button);body.append(input);body.append(log);
html.append(header);html.append(body);
global.document={documentElement:html,body,readyState:'complete',
  createElement:tag=>new Element(tag),querySelector:()=>header,querySelectorAll:()=>[],
  getElementById:()=>header.childNodes.find(x=>x.dataset.i18nOwned!==undefined)?.childNodes[0]};
global.window={dispatchEvent:event=>{languageEvent=event;}};
global.localStorage={getItem:()=>null,setItem:()=>{}};
global.MutationObserver=class{constructor(fn){observer=fn;}observe(){}};
vm.runInThisContext(fs.readFileSync(path.join(root,'i18n/ui.js'),'utf8'));
assert.equal(html.lang,'en');assert.equal(button.childNodes[0].nodeValue,'Connect USB');
assert.equal(input.value,'1500');assert.equal(input.getAttribute('placeholder'),'E.g. 80, 140');
assert.equal(log.childNodes[0].nodeValue,'Ingresso REPL senza soft reset…');
window.VarioI18n.setLanguage('it');assert.equal(button.childNodes[0].nodeValue,'Collega USB');
button.textContent='Scollega';observer([{type:'childList',addedNodes:button.childNodes}]);
window.VarioI18n.setLanguage('en');assert.equal(button.childNodes[0].nodeValue,'Disconnect');
observer([{type:'characterData',target:button.childNodes[0]}]);
window.VarioI18n.setLanguage('it');assert.equal(button.childNodes[0].nodeValue,'Scollega');
assert.equal(languageEvent.type,'variolanguagechange');
console.log(JSON.stringify({suite:'i18n',status:'PASS',coverage:'switch without reload; dynamic text; source restoration; unchanged input and protocol/log text'}));
