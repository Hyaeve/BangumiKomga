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
      logStats: { total: 0, today: 0, errors: 0, actions: 0 },
      tasks: [],
      editingTask: null,
      taskTypeOptions: [{ value: 'metadata_completion', label: '元数据补全' }],
      recordSearch: '',
      recordSortNewest: true,
      recordStats: { total: 0, today: 0, comic: 0, novel: 0 },
      cards: [],
      cardHues: [105, 270, 195, 35, 320, 155],
      status: { running: false, last_result: null, last_error: null },
      config: {
        BANGUMI_ACCESS_TOKEN: '', OPENAI_BASE_URL: '', OPENAI_API_KEY: '', OPENAI_MODEL: '', TRANSLATE_SUMMARY_TO_ZH: false,
        KOMGA_BASE_URL: '', KOMGA_EMAIL: '', KOMGA_EMAIL_PASSWORD: '', KOMGA_API_KEY: '',
        KOMGA_SERVERS: [], KOMGA_LIBRARY_LIST: [], BANGUMI_KOMGA_SERVICE_TYPE: 'poll', BANGUMI_KOMGA_SERVICE_POLL_INTERVAL: 20,
        BANGUMI_KOMGA_SERVICE_POLL_REFRESH_ALL_METADATA_INTERVAL: 10000
        ,RECORD_RETENTION_DAYS: 30, METADATA_TASKS: []
      },
      navItems: [
        { id: 'scrape', label: '刮削卡片', title: '刮削卡片', subtitle: '为不同媒体库配置独立的增量匹配规则' },
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
    currentNav() { return this.navItems.find(item => item.id === this.view) || this.navItems[0]; },
    activeServer() { return this.config.KOMGA_SERVERS && this.config.KOMGA_SERVERS[0]; },
    lastRunText() { return this.status.last_result ? `最近完成：${this.status.last_result === 'full' ? '全量刮削' : '增量刮削'}` : '尚未执行刮削'; },
    credentialHint() { return this.loginForm.username || '已登录'; }
    ,filteredRecords() {
      const keyword = this.recordSearch.trim().toLocaleLowerCase();
      if (!keyword) return this.records;
      return this.records.filter(record => [record.item_type, record.item_title, record.source_title, record.matched_title, record.match_source, record.library_name, record.server_name, ...(record.metadata_fields || [])].some(value => String(value || '').toLocaleLowerCase().includes(keyword)));
    },
    sortedRecords() {
      return [...this.filteredRecords].sort((a, b) => {
        const left = String(a.recorded_at || ''), right = String(b.recorded_at || '');
        return this.recordSortNewest ? right.localeCompare(left) : left.localeCompare(right);
      });
    }
  },
  watch: { view(value) { if (!['scrape', 'records', 'tasks', 'logs', 'settings'].includes(value)) { this.view = 'scrape'; return; } history.replaceState(null, '', `#${value}`); document.title = `${this.currentNav.title} · BangumiKomga`; this.closeContextMenu(); if (value === 'records') this.loadRecords(); if (value === 'logs') this.loadLogs(); if (value === 'tasks') this.loadTasks(); } },
  async mounted() { document.addEventListener('wheel', this.handleServerWheel, { passive: false }); if (!['scrape', 'records', 'tasks', 'logs', 'settings'].includes(this.view)) this.view = 'scrape'; document.title = `${this.currentNav.title} · BangumiKomga`; await this.checkSession(); },
  beforeUnmount() { document.removeEventListener('wheel', this.handleServerWheel); },
  methods: {
    async api(path, options = {}) {
      const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`);
      return data;
    },
    notify(text, error = false) { this.message = text; this.messageError = error; if (text) setTimeout(() => { this.message = ''; }, 3500); },
    async checkSession() {
      try { const session = await this.api('/api/auth/session'); this.authenticated = session.authenticated; this.loginForm.username = session.username || ''; this.credentialForm.username = session.username || ''; if (this.authenticated) await this.loadApp(); } catch (_) { this.authenticated = false; }
    },
    async login() {
      try { await this.api('/api/auth/login', { method: 'POST', body: JSON.stringify(this.loginForm) }); this.authenticated = true; this.credentialForm.username = this.loginForm.username; this.loginForm.password = ''; await this.loadApp(); }
      catch (error) { this.notify(error.message, true); }
    },
    async logout() { await this.api('/api/auth/logout', { method: 'POST', body: '{}' }); this.authenticated = false; },
    async loadApp() {
      const config = await this.api('/api/config'); this.applyConfig(config);
      if (this.config.KOMGA_BASE_URL && (this.komgaAuthMode === 'key' ? this.config.KOMGA_API_KEY : (this.config.KOMGA_EMAIL && this.config.KOMGA_EMAIL_PASSWORD))) await this.loadLibraries(false);
      await Promise.all(this.cards.filter(card => card.serverId && card.id).map(card => this.loadCardPreview(card)));
      this.pollStatus();
    },
    applyConfig(config) { this.config = { ...this.config, ...config, KOMGA_SERVERS: (config.KOMGA_SERVERS || []).map(server => ({ auth_mode: server.auth_mode || (server.api_key ? 'key' : 'password'), ...server })) }; this.tasks = this.config.METADATA_TASKS || []; if (!this.config.KOMGA_SERVERS.length && this.config.KOMGA_BASE_URL) this.config.KOMGA_SERVERS = [{ id: 'legacy', name: '默认 Komga', base_url: this.config.KOMGA_BASE_URL, email: this.config.KOMGA_EMAIL, password: this.config.KOMGA_EMAIL_PASSWORD, api_key: this.config.KOMGA_API_KEY, auth_mode: this.config.KOMGA_API_KEY ? 'key' : 'password' }]; this.komgaAuthMode = this.config.KOMGA_API_KEY ? 'key' : 'password'; this.cards = (this.config.KOMGA_LIBRARY_LIST || []).map((item, index) => this.makeCard(item, index)); },
    makeCard(item = {}, index = 0) { const defaultOverwriteFields = this.overwriteFieldOptions.map(field => field.value); return { uid: `${Date.now()}-${Math.random()}`, id: item.LIBRARY || '', serverId: item.SERVER_ID || '', name: '', path: '', covers: [], isNovel: !!item.IS_NOVEL_ONLY, rules: item.REQUIRED_FIELDS || [], overwriteFields: Array.isArray(item.OVERWRITE_FIELDS) && item.OVERWRITE_FIELDS.length ? item.OVERWRITE_FIELDS : defaultOverwriteFields, translateSummary: !!item.TRANSLATE_SUMMARY_TO_ZH, aiRecognition: !!item.AI_RECOGNITION, hue: this.cardHues[index % this.cardHues.length] }; },
    addCard() { const card = this.makeCard({}, this.cards.length); this.cards.push(card); this.openCardSettings(card, true); },
    resetServerDraft() { this.serverDraft = { id: '', name: '', base_url: '', email: '', password: '', api_key: '', auth_mode: 'password' }; this.showServerDraftSecret = false; },
    addServer() { const draft = this.serverDraft; if (!draft.name.trim() || !draft.base_url.trim()) { this.notify('请填写 Komga 名称和地址', true); return; } if (draft.auth_mode === 'key' ? !draft.api_key : (!draft.email || !draft.password)) { this.notify('请填写完整的 Komga 认证信息', true); return; } (this.config.KOMGA_SERVERS ||= []).push({ ...draft, id: `server-${Date.now()}`, name: draft.name.trim(), base_url: draft.base_url.trim().replace(/\/$/, '') }); this.resetServerDraft(); this.notify('Komga 服务器已添加'); },
    removeServer(index) { this.config.KOMGA_SERVERS.splice(index, 1); },
    openServerEditor(server) { this.editingServer = { ...server }; },
    saveServerEdit() { const index = this.config.KOMGA_SERVERS.findIndex(item => item.id === this.editingServer.id); if (index >= 0) this.config.KOMGA_SERVERS.splice(index, 1, { ...this.editingServer, name: this.editingServer.name.trim(), base_url: this.editingServer.base_url.trim().replace(/\/$/, '') }); this.editingServer = null; this.notify('Komga 服务器已更新'); },
    removeCard(index) { this.cards.splice(index, 1); },
    dragStart(index, event) { this.dragIndex = index; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(index)); },
    dropCard(index) { if (this.dragIndex === null || this.dragIndex === index) return; const [card] = this.cards.splice(this.dragIndex, 1); this.cards.splice(index, 0, card); this.dragIndex = null; },
    openCardMenu(index, event) { const menuWidth = 170, menuHeight = 132; this.contextMenu = { visible: true, index, x: Math.min(event.clientX, window.innerWidth - menuWidth - 12), y: Math.min(event.clientY, window.innerHeight - menuHeight - 12) }; },
    closeContextMenu() { if (this.contextMenu.visible) this.contextMenu = { visible: false, x: 0, y: 0, index: null }; },
    deleteCard(index) { this.removeCard(index); this.closeContextMenu(); this.notify('媒体库卡片已删除'); },
    openCardSettings(card, isNew = false) { this.editingCard = card; this.editingCardOriginal = isNew ? null : JSON.parse(JSON.stringify(card)); this.editingCardIsNew = isNew; this.closeContextMenu(); if (card.serverId) this.loadCardLibraries(card); },
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
    changeCardServer(card) { card.id = ''; card.name = ''; card.path = ''; card.covers = []; this.loadCardLibraries(card); },
    async loadCardLibraries(card) { if (!card.serverId) return; try { const data = await this.api(`/api/komga/libraries?server_id=${encodeURIComponent(card.serverId)}`); this.libraries = data.items || []; this.syncCardName(card); } catch (error) { this.notify(error.message, true); } },
    async loadCardPreview(card, force = false) { if (!card.serverId || !card.id) { card.covers = []; return; } try { const data = await this.api(`/api/komga/previews?server_id=${encodeURIComponent(card.serverId)}&library_id=${encodeURIComponent(card.id)}${force ? '&refresh=1' : ''}`); card.covers = (data.items || []).map(item => ({ ...item, failed: false })); } catch (_) { card.covers = []; } },
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
    collectConfig() { const next = { ...this.config, KOMGA_LIBRARY_LIST: this.cards.filter(card => card.id).map(card => ({ LIBRARY: card.id, SERVER_ID: card.serverId, IS_NOVEL_ONLY: card.isNovel, REQUIRED_FIELDS: card.rules, OVERWRITE_FIELDS: card.overwriteFields, TRANSLATE_SUMMARY_TO_ZH: card.translateSummary, AI_RECOGNITION: card.aiRecognition })) }; if (this.komgaAuthMode === 'key') { next.KOMGA_EMAIL = ''; next.KOMGA_EMAIL_PASSWORD = ''; } else { next.KOMGA_API_KEY = ''; } return next; },
    async save() { try { this.config = await this.api('/api/config', { method: 'POST', body: JSON.stringify(this.collectConfig()) }); this.notify('设置已保存'); return true; } catch (error) { this.notify(error.message, true); return false; } },
    async testBangumiSearch() {
      const query = this.bangumiTestQuery.trim();
      if (!query) { this.bangumiTestMessage = '请输入漫画或小说名称'; this.bangumiTestError = true; return; }
      this.bangumiTestBusy = true; this.bangumiTestMessage = ''; this.bangumiTestError = false;
      try {
        const data = await this.api(`/api/bangumi/search?q=${encodeURIComponent(query)}`);
        const items = data.items || []; this.bangumiTestResults = items;
        this.bangumiTestMessage = items.length ? `搜索成功：${items.slice(0, 3).map(item => item.name_cn || item.name).join('、')}` : '未找到匹配条目';
        this.bangumiTestError = !items.length;
      } catch (error) { this.bangumiTestMessage = `搜索失败：${error.message}`; this.bangumiTestError = true; }
      finally { this.bangumiTestBusy = false; }
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
    async refresh(full) { try { await this.api('/api/refresh', { method: 'POST', body: JSON.stringify({ full }) }); this.notify(full ? '全量刮削已开始' : '增量刮削已开始'); } catch (error) { this.notify(error.message, true); } },
    async loadRecords() { try { const [records, stats] = await Promise.all([this.api('/api/scrape-records?limit=300'), this.api('/api/scrape-records/stats')]); this.records = records.items || []; this.recordStats = stats; } catch (error) { this.notify(error.message, true); } },
    async loadLogs() { try { const [logs, stats] = await Promise.all([this.api(`/api/runtime-logs?limit=200&q=${encodeURIComponent(this.logSearch)}`), this.api('/api/runtime-logs/stats')]); this.logs = logs.items || []; this.logStats = stats; } catch (error) { this.notify(error.message, true); } },
    async loadTasks() { try { const data = await this.api('/api/tasks'); this.tasks = data.items || []; } catch (error) { this.notify(error.message, true); } },
    newTask() { this.editingTask = { id: '', name: '', functions: [], fields: ['title', 'summary'], card_ids: [], enabled: true }; },
    editTask(task) { this.editingTask = { ...task, functions: [...(task.functions || (task.type ? [task.type] : []))], fields: [...(task.fields || [])], card_ids: [...(task.card_ids || [])] }; },
    async saveTask() { if (!this.editingTask) return; if (!this.editingTask.name.trim()) { this.notify('请填写自定义任务名称', true); return; } if (!this.editingTask.functions.length) { this.notify('请至少选择一个任务功能', true); return; } if (this.editingTask.functions.includes('metadata_completion') && !this.editingTask.fields.length) { this.notify('请至少选择一个元数据项', true); return; } if (!this.editingTask.card_ids.length) { this.notify('请至少选择一个媒体库', true); return; } try { const data = await this.api('/api/tasks', { method: 'POST', body: JSON.stringify(this.editingTask) }); this.tasks = data.items || []; this.config.METADATA_TASKS = this.tasks; this.editingTask = null; this.notify('计划任务已保存'); } catch (error) { this.notify(error.message, true); } },
    async deleteTask(task) { try { const data = await this.api('/api/tasks/delete', { method: 'POST', body: JSON.stringify({ id: task.id }) }); this.tasks = data.items || []; this.notify('计划任务已删除'); } catch (error) { this.notify(error.message, true); } },
    async runTask(task) { try { await this.api('/api/tasks/run', { method: 'POST', body: JSON.stringify({ id: task.id }) }); this.notify('计划任务已开始执行'); } catch (error) { this.notify(error.message, true); } },
    handleServerWheel(event) { const grid = event.target && event.target.closest ? event.target.closest('.server-card-grid') : null; if (!grid || grid.scrollWidth <= grid.clientWidth) return; event.preventDefault(); grid.scrollLeft += Math.abs(event.deltaY) > Math.abs(event.deltaX) ? event.deltaY : event.deltaX; },
    toggleRecordSort() { this.recordSortNewest = !this.recordSortNewest; },
    formatRecordTime(value) { return String(value || '').replace('T', ' ').replace(/-/g, '/').replace(/\.\d{3}Z?$/, ''); },
    cardServerName(card) { return this.config.KOMGA_SERVERS.find(server => server.id === card.serverId)?.name || 'Komga 服务'; },
    metadataText(record) { const labels = { status: '状态', summary: '简介', publisher: '出版商', genres: '流派', tags: '标签', title: '标题', alternateTitles: '别名', ageRating: '年龄分级', links: 'Bangumi 链接', totalBookCount: '册数', language: '语言', titleSort: '标题排序', authors: '作者', isbn: 'ISBN', number: '卷号', releaseDate: '发行日期', numberSort: '卷号排序', thumbnail: '封面' }; return (record.metadata_fields || []).map(field => labels[field] || field).join('、'); },
    recordTooltip(record) { const source = record.source_title || record.item_title || ''; const matched = record.matched_title && record.matched_title !== source ? ` → ${record.matched_title}` : ''; return `${source}${matched}`; },
    async pollStatus() { if (!this.authenticated) return; try { this.status = await this.api('/api/status'); } catch (_) {} setTimeout(() => this.pollStatus(), 3000); },
    openCredentialModal() { this.credentialForm = { username: '', password: '' }; this.showCredentialModal = true; },
    requestCredentialSave() { if (!this.credentialForm.username || !this.credentialForm.password) { this.notify('账号和密码不能为空', true); return; } this.showCredentialConfirm = true; },
    async confirmCredentialSave() { try { await this.api('/api/auth/credentials', { method: 'POST', body: JSON.stringify(this.credentialForm) }); this.showCredentialConfirm = false; this.showCredentialModal = false; this.loginForm.username = this.credentialForm.username; this.notify('后台账号密码已更新，请牢记新密码'); } catch (error) { this.notify(error.message, true); } }
  }
}).mount('#app');
