const TagPicker = {
  props: {
    id: { type: String, required: true },
    label: { type: String, required: true },
    modelValue: { type: Array, default: () => [] },
    options: { type: Array, default: () => [] },
    placeholder: { type: String, default: '请选择' },
    single: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false }
  },
  emits: ['update:modelValue'],
  data() {
    return { open: false, panelStyle: {} };
  },
  computed: {
    canSelectAll() { return !this.single && this.id !== 'card-features'; },
    allSelected() { return this.options.length > 0 && this.options.every(option => this.modelValue.includes(option.value)); },
    selectedOptions() {
      return this.options.filter(option => this.modelValue.includes(option.value));
    }
  },
  watch: {
    modelValue: {
      deep: true,
      handler() { this.$nextTick(this.positionPanel); }
    }
  },
  mounted() {
    document.addEventListener('close-tag-pickers', this.closeFromEscape);
    document.addEventListener('pointerdown', this.handleOutside);
    document.addEventListener('focusin', this.handleOutside);
    window.addEventListener('resize', this.positionPanel);
    window.addEventListener('scroll', this.handleScroll, true);
    this.resizeObserver = new ResizeObserver(this.positionPanel);
    this.resizeObserver.observe(this.$refs.field);
  },
  beforeUnmount() {
    document.removeEventListener('close-tag-pickers', this.closeFromEscape);
    document.removeEventListener('pointerdown', this.handleOutside);
    document.removeEventListener('focusin', this.handleOutside);
    window.removeEventListener('resize', this.positionPanel);
    window.removeEventListener('scroll', this.handleScroll, true);
    this.resizeObserver.disconnect();
  },
  methods: {
    closeFromEscape() { if (this.open) this.close(true); },
    toggle() {
      if (this.disabled) return;
      if (this.open) this.close();
      else {
        this.open = true;
        this.$nextTick(this.positionPanel);
      }
    },
    close(restoreFocus = false) {
      this.open = false;
      if (restoreFocus) this.$refs.trigger.focus();
    },
    handleOutside(event) {
      if (!this.open || this.$refs.field.contains(event.target) || this.$refs.panel?.contains(event.target)) return;
      this.close();
    },
    handleScroll(event) {
      if (!this.$refs.panel?.contains(event.target)) this.positionPanel();
    },
    positionPanel() {
      if (!this.open || !this.$refs.panel) return;
      const field = this.$refs.field.getBoundingClientRect();
      const viewport = window.visualViewport;
      const viewportTop = viewport?.offsetTop || 0;
      const viewportLeft = viewport?.offsetLeft || 0;
      const viewportHeight = viewport?.height || window.innerHeight;
      const viewportWidth = viewport?.width || window.innerWidth;
      const gap = 8, margin = 12;
      const below = viewportTop + viewportHeight - field.bottom - gap - margin;
      const above = field.top - viewportTop - gap - margin;
      const desiredHeight = Math.min(320, this.$refs.panel.scrollHeight + 2);
      const upward = below < desiredHeight && above > below;
      const height = Math.min(desiredHeight, Math.max(44, upward ? above : below));
      const width = Math.min(field.width, viewportWidth - margin * 2);
      const left = Math.max(viewportLeft + margin, Math.min(field.left, viewportLeft + viewportWidth - width - margin));
      this.panelStyle = {
        left: `${left}px`,
        top: `${Math.max(viewportTop + margin, upward ? field.top - gap - height : field.bottom + gap)}px`,
        width: `${width}px`,
        maxHeight: `${height}px`
      };
    },
    select(value, checked) {
      const selected = this.single ? [] : this.modelValue.filter(item => item !== value);
      if (checked) selected.push(value);
      this.$emit('update:modelValue', selected);
    },
    selectAll() { this.$emit('update:modelValue', this.allSelected ? [] : this.options.map(option => option.value)); },
    async focusOption(last = false) {
      this.open = true;
      await this.$nextTick();
      this.positionPanel();
      const options = this.$refs.panel.querySelectorAll('input');
      options[last ? options.length - 1 : 0]?.focus();
    },
    triggerKeydown(event) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        this.focusOption(event.key === 'ArrowUp');
      } else if (event.key === 'Escape' && this.open) {
        event.preventDefault();
        event.stopPropagation();
        this.close(true);
      } else if (event.key === 'Tab' && this.open) {
        if (event.shiftKey) this.close();
        else {
          event.preventDefault();
          this.focusOption();
        }
      }
    },
    panelKeydown(event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        this.close(true);
        return;
      }
      if (event.key === 'Tab') {
        this.close(true);
        return;
      }
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const options = Array.from(this.$refs.panel.querySelectorAll('input'));
      const index = options.indexOf(document.activeElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 :
        (index + (event.key === 'ArrowUp' ? -1 : 1) + options.length) % options.length;
      options[next]?.focus();
    }
  },
  template: `
    <fieldset ref="field" :id="id" class="tag-picker" :class="{ 'is-open': open }">
      <legend :id="id + '-label'">{{ label }}</legend>
      <button ref="trigger" type="button" class="tag-picker-trigger"
        :aria-labelledby="id + '-label'" aria-haspopup="dialog" :disabled="disabled"
        :aria-expanded="open" :aria-controls="open ? id + '-panel' : undefined"
        @click="toggle" @keydown="triggerKeydown">
        <span class="tag-picker-values">
          <span v-for="option in selectedOptions" :key="option.value" class="tag-picker-chip" :data-tooltip="option.label">{{ option.label }}</span>
          <span v-if="!selectedOptions.length" class="tag-picker-placeholder">{{ placeholder }}</span>
        </span>
        <span class="tag-picker-chevron" aria-hidden="true"></span>
      </button>
      <teleport to="body">
        <div v-if="open" ref="panel" :id="id + '-panel'" class="tag-picker-panel"
          role="dialog" :aria-label="label + '候选项'" :style="panelStyle" @keydown="panelKeydown">
          <label v-if="canSelectAll && options.length" class="tag-picker-option select-all" :class="{'is-selected':allSelected}">
            <input type="checkbox" :checked="allSelected" :indeterminate="!allSelected && selectedOptions.length > 0" @change="selectAll">
            <span class="tag-picker-option-text">全选</span>
          </label>
          <label v-for="option in options" :key="option.value" class="tag-picker-option"
            :class="{ 'is-selected': modelValue.includes(option.value) }">
            <input :type="single ? 'radio' : 'checkbox'" :name="single ? id : undefined" :checked="modelValue.includes(option.value)"
              @change="select(option.value, $event.target.checked)">
            <span class="tag-picker-option-text">{{ option.label }}<small v-if="option.detail">{{ option.detail }}</small></span>
          </label>
          <div v-if="!options.length" class="tag-picker-empty">暂无可选项</div>
        </div>
      </teleport>
    </fieldset>
  `
};
