const { createApp } = Vue;

createApp({
  components: { TagPicker },
  data() {
    return {
      authenticated: false,
      loginForm: { username: '', password: '' },
      showLoginPassword: false,
      loginBackground: [],
      loginBackgroundTimer: null,
      credentialForm: { username: '', password: '' },
      showCredentialModal: false,
      showCredentialConfirm: false,
      sidebarCollapsed: false,
      komgaAuthMode: 'password',
      showKomgaPassword: false,
      showKomgaApiKey: false,
      showBangumiToken: false,
      showOpenAiKey: false,
      showServerDraftSecret: false,
      bangumiTestQuery: '',
      bangumiTestMessage: '',
      bangumiTestError: false,
      bangumiTestBusy: false,
      bangumiTestResults: [],
      showBangumiPreview: false,
      previewBangumiSubject: null,
      dragIndex: null,
      contextMenu: { visible: false, x: 0, y: 0, index: null },
      editingCard: null,
      editingCardOriginal: null,
      editingCardIsNew: false,
      editingServer: null,
      serverDraft: { id: '', name: '', base_url: '', email: '', password: '', api_key: '', auth_mode: 'password' },
      view: window.location.hash.slice(1) || 'scrape',
      message: '',
      messageError: false,
      libraries: [],
      records: [],
      logs: [],
      logSearch: '',
      logStats: { total: 0, today: 0, success: 0, failed: 0 },
      recordPage: 1, logPage: 1, recordTotal: 0, logTotal: 0,
      recordRequest: 0, logRequest: 0,
      tasks: [],
      editingTask: null,
      deletingTask: null,
      taskDragIndex: null,
      taskDragMoved: false,
      liveRefreshTimer: null,
      taskTypeOptions: [
        { value: 'metadata_correction', label: '元数据修正' },
        { value: 'metadata_completion', label: '元数据补全' },
        { value: 'summary_translation', label: 'AI翻译' },
        { value: 'card_collage_refresh', label: '卡片拼贴刷新' }
      ],
      cardFeatureOptions: [
        { value: 'scrapeEnabled', label: '刮削匹配' },
        { value: 'aiRecognition', label: 'AI 识别' },
        { value: 'sortVolumes', label: '卷号排序' },
        { value: 'loginBackground', label: '登录背景', detail: '允许未登录访客查看该媒体库封面' }
      ],
      serviceModeOptions: [
        { value: 'sse', label: '实时监控（SSE，推荐）' },
        { value: 'poll', label: '定时轮询增量' },
        { value: 'once', label: '仅手动执行' }
      ],
      mediaTypeOptions: [
        { value: 'comic', label: '漫画匹配' },
        { value: 'book', label: '书籍匹配' },
        { value: 'mixed', label: '混合匹配' }
      ],
      correctionOptions: [
        { value: 'simplify', label: '繁转简' },
        { value: 'extract_title', label: '标题提取' }
      ],
      recordSearch: '',
      recordSortNewest: true,
      expandedRecordIds: [],
      recordStats: { total: 0, today: 0, comic: 0, novel: 0 },
      cards: [],
      cardHues: [105, 270, 195, 35, 320, 155],
      status: { running: false, last_result: null, last_error: null },
      config: {
        BANGUMI_ACCESS_TOKEN: '', OPENAI_BASE_URL: '', OPENAI_API_KEY: '', OPENAI_MODEL: '', TRANSLATE_SUMMARY_TO_ZH: false,
        KOMGA_BASE_URL: '', KOMGA_EMAIL: '', KOMGA_EMAIL_PASSWORD: '', KOMGA_API_KEY: '',
        KOMGA_SERVERS: [], KOMGA_LIBRARY_LIST: [], BANGUMI_KOMGA_SERVICE_TYPE: 'sse', BANGUMI_KOMGA_SERVICE_POLL_INTERVAL: 20,
        BANGUMI_KOMGA_SERVICE_POLL_REFRESH_ALL_METADATA_INTERVAL: 10000
        ,RECORD_RETENTION_DAYS: 30, LOG_RETENTION_DAYS: 30, METADATA_TASKS: []
      },
      navItems: [
        { id: 'scrape', label: '媒体卡片', title: '媒体卡片', subtitle: '为不同媒体库配置独立的匹配规则' },
        { id: 'records', label: '刮削记录', title: '刮削记录', subtitle: '按书籍查看每一卷的元数据匹配结果' },
        { id: 'tasks', label: '计划任务', title: '计划任务', subtitle: '按媒体库安排元数据补全任务' },
        { id: 'logs', label: '运行日志', title: '运行日志', subtitle: '查看后台操作与刮削执行轨迹' },
        { id: 'settings', label: '系统设置', title: '系统设置', subtitle: '连接服务、Bangumi 密钥与账号安全' }
      ],
      requiredFieldOptions: [
        { value: 'title', label: '标题' }, { value: 'summary', label: '简介' }, { value: 'publisher', label: '出版商' },
        { value: 'genres', label: '流派' }, { value: 'tags', label: '标签' },
        { value: 'links', label: 'Bangumi 链接' }, { value: 'thumbnail', label: '封面' }
      ],
      overwriteFieldOptions: [
        { value: 'title', label: '标题' }, { value: 'summary', label: '简介' }, { value: 'status', label: '状态' },
        { value: 'publisher', label: '出版商' }, { value: 'genres', label: '流派' }, { value: 'tags', label: '标签' },
        { value: 'alternateTitles', label: '别名' }, { value: 'ageRating', label: '年龄分级' }, { value: 'links', label: 'Bangumi 链接' },
        { value: 'totalBookCount', label: '册数' }, { value: 'language', label: '语言' }, { value: 'titleSort', label: '标题排序' },
        { value: 'authors', label: '作者' }, { value: 'isbn', label: 'ISBN' }, { value: 'number', label: '卷号' },
        { value: 'releaseDate', label: '发行日期' }, { value: 'numberSort', label: '卷号排序' }, { value: 'thumbnail', label: '封面' }
      ]
    };
  },
  computed: {
    loginBackgroundColumns() {
      if (!this.loginBackground.length) return [];
      return Array.from({length:6}, (_, column) => Array.from({length:6}, (_, row) =>
        this.loginBackground[(column*6+row)%this.loginBackground.length]));
    },
    serviceModeChoice: {
      get() { return [this.config.BANGUMI_KOMGA_SERVICE_TYPE]; },
      set(values) { if (values[0]) { this.config.BANGUMI_KOMGA_SERVICE_TYPE = values[0]; this.saveServiceMode(); } }
    },
    editingMediaType: {
      get() { return [this.editingCard?.mediaType || 'comic']; },
      set(values) { if (values.length) this.editingCard.mediaType = values[0]; }
    },
    taskMetadataOptions() { return this.editingTask?.functions.some(value => ['summary_translation', 'metadata_correction'].includes(value)) ? this.overwriteFieldOptions.filter(option => ['title', 'summary', 'publisher', 'authors'].includes(option.value)) : this.overwriteFieldOptions; },
    cardServerOptions() { return this.config.KOMGA_SERVERS.map(server => ({value:server.id,label:server.name})); },
    cardLibraryOptions() { return this.libraries.map(library => ({value:library.id,label:library.name})); },
    editingServerChoice: {
      get() { return this.editingCard?.serverId ? [this.editingCard.serverId] : []; },
      set(values) { this.editingCard.serverId = values[0] || ''; this.changeCardServer(this.editingCard); }
    },
    editingLibraryChoice: {
      get() { return this.editingCard?.id ? [this.editingCard.id] : []; },
      set(values) { this.editingCard.id = values[0] || ''; this.syncCardName(this.editingCard); }
    },
    taskLibraryOptions() {
      return this.cards.filter(card => card.id).map(card => ({
        value: this.taskLibraryKey(card), label: card.name || '未命名媒体库', detail: this.cardServerName(card)
      }));
    },
    editingCardFeatures: {
      get() { return this.cardFeatureOptions.filter(option => this.editingCard?.[option.value]).map(option => option.value); },
      set(values) { this.cardFeatureOptions.forEach(option => { this.editingCard[option.value] = values.includes(option.value); }); }
    },
    currentNav() { return this.navItems.find(item => item.id === this.view) || this.navItems[0]; },
    activeServer() { return this.config.KOMGA_SERVERS && this.config.KOMGA_SERVERS[0]; },
    lastRunText() { if (!this.status.last_result) return '尚未执行刮削'; if (this.status.last_result === 'full') return '最近完成：全量刮削'; if (this.status.last_result.includes('card_collage')) return '最近完成：卡片拼贴刷新'; return '最近完成：增量刮削'; },
    credentialHint() { return this.loginForm.username || '已登录'; }
    ,filteredRecords() {
      const keyword = this.recordSearch.trim().toLocaleLowerCase();
      if (!keyword) return this.records;
      return this.records.filter(record => [record.item_type, record.item_title, record.source_title, record.matched_title, record.match_source, record.source_path, record.library_name, record.server_name, ...(record.metadata_fields || []), ...((record.volumes || []).flatMap(volume => [volume.item_title, volume.matched_title, volume.match_source, volume.source_path, ...(volume.metadata_fields || [])]))].some(value => String(value || '').toLocaleLowerCase().includes(keyword)));
    },
    sortedRecords() {
      return [...this.records].sort((a, b) => {
        const left = String(a.recorded_at || ''), right = String(b.recorded_at || '');
        return this.recordSortNewest ? right.localeCompare(left) : left.localeCompare(right);
      });
    }
  },
  watch: {
    authenticated(value) { clearInterval(this.loginBackgroundTimer); if (!value) this.loadLoginBackground(); else this.loginBackground = []; },
    recordSearch() { this.recordPage = 1; this.loadRecords(); },
    logSearch() { this.logPage = 1; this.loadLogs(); },
    'editingTask.functions'(values, previous) {
      if (!this.editingTask || !previous || values?.[0] === previous?.[0]) return;
      this.editingTask.fields = [];
      this.editingTask.operations = [];
      this.editingTask.ai_completion = false;
      this.editingTask.include_locked = false;
      this.editingTask.lock_completed = false;
    },
    view(value) { if (!['scrape', 'records', 'tasks', 'logs', 'settings'].includes(value)) { this.view = 'scrape'; return; } history.replaceState(null, '', `#${value}`); document.title = `${this.currentNav.title} · BangumiKomga`; this.closeContextMenu(); if (value === 'records') this.loadRecords(true); if (value === 'logs') this.loadLogs(true); if (value === 'tasks') this.loadTasks(); this.startLiveRefresh(); this.$nextTick(() => this.decorateFieldLabels()); },
    bangumiTestQuery() { this.resetBangumiSearch(); }
  },
  async mounted() { document.addEventListener('keydown', this.closeTopModal); document.addEventListener('wheel', this.handleServerWheel, { passive: false }); document.addEventListener('visibilitychange', this.startLiveRefresh); if (!['scrape', 'records', 'tasks', 'logs', 'settings'].includes(this.view)) this.view = 'scrape'; document.title = `${this.currentNav.title} · BangumiKomga`; await this.checkSession(); this.startLiveRefresh(); this.$nextTick(() => this.decorateFieldLabels()); },
  beforeUnmount() { document.removeEventListener('keydown', this.closeTopModal); document.removeEventListener('wheel', this.handleServerWheel); document.removeEventListener('visibilitychange', this.startLiveRefresh); clearInterval(this.liveRefreshTimer); },
  methods: {
    closeTopModal(event) {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      if (document.querySelector('.tag-picker-panel')) {
        document.dispatchEvent(new Event('close-tag-pickers'));
        return;
      }
      if (this.showCredentialConfirm) this.showCredentialConfirm = false;
      else if (this.deletingTask) this.deletingTask = null;
      else if (this.showBangumiPreview) this.showBangumiPreview = false;
      else if (this.editingServer) this.editingServer = null;
      else if (this.editingTask) this.editingTask = null;
      else if (this.editingCard) this.closeCardSettings();
      else if (this.showCredentialModal) this.showCredentialModal = false;
      else this.closeContextMenu();
    },
    decorateFieldLabels() {
      document.querySelectorAll('#app label').forEach(label => {
        if (label.querySelector(':scope > .field-label')) return;
        const textNode = Array.from(label.childNodes).find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
        if (!textNode) return;
        const span = document.createElement('span');
        span.className = 'field-label';
        span.textContent = textNode.textContent.trim();
        textNode.remove();
        label.insertBefore(span, label.firstChild);
      });
    },
    async api(path, options = {}) {
      const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`);
      return data;
    },
    notify(text, error = false) { this.message = text; this.messageError = error; if (text) setTimeout(() => { this.message = ''; }, 3500); },
    async checkSession() {
      try { const session = await this.api('/api/auth/session'); this.authenticated = session.authenticated; this.credentialForm.username = session.authenticated ? session.username || '' : ''; if (this.authenticated) await this.loadApp(); else await this.loadLoginBackground(); } catch (_) { this.authenticated = false; await this.loadLoginBackground(); }
    },
    async loadLoginBackground() {
      if (this.authenticated) return;
      let pending = false;
      try { const data = await this.api('/api/login-background'); pending = !!data.pending; if (!this.authenticated) this.loginBackground = data.items || []; } catch (_) { this.loginBackground = []; }
      clearInterval(this.loginBackgroundTimer);
      if (!this.authenticated) this.loginBackgroundTimer = setInterval(() => this.loadLoginBackground(), pending ? 2000 : 60000);
    },
    async login() {
      try { await this.api('/api/auth/login', { method: 'POST', body: JSON.stringify(this.loginForm) }); this.authenticated = true; this.credentialForm.username = this.loginForm.username; this.loginForm.password = ''; await this.loadApp(); }
      catch (error) { this.notify(error.message, true); }
    },
    async logout() { await this.api('/api/auth/logout', { method: 'POST', body: '{}' }); this.loginForm = {username:'',password:''}; this.showLoginPassword = false; this.authenticated = false; },
    async loadApp() {
      const config = await this.api('/api/config'); this.applyConfig(config);
      if (this.config.KOMGA_BASE_URL && (this.komgaAuthMode === 'key' ? this.config.KOMGA_API_KEY : (this.config.KOMGA_EMAIL && this.config.KOMGA_EMAIL_PASSWORD))) await this.loadLibraries(false);
      await Promise.all(this.cards.filter(card => card.serverId && card.id).map(card => this.loadCardPreview(card)));
      if (this.view === 'records') await this.loadRecords(true);
      else if (this.view === 'logs') await this.loadLogs(true);
      else if (this.view === 'tasks') await this.loadTasks();
      this.pollStatus();
    },
    applyConfig(config) { this.config = { ...this.config, ...config, KOMGA_SERVERS: (config.KOMGA_SERVERS || []).map(server => ({ auth_mode: server.auth_mode || (server.api_key ? 'key' : 'password'), ...server })) }; this.tasks = this.config.METADATA_TASKS || []; if (!this.config.KOMGA_SERVERS.length && this.config.KOMGA_BASE_URL) this.config.KOMGA_SERVERS = [{ id: 'legacy', name: '默认 Komga', base_url: this.config.KOMGA_BASE_URL, email: this.config.KOMGA_EMAIL, password: this.config.KOMGA_EMAIL_PASSWORD, api_key: this.config.KOMGA_API_KEY, auth_mode: this.config.KOMGA_API_KEY ? 'key' : 'password' }]; this.komgaAuthMode = this.config.KOMGA_API_KEY ? 'key' : 'password'; this.cards = (this.config.KOMGA_LIBRARY_LIST || []).map((item, index) => this.makeCard(item, index)); },
    makeCard(item = {}, index = 0) { const defaultOverwriteFields = this.overwriteFieldOptions.map(field => field.value); return { uid: `${Date.now()}-${Math.random()}`, id: item.LIBRARY || '', serverId: item.SERVER_ID || '', name: '', path: '', covers: [], mediaType: ['comic','book','mixed'].includes(item.MEDIA_TYPE) ? item.MEDIA_TYPE : item.IS_NOVEL_ONLY ? 'book' : 'comic', scrapeEnabled: item.SCRAPE_ENABLED !== false, rules: item.REQUIRED_FIELDS || [], overwriteFields: Array.isArray(item.OVERWRITE_FIELDS) ? item.OVERWRITE_FIELDS : defaultOverwriteFields, aiRecognition: !!item.AI_RECOGNITION, sortVolumes: !!item.SORT_VOLUMES, loginBackground: !!item.LOGIN_BACKGROUND, hue: this.cardHues[index % this.cardHues.length] }; },
    mediaTypeLabel(card) { return {comic:'漫画媒体库',book:'书籍媒体库',mixed:'混合媒体库'}[card.mediaType] || '漫画媒体库'; },
    addCard() { const card = this.makeCard({}, this.cards.length); this.cards.push(card); this.openCardSettings(card, true); },
    resetServerDraft() { this.serverDraft = { id: '', name: '', base_url: '', email: '', password: '', api_key: '', auth_mode: 'password' }; this.showServerDraftSecret = false; },
    addServer() { const draft = this.serverDraft; if (!draft.name.trim() || !draft.base_url.trim()) { this.notify('请填写 Komga 名称和地址', true); return; } if (draft.auth_mode === 'key' ? !draft.api_key : (!draft.email || !draft.password)) { this.notify('请填写完整的 Komga 认证信息', true); return; } (this.config.KOMGA_SERVERS ||= []).push({ ...draft, id: `server-${Date.now()}`, name: draft.name.trim(), base_url: draft.base_url.trim().replace(/\/$/, '') }); this.resetServerDraft(); this.notify('Komga 服务器已添加'); },
    removeServer(index) { this.config.KOMGA_SERVERS.splice(index, 1); },
    openServerEditor(server) { this.editingServer = { ...server }; this.$nextTick(() => this.decorateFieldLabels()); },
    saveServerEdit() { const index = this.config.KOMGA_SERVERS.findIndex(item => item.id === this.editingServer.id); if (index >= 0) this.config.KOMGA_SERVERS.splice(index, 1, { ...this.editingServer, name: this.editingServer.name.trim(), base_url: this.editingServer.base_url.trim().replace(/\/$/, '') }); this.editingServer = null; this.notify('Komga 服务器已更新'); },
    removeCard(index) { this.cards.splice(index, 1); },
    dragStart(index, event) { this.dragIndex = index; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(index)); },
    dropCard(index) { if (this.dragIndex === null || this.dragIndex === index) return; const [card] = this.cards.splice(this.dragIndex, 1); this.cards.splice(index, 0, card); this.dragIndex = null; },
    openCardMenu(index, event) { const menuWidth = 170, menuHeight = 132; this.contextMenu = { visible: true, index, x: Math.min(event.clientX, window.innerWidth - menuWidth - 12), y: Math.min(event.clientY, window.innerHeight - menuHeight - 12) }; },
    closeContextMenu() { if (this.contextMenu.visible) this.contextMenu = { visible: false, x: 0, y: 0, index: null }; },
    async deleteCard(index) { const card = this.cards[index]; if (!card) return; this.removeCard(index); this.closeContextMenu(); if (await this.save()) this.notify('媒体卡片已删除'); else this.cards.splice(index, 0, card); },
    openCardSettings(card, isNew = false) { this.editingCard = card; this.editingCardOriginal = isNew ? null : JSON.parse(JSON.stringify(card)); this.editingCardIsNew = isNew; this.closeContextMenu(); this.$nextTick(() => this.decorateFieldLabels()); if (card.serverId) this.loadCardLibraries(card); },
    closeCardSettings(event) {
      if (event && (event.type === 'submit' || (event.submitter && event.submitter.type === 'submit'))) { this.saveCardSettings(); return; }
      const index = this.editingCard ? this.cards.indexOf(this.editingCard) : -1;
      if (this.editingCardIsNew && index >= 0) this.cards.splice(index, 1);
      else if (this.editingCard && this.editingCardOriginal && index >= 0) this.cards.splice(index, 1, this.editingCardOriginal);
      this.editingCard = null; this.editingCardOriginal = null; this.editingCardIsNew = false;
    },
    async saveCardSettings() {
      if (!this.editingCard || !this.editingCard.serverId || !this.editingCard.id) { this.notify('请先选择 Komga 服务和媒体库', true); return; }
      const saved = await this.save();
      if (!saved) return;
      this.editingCard = null; this.editingCardOriginal = null; this.editingCardIsNew = false;
      this.notify('媒体库卡片已保存');
    },
    syncCardName(card) { const library = this.libraries.find(item => item.id === card.id); if (library) { card.name = library.name; card.path = library.root || library.path || ''; this.loadCardPreview(card); } },
    changeCardServer(card) { card.id = ''; card.name = ''; card.path = ''; card.covers = []; this.libraries = []; this.loadCardLibraries(card); },
    async loadCardLibraries(card) { this.libraries = []; const serverId = card.serverId; if (!serverId) return; try { const data = await this.api(`/api/komga/libraries?server_id=${encodeURIComponent(serverId)}`); if (card.serverId !== serverId || this.editingCard !== card) return; this.libraries = data.items || []; this.syncCardName(card); } catch (error) { this.notify(error.message, true); } },
    async loadCardPreview(card, force = false) { if (!card.serverId || !card.id) { card.covers = []; return; } try { const data = await this.api(`/api/komga/previews?server_id=${encodeURIComponent(card.serverId)}&library_id=${encodeURIComponent(card.id)}${force ? '&refresh=1' : ''}`); const items = data.items || []; card.covers = items.length ? Array.from({length:9}, (_, index) => ({...items[index % items.length], preview_id:`${items[index % items.length].id}-${index}`,failed:false})) : []; } catch (_) { card.covers = []; } },
    coverError(cover) { cover.failed = true; },
    async refreshCardPreview(index) { const card = this.cards[index]; this.closeContextMenu(); await this.loadCardPreview(card, true); this.notify('封面拼贴已刷新'); },
    async loadLibraries(showMessage = true) {
      const server = this.activeServer;
      const hasCredentials = server ? (server.auth_mode === 'key' ? !!server.api_key : !!(server.email && server.password)) : (this.komgaAuthMode === 'key' ? !!this.config.KOMGA_API_KEY : !!(this.config.KOMGA_EMAIL && this.config.KOMGA_EMAIL_PASSWORD));
      if (!(server ? server.base_url : this.config.KOMGA_BASE_URL) || !hasCredentials) { if (showMessage) this.notify('请先填写 Komga 地址和认证信息', true); return; }
      try { const data = await this.api(`/api/komga/libraries${this.activeServer ? `?server_id=${encodeURIComponent(this.activeServer.id)}` : ''}`); this.libraries = data.items || []; this.cards.forEach(card => this.syncCardName(card)); if (showMessage) this.notify(`已读取 ${this.libraries.length} 个媒体库`); }
      catch (error) { if (showMessage) this.notify(error.message, true); }
    },
    async testServer(server) {
      try {
        const data = await this.api(`/api/komga/libraries?server_id=${encodeURIComponent(server.id)}`);
        this.libraries = data.items || [];
        this.notify(`${server.name || 'Komga 服务'} 连接成功，读取到 ${this.libraries.length} 个媒体库`);
      } catch (error) { this.notify(`连接失败：${error.message}`, true); }
    },
    collectConfig() { const next = { ...this.config, KOMGA_LIBRARY_LIST: this.cards.filter(card => card.id).map(card => ({ LIBRARY: card.id, SERVER_ID: card.serverId, IS_NOVEL_ONLY: card.mediaType === 'book', MEDIA_TYPE: card.mediaType, SCRAPE_ENABLED: card.scrapeEnabled, REQUIRED_FIELDS: card.rules, OVERWRITE_FIELDS: card.overwriteFields, TRANSLATE_SUMMARY_TO_ZH: false, AI_RECOGNITION: card.aiRecognition, SORT_VOLUMES: card.sortVolumes, LOGIN_BACKGROUND: card.loginBackground })) }; if (this.komgaAuthMode === 'key') { next.KOMGA_EMAIL = ''; next.KOMGA_EMAIL_PASSWORD = ''; } else { next.KOMGA_API_KEY = ''; } return next; },
    stepRetention(key, step) { this.config[key] = Math.max(1, Math.min(365, Number(this.config[key] || 30) + step)); this.save(); },
    async save() { try { this.config = await this.api('/api/config', { method: 'POST', body: JSON.stringify(this.collectConfig()) }); this.notify('设置已保存'); return true; } catch (error) { this.notify(error.message, true); return false; } },
    async saveServiceMode() { await this.save(); this.$nextTick(() => this.decorateFieldLabels()); },
    async testBangumiSearch() {
      const query = this.bangumiTestQuery.trim();
      if (!query) { this.bangumiTestMessage = '请输入漫画或小说名称'; this.bangumiTestError = true; return; }
      this.bangumiTestBusy = true; this.bangumiTestMessage = ''; this.bangumiTestError = false; this.bangumiTestResults = [];
      try {
        const data = await this.api(`/api/bangumi/search?q=${encodeURIComponent(query)}`);
        const items = data.items || []; this.bangumiTestResults = items;
        this.bangumiTestMessage = items.length ? `搜索成功：${items.slice(0, 3).map(item => item.name_cn || item.name).join('、')}` : '未找到匹配条目';
        this.bangumiTestError = !items.length;
      } catch (error) { this.bangumiTestMessage = `搜索失败：${error.message}`; this.bangumiTestError = true; }
      finally { this.bangumiTestBusy = false; }
    },
    resetBangumiSearch() {
      this.bangumiTestResults = []; this.bangumiTestMessage = ''; this.bangumiTestError = false;
      this.previewBangumiSubject = null; this.showBangumiPreview = false;
    },
    async previewBangumi() {
      const first = this.bangumiTestResults[0];
      if (!first) return;
      try { const data = await this.api(`/api/bangumi/subject?id=${encodeURIComponent(first.id)}`); this.previewBangumiSubject = data.item || first; this.showBangumiPreview = true; }
      catch (error) { this.notify(error.message, true); }
    },
    toggleCardField(card, key, value) { const fields = Array.isArray(card[key]) ? [...card[key]] : []; const index = fields.indexOf(value); if (index >= 0) fields.splice(index, 1); else fields.push(value); card[key] = fields; },
    async backupConfig() { try { const data = await this.api('/api/config/backup'); const blob = new Blob([JSON.stringify(data.config, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `bangumikomga-config-${new Date().toISOString().slice(0, 10)}.json`; link.click(); URL.revokeObjectURL(link.href); this.notify('配置备份已下载'); } catch (error) { this.notify(error.message, true); } },
    async restoreConfig(event) { const file = event.target.files && event.target.files[0]; event.target.value = ''; if (!file || !window.confirm('还原配置会覆盖当前系统设置，是否继续？')) return; try { const payload = JSON.parse(await file.text()); const restored = await this.api('/api/config/restore', { method: 'POST', body: JSON.stringify({ config: payload.config || payload }) }); this.applyConfig(restored); this.notify('配置已还原'); if (this.config.KOMGA_SERVERS.length) await this.loadLibraries(false); } catch (error) { this.notify(`还原失败：${error.message}`, true); } },
    async refresh(full, index) { const card = this.cards[index]; if (!card?.id) { this.notify('请先配置媒体卡片', true); return; } try { await this.api('/api/refresh', { method: 'POST', body: JSON.stringify({ full, target_id: this.taskLibraryKey(card) }) }); this.notify(full ? '全量刮削已开始' : '增量刮削已开始'); } catch (error) { this.notify(error.message, true); } },
    async loadRecords(showError = false) {
      const request = ++this.recordRequest;
      try {
        const [records, stats] = await Promise.all([
          this.api(`/api/scrape-records?limit=50&offset=${(this.recordPage-1)*50}&q=${encodeURIComponent(this.recordSearch)}&sort=${this.recordSortNewest?'newest':'oldest'}`),
          this.api('/api/scrape-records/stats')
        ]);
        if (request !== this.recordRequest) return;
        const items = records.items || [];
        await Promise.all(items.map(async record => {
          const previous = this.records.find(item => item.id === record.id);
          if (!previous?.volume_offset || !this.recordExpanded(record)) return;
          const offset = Math.min(previous.volume_offset, Math.max(0, Math.ceil(record.volume_count / 50)-1)*50);
          const details = await this.api(`/api/scrape-records/details?id=${encodeURIComponent(record.id)}&offset=${offset}`);
          record.volumes = details.items || [];
          record.volume_offset = offset;
        }));
        if (request !== this.recordRequest) return;
        this.records = items;
        this.recordTotal = records.total ?? stats.total;
        this.recordStats = stats;
        const last = Math.max(1, Math.ceil(this.recordTotal/50));
        if (this.recordPage > last) { this.recordPage = last; return this.loadRecords(); }
      } catch (error) { if (showError) this.notify(error.message, true); }
    },
    async loadLogs(showError = false) { const request = ++this.logRequest; try { const [logs, stats] = await Promise.all([this.api(`/api/runtime-logs?limit=100&offset=${(this.logPage-1)*100}&q=${encodeURIComponent(this.logSearch)}`), this.api('/api/runtime-logs/stats')]); if (request !== this.logRequest) return; this.logs = logs.items || []; this.logTotal = logs.total ?? stats.total; this.logStats = stats; const last = Math.max(1, Math.ceil(this.logTotal/100)); if (this.logPage > last) { this.logPage = last; return this.loadLogs(); } } catch (error) { if (showError) this.notify(error.message, true); } },
    changePage(kind, delta) { if (kind === 'records') { this.recordPage += delta; this.expandedRecordIds = []; this.loadRecords(true); } else { this.logPage += delta; this.loadLogs(true); } },
    startLiveRefresh() { clearInterval(this.liveRefreshTimer); this.liveRefreshTimer = null; if (!this.authenticated || document.hidden || !['records', 'logs'].includes(this.view)) return; this.liveRefreshTimer = setInterval(() => { if (this.view === 'records') this.loadRecords(); else if (this.view === 'logs') this.loadLogs(); }, 4000); },
    async loadTasks() { try { const data = await this.api('/api/tasks'); this.tasks = data.items || []; } catch (error) { this.notify(error.message, true); } },
    newTask() { this.editingTask = { id: '', name: '', functions: [], fields: [], operations: [], ai_completion: false, include_locked: false, lock_completed: false, card_ids: [], cron: '0 6 * * *', enabled: true }; this.$nextTick(() => this.decorateFieldLabels()); },
    toggleTaskOperation(value) { const values = this.editingTask.operations; this.editingTask.operations = values.includes(value) ? values.filter(item=>item!==value) : [...values,value]; },
    editTask(task) { if (this.taskDragMoved) { this.taskDragMoved = false; return; } this.editingTask = { ...task, operations: (task.operations || []).filter(value=>value!=='include_locked'), include_locked: task.include_locked ?? (task.operations || []).includes('include_locked'), lock_completed: task.lock_completed ?? this.taskType(task)==='summary_translation', ai_completion: !!task.ai_completion, cron: task.cron || '0 6 * * *', functions: [...(task.functions || (task.type ? [task.type] : [])).slice(0, 1)], fields: [...(task.fields?.length ? task.fields : this.taskType(task) === 'summary_translation' ? ['summary'] : [])], card_ids: [...(task.card_ids || [])].map(value => this.normalizeTaskLibraryKey(value)) }; this.$nextTick(() => this.decorateFieldLabels()); },
    validCronExpression(value) { const parts = String(value || '').trim().split(/\s+/); return parts.length === 5 && parts.every(part => /^[0-9A-Za-z*?,/\-]+$/.test(part)); },
    async saveTask() { if (!this.editingTask) return; this.editingTask.functions = this.editingTask.functions.slice(0, 1); if (!this.editingTask.functions.length) { this.notify('请选择任务功能', true); return; } if (this.editingTask.functions[0] !== 'card_collage_refresh' && !this.editingTask.fields.length) { this.notify('请至少选择一个元数据项', true); return; } if (this.editingTask.functions.includes('metadata_correction')) { const ops = this.editingTask.operations || []; if (!ops.some(value => ['simplify','extract_title'].includes(value))) { this.notify('请选择繁转简或标题提取', true); return; } if (!ops.includes('simplify') && !this.editingTask.fields.includes('title')) { this.notify('标题提取需要选择标题元数据', true); return; } } if (!this.validCronExpression(this.editingTask.cron)) { this.notify('请输入有效的五段 Cron 表达式', true); return; } if (!this.editingTask.card_ids.length) { this.notify('请至少选择一个媒体库', true); return; } if (!this.editingTask.name.trim()) this.editingTask.name = this.uniqueTaskName(this.taskTypeLabel(this.editingTask.functions[0]), this.editingTask.id); try { const data = await this.api('/api/tasks', { method: 'POST', body: JSON.stringify(this.editingTask) }); this.tasks = data.items || []; this.config.METADATA_TASKS = this.tasks; this.editingTask = null; this.notify('计划任务已保存'); } catch (error) { this.notify(error.message, true); } },
    requestDeleteTask(task) { this.deletingTask = task; },
    async deleteTask() { const task = this.deletingTask; if (!task) return; try { const data = await this.api('/api/tasks/delete', { method: 'POST', body: JSON.stringify({ id: task.id }) }); this.tasks = data.items || []; this.config.METADATA_TASKS = this.tasks; this.deletingTask = null; this.notify('计划任务已删除'); } catch (error) { this.notify(error.message, true); } },
    async toggleTask(task) { task.enabled = !task.enabled; try { this.config.METADATA_TASKS = this.tasks; this.config = await this.api('/api/config', { method: 'POST', body: JSON.stringify(this.collectConfig()) }); this.notify(task.enabled ? '计划任务已启用' : '计划任务已停用'); } catch (error) { task.enabled = !task.enabled; this.notify(error.message, true); } },
    taskDragStart(index, event) { this.taskDragIndex = index; this.taskDragMoved = false; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(index)); },
    async taskDrop(index) { if (this.taskDragIndex === null || this.taskDragIndex === index) return; const [task] = this.tasks.splice(this.taskDragIndex, 1); this.tasks.splice(index, 0, task); this.taskDragMoved = true; this.taskDragIndex = null; this.config.METADATA_TASKS = this.tasks; await this.save(); },
    taskStatus(task) { return this.status.tasks?.[task.id] || {}; },
    taskRunning(task) { return !!this.taskStatus(task).state; },
    async runTask(task) { const stopping = this.taskRunning(task); try { await this.api(stopping ? '/api/tasks/stop' : '/api/tasks/run', { method: 'POST', body: JSON.stringify({ id: task.id }) }); this.status = await this.api('/api/status'); this.notify(stopping ? '正在停止任务' : '计划任务已开始执行'); } catch (error) { this.notify(error.message, true); } },
    handleServerWheel(event) { const grid = event.target && event.target.closest ? event.target.closest('.server-card-grid') : null; if (!grid || grid.scrollWidth <= grid.clientWidth) return; event.preventDefault(); grid.scrollLeft += Math.abs(event.deltaY) > Math.abs(event.deltaX) ? event.deltaY : event.deltaX; },
    toggleRecordSort() { this.recordSortNewest = !this.recordSortNewest; this.recordPage = 1; this.loadRecords(true); },
    taskType(task) { return (task.functions || [task.type || 'metadata_completion'])[0]; },
    taskTypeLabel(value) { return this.taskTypeOptions.find(option => option.value === value)?.label || value || '计划任务'; },
    taskLibraryKey(card) { return `${card.serverId || ''}::${card.id || ''}`; },
    normalizeTaskLibraryKey(value) { if (String(value).includes('::')) return String(value); const card = this.cards.find(item => item.id === String(value)); return card ? this.taskLibraryKey(card) : String(value); },
    uniqueTaskName(base, currentId = '') { const names = new Set(this.tasks.filter(task => task.id !== currentId).map(task => task.name)); if (!names.has(base)) return base; if (!names.has(`${base} 副本`)) return `${base} 副本`; let index = 2; while (names.has(`${base} 副本 ${index}`)) index += 1; return `${base} 副本 ${index}`; },
    toggleRecord(record) { const index = this.expandedRecordIds.indexOf(record.id); if (index >= 0) this.expandedRecordIds.splice(index, 1); else this.expandedRecordIds.push(record.id); },
    recordExpanded(record) { return this.expandedRecordIds.includes(record.id); },
    async changeDetailPage(record, delta) { const offset = Math.max(0, (record.volume_offset || 0) + delta * 50); try { const data = await this.api(`/api/scrape-records/details?id=${encodeURIComponent(record.id)}&offset=${offset}`); record.volumes = data.items || []; record.volume_count = data.total; record.volume_offset = offset; } catch(error) { this.notify(error.message, true); } },
    formatRecordTime(value) { return String(value || '').replace('T', ' ').replace(/-/g, '/').replace(/\.\d{3}Z?$/, ''); },
    cardServerName(card) { return this.config.KOMGA_SERVERS.find(server => server.id === card.serverId)?.name || 'Komga 服务'; },
    metadataText(record) { const labels = { status: '状态', summary: '简介', publisher: '出版商', genres: '流派', tags: '标签', title: '标题', alternateTitles: '别名', ageRating: '年龄分级', links: 'Bangumi 链接', totalBookCount: '册数', language: '语言', titleSort: '标题排序', authors: '作者', isbn: 'ISBN', number: '卷号', releaseDate: '发行日期', numberSort: '卷号排序', thumbnail: '封面' }; return (record.metadata_fields || []).map(field => field.endsWith('Lock') ? `${labels[field.slice(0,-4)] || field.slice(0,-4)}锁定` : labels[field] || field).join('、'); },
    recordTooltip(record) { const source = record.source_title || record.item_title || ''; const matched = record.matched_title && record.matched_title !== source ? ` → ${record.matched_title}` : ''; return `${source}${matched}`; },
    async pollStatus() { if (!this.authenticated) return; try { this.status = await this.api('/api/status'); } catch (_) {} setTimeout(() => this.pollStatus(), 3000); },
    openCredentialModal() { this.credentialForm = { username: '', password: '' }; this.showCredentialModal = true; },
    requestCredentialSave() { if (!this.credentialForm.username || !this.credentialForm.password) { this.notify('账号和密码不能为空', true); return; } this.showCredentialConfirm = true; },
    async confirmCredentialSave() { try { await this.api('/api/auth/credentials', { method: 'POST', body: JSON.stringify(this.credentialForm) }); this.showCredentialConfirm = false; this.showCredentialModal = false; this.loginForm.username = this.credentialForm.username; this.notify('后台账号密码已更新，请牢记新密码'); } catch (error) { this.notify(error.message, true); } }
  }
}).mount('#app');
