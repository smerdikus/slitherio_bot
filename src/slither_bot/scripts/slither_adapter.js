// Compatibility adapter for Slither's exposed client state. No network protocol injection.
// Names are feature-detected; absent measurements remain null. See README's compatibility notes.
(() => {
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const number = value => finite(value) ? value : null;
  const player = () => window.slither ?? window.snake ?? null;
  let previousPlayer = null, instance = 0, seenRunning = false, requested = false;
  const alive = () => {
    const p = player();
    return p && finite(p.xx) && finite(p.yy) && !p.dead && window.playing === true;
  };
  function identity() {
    const p = player();
    if (alive() && p !== previousPlayer) {instance++; previousPlayer = p;}
    return instance;
  }
  function canvas() {
    if (window.mc instanceof HTMLCanvasElement) return window.mc;
    return [...document.querySelectorAll('canvas')]
      .filter(c => c.getBoundingClientRect().width > 0)
      .sort((a,b) => b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight)[0] ?? null;
  }
  function nicknameInput() {
    return window.nick instanceof HTMLInputElement ? window.nick
      : document.querySelector('input[placeholder="Nickname" i]');
  }
  function playButton() {
    return [...document.querySelectorAll('button,input[type="button"],input[type="submit"],[role="button"]')]
      .find(e => /^play(?:\s|!|$)/i.test((e.textContent || e.value || '').trim())
        && e.getBoundingClientRect().width > 0);
  }
  function status() {
    identity();
    if (alive()) {seenRunning = true; requested = false; return 'RUNNING';}
    if (window.connecting === true || requested) return 'STARTING';
    if (seenRunning && (player()?.dead || window.playing === false || player() === null)) return 'DEAD';
    if (nicknameInput() || playButton()) return 'MENU';
    return 'UNKNOWN';
  }
  window.__slitherAdapter = {
    start(nickname) {
      const input = nicknameInput();
      if (input) {
        input.value = nickname;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        input.dispatchEvent(new Event('change', {bubbles:true}));
        input.blur();
      }
      const button = playButton();
      if (button && !button.disabled && !alive()) button.click();
      else if (typeof window.connect === 'function') window.connect();
      else throw new Error('Slither start control not found. Site may have changed; inspect the adapter.');
      requested = true;
    },
    available(id) {return alive() && identity() === id;},
    capture(sectors) {
      const state = status(), p = player(), c = canvas();
      const result = {status:state, instance_id:instance, viewport:[innerWidth,innerHeight],
        center:null, rect:null, size:null, score:null, heading:null, world:null, scale:null,
        enemies:Array(sectors).fill(null), food:Array(sectors).fill(null),
        boundary:Array(sectors).fill(null)};
      if (!c) return result;
      const r = c.getBoundingClientRect();
      // Clip only the usable input rectangle, not the projection origin or direction.
      const left = Math.max(0,r.left), top = Math.max(0,r.top);
      result.rect = {left, top, width:Math.max(0,Math.min(innerWidth,r.right)-left),
        height:Math.max(0,Math.min(innerHeight,r.bottom)-top)};
      if (!p || !finite(p.xx) || !finite(p.yy)) return result;
      const x = p.xx + (number(p.fx) ?? 0), y = p.yy + (number(p.fy) ?? 0);
      result.world = [x,y];
      result.heading = number(p.ang);
      // Report displayed game length only if its lookup tables are available.
      const base = window.fpsls?.[p.sct], multiplier = window.fmlts?.[p.sct];
      if (finite(base) && finite(multiplier) && multiplier > 0 && finite(p.fam)) {
        result.size = result.score = Math.floor(150*(base+p.fam/multiplier-1)-50)/10;
      }
      const w = finite(window.mww) ? window.mww : c.width;
      const h = finite(window.mhh) ? window.mhh : c.height;
      if (!(w > 0 && h > 0 && r.width > 0 && r.height > 0 && finite(window.gsc) && window.gsc > 0
          && finite(window.view_xx) && finite(window.view_yy))) return result;
      const sx = window.gsc*r.width/w, sy = window.gsc*r.height/h;
      result.scale = [sx,sy];
      result.center = [r.left+r.width/2+(x-window.view_xx)*sx,
        r.top+r.height/2+(y-window.view_yy)*sy];
      const diagonal = Math.hypot(result.rect.width,result.rect.height);
      if (!(diagonal > 0)) {result.center = null; return result;}
      const sector = (dx,dy) => Math.floor((Math.atan2(dy,dx)+2*Math.PI)%(2*Math.PI)
        *sectors/(2*Math.PI)+0.5)%sectors;
      const enemies = window.slithers ?? window.snakes;
      if (Array.isArray(enemies)) {
        // 1 means no body sample within one viewport diagonal, not knowledge of the entire map.
        result.enemies.fill(1);
        for (const enemy of enemies) {
          if (!enemy || enemy === p || (p.id != null && enemy.id === p.id) || enemy.dead) continue;
          for (const part of [enemy,...(Array.isArray(enemy.pts) ? enemy.pts : [])]) {
            if (!part || !finite(part.xx) || !finite(part.yy)) continue;
            const dx = (part.xx+(number(part.fx)??0)-x)*sx;
            const dy = (part.yy+(number(part.fy)??0)-y)*sy;
            const i = sector(dx,dy);
            result.enemies[i] = Math.min(result.enemies[i], Math.hypot(dx,dy)/diagonal);
          }
        }
      }
      if (Array.isArray(window.foods)) {
        result.food.fill(0);
        const count = Number.isInteger(window.foods_c) ? window.foods_c : window.foods.length;
        let visible = 0;
        for (let i=0;i<count;i++) {
          const f = window.foods[i];
          if (!f || f.eaten || !finite(f.xx) || !finite(f.yy)) continue;
          const dx = (f.xx-x)*sx, dy = (f.yy-y)*sy;
          if (Math.hypot(dx,dy) > diagonal) continue;
          result.food[sector(dx,dy)]++; visible++;
        }
        if (visible) result.food = result.food.map(n => n/visible);
      }
      // grd is both the circular map radius and its center coordinate, in game units.
      if (finite(window.grd) && window.grd > 0) {
        const ox = x-window.grd, oy = y-window.grd;
        for (let i=0;i<sectors;i++) {
          const angle = 2*Math.PI*i/sectors, dx = Math.cos(angle)/sx, dy = Math.sin(angle)/sy;
          const a = dx*dx+dy*dy, b = ox*dx+oy*dy;
          const discriminant = b*b-a*(ox*ox+oy*oy-window.grd*window.grd);
          if (discriminant >= 0) result.boundary[i] = Math.max(0,Math.min(1,
            (-b+Math.sqrt(discriminant))/a/diagonal));
        }
      }
      return result;
    }
  };
})();
