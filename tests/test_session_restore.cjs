const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = { Vue: { createApp: options => ({ mount: () => { context.options = options; } }) }, TagPicker: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/config.js'), 'utf8'), context);
const restore = context.options.methods.checkSession;

async function main() {
  let background = 0;
  const messages = [];
  const client = {
    authenticated: false,
    credentialForm: {},
    api: async (url, options) => {
      assert.equal(url, '/api/auth/session');
      assert.equal(options.cache, 'no-store');
      return { authenticated: true, username: 'remembered-user' };
    },
    loadApp: async () => { throw new Error('Komga unavailable'); },
    loadLoginBackground: async () => { background++; },
    notify: message => messages.push(message)
  };
  await restore.call(client);
  assert.equal(client.authenticated, true, 'App loading failure must not discard a valid session');
  assert.equal(client.credentialForm.username, 'remembered-user');
  assert.equal(background, 0);
  assert.match(messages.pop(), /登录已恢复/);

  client.api = async () => { throw new Error('Network unavailable'); };
  await restore.call(client);
  assert.equal(client.authenticated, true, 'Network failure is not proof of logout');
  assert.match(messages.pop(), /登录状态检查失败/);

  client.api = async () => ({ authenticated: false });
  await restore.call(client);
  assert.equal(client.authenticated, false);
  assert.equal(client.credentialForm.username, '');
  console.log('Session restoration regression tests passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
