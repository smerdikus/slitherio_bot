(() => {
  if (window.top && window.top !== window) return;
  const cfg = window.__slitherBridgeConfig;
  const boostCode = cfg.boost_code || "ShiftLeft";
  const physicalBoost = new Set();
  const boostCodes = boostCode === "Space" ? ["Space", "ArrowUp"] : ["Space", boostCode];
  const state = {generation: cfg.generation, mode: cfg.mode, focused: true, shutdown: false};
  const shortcuts = Object.fromEntries(Object.entries(cfg.keys).map(([command, code]) => [code, command]));
  let ledger = null;
  function emit(kind, payload = {}, origin = 'human_candidate') {
    // Binding promises are intentionally not awaited in DOM event handlers.
    window.__slitherInput({kind, payload, origin, generation: state.generation,
      page_ms: performance.now()}).catch(() => {});
  }
  function identify(kind, payload) {
    if (!ledger || performance.now() - ledger.at > 500) return 'human_candidate';
    const match = kind === ledger.kind && (kind === 'pointer'
      ? Math.abs(payload.x - ledger.x) <= 1 && Math.abs(payload.y - ledger.y) <= 1
      : payload.code === boostCode && payload.down === ledger.down);
    if (match) {
      payload.command_id = ledger.id;
      // Coincident physical input cannot be distinguished perfectly. Keep this ambiguity explicit.
      ledger = null;
      return 'automation_candidate';
    }
    return 'human_candidate';
  }
  window.addEventListener('keydown', event => {
    const command = shortcuts[event.code];
    if (!command) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (event.repeat) return;
    if (command === 'toggle_mode') {
      state.mode = state.mode === 'AI' ? 'HUMAN' : 'AI';
      state.generation++;
    } else if (command === 'restart' || command === 'shutdown') {
      state.generation++;
      if (command === 'shutdown') state.shutdown = true;
    }
    ledger = null;
    emit('command', {command, mode: state.mode}, 'control');
  }, true);
  window.addEventListener('keyup', event => {
    if (shortcuts[event.code]) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  window.addEventListener('pointermove', event => {
    const payload = {x: event.clientX, y: event.clientY, buttons: event.buttons,
      trusted: event.isTrusted};
    emit('pointer', payload, identify('pointer', payload));
  }, true);
  for (const name of ['keydown', 'keyup']) window.addEventListener(name, event => {
    if (!boostCodes.includes(event.code) || event.repeat) return;
    const payload = {code: event.code, down: name === 'keydown', trusted: event.isTrusted};
    const origin = identify('boost', payload);
    if (origin === 'human_candidate') {
      if (payload.down) physicalBoost.add(event.code); else physicalBoost.delete(event.code);
    }
    // Slither uses Space for both owners. Release the automation keyboard state while
    // preventing its keyup from cancelling a human boost held through takeover.
    if (origin === 'automation_candidate' && !payload.down && boostCode === 'Space'
        && physicalBoost.size > 0) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
    emit('boost', payload, origin);
  }, true);
  if (boostCode === 'Space') {
    for (const name of ['pointerdown', 'pointerup']) window.addEventListener(name, event => {
      if (event.button !== 0) return;
      const down = name === 'pointerdown';
      if (down) physicalBoost.add('MouseLeft'); else physicalBoost.delete('MouseLeft');
      emit('boost', {code:'MouseLeft', down, trusted:event.isTrusted});
    }, true);
  }
  function lostFocus() {
    if (!state.focused) return;
    physicalBoost.clear();
    state.focused = false;
    state.mode = 'HUMAN';
    state.generation++;
    ledger = null;
    emit('focus', {focused: false}, 'control');
  }
  window.addEventListener('blur', lostFocus, true);
  document.addEventListener('visibilitychange', () => { if (document.hidden) lostFocus(); });
  window.addEventListener('focus', () => {
    state.focused = true;
    emit('focus', {focused: true}, 'control');
  }, true);
  window.__slitherBridge = {
    state,
    claim(command) {
      if (!command.cleanup && (command.generation !== state.generation || state.mode !== 'AI'
          || !state.focused || state.shutdown)) return false;
      ledger = {...command, at: performance.now()};
      emit('automation_command', command, 'automation');
      return true;
    },
    finish(id) { if (ledger?.id === id) ledger = null; },
  };
})();
