const COLORS = ['#a78bfa', '#5ed6be', '#79b8ff', '#f4bd6b', '#f28eb8', '#8fd17c', '#9aa8ff', '#ed9a78'];
export default {
  props: {root: Object, citations: Array},
  data() { return {expanded: ['0'], selected: '0', detailOpen: false, zoom: 1,
    panX: 0, panY: 0, positions: {}, drag: null, autoFit: true}; },
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
      const nodes = [], edges = [];
      const lookup = new Map(this.allNodes.map(n => [n.id, n]));
      let row = 0, maxDepth = 0;
      const visit = id => {
        const data = lookup.get(id);
        const children = this.expanded.includes(id) ? data.children.map((_, i) => visit(`${id}.${i}`)) : [];
        const y = children.length ? (children[0].y + children[children.length - 1].y) / 2 : 32 + row++ * 116;
        const node = {...data, x: 32 + data.depth * 284, y};
        maxDepth = Math.max(maxDepth, data.depth);
        nodes.push(node);
        children.forEach(child => edges.push({parent:node.id, child:child.id}));
        return node;
      };
      visit('0');
      const placed = nodes.map(node => ({...node, ...this.positions[node.id]}));
      const byId = new Map(placed.map(node => [node.id, node]));
      const links = edges.map(edge => {
        const parent = byId.get(edge.parent), child = byId.get(edge.child);
        const forward = child.x + 112 >= parent.x + 112;
        const x1 = parent.x + (forward ? 224 : 0), x2 = child.x + (forward ? 0 : 224);
        const bend = Math.max(40, Math.abs(x2 - x1) * .45) * (forward ? 1 : -1);
        return {id:child.id, color:child.color,
          path:`M ${x1} ${parent.y + 44} C ${x1 + bend} ${parent.y + 44}, ${x2 - bend} ${child.y + 44}, ${x2} ${child.y + 44}`};
      });
      return {nodes:placed, links, width:maxDepth * 284 + 288, height:Math.max(180, row * 116 + 32)};
    },
    current() { return this.allNodes.find(n => n.id === this.selected) || this.allNodes[0]; },
    evidence() { return this.citations.filter(c => (this.current.citations || []).includes(c.number)); },
    branches() { return this.allNodes.filter(n => n.depth === 1); },
  },
  mounted() {
    this.pointers = new Map();
    this.suppressClickUntil = 0;
    this.resizeObserver = new ResizeObserver(() => {
      const el = this.$refs.viewport;
      if (!el.clientWidth || !el.clientHeight) return;
      if (this.autoFit) this.fit();
      else if (this.viewportSize) {
        this.panX += (el.clientWidth - this.viewportSize.width) / 2;
        this.panY += (el.clientHeight - this.viewportSize.height) / 2;
      }
      this.viewportSize = {width:el.clientWidth, height:el.clientHeight};
    });
    this.resizeObserver.observe(this.$refs.viewport);
    this.$nextTick(() => this.fit());
  },
  beforeUnmount() {
    this.resizeObserver?.disconnect();
    cancelAnimationFrame(this.moveFrame);
  },
  methods: {
    async toggle(node) {
      const previous = {x:node.x, y:node.y};
      this.autoFit = false;
      this.expanded = this.expanded.includes(node.id) ? this.expanded.filter(id => id !== node.id) : [...this.expanded, node.id];
      this.selected = node.id;
      await this.$nextTick();
      const next = this.layout.nodes.find(n => n.id === node.id);
      if (next) {
        this.panX += (previous.x - next.x) * this.zoom;
        this.panY += (previous.y - next.y) * this.zoom;
        if (this.expanded.includes(node.id)) this.reveal([next, ...this.layout.nodes.filter(
          child => child.depth === node.depth + 1 && child.id.startsWith(node.id + '.'))]);
      }
    },
    reveal(nodes) {
      const el = this.$refs.viewport;
      const left = Math.min(...nodes.map(n => n.x)), right = Math.max(...nodes.map(n => n.x + 224));
      const top = Math.min(...nodes.map(n => n.y)), bottom = Math.max(...nodes.map(n => n.y + 88));
      this.zoomAt(Math.min(this.zoom, (el.clientWidth - 64) / (right - left),
        (el.clientHeight - 64) / (bottom - top)), el.clientWidth / 2, el.clientHeight / 2);
      this.panX += Math.max(32 - (left * this.zoom + this.panX),
        Math.min(0, el.clientWidth - 32 - (right * this.zoom + this.panX)));
      this.panY += Math.max(32 - (top * this.zoom + this.panY),
        Math.min(0, el.clientHeight - 32 - (bottom * this.zoom + this.panY)));
    },
    expandAll() { this.expanded = this.allNodes.filter(n => n.children.length).map(n => n.id); },
    collapseAll() { this.expanded = []; this.selected = '0'; this.detailOpen = false; this.$nextTick(() => this.fit()); },
    fit() {
      const el = this.$refs.viewport;
      if (!el?.clientWidth || !el.clientHeight) return;
      const nodes = this.layout.nodes;
      const left = Math.min(...nodes.map(n => n.x)), top = Math.min(...nodes.map(n => n.y));
      const width = Math.max(...nodes.map(n => n.x + 224)) - left;
      const height = Math.max(...nodes.map(n => n.y + 88)) - top;
      this.zoom = Math.min(1, Math.max(.1, Math.min((el.clientWidth - 64) / width, (el.clientHeight - 64) / height)));
      this.panX = (el.clientWidth - width * this.zoom) / 2 - left * this.zoom;
      this.panY = (el.clientHeight - height * this.zoom) / 2 - top * this.zoom;
      this.autoFit = true;
    },
    resetLayout() { this.positions = {}; this.$nextTick(() => this.fit()); },
    zoomAt(value, x, y) {
      const next = Math.min(2.5, Math.max(.1, value)), ratio = next / this.zoom;
      this.panX = x - (x - this.panX) * ratio;
      this.panY = y - (y - this.panY) * ratio;
      this.zoom = next;
      this.autoFit = false;
    },
    scale(delta) {
      const el = this.$refs.viewport;
      this.zoomAt(Math.round((this.zoom + delta) * 100) / 100, el.clientWidth / 2, el.clientHeight / 2);
    },
    wheel(event) {
      if (this.drag) return;
      const rect = this.$refs.viewport.getBoundingClientRect();
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1);
      this.zoomAt(this.zoom * Math.exp(-Math.max(-300, Math.min(300, delta)) * .002),
        event.clientX - rect.left, event.clientY - rect.top);
    },
    inspect(node) { this.selected = node.id; this.detailOpen = true; },
    ignoreDragClick(event) {
      if (event.detail && performance.now() < this.suppressClickUntil) {
        this.suppressClickUntil = 0;
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    pointerDown(event) {
      // A fresh press is deliberate; suppress only the click generated by a drag.
      this.suppressClickUntil = 0;
      if (event.target.closest('.map-node-toggle,a') || event.button !== 0) return;
      const el = this.$refs.viewport;
      this.applyGesture();
      this.pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
      const node = event.target.closest('.map-node');
      if (!node) el.focus({preventScroll:true});
      (event.target.closest('.map-node-label') || el).setPointerCapture(event.pointerId);
      this.beginGesture(node?.dataset.nodeId);
    },
    beginGesture(nodeId) {
      const points = [...this.pointers.values()];
      if (!points.length) { this.drag = null; return; }
      if (points.length >= 2) {
        const [a, b] = points, rect = this.$refs.viewport.getBoundingClientRect();
        const x = (a.x + b.x) / 2 - rect.left, y = (a.y + b.y) / 2 - rect.top;
        this.drag = {kind:'pinch', distance:Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
          zoom:this.zoom, worldX:(x - this.panX) / this.zoom, worldY:(y - this.panY) / this.zoom,
          left:rect.left, top:rect.top, moved:true};
      } else {
        const node = this.layout.nodes.find(n => n.id === nodeId);
        this.drag = {kind:node ? 'node' : 'pan', id:nodeId, start:points[0], moved:false,
          x:node?.x ?? this.panX, y:node?.y ?? this.panY};
      }
    },
    pointerMove(event) {
      if (!this.pointers.has(event.pointerId)) return;
      this.pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
      if (!this.moveFrame) this.moveFrame = requestAnimationFrame(() => {
        this.moveFrame = null;
        this.applyGesture();
      });
    },
    applyGesture() {
      const drag = this.drag, points = [...this.pointers.values()];
      if (!drag || !points.length) return;
      if (drag.kind === 'pinch' && points.length >= 2) {
        const [a, b] = points;
        this.zoom = Math.min(2.5, Math.max(.1, drag.zoom * Math.hypot(a.x - b.x, a.y - b.y) / drag.distance));
        this.panX = (a.x + b.x) / 2 - drag.left - drag.worldX * this.zoom;
        this.panY = (a.y + b.y) / 2 - drag.top - drag.worldY * this.zoom;
      } else {
        const dx = points[0].x - drag.start.x, dy = points[0].y - drag.start.y;
        if (!drag.moved && Math.hypot(dx, dy) < 4) return;
        drag.moved = true;
        if (drag.kind === 'node') {
          this.selected = drag.id;
          this.positions[drag.id] = {x:drag.x + dx / this.zoom, y:drag.y + dy / this.zoom};
        } else { this.panX = drag.x + dx; this.panY = drag.y + dy; }
      }
      this.autoFit = false;
    },
    pointerEnd(event) {
      if (!this.pointers.has(event.pointerId)) return;
      this.applyGesture();
      const moved = this.drag?.moved;
      if (moved) this.suppressClickUntil = performance.now() + 250;
      this.pointers.delete(event.pointerId);
      if (this.$refs.viewport.hasPointerCapture(event.pointerId)) this.$refs.viewport.releasePointerCapture(event.pointerId);
      this.beginGesture();
      if (this.drag && moved) this.drag.moved = true;
    },
    keyDown(event) {
      const directions = {ArrowLeft:[-32, 0], ArrowRight:[32, 0], ArrowUp:[0, -32], ArrowDown:[0, 32]};
      const movement = directions[event.key], card = event.target.closest('.map-node');
      if (movement && card && event.shiftKey) {
        const node = this.layout.nodes.find(n => n.id === card.dataset.nodeId);
        this.positions[node.id] = {x:node.x + movement[0] / this.zoom, y:node.y + movement[1] / this.zoom};
      } else if (event.target === this.$refs.viewport) {
        if (movement) { this.panX += movement[0]; this.panY += movement[1]; }
        else if (event.key === '+' || event.key === '=') this.scale(.15);
        else if (event.key === '-') this.scale(-.15);
        else if (event.key === '0' || event.key === 'Home') { event.preventDefault(); this.fit(); return; }
        else return;
      } else return;
      this.autoFit = false;
      event.preventDefault();
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
        <button @click="fit">Fit map</button>
        <button @click="resetLayout">Reset layout</button>
      </div>
      <div class="map-stage">
      <div class="map-viewport" :class="{'map-dragging':drag?.moved}" ref="viewport" tabindex="0"
        aria-label="Mind map canvas. Drag to pan, scroll to zoom. Arrow keys move the canvas; plus and minus zoom; Home fits the map."
        :style="{backgroundPosition:panX+'px '+panY+'px',backgroundSize:(20*zoom)+'px '+(20*zoom)+'px'}"
        @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerEnd" @pointercancel="pointerEnd"
        @lostpointercapture="pointerEnd" @click.capture="ignoreDragClick" @wheel.prevent="wheel" @keydown="keyDown">
          <svg class="map-svg" width="100%" height="100%" aria-label="Topic connections">
          <g class="map-world" :style="{transform:'translate('+panX+'px,'+panY+'px) scale('+zoom+')'}">
            <path v-for="link in layout.links" :key="link.id" :d="link.path" :stroke="link.color" stroke-width="2" fill="none" opacity=".6"/>
            <foreignObject v-for="node in layout.nodes" :key="node.id" :x="node.x" :y="node.y" width="224" height="88">
              <div class="map-node" :class="{'map-node-selected':selected===node.id}" :style="{'--branch':node.color}" :data-node-id="node.id">
                <button class="map-node-label" @click="inspect(node)" :aria-label="'Inspect topic '+node.name" :title="node.name+' · Drag to move; Shift + arrow keys to nudge'">
                  <span>{{node.name}}</span><small>{{node.children.length ? node.children.length + ' subtopics' : 'Concept'}}<template v-if="node.citations?.length"> · {{node.citations.length}} source refs</template></small>
                </button>
                <button v-if="node.children.length" class="map-node-toggle" @click.stop="toggle(node)"
                  :aria-expanded="expanded.includes(node.id)" :aria-label="(expanded.includes(node.id) ? 'Collapse ' : 'Expand ') + node.name">{{expanded.includes(node.id) ? '−' : '+'}}</button>
              </div>
            </foreignObject>
          </g>
          </svg>
      </div>
      <div class="map-gesture-hint" aria-hidden="true">Drag to move · Scroll or pinch to zoom</div>
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
