const { createApp } = Vue;

createApp({
  data() {
    return {
      authenticated: false,
      loginForm: { username: '', password: '' },
      credentialForm: { username: '', password: '' },
      showCredentialModal: false,
      showCredentialConfirm: false,
      sidebarCollapsed: false,
      komgaAuthMode: 'password',
      showKomgaPassword: false,
      showKomgaApiKey: false,
      showBangumiToken: false,
      dragIndex: null,
      contextMenu: { visible: false, x: 0, y: 0, index: null },
      view: 'scrape',
      message: '',
      messageError: false,
      libraries: [],
      records: [],
      cards: [],
      cardHues: [105, 270, 195, 35, 320, 155],
      status: { running: false, last_result: null, last_error: null },
      config: {
        BANGUMI_ACCESS_TOKEN: '', KOMGA_BASE_URL: '', KOMGA_EMAIL: '', KOMGA_EMAIL_PASSWORD: '', KOMGA_API_KEY: '',
        KOMGA_LIBRARY_LIST: [], BANGUMI_KOMGA_SERVICE_TYPE: 'poll', BANGUMI_KOMGA_SERVICE_POLL_INTERVAL: 20,
        BANGUMI_KOMGA_SERVICE_POLL_REFRESH_ALL_METADATA_INTERVAL: 10000
      },
      navItems: [
        { id: 'scrape', label: '刮削卡片', title: '刮削卡片', subtitle: '为不同媒体库配置独立的增量匹配规则', icon: '▦' },
        { id: 'records', label: '刮削记录', title: '刮削记录', subtitle: '查看已完成的漫画与小说元数据更新', icon: '◷' },
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
  watch: { view(value) { if (value === 'records') this.loadRecords(); } },
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
      const config = await this.api('/api/config'); this.config = { ...this.config, ...config }; this.komgaAuthMode = this.config.KOMGA_API_KEY ? 'key' : 'password'; this.cards = (config.KOMGA_LIBRARY_LIST || []).map((item, index) => this.makeCard(item, index));
      if (this.config.KOMGA_BASE_URL && (this.komgaAuthMode === 'key' ? this.config.KOMGA_API_KEY : (this.config.KOMGA_EMAIL && this.config.KOMGA_EMAIL_PASSWORD))) await this.loadLibraries(false);
      this.pollStatus();
    },
    makeCard(item = {}, index = 0) { return { uid: `${Date.now()}-${Math.random()}`, id: item.LIBRARY || '', name: '', path: '', isNovel: !!item.IS_NOVEL_ONLY, rules: item.REQUIRED_FIELDS || [], showRules: false, hue: this.cardHues[index % this.cardHues.length] }; },
    addCard() { this.cards.push(this.makeCard({}, this.cards.length)); },
    removeCard(index) { this.cards.splice(index, 1); },
    dragStart(index, event) { this.dragIndex = index; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(index)); },
    dropCard(index) { if (this.dragIndex === null || this.dragIndex === index) return; const [card] = this.cards.splice(this.dragIndex, 1); this.cards.splice(index, 0, card); this.dragIndex = null; },
    openCardMenu(index, event) { const menuWidth = 150, menuHeight = 44; this.contextMenu = { visible: true, index, x: Math.min(event.clientX, window.innerWidth - menuWidth - 12), y: Math.min(event.clientY, window.innerHeight - menuHeight - 12) }; },
    closeContextMenu() { if (this.contextMenu.visible) this.contextMenu = { visible: false, x: 0, y: 0, index: null }; },
    deleteCard(index) { this.removeCard(index); this.closeContextMenu(); this.notify('媒体库卡片已删除'); },
    syncCardName(card) { const library = this.libraries.find(item => item.id === card.id); if (library) { card.name = library.name; card.path = library.root || library.path || ''; } },
    async loadLibraries(showMessage = true) {
      const hasCredentials = this.komgaAuthMode === 'key' ? !!this.config.KOMGA_API_KEY : !!(this.config.KOMGA_EMAIL && this.config.KOMGA_EMAIL_PASSWORD);
      if (!this.config.KOMGA_BASE_URL || !hasCredentials) { if (showMessage) this.notify('请先填写 Komga 地址和认证信息', true); return; }
      try { const data = await this.api('/api/komga/libraries'); this.libraries = data.items || []; this.cards.forEach(card => this.syncCardName(card)); if (showMessage) this.notify(`已读取 ${this.libraries.length} 个媒体库`); }
      catch (error) { if (showMessage) this.notify(error.message, true); }
    },
    collectConfig() { const next = { ...this.config, KOMGA_LIBRARY_LIST: this.cards.filter(card => card.id).map(card => ({ LIBRARY: card.id, IS_NOVEL_ONLY: card.isNovel, REQUIRED_FIELDS: card.rules })) }; if (this.komgaAuthMode === 'key') { next.KOMGA_EMAIL = ''; next.KOMGA_EMAIL_PASSWORD = ''; } else { next.KOMGA_API_KEY = ''; } return next; },
    async save() { try { this.config = await this.api('/api/config', { method: 'POST', body: JSON.stringify(this.collectConfig()) }); this.notify('设置已保存'); } catch (error) { this.notify(error.message, true); } },
    async refresh(full) { try { await this.api('/api/refresh', { method: 'POST', body: JSON.stringify({ full }) }); this.notify(full ? '全量刮削已开始' : '增量刮削已开始'); } catch (error) { this.notify(error.message, true); } },
    async loadRecords() { try { this.records = (await this.api('/api/scrape-records?limit=100')).items || []; } catch (error) { this.notify(error.message, true); } },
    metadataText(record) { const labels = { status: '状态', summary: '简介', publisher: '出版商', genres: '流派', tags: '标签', title: '标题', alternateTitles: '别名', ageRating: '年龄分级', links: 'Bangumi 链接', totalBookCount: '册数', language: '语言', titleSort: '标题排序', authors: '作者', isbn: 'ISBN', number: '卷号', releaseDate: '发行日期', numberSort: '卷号排序', thumbnail: '封面' }; return (record.metadata_fields || []).map(field => labels[field] || field).join('、'); },
    async pollStatus() { if (!this.authenticated) return; try { this.status = await this.api('/api/status'); } catch (_) {} setTimeout(() => this.pollStatus(), 3000); },
    openCredentialModal() { this.credentialForm = { username: '', password: '' }; this.showCredentialModal = true; },
    requestCredentialSave() { if (!this.credentialForm.username || !this.credentialForm.password) { this.notify('账号和密码不能为空', true); return; } this.showCredentialConfirm = true; },
    async confirmCredentialSave() { try { await this.api('/api/auth/credentials', { method: 'POST', body: JSON.stringify(this.credentialForm) }); this.showCredentialConfirm = false; this.showCredentialModal = false; this.loginForm.username = this.credentialForm.username; this.notify('后台账号密码已更新，请牢记新密码'); } catch (error) { this.notify(error.message, true); } }
  }
}).mount('#app');
