// Offline controller checks. No real browser session, provider or SMTP request.
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', hidden: true, textContent: '', className: '', checked: false,
    disabled: false, children: [], handlers: {}, classList: {remove() {}},
    addEventListener(name, handler) {this.handlers[name] = handler;},
    replaceChildren(...children) {this.children = children; this.firstChild = children[0];},
    append(...children) {this.children.push(...children);}, pause() {}, removeAttribute() {},
  });
  return elements.get(id);
}
const context = vm.createContext({
  document: {getElementById: element, querySelector: () => ({content: 'offline-token'}),
    createElement: () => element(Symbol())},
  window: {addEventListener() {}}, fetch: () => new Promise(() => {}),
  localStorage: {setItem() {}, getItem() {return null;}, removeItem() {}},
  URL: {revokeObjectURL() {}}, setTimeout, clearTimeout,
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../sunojob/static/app.js'), 'utf8'), context);
const session = (id, version = 3) => ({id, version, state: 'both_confirmed', language: 'en-IN',
  readback: null, customer_confirmation: {reply: 'I confirm'}, owner_confirmation: {name: 'Demo Owner'},
  card: {sources: [], extraction: {instructions: [], questions: [], corrections: []}}});
const job = (version = 3) => ({version, state: 'complete', created_at: '2026-11-07T19:00:00+00:00',
  sender: 'sender@example.com',
  targets: [{role: 'customer', address: 'customer@example.com', status: 'accepted_by_smtp'},
    {role: 'owner', address: 'owner@example.com', status: 'accepted_by_smtp'}]});
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  context.session = session('first'); context.jobs = [job()]; context.calls = [];
  vm.runInContext('api=async(path,body)=>{calls.push({path,body});return jobs;};render(session);', context);
  await flush();
  assert.equal(element('customer-email').value, 'customer@example.com');
  assert.equal(element('owner-email').value, 'owner@example.com');
  assert.equal(element('email-reviewed').checked, false);
  assert.equal(vm.runInContext('emailPreview', context), null);
  assert.equal(context.calls.some(call => call.body !== undefined), false);
  element('customer-email').value = 'my-edit@example.com';
  element('customer-email').handlers.input();
  await vm.runInContext('loadEmailJobs(current.id)', context);
  assert.equal(element('customer-email').value, 'my-edit@example.com');
  context.session = {...session('first'), state: 'needs_correction', pending_text: 'Make it 45'};
  context.jobs = [job(), {...job(), state: 'prepared'}];
  vm.runInContext('render(session)', context);
  await flush();
  assert.equal(element('receipt-panel').hidden, true);
  assert.equal(element('email-history-panel').hidden, false);
  assert.equal(element('email-jobs').children.length, 2);
  assert.match(element('email-jobs').children[0].children[0].textContent, /Both copies accepted/);
  assert.match(element('email-jobs').children[0].children[1].textContent, /sender@example.com/);
  assert.match(element('email-jobs').children[1].children[0].textContent, /not sent/);
  assert.equal(element('send-emails').disabled, true);
  context.session = session('first', 4);
  vm.runInContext('render(session)', context);
  await flush();
  assert.equal(element('customer-email').value, '');
  assert.equal(element('owner-email').value, '');
  context.oldSession = session('old'); context.newSession = session('new');
  let resolveOld;
  context.delayed = new Promise(resolve => {resolveOld = resolve;});
  vm.runInContext("api=async(path)=>path.includes('/old/')?delayed:[];render(oldSession);render(newSession);", context);
  resolveOld([job()]);
  await flush();
  assert.equal(element('customer-email').value, '');
  assert.equal(element('owner-email').value, '');
  assert.match(vm.runInContext("indiaTime('2026-11-07T19:00:00+00:00')", context), /8 Nov 2026/);
  assert.match(vm.runInContext("indiaTime('2026-11-07T19:00:00+00:00')", context), /12:30:00/);
  assert.match(vm.runInContext("indiaTime('2026-11-07T19:00:00+00:00')", context), /IST/);
  const label = vm.runInContext("mailTarget({role:'customer',address:'customer@example.com',status:'accepted_by_smtp',detail:'Accepted by SMTP; inbox delivery is not verified'})", context);
  assert.equal((label.match(/Accepted by SMTP/g) || []).length, 1);
  console.log('Recipient restoration, pending-correction email history, preview separation, version isolation, no automatic sends and IST checks passed.');
})().catch(error => {console.error(error);process.exitCode = 1;});
