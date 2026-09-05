const { createApp } = Vue;

createApp({
  data() {
    return {
      authenticated: false,
      loginForm: { username: 'admin', password: 'password' },
      credentialForm: { username: '', password: '' },
      showCredentialModal: false,
      showCredentialConfirm: false,
      sidebarCollapsed: false,
      view: 'scrape',
      message: '',
      messageError: false,
      libraries: [],
      logs: [],
      cards: [],
      cardHues: [105, 270, 195, 35, 320, 155],
      status: { running: false, last_result: null, last_error: null },
      config: {
        BANGUMI_ACCESS_TOKEN: '', KOMGA_BASE_URL: '', KOMGA_EMAIL: '', KOMGA_EMAIL_PASSWORD: '',
        KOMGA_LIBRARY_LIST: [], BANGUMI_KOMGA_SERVICE_TYPE: 'poll', BANGUMI_KOMGA_SERVICE_POLL_INTERVAL: 20,
        BANGUMI_KOMGA_SERVICE_POLL_REFRESH_ALL_METADATA_INTERVAL: 10000
      },
      navItems: [
        { id: 'scrape', label: '刮削卡片', title: '刮削卡片', subtitle: '为不同媒体库配置独立的增量匹配规则', icon: '▦' },
        { id: 'logs', label: '运行日志', title: '运行日志', subtitle: '查看服务状态与最近的刮削记录', icon: '≡' },
        { id: 'settings', label: '系统设置', title: '系统设置', subtitle: '连接服务、Bangumi 密钥与账号安全', icon: '⚙' }
      ],
      fieldOptions: [
        { value: 'summary', label: '简介' }, { value: 'publisher', label: '出版商' },
        { value: 'genres', label: '流派' }, { value: 'tags', label: '标签' },
        { value: 'links', label: 'Bangumi 链接' }, { value: 'thumbnail', label: '封面' }
      ]
    };
  },
  computed: {
    currentNav() { return this.navItems.find(item => item.id === this.view) || this.navItems[0]; },
    lastRunText() { return this.status.last_result ? `最近完成：${this.status.last_result === 'full' ? '全量刮削' : '增量刮削'}` : '尚未执行刮削'; },
    credentialHint() { return this.loginForm.username || '已登录'; }
  },
  async mounted() { await this.checkSession(); },
  methods: {
    async api(path, options = {}) {
      const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`);
      return data;
    },
    notify(text, error = false) { this.message = text; this.messageError = error; if (text) setTimeout(() => { this.message = ''; }, 3500); },
    async checkSession() {
      try { const session = await this.api('/api/auth/session'); this.authenticated = session.authenticated; if (this.authenticated) await this.loadApp(); } catch (_) { this.authenticated = false; }
    },
    async login() {
      try { await this.api('/api/auth/login', { method: 'POST', body: JSON.stringify(this.loginForm) }); this.authenticated = true; this.loginForm.password = ''; await this.loadApp(); }
      catch (error) { this.notify(error.message, true); }
    },
    async logout() { await this.api('/api/auth/logout', { method: 'POST', body: '{}' }); this.authenticated = false; },
    async loadApp() {
      const config = await this.api('/api/config'); this.config = { ...this.config, ...config }; this.cards = (config.KOMGA_LIBRARY_LIST || []).map((item, index) => this.makeCard(item, index));
      if (this.config.KOMGA_BASE_URL && this.config.KOMGA_EMAIL && this.config.KOMGA_EMAIL_PASSWORD) await this.loadLibraries(false);
      this.pollStatus();
    },
    makeCard(item = {}, index = 0) { return { uid: `${Date.now()}-${Math.random()}`, id: item.LIBRARY || '', name: '', path: '', isNovel: !!item.IS_NOVEL_ONLY, rules: item.REQUIRED_FIELDS || [], showRules: false, hue: this.cardHues[index % this.cardHues.length] }; },
    addCard() { this.cards.push(this.makeCard({}, this.cards.length)); },
    removeCard(index) { this.cards.splice(index, 1); },
    syncCardName(card) { const library = this.libraries.find(item => item.id === card.id); if (library) { card.name = library.name; card.path = library.root || library.path || ''; } },
    async loadLibraries(showMessage = true) {
      if (!this.config.KOMGA_BASE_URL || !this.config.KOMGA_EMAIL || !this.config.KOMGA_EMAIL_PASSWORD) return;
      try { const data = await this.api('/api/komga/libraries'); this.libraries = data.items || []; this.cards.forEach(card => this.syncCardName(card)); if (showMessage) this.notify(`已读取 ${this.libraries.length} 个媒体库`); }
      catch (error) { if (showMessage) this.notify(error.message, true); }
    },
    collectConfig() { return { ...this.config, KOMGA_LIBRARY_LIST: this.cards.filter(card => card.id).map(card => ({ LIBRARY: card.id, IS_NOVEL_ONLY: card.isNovel, REQUIRED_FIELDS: card.rules })) }; },
    async save() { try { this.config = await this.api('/api/config', { method: 'POST', body: JSON.stringify(this.collectConfig()) }); this.notify('设置已保存'); } catch (error) { this.notify(error.message, true); } },
    async refresh(full) { try { await this.api('/api/refresh', { method: 'POST', body: JSON.stringify({ full }) }); this.notify(full ? '全量刮削已开始' : '增量刮削已开始'); } catch (error) { this.notify(error.message, true); } },
    async loadLogs() { try { this.logs = (await this.api('/api/logs')).lines || []; } catch (error) { this.notify(error.message, true); } },
    logClass(line) { return /ERROR|CRITICAL/i.test(line) ? 'error' : /WARN/i.test(line) ? 'warn' : ''; },
    async pollStatus() { if (!this.authenticated) return; try { this.status = await this.api('/api/status'); if (this.view === 'logs') await this.loadLogs(); } catch (_) {} setTimeout(() => this.pollStatus(), 3000); },
    openCredentialModal() { this.credentialForm = { username: '', password: '' }; this.showCredentialModal = true; },
    requestCredentialSave() { if (!this.credentialForm.username || !this.credentialForm.password) { this.notify('账号和密码不能为空', true); return; } this.showCredentialConfirm = true; },
    async confirmCredentialSave() { try { await this.api('/api/auth/credentials', { method: 'POST', body: JSON.stringify(this.credentialForm) }); this.showCredentialConfirm = false; this.showCredentialModal = false; this.loginForm.username = this.credentialForm.username; this.notify('后台账号密码已更新，请牢记新密码'); } catch (error) { this.notify(error.message, true); } }
  }
}).mount('#app');
