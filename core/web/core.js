// The core: the assistant drawn as a living sphere of its memories (the dashboard, index.html).
// An outer shell of fine dust, and inside it a neural network of memories joined by links. Light signals run along the
// links only while it really works (listening, recalling, speaking, a background job); idle, the network rests.
// Drawn on the graphics card (WebGL). Without it, or on a software renderer, a lighter 2D version is drawn instead.
// The number of points is fixed, however big the memory gets: growth shows as brighter topics, not more points.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  // colours from the theme (themes.js): the accent, the three memory kinds Hindsight keeps (facts, experiences,
  // observations), the recall highlight and the white-ish node cores. "rgb" strings for 2D, 0..1 triplets for WebGL.
  const C = {};
  const recolor = () => {
    const T = window.TH || { a: "95,216,255", a2: "140,215,255", a3: "30,88,120", k: ["95,216,255", "140,170,255", "79,224,166"], rc: "225,248,255", rc2: "255,255,255", hi: "235,250,255" };
    for (const k of ["a", "a2", "a3", "rc", "rc2", "hi"]) C[k] = T[k];
    C.k = T.k;
    const f = (t) => t.split(",").map((x) => Number(x) / 255);
    C.gl = { uA: f(T.a), uA2: f(T.a2), uK0: f(T.k[0]), uK1: f(T.k[1]), uK2: f(T.k[2]), uRc: f(T.rc), uRc2: f(T.rc2), uHi: f(T.hi) };
  };
  recolor();
  const COLS = "uniform highp vec3 uA, uA2, uK0, uK1, uK2, uRc, uRc2, uHi;";  // highp in both shaders, or WebGL refuses to link them

  // ---------- the network (model space: the outer shell has radius 1) ----------
  const SIZES = { big: [28, 36, 990, 1100], small: [18, 24, 500, 900], mini: [20, 30, 560, 700] };  // topics, per topic, loose, dust
  function build(size) {
    const [NC, PER, FREE, DUST] = SIZES[size] || SIZES.big;  // big: about 2,000 glowing points
    const rnd = () => Math.random() * 2 - 1, nodes = [], clusters = [];
    const add = (x, y, z, kind, cl, size, hub) => { nodes.push({ x, y, z, kind, cl, size, hub, ph: Math.random() * 6.28, lit: 0 }); return nodes.length - 1; };
    const core = add(0, 0, 0, 0, -1, 1.9, true);
    for (let ci = 0; ci < NC; ci++) {  // topics: a hub and its memories, at different depths
      const u = 1 - (ci + .5) / NC * 2, a = ci * 2.39996 + Math.random() * .5, s = Math.sqrt(1 - u * u), depth = .3 + Math.random() * .45;
      const dx = s * Math.cos(a) * depth, dy = u * depth, dz = s * Math.sin(a) * depth, mine = [];
      for (let j = 0; j < PER; j++) {
        let ox = 0, oy = 0, oz = 0;
        if (j) do { ox = rnd() * .16; oy = rnd() * .16; oz = rnd() * .16; } while (Math.hypot(dx + ox, dy + oy, dz + oz) > .9);
        mine.push(add(dx + ox, dy + oy, dz + oz, ci % 3, ci, j ? .55 + Math.random() * .6 : 1.6, !j));
      }
      clusters.push(mine);
    }
    for (let i = 0; i < FREE; i++) {  // loose neurons, denser towards the middle, thinning out before the edge
      const r = .9 * Math.pow(Math.random(), .5), u = rnd(), a = Math.random() * 6.283, s = Math.sqrt(1 - u * u);
      add(s * Math.cos(a) * r, u * r, s * Math.sin(a) * r, i % 3, -1, .3 + Math.random() * .3, false);
    }
    // links: nearest neighbours, found through a grid so this stays fast with thousands of points
    const adj = nodes.map(() => []), edges = [];
    const link = (a, b) => { if (a === b || adj[a].includes(b)) return; edges.push(a, b); adj[a].push(b); adj[b].push(a); };
    const G = 16, cell = (v) => Math.max(0, Math.min(G - 1, ((v + 1) / 2 * G) | 0)), grid = new Map();
    nodes.forEach((n, i) => { if (i === core) return; const k = cell(n.x) + G * (cell(n.y) + G * cell(n.z)); (grid.get(k) || grid.set(k, []).get(k)).push(i); });
    const near = (i, k, skip) => {
      const n = nodes[i], cx = cell(n.x), cy = cell(n.y), cz = cell(n.z), found = [];
      for (let r = 1; found.length < k + 4 && r < 4; r++) {
        found.length = 0;
        for (let x = cx - r; x <= cx + r; x++) for (let y = cy - r; y <= cy + r; y++) for (let z = cz - r; z <= cz + r; z++) {
          if (x < 0 || y < 0 || z < 0 || x >= G || y >= G || z >= G) continue;
          for (const j of grid.get(x + G * (y + G * z)) || []) if (j !== i && !skip(j)) found.push(j);
        }
      }
      const d2 = (j) => (nodes[j].x - n.x) ** 2 + (nodes[j].y - n.y) ** 2 + (nodes[j].z - n.z) ** 2;
      return found.sort((p, q) => d2(p) - d2(q)).slice(0, k);
    };
    clusters.forEach((mine) => {
      const hub = mine[0], inCl = new Set(mine);
      mine.forEach((n, j) => { if (!j) return; if (j < 7) link(n, hub); near(n, 2, (m) => !inCl.has(m) || m === hub).forEach((m) => link(n, m)); });
      link(hub, core);
    });
    clusters.forEach((mine) => {  // each topic also knows its nearest neighbour topic
      const h = nodes[mine[0]], d2 = (c) => (nodes[c[0]].x - h.x) ** 2 + (nodes[c[0]].y - h.y) ** 2 + (nodes[c[0]].z - h.z) ** 2;
      link(mine[0], clusters.filter((c) => c !== mine).sort((p, q) => d2(p) - d2(q))[0][0]);
    });
    for (let i = 1 + NC * PER; i < nodes.length; i++) near(i, 3, () => false).forEach((m) => link(i, m));
    const dust = [];
    for (let i = 0; i < DUST; i++) {
      const y = 1 - (i / (DUST - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.39996323;
      dust.push({ x: Math.cos(th) * r, y, z: Math.sin(th) * r, ph: Math.random() * 6.28 });
    }
    return { nodes, edges, adj, clusters, dust, core, PER };
  }

  // ---------- WebGL ----------
  const PROJ = `
    ${COLS}
    uniform vec2 uC, uRes; uniform float uR, uT, uAmp, uIdle, uBreathe, uRot, uDpr, uHb;
    vec3 turn(vec3 p) {
      float c = cos(uRot), s = sin(uRot), cx = cos(.38), sx = sin(.38);
      vec3 q = vec3(p.x * c + p.z * s, p.y, -p.x * s + p.z * c);
      return vec3(q.x, q.y * cx - q.z * sx, q.y * sx + q.z * cx);
    }
    vec4 place(vec3 q, float scale) {
      float f = 3.2 / (3.2 - q.z); vec2 sp = uC + q.xy * scale * f;
      return vec4(sp.x / uRes.x * 2. - 1., 1. - sp.y / uRes.y * 2., 0., 1.);
    }
    vec3 drift(vec3 p, float ph) {
      float sw = 1. + uAmp * .07 * sin(uT * 9. + ph) + uIdle * .04 * sin(uT * 1.9 + ph);
      return (p + vec3(sin(uT * .5 + ph), cos(uT * .6 + ph), sin(uT * .4 + ph * 2.)) * .025) * sw;
    }`;
  const SH = {
    dust: [`attribute vec3 aP; attribute float aPh; varying float vA;${PROJ}
      void main() {
        float w = uAmp * (.07 * sin(aP.y * 7. + uT * 11. + aPh) + .06 * sin(aP.x * 5. - uT * 7.))
                + uIdle * (.07 * sin(aP.y * 5. + uT * 2.4 + aPh * .4) + .06 * sin(aP.x * 4. - uT * 1.7));
        vec3 q = turn(aP); float d = (q.z + 1.) / 2., small = step(uR / uDpr, 110.);
        gl_Position = place(q, uR * uBreathe * (1. + w));
        vA = q.z >= 0. ? .05 + d * .32 + uAmp * .15 * d : .05 + d * .22;
        gl_PointSize = (mix(1., .7, small) + d * mix(.9, .5, small)) * uDpr;
      }`, `precision mediump float; ${COLS} varying float vA; void main() { gl_FragColor = vec4(uA, 1.) * vA; }`],
    link: [`attribute vec3 aP; attribute float aPh, aLit; varying vec4 vC;${PROJ}
      void main() {
        vec3 q = turn(drift(aP, aPh)); float d = (q.z + 1.) / 2.;
        gl_Position = place(q, uR * uBreathe);
        vC = aLit > .05 ? vec4(uRc, 1.) * (.12 + aLit * .5) : vec4(uA2 * .86, 1.) * (.03 + d * .11 + uAmp * .06);
      }`, `precision mediump float; varying vec4 vC; void main() { gl_FragColor = vC; }`],
    node: [`attribute vec3 aP; attribute float aPh, aSize, aKind, aLit; varying vec3 vCol; varying float vA, vDot, vDA, vLit;${PROJ}
      void main() {
        vec3 q = turn(drift(aP, aPh)); float d = (q.z + 1.) / 2., small = step(uR / uDpr, 110.);
        gl_Position = place(q, uR * uBreathe);
        float base = mix(2.1, 1., small) * aSize * (.6 + d * .7), gs = base * (9. + aLit * 7. + uAmp * 3.) * (1. + uHb * .45);
        gl_PointSize = gs * uDpr;
        vCol = aKind < -.5 ? uHi : aKind < .5 ? uK0 : aKind < 1.5 ? uK1 : uK2;
        vLit = aLit; vA = min(1., .25 + d * .55 + aLit * .4 + uHb * .25);
        vDot = base * (.55 + aLit * .3) / (gs / 2.); vDA = .35 + d * .6;
      }`, `precision mediump float; ${COLS} varying vec3 vCol; varying float vA, vDot, vDA, vLit;
      void main() {
        float r = length(gl_PointCoord - .5) * 2.; if (r > 1.) discard;
        vec3 col = vLit > .15 ? uRc : vCol;
        float g = r < .18 ? mix(1., .55, r / .18) : r < .5 ? mix(.55, .12, (r - .18) / .32) : mix(.12, 0., (r - .5) / .5);
        vec3 c = col * g * vA;
        if (r < vDot) c += (vLit > .15 ? uRc2 * (.7 + vLit * .3) : uHi * vDA) * smoothstep(vDot, vDot * .7, r);
        gl_FragColor = vec4(c, max(c.r, max(c.g, c.b)));
      }`],
    pulse: [`attribute vec3 aP; attribute float aAmber; varying float vAmber;${PROJ}
      void main() { gl_Position = place(turn(aP), uR * uBreathe); gl_PointSize = (uR / uDpr < 110. ? 8. : 16.) * uDpr; vAmber = aAmber; }`,
      `precision mediump float; ${COLS} varying float vAmber;
      void main() {
        float r = length(gl_PointCoord - .5) * 2.; if (r > 1.) discard;
        float g = r < .18 ? mix(1., .55, r / .18) : r < .5 ? mix(.55, .12, (r - .18) / .32) : mix(.12, 0., (r - .5) / .5);
        vec3 c = (vAmber > .5 ? uRc : uHi) * g;
        gl_FragColor = vec4(c, max(c.r, max(c.g, c.b)));
      }`],
  };

  function glRenderer(gl, net) {
    const prog = (vs, fs) => {
      const p = gl.createProgram();
      for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
        const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
        gl.attachShader(p, s);
      }
      gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
      const u = {}; for (const n of ["uC", "uRes", "uR", "uT", "uAmp", "uIdle", "uBreathe", "uRot", "uDpr", "uHb", ...Object.keys(C.gl)]) u[n] = gl.getUniformLocation(p, n);
      return { p, u, a: (n) => gl.getAttribLocation(p, n) };
    };
    const P = Object.fromEntries(Object.entries(SH).map(([k, [v, f]]) => [k, prog(v, f)]));
    const buf = (data, usage) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, usage || gl.STATIC_DRAW); return b; };
    const { nodes, edges, dust } = net;
    const dustB = buf(new Float32Array(dust.flatMap((p) => [p.x, p.y, p.z, p.ph])));
    const nodeB = buf(new Float32Array(nodes.flatMap((n, i) => [n.x, n.y, n.z, n.ph, n.size, i === net.core ? -1 : n.kind])));
    const linkB = buf(new Float32Array(edges.flatMap((i) => [nodes[i].x, nodes[i].y, nodes[i].z, nodes[i].ph])));
    const nodeLit = new Float32Array(nodes.length), linkLit = new Float32Array(edges.length);
    const nodeLitB = buf(nodeLit, gl.DYNAMIC_DRAW), linkLitB = buf(linkLit, gl.DYNAMIC_DRAW);
    const pulseData = new Float32Array(260 * 4), pulseB = buf(pulseData, gl.DYNAMIC_DRAW);
    const attr = (pr, name, b, size, stride, off) => {
      const l = pr.a(name); if (l < 0) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, size, gl.FLOAT, false, stride * 4, off * 4);
    };
    let litDirty = false;
    const uniforms = (pr, s) => {
      gl.useProgram(pr.p);
      gl.uniform2f(pr.u.uC, s.cx * s.dpr, s.cy * s.dpr); gl.uniform2f(pr.u.uRes, s.W * s.dpr, s.H * s.dpr);
      gl.uniform1f(pr.u.uR, s.R * s.dpr); gl.uniform1f(pr.u.uT, s.t); gl.uniform1f(pr.u.uAmp, s.amp); gl.uniform1f(pr.u.uIdle, s.idle);
      gl.uniform1f(pr.u.uBreathe, s.breathe); gl.uniform1f(pr.u.uRot, s.rot); gl.uniform1f(pr.u.uDpr, s.dpr); gl.uniform1f(pr.u.uHb, s.hb);
      for (const k in C.gl) gl.uniform3fv(pr.u[k], C.gl[k]);
    };
    return {
      lit() { litDirty = true; },
      sizes() { gl.bindBuffer(gl.ARRAY_BUFFER, nodeB); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(nodes.flatMap((n, i) => [n.x, n.y, n.z, n.ph, n.size, i === net.core ? -1 : n.kind])), gl.STATIC_DRAW); },
      draw(s, pulses) {
        gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
        gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); gl.enable(gl.BLEND);
        if (litDirty) {
          nodes.forEach((n, i) => (nodeLit[i] = n.lit));
          for (let k = 0; k < edges.length; k++) linkLit[k] = nodes[edges[k]].lit;
          gl.bindBuffer(gl.ARRAY_BUFFER, nodeLitB); gl.bufferSubData(gl.ARRAY_BUFFER, 0, nodeLit);
          gl.bindBuffer(gl.ARRAY_BUFFER, linkLitB); gl.bufferSubData(gl.ARRAY_BUFFER, 0, linkLit);
          litDirty = false;
        }
        // all colours are premultiplied, so "one" adds light (glow) and "one minus alpha" never darkens
        gl.blendFunc(gl.ONE, gl.ONE);
        uniforms(P.dust, s); attr(P.dust, "aP", dustB, 3, 4, 0); attr(P.dust, "aPh", dustB, 1, 4, 3);
        gl.drawArrays(gl.POINTS, 0, dust.length);
        uniforms(P.link, s); attr(P.link, "aP", linkB, 3, 4, 0); attr(P.link, "aPh", linkB, 1, 4, 3); attr(P.link, "aLit", linkLitB, 1, 1, 0);
        gl.drawArrays(gl.LINES, 0, edges.length);
        uniforms(P.node, s); attr(P.node, "aP", nodeB, 3, 6, 0); attr(P.node, "aPh", nodeB, 1, 6, 3); attr(P.node, "aSize", nodeB, 1, 6, 4);
        attr(P.node, "aKind", nodeB, 1, 6, 5); attr(P.node, "aLit", nodeLitB, 1, 1, 0);
        gl.drawArrays(gl.POINTS, 0, nodes.length);
        if (pulses.length) {
          pulses.forEach((q, i) => {
            const a = nodes[q.a], b = nodes[q.b];
            pulseData.set([a.x + (b.x - a.x) * q.u, a.y + (b.y - a.y) * q.u, a.z + (b.z - a.z) * q.u, q.amber ? 1 : 0], i * 4);
          });
          gl.bindBuffer(gl.ARRAY_BUFFER, pulseB); gl.bufferSubData(gl.ARRAY_BUFFER, 0, pulseData.subarray(0, pulses.length * 4));
          uniforms(P.pulse, s); attr(P.pulse, "aP", pulseB, 3, 4, 0); attr(P.pulse, "aAmber", pulseB, 1, 4, 3);
          gl.drawArrays(gl.POINTS, 0, pulses.length);
        }
        for (const l of [0, 1, 2, 3, 4, 5]) gl.disableVertexAttribArray(l);
      },
    };
  }

  // ---------- 2D fallback (no WebGL, or a software renderer): fewer points, same look ----------
  function flatRenderer(ctx, net) {
    const sprite = (rgb) => {
      const c = document.createElement("canvas"); c.width = c.height = 64; const g = c.getContext("2d");
      const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      gr.addColorStop(0, `rgba(${rgb},1)`); gr.addColorStop(.18, `rgba(${rgb},.55)`); gr.addColorStop(.5, `rgba(${rgb},.12)`); gr.addColorStop(1, `rgba(${rgb},0)`);
      g.fillStyle = gr; g.fillRect(0, 0, 64, 64); return c;
    };
    let GLOW, AMBER, WHITE;
    const paint = () => { GLOW = C.k.map(sprite); AMBER = sprite(C.rc); WHITE = sprite(C.hi); };
    paint();
    const { nodes, edges, dust } = net;
    return {
      lit() {},
      recolor: paint,
      draw(s, pulses) {
        const { cx, cy, R, t, amp, idle, breathe } = s, small = R < 110;
        const cosY = Math.cos(s.rot), sinY = Math.sin(s.rot), cosX = Math.cos(.38), sinX = Math.sin(.38);
        const proj = (x0, y0, z0, sc, o) => {
          let x = x0 * cosY + z0 * sinY, z = -x0 * sinY + z0 * cosY, y = y0;
          const y2 = y * cosX - z * sinX; z = y * sinX + z * cosX; y = y2;
          const f = 3.2 / (3.2 - z); o.sx = cx + x * sc * f; o.sy = cy + y * sc * f; o.sz = z;
        };
        for (const p of dust) {
          const w = amp * (.07 * Math.sin(p.y * 7 + t * 11 + p.ph) + .06 * Math.sin(p.x * 5 - t * 7)) + idle * (.07 * Math.sin(p.y * 5 + t * 2.4 + p.ph * .4) + .06 * Math.sin(p.x * 4 - t * 1.7));
          proj(p.x, p.y, p.z, R * breathe * (1 + w), p);
        }
        for (const n of nodes) {
          const sw = 1 + amp * .07 * Math.sin(t * 9 + n.ph) + idle * .04 * Math.sin(t * 1.9 + n.ph);
          proj((n.x + Math.sin(t * .5 + n.ph) * .025) * sw, (n.y + Math.cos(t * .6 + n.ph) * .025) * sw, (n.z + Math.sin(t * .4 + n.ph * 2) * .025) * sw, R * breathe, n);
        }
        const dots = (front) => { for (const p of dust) { if ((p.sz >= 0) !== front) continue; const d = (p.sz + 1) / 2;
          ctx.fillStyle = `rgba(${C.a},${front ? .05 + d * .32 + amp * .15 * d : .05 + d * .22})`; const z = (small ? .7 : 1) + d * (small ? .5 : .9); ctx.fillRect(p.sx - z / 2, p.sy - z / 2, z, z); } };
        dots(false);
        ctx.lineWidth = small ? .5 : 1;
        const bk = [[], [], [], []];
        for (let k = 0; k < edges.length; k += 2) {
          const a = nodes[edges[k]], b = nodes[edges[k + 1]], lit = Math.max(a.lit, b.lit);
          if (lit > .05) { ctx.strokeStyle = `rgba(${C.rc},${.12 + lit * .5})`; ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke(); continue; }
          bk[Math.min(3, ((a.sz + b.sz) / 2 + 1) * 2 | 0)].push(a, b);
        }
        bk.forEach((l, i) => { ctx.strokeStyle = `rgba(${C.a2},${.03 + (i + .5) / 4 * .11 + amp * .06})`; ctx.beginPath();
          for (let k = 0; k < l.length; k += 2) { ctx.moveTo(l[k].sx, l[k].sy); ctx.lineTo(l[k + 1].sx, l[k + 1].sy); } ctx.stroke(); });
        ctx.globalCompositeOperation = "lighter";
        for (const q of pulses) {
          const a = nodes[q.a], b = nodes[q.b], z = small ? 8 : 16;
          ctx.drawImage(q.amber ? AMBER : WHITE, a.sx + (b.sx - a.sx) * q.u - z / 2, a.sy + (b.sy - a.sy) * q.u - z / 2, z, z);
        }
        for (const n of nodes) {
          const d = (n.sz + 1) / 2, base = (small ? 1 : 2.1) * n.size * (.6 + d * .7), gs = base * (9 + n.lit * 7 + amp * 3) * (1 + s.hb * .45);
          ctx.globalAlpha = Math.min(1, .25 + d * .55 + n.lit * .4 + s.hb * .25);
          ctx.drawImage(n.lit > .15 ? AMBER : n === nodes[net.core] ? WHITE : GLOW[n.kind], n.sx - gs / 2, n.sy - gs / 2, gs, gs);
          ctx.globalAlpha = 1;
          ctx.fillStyle = n.lit > .15 ? `rgba(${C.rc2},${.7 + n.lit * .3})` : `rgba(${C.hi},${.35 + d * .6})`;
          ctx.beginPath(); ctx.arc(n.sx, n.sy, base * (.55 + n.lit * .3), 0, 6.283); ctx.fill();
        }
        ctx.globalCompositeOperation = "source-over";
        dots(true);
      },
    };
  }

  // ---------- the halo (glow and rings), always 2D, under the network ----------
  function halo(ctx, s, thinkGlow) {
    const { cx, cy, R, amp, idle, rot, t, hb, a1, a2 } = s, small = R < 110;
    // the core's glow, and on each slow heartbeat a bloom in its heart, as one gradient (one fill per frame)
    const gR = R * (1.25 + hb * .14), g = ctx.createRadialGradient(cx, cy, 0, cx, cy, gR);
    if (hb > .01) { g.addColorStop(0, `rgba(${C.rc},${.10 + hb * .5})`); g.addColorStop(.24, `rgba(${C.a},${.10 + amp * .2 + hb * .28})`); }
    else g.addColorStop(0, `rgba(${C.a},${.10 + amp * .22 + thinkGlow * .08})`);
    g.addColorStop(.5, `rgba(${C.a3},${.08 + amp * .08 + hb * .1})`); g.addColorStop(1, `rgba(${C.a3},0)`);
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, gR, 0, 6.283); ctx.fill();
    ctx.save(); ctx.translate(cx, cy);
    const ringA = .35 + amp * .4 + hb * .4, hs = 1 + hb * .09;  // the rings swell on each beat
    ctx.rotate(-rot * .4);  // fine tick ring
    const r1 = R * 1.2 * hs, ticks = small ? 48 : 120;
    ctx.strokeStyle = `rgba(${C.a},${ringA * .7})`; ctx.lineWidth = 1; ctx.beginPath();
    for (let i = 0; i < ticks; i++) { const a = i / ticks * 6.283, l = i % 10 === 0 ? 7 : 3; ctx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1); ctx.lineTo(Math.cos(a) * (r1 + l), Math.sin(a) * (r1 + l)); }
    ctx.stroke();
    ctx.rotate(rot * .4);  // the voice ring: bars that move with the voice (slowly when idle, a spike on each beat)
    const r2 = R * 1.1 * hs, bars = small ? 48 : 96;
    ctx.strokeStyle = `rgba(${C.a},${.25 + idle * .35 + amp * .6})`; ctx.lineWidth = small ? 1.4 : 2; ctx.beginPath();
    for (let i = 0; i < bars; i++) {
      const a = i / bars * 6.283;
      const v = amp * (.5 + .5 * Math.sin(i * .9 + t * 13)) * (.6 + .4 * Math.sin(i * .23 - t * 4)) + idle * (.5 + .5 * Math.sin(i * .37 + t * 2.8)) * (.6 + .4 * Math.sin(i * .13 - t * 1.4))
        + hb * (.9 + .5 * Math.sin(i * .5)) + .02;
      const l = v * R * .16; ctx.moveTo(Math.cos(a) * r2, Math.sin(a) * r2); ctx.lineTo(Math.cos(a) * (r2 + l), Math.sin(a) * (r2 + l));
    }
    ctx.stroke();
    // two arc pairs, each arc opposite its twin and all four of different lengths. Idle: a slow drift. Thinking: they
    // counter-turn like a loader and meet on every beat (see the frame loop).
    ctx.lineCap = "butt";
    const pair = (r, a, h1, h2) => { ctx.beginPath(); ctx.arc(0, 0, r, a - h1, a + h1); ctx.stroke(); ctx.beginPath(); ctx.arc(0, 0, r, a + Math.PI - h2, a + Math.PI + h2); ctx.stroke(); };
    ctx.strokeStyle = thinkGlow > .1 ? `rgba(${C.rc},${.32 + thinkGlow * .22 + hb * .12})` : `rgba(${C.a},${ringA})`;
    ctx.lineWidth = (small ? 1.5 : 2.5) * (1 + hb * .8);
    pair(R * 1.34 * hs, a1, .62, .40);
    ctx.strokeStyle = thinkGlow > .1 ? `rgba(${C.rc},${.22 + thinkGlow * .16 + hb * .1})` : `rgba(${C.a},${ringA * .6})`;
    ctx.lineWidth = (small ? 1 : 1.6) * (1 + hb * .8);
    pair(R * 1.42 * hs, a2, .50, .30);
    ctx.restore();
  }

  // ---------- public: Core.start(stage), then mode / target / talk ----------
  window.Core = {
    recolor() { recolor(); if (window.Core._r && window.Core._r.recolor) window.Core._r.recolor(); },  // a new theme
    start(stage, opts = {}) {  // opts.points: "mini" for the small window
      const back = document.createElement("canvas"), front = document.createElement("canvas");
      back.className = front.className = "core-layer"; stage.prepend(back, front);
      let gl = null, cheap = false;
      try { gl = front.getContext("webgl", { premultipliedAlpha: true, antialias: true, alpha: true }); } catch {}
      if (gl) {  // a software renderer can't keep up with the big network: use the light version
        const info = gl.getExtension("WEBGL_debug_renderer_info");
        const name = info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : "";
        cheap = /llvmpipe|softpipe|swiftshader|software/i.test(name);
        if (cheap) { gl = null; front.remove(); }
      }
      const bctx = back.getContext("2d");
      let net = build(opts.points || (gl ? "big" : "small")), r = null;
      if (gl) try { r = glRenderer(gl, net); } catch (e) { console.warn("core: WebGL failed, drawing in 2D:", e.message); gl = null; front.remove(); net = build(opts.points || "small"); }
      if (!r) { if (!gl && front.isConnected) front.remove(); r = flatRenderer(bctx, net); }
      window.Core._r = r;
      const state = { mode: "idle", amp: 0, ampT: 0, thinkGlow: 0, lit: -1, rot: 0, bg: false, hbT: 0, a1: null, a2: null, spin: false, spinS: 0, spinS0: 0 };
      const orb = { x: 0, y: 0, r: 0, tx: 0, ty: 0, tr: 0, slow: false };
      let W = 0, H = 0, DPR = 1, raf = 0, t0 = performance.now(), last = 0;
      const pulses = [];
      let HDPR = 1, box = null;
      const resize = () => {
        const b = stage.getBoundingClientRect(); W = b.width; H = b.height;
        // a big window on a sharp screen means millions of pixels per frame: keep the network to about 4 MP, and draw the
        // soft halo (glow and rings, a 2D canvas) at one pixel per point, which looks the same and costs a fraction
        DPR = Math.min(devicePixelRatio || 1, 1.5, Math.sqrt(4.2e6 / Math.max(1, W * H)));
        HDPR = gl ? Math.min(1, DPR) : DPR;
        front.width = W * DPR; front.height = H * DPR;
        back.width = W * HDPR; back.height = H * HDPR;
        bctx.setTransform(HDPR, 0, 0, HDPR, 0, 0); box = null;
        if (api && api.onResize) api.onResize();  // the page places the core only after the core knows its new size
      };
      let api = null;
      new ResizeObserver(resize).observe(stage); resize();
      const frame = (now) => {
        raf = requestAnimationFrame(frame);
        if (orb.slow && now - last < 30) return;  // docked in the corner: 30 frames a second is plenty
        last = now;
        const dt = Math.min(.05, (now - t0) / 1000); t0 = now; const t = now / 1000;
        const k = 1 - Math.pow(.0009, dt);
        orb.x += (orb.tx - orb.x) * k; orb.y += (orb.ty - orb.y) * k; orb.r += (orb.tr - orb.r) * k;
        const speaking = state.mode === "speak";
        if (speaking) { state.ampT -= dt; if (state.ampT <= 0) { state.ampT = .07 + Math.random() * .16; state.amp = Math.max(state.amp, .45 + Math.random() * .55); } state.amp *= Math.pow(.02, dt); }
        else state.amp *= Math.pow(.01, dt);
        if (state.mode === "listen") state.amp = Math.max(state.amp, .12 + .1 * Math.sin(t * 9) ** 2);
        state.thinkGlow += ((state.mode === "think" ? 1 : 0) - state.thinkGlow) * (1 - Math.pow(.02, dt));
        state.rot += dt * (reduce ? .03 : .14 + state.amp * .25);
        const thinking = state.mode === "think";
        // thinking is a heartbeat: one long, slow beat ("biiiim"), a quick swell and a long fade. It fires when the
        // counter-turning arc pairs meet, so the lines and the glow stay in step. The network itself rests.
        state.hbT = thinking ? state.hbT + dt : (state.thinkGlow < .02 ? 0 : state.hbT + dt);
        const beat = state.hbT < .2 ? Math.sin(state.hbT / .2 * Math.PI / 2) ** 2 : Math.exp(-(state.hbT - .2) / .55);
        const hb = reduce ? 0 : (thinking ? 1 : state.thinkGlow) * beat;
        {  // the outer arc pairs: a slow drift; while thinking they meet halfway, then counter-turn at 1.9 rad/s and
           // slow down to a quarter on every second meeting, which is the beat; afterwards they ease back
          const n1 = state.rot * .9, n2 = -state.rot * .7 + 1.57;
          const wrap = (d) => { d = (d + Math.PI / 2) % Math.PI; if (d < 0) d += Math.PI; return d - Math.PI / 2; };  // a pair repeats every half turn
          if (state.a1 === null) { state.a1 = n1; state.a2 = n2; }
          if (thinking && !reduce) {
            if (!state.spin) { state.spin = true; state.spinS = state.spinS0 = state.a1 + wrap(state.a2 - state.a1) / 2; }
            const rel = 2 * (state.spinS - state.spinS0), mi = Math.round(rel / Math.PI), on = mi % 2 === 0;
            const sep = Math.abs(rel - mi * Math.PI), near = on ? Math.min(1, sep / .5) : 1, ease = near * near * (3 - 2 * near);
            state.spinS += dt * 1.9 * (.25 + .75 * ease);
            const rel2 = 2 * (state.spinS - state.spinS0), sep2 = Math.abs(rel2 - Math.round(rel2 / Math.PI) * Math.PI);
            if (on && sep2 < sep && sep2 < .06 && state.hbT > .5) { state.hbT = 0; if (api.onBeat) api.onBeat(); }  // they meet again: a beat
          } else state.spin = false;
          const ka = 1 - Math.pow(state.spin ? .004 : .06, dt);
          state.a1 += wrap((state.spin ? state.spinS : n1) - state.a1) * ka;
          state.a2 += wrap((state.spin ? 2 * state.spinS0 - state.spinS : n2) - state.a2) * ka;  // the outer pair turns the other way
        }
        const idle = (reduce ? .1 : .55) * (1 - Math.min(1, state.amp * 1.2)) * (.7 + .3 * Math.sin(t * .8));
        const s = { cx: orb.x, cy: orb.y, R: orb.r, t, amp: state.amp, idle, rot: state.rot, hb, a1: state.a1, a2: state.a2,
          breathe: (1 + Math.sin(t * 1.1) * .012) * (1 + hb * .03), W, H, dpr: DPR };
        // signals: only while it really talks with you (listening, speaking) or a background job runs; not while thinking
        const m = net, working = (state.mode !== "idle" && !thinking) || state.bg;
        {
          const rate = !working ? 0 : (reduce ? .5 : 4) + state.amp * 16;
          if (Math.random() < rate * dt) {
            const e = (Math.random() * m.edges.length / 2 | 0) * 2, flip = Math.random() < .5;
            pulses.push({ a: m.edges[e + (flip ? 1 : 0)], b: m.edges[e + (flip ? 0 : 1)], u: 0, spd: 1.1 + Math.random() * 1.2, hops: 2 + (Math.random() * 3 | 0) });
          }
          let anyLit = false;
          for (const n of m.nodes) if (n.lit > .002) { n.lit *= Math.pow(.3, dt); anyLit = true; } else n.lit = 0;
          for (let i = pulses.length - 1; i >= 0; i--) {
            const q = pulses[i]; q.u += dt * q.spd * (1 + state.amp);
            if (q.u < 1) continue;
            const b = m.nodes[q.b]; b.lit = Math.max(b.lit, .35); anyLit = true;
            const nx = m.adj[q.b].filter((n) => n !== q.a);
            if (--q.hops > 0 && working && nx.length && pulses.length < 240) { q.a = q.b; q.b = nx[Math.random() * nx.length | 0]; q.u = 0; }
            else pulses.splice(i, 1);
          }
          if (anyLit) r.lit();
        }
        // only the square around the core changes: clear that (and where it was last frame), not the whole stage
        const e = orb.r * 1.9, nb = [orb.x - e, orb.y - e, orb.x + e, orb.y + e];
        const cb = box ? [Math.min(box[0], nb[0]), Math.min(box[1], nb[1]), Math.max(box[2], nb[2]), Math.max(box[3], nb[3])] : [0, 0, W, H];
        bctx.clearRect(cb[0] - 2, cb[1] - 2, cb[2] - cb[0] + 4, cb[3] - cb[1] + 4); box = nb;
        halo(bctx, s, state.thinkGlow);
        r.draw(s, pulses);
      };
      const run = () => { if (!raf && !document.hidden) { t0 = performance.now(); raf = requestAnimationFrame(frame); } };
      const stop = () => { cancelAnimationFrame(raf); raf = 0; };
      document.addEventListener("visibilitychange", () => (document.hidden ? stop() : run()));  // hidden: uses nothing
      run();
      api = {
        get size() { return { W, H }; },
        gpu: !!gl,
        mode(m) { if (m === "think" && state.mode !== "think") { state.hbT = 0; if (api.onBeat) setTimeout(api.onBeat); } state.mode = m; },  // the first beat lands at once
        background(on) { state.bg = !!on; },
        // the biggest topics in memory: their hubs grow with how much it knows about them (the point count stays fixed)
        topics(counts) {
          const max = Math.max(1, ...counts);
          net.clusters.forEach((c, i) => { const v = counts[i] || 0; net.nodes[c[0]].size = .9 + 1.5 * Math.sqrt(v / max); });
          if (r.sizes) r.sizes();
        },  // the nightly review or the morning brief is running
        talk() { state.amp = Math.max(state.amp, .5 + Math.random() * .4); },  // a piece of the reply arrived
        target(x, y, rr, slow) { const first = !orb.r; Object.assign(orb, { tx: x, ty: y, tr: rr, slow: !!slow }); if (first) Object.assign(orb, { x, y, r: rr }); },
      };
      return api;
    },
  };
})();
