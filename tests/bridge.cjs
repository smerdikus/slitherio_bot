// DOM bridge logic check; this does not launch a browser or verify physical input.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const handlers = new Map(), documentHandlers = new Map(), events = [];
let now = 0;
const window = {
  __slitherBridgeConfig: {generation:0, mode:'AI', keys:{toggle_mode:'F8',
    toggle_training:'F9', checkpoint:'F10', restart:'F11', shutdown:'Escape'}},
  __slitherInput: async event => {events.push(event);},
  addEventListener: (kind, fn) => {handlers.set(kind, [...(handlers.get(kind) || []), fn]);},
};
const document = {hidden:false, addEventListener: (kind, fn) => documentHandlers.set(kind, fn)};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,
  '../src/slither_bot/scripts/input_bridge.js'), 'utf8'), {window, document, performance:{now:()=>now}});
function fire(kind, properties = {}) {
  const event = {code:'', repeat:false, prevented:false, stopped:false,
    preventDefault() {this.prevented=true;}, stopImmediatePropagation() {this.stopped=true;},
    ...properties};
  for (const handler of handlers.get(kind) || []) {handler(event); if(event.stopped) break;}
  return event;
}
const bridge = window.__slitherBridge;
assert(bridge.claim({id:1, kind:'pointer', generation:0, x:100, y:200}));
fire('pointermove', {clientX:100, clientY:200, buttons:0, isTrusted:true});
assert.equal(events.at(-1).origin, 'automation_candidate');
assert.equal(events.at(-1).payload.command_id, 1);
const before = events.length;
assert(fire('keydown', {code:'F8', repeat:true}).prevented);
assert.equal(events.length, before);
assert.equal(bridge.state.generation, 0);
assert(fire('keydown', {code:'F8'}).prevented);
assert.equal(bridge.state.mode, 'HUMAN');
assert.equal(bridge.state.generation, 1);
assert.equal(bridge.claim({id:2, kind:'boost', down:true, generation:0}), false);
assert(bridge.claim({id:3, kind:'boost', down:false, generation:1, cleanup:true}));
fire('keyup', {code:'ShiftLeft', isTrusted:true});
assert.equal(events.at(-1).origin, 'automation_candidate');
fire('keydown', {code:'Space', isTrusted:true});
assert.equal(events.at(-1).origin, 'human_candidate');
fire('keydown', {code:'F8'});
fire('blur');
assert.equal(bridge.state.mode, 'HUMAN');
const generation = bridge.state.generation;
fire('blur');
assert.equal(bridge.state.generation, generation);
fire('focus');
assert.equal(bridge.state.mode, 'HUMAN');
fire('keydown', {code:'F8'});
assert(bridge.claim({id:4, kind:'pointer', generation:bridge.state.generation, x:100, y:200}));
now = 501;
fire('pointermove', {clientX:100, clientY:200, buttons:0, isTrusted:true});
assert.equal(events.at(-1).origin, 'human_candidate');
fire('keydown', {code:'Escape'});
assert.equal(bridge.claim({id:5, kind:'boost', generation:bridge.state.generation, down:true}), false);
console.log('Bridge checks passed: shortcuts, repeat suppression, generation, focus, ledger, shutdown.');
