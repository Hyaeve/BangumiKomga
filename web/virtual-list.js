// Variable-height window with bounded page caching; only visible rows enter the DOM.
const VirtualList = {
  props: { total: Number, items: Array, load: Function, version: String, pageSize: {default:50},
    estimate: {default:80}, label: String, refresh: Number },
  data: () => ({top:0, height:640, sizes:{}, pages:{}, pending:{}, failures:{}, generation:0}),
  computed: {
    count() { return this.total || 0; },
    measured() { return Object.entries(this.sizes).map(([i,h])=>[Number(i),h]).sort((a,b)=>a[0]-b[0]); },
    start() { return Math.max(0,this.indexAt(this.top)-4); },
    end() { return Math.min(this.count,this.indexAt(this.top+this.height)+6); },
    rows() { return Array.from({length:Math.max(0,this.end-this.start)},(_,i)=>{
      const index=this.start+i, page=Math.floor(index/this.pageSize);
      return {index,item:this.pages[page]?.[index%this.pageSize]};
    }); },
    fullHeight() { return this.offset(this.count); }
  },
  watch: {
    version() { this.reset(true); },
    items() { this.reset(false); },
    refresh() { this.refreshVisible(); },
    start() { this.fill(); }, end() { this.fill(); }
  },
  mounted() {
    this.resize=new ResizeObserver(entries=>{
      for(const entry of entries) {
        if(entry.target===this.$refs.viewport) this.height=entry.contentRect.height;
        else {
          const index=Number(entry.target.dataset.virtualIndex);
          const height=entry.borderBoxSize?.[0]?.blockSize || entry.target.getBoundingClientRect().height;
          if(height>0 && Math.abs((this.sizes[index]||this.estimate)-height)>1)
            this.sizes[index]=height;
        }
      }
    });
    this.resize.observe(this.$refs.viewport);
    this.reset(true);
  },
  updated() {
    this.resize?.disconnect();
    if(this.$refs.viewport) this.resize?.observe(this.$refs.viewport);
    this.$el.querySelectorAll('[data-virtual-index]').forEach(node=>this.resize?.observe(node));
  },
  beforeUnmount() { this.generation++; this.resize?.disconnect(); },
  methods: {
    async refreshVisible() {
      const generation=this.generation;
      for(const key of Object.keys(this.pages)) {
        const page=Number(key);
        if(!page) continue;
        try {
          const result=await this.load(page*this.pageSize);
          if(generation===this.generation) this.pages[page]=result.items||[];
        } catch(_) {}
      }
    },
    offset(index) {
      let value=index*this.estimate;
      for(const [i,h] of this.measured) { if(i>=index) break; value+=h-this.estimate; }
      return value;
    },
    indexAt(y) {
      let low=0,high=this.count;
      while(low<high) { const mid=Math.floor((low+high)/2); if(this.offset(mid+1)<=y) low=mid+1; else high=mid; }
      return low;
    },
    reset(scroll) {
      this.generation++; this.pages={0:this.items||[]}; this.pending={}; this.failures={};
      if(scroll) { this.sizes={}; this.top=0; if(this.$refs.viewport) this.$refs.viewport.scrollTop=0; }
      this.$nextTick(()=>this.fill());
    },
    async fill() {
      const generation=this.generation;
      const first=Math.floor(this.start/this.pageSize),last=Math.floor(Math.max(this.start,this.end-1)/this.pageSize);
      for(const key of Object.keys(this.pages))
        if(Number(key)!==0 && (Number(key)<first-1 || Number(key)>last+1)) delete this.pages[key];
      for(let page=first;page<=last;page++) {
        if(this.pages[page] || this.pending[page] || this.failures[page]) continue;
        this.pending[page]=true;
        try {
          const result=await this.load(page*this.pageSize);
          if(generation===this.generation) this.pages[page]=result.items||[];
        } catch(error) { if(generation===this.generation) this.failures[page]=error.message; }
        finally { if(generation===this.generation) delete this.pending[page]; }
      }
      // Measurements are cheap but must not accumulate indefinitely.
      if(Object.keys(this.sizes).length>2000)
        for(const key of Object.keys(this.sizes)) if(Math.abs(Number(key)-this.start)>500) delete this.sizes[key];
    },
    retry() { this.failures={}; this.fill(); },
    scroll(event) { this.top=event.target.scrollTop; }
  },
  template:`<div ref="viewport" class="virtual-viewport" @scroll.passive="scroll" :aria-label="label" tabindex="0">
    <div :style="{height:offset(start)+'px'}" aria-hidden="true"></div>
    <div v-for="row in rows" :key="row.index" :data-virtual-index="row.item ? row.index : null" class="virtual-row">
      <slot v-if="row.item" :item="row.item"></slot>
      <div v-else class="virtual-placeholder" :style="{height:estimate+'px'}" role="status">
        <button v-if="failures[Math.floor(row.index/pageSize)]" @click="retry">加载失败，点击重试</button><span v-else>加载中…</span>
      </div>
    </div>
    <div :style="{height:Math.max(0,fullHeight-offset(end))+'px'}" aria-hidden="true"></div>
    <slot v-if="!count" name="empty"></slot>
  </div>`
};
