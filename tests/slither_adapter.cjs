// Tests the adapter contract with recorded-shape client objects, not the live website.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class HTMLCanvasElement {
  width=1600; height=1000; clientWidth=800; clientHeight=500;
  getBoundingClientRect() {return {left:20,top:30,right:820,bottom:530,width:800,height:500};}
}
class HTMLInputElement {
  value=''; dispatchEvent() {} blur() {}
}
const window = {mc:new HTMLCanvasElement(), nick:new HTMLInputElement(), playing:false,
  connecting:false, slither:null, gsc:2, view_xx:500,view_yy:500,mww:1600,mhh:1000,
  grd:1000, foods:[{xx:600,yy:500}], foods_c:1, slithers:[],fpsls:[0,2],fmlts:[1,2],
  connect() {this.connecting=true;}};
const document = {querySelector:()=>null,querySelectorAll:()=>[]};
vm.runInNewContext(fs.readFileSync('src/slither_bot/scripts/slither_adapter.js','utf8'),
  {window, document, HTMLCanvasElement,HTMLInputElement,Event:class {},innerWidth:900,innerHeight:600});
const adapter=window.__slitherAdapter;
assert.equal(adapter.capture(8).status,'MENU');
adapter.start('demo');
assert.equal(window.nick.value,'demo');
assert.equal(adapter.capture(8).status,'STARTING');
window.slither={id:7,xx:500,yy:500,ang:0,sct:1,fam:0,dead:false};
window.playing=true;window.connecting=false;
window.slithers=[window.slither,{id:8,xx:550,yy:500,pts:[{xx:560,yy:510}]}];
const first=adapter.capture(8);
assert.equal(first.status,'RUNNING');
assert.deepEqual([...first.center],[420,280]);
assert.equal(first.size,10);
assert.equal(first.food[0],1);
assert(first.enemies[0]>0 && first.enemies[0]<0.1);
assert(first.boundary.every(x=>x>=0 && x<=1));
assert(adapter.available(first.instance_id));
window.slither={...window.slither,id:9};
assert(!adapter.available(first.instance_id)); // rejects a respawn even before next capture
const next=adapter.capture(8);
assert.equal(next.instance_id,first.instance_id+1);
window.slither.dead=true;
assert.equal(adapter.capture(8).status,'DEAD');
window.slither=null;window.playing=false;
assert.equal(adapter.capture(8).size,null);
window.slither={id:10,xx:500,yy:500,ang:0};window.playing=true;
delete window.gsc;
assert.equal(adapter.capture(8).center,null);
assert(adapter.capture(8).enemies.every(x=>x===null));
console.log('Slither adapter checks passed: lifecycle, projection, features, missingness, respawn gate.');
