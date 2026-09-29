const COLORS = ['#a78bfa', '#5ed6be', '#79b8ff', '#f4bd6b', '#f28eb8', '#8fd17c', '#9aa8ff', '#ed9a78'];
export default {
  props: {root: Object, citations: Array},
  data() { return {expanded: ['0'], selected: '0', detailOpen: false, zoom: 1, drag: null}; },
  computed: {
    allNodes() {
      const nodes = [];
      const visit = (raw, id, depth, color) => {
        nodes.push({...raw, id, depth, color, children: raw.children || []});
        (raw.children || []).forEach((child, i) => visit(child, `${id}.${i}`, depth + 1, depth === 0 ? COLORS[i % COLORS.length] : color));
      };
      visit(this.root, '0', 0, '#e3e8f2');
      return nodes;
    },
    layout() {
      const nodes = [], links = [];
      const lookup = new Map(this.allNodes.map(n => [n.id, n]));
      let row = 0, maxDepth = 0;
      const visit = id => {
        const data = lookup.get(id);
        const children = this.expanded.includes(id) ? data.children.map((_, i) => visit(`${id}.${i}`)) : [];
        const y = children.length ? (children[0].y + children[children.length - 1].y) / 2 : 32 + row++ * 116;
        const node = {...data, x: 32 + data.depth * 284, y};
        maxDepth = Math.max(maxDepth, data.depth);
        nodes.push(node);
        children.forEach(child => links.push({id:child.id, color:child.color,
          path:`M ${node.x + 224} ${y + 44} C ${node.x + 254} ${y + 44}, ${child.x - 30} ${child.y + 44}, ${child.x} ${child.y + 44}`}));
        return node;
      };
      visit('0');
      return {nodes, links, width: maxDepth * 284 + 288, height: Math.max(180, row * 116 + 32)};
    },
    current() { return this.allNodes.find(n => n.id === this.selected) || this.allNodes[0]; },
    evidence() { return this.citations.filter(c => (this.current.citations || []).includes(c.number)); },
    branches() { return this.allNodes.filter(n => n.depth === 1); },
  },
  mounted() { this.$nextTick(() => this.fit()); },
  methods: {
    async toggle(node) {
      const previousY = node.y;
      this.expanded = this.expanded.includes(node.id) ? this.expanded.filter(id => id !== node.id) : [...this.expanded, node.id];
      this.selected = node.id;
      await this.$nextTick();
      const next = this.layout.nodes.find(n => n.id === node.id);
      if (next) this.$refs.viewport.scrollTop += (next.y - previousY) * this.zoom;
    },
    expandAll() { this.expanded = this.allNodes.filter(n => n.children.length).map(n => n.id); },
    collapseAll() { this.expanded = []; this.selected = '0'; this.detailOpen = false; this.$nextTick(() => this.fit()); },
    fit() {
      const el = this.$refs.viewport;
      this.zoom = Math.min(1, Math.max(.35, (el.clientWidth - 24) / this.layout.width));
      el.scrollTo({top:0, left:0});
    },
    async scale(delta) {
      const el = this.$refs.viewport, old = this.zoom;
      const cx = (el.scrollLeft + el.clientWidth / 2) / old, cy = (el.scrollTop + el.clientHeight / 2) / old;
      this.zoom = Math.min(1.8, Math.max(.35, Math.round((old + delta) * 100) / 100));
      await this.$nextTick();
      el.scrollLeft = cx * this.zoom - el.clientWidth / 2;
      el.scrollTop = cy * this.zoom - el.clientHeight / 2;
    },
    pointerDown(event) {
      if (event.target.closest('button,a') || event.pointerType !== 'mouse' || event.button !== 0) return;
      const el = this.$refs.viewport;
      this.drag = {x:event.clientX, y:event.clientY, left:el.scrollLeft, top:el.scrollTop};
      el.setPointerCapture(event.pointerId);
    },
    pointerMove(event) {
      if (!this.drag) return;
      this.$refs.viewport.scrollLeft = this.drag.left - event.clientX + this.drag.x;
      this.$refs.viewport.scrollTop = this.drag.top - event.clientY + this.drag.y;
    },
  },
  template: `
    <section class="mindmap-explorer" aria-label="Interactive mind map">
      <div class="map-toolbar">
        <div class="map-count" role="status">{{layout.nodes.length}} / {{allNodes.length}} topics</div>
        <button @click="expandAll">Expand all</button>
        <button @click="collapseAll">Collapse all</button>
        <span class="map-toolbar-spacer"></span>
        <button @click="scale(-.15)" aria-label="Zoom out">−</button>
        <span class="map-zoom">{{Math.round(zoom * 100)}}%</span>
        <button @click="scale(.15)" aria-label="Zoom in">+</button>
        <button @click="fit">Fit width</button>
      </div>
      <div class="map-stage">
      <div class="map-viewport" ref="viewport" tabindex="0" aria-label="Mind map canvas. Scroll to explore."
        @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="drag=null" @pointercancel="drag=null">
        <div class="map-size" :style="{width:layout.width * zoom + 'px',height:layout.height * zoom + 'px'}">
          <svg class="map-svg" :width="layout.width" :height="layout.height" :style="{transform:'scale('+zoom+')'}" aria-label="Topic connections">
            <path v-for="link in layout.links" :key="link.id" :d="link.path" :stroke="link.color" stroke-width="2" fill="none" opacity=".6"/>
            <foreignObject v-for="node in layout.nodes" :key="node.id" :x="node.x" :y="node.y" width="224" height="88">
              <div class="map-node" :class="{'map-node-selected':selected===node.id}" :style="{'--branch':node.color}" :data-node-id="node.id">
                <button class="map-node-label" @click="selected=node.id; detailOpen=true" :aria-label="'Inspect topic '+node.name" :title="node.name">
                  <span>{{node.name}}</span><small>{{node.children.length ? node.children.length + ' subtopics' : 'Concept'}}<template v-if="node.citations?.length"> · {{node.citations.length}} source refs</template></small>
                </button>
                <button v-if="node.children.length" class="map-node-toggle" @click.stop="toggle(node)"
                  :aria-expanded="expanded.includes(node.id)" :aria-label="(expanded.includes(node.id) ? 'Collapse ' : 'Expand ') + node.name">{{expanded.includes(node.id) ? '−' : '+'}}</button>
              </div>
            </foreignObject>
          </svg>
        </div>
      </div>
      <div v-if="detailOpen" class="map-detail" aria-live="polite" role="region" aria-label="Topic details">
        <button class="map-detail-close" @click="detailOpen=false" aria-label="Close topic details">×</button>
        <strong :style="{color:current.color}">{{current.name}}</strong>
        <p>{{current.description || (current.children.length ? 'Expand this topic to explore its concepts and examples.' : 'Follow the source references to read more about this concept.')}}</p>
        <div v-if="evidence.length" class="map-evidence"><span>Evidence:</span><a v-for="ref in evidence" :key="ref.number" :href="'/evidence/'+ref.id" target="_blank" rel="noopener" :title="ref.name+' · '+ref.locator">[{{ref.number}}] {{ref.name}}</a></div>
        <span v-else-if="current.citations?.length" class="map-evidence">Evidence: {{current.citations.map(n=>'['+n+']').join(', ')}}</span>
      </div>
      </div>
    </section>`
};
