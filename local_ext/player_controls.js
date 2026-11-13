/* 网页统一控制层；借鉴 HGhub-MacOS-iOS-Version 的锁屏、长按与诊断设计。
 * 算法来源与许可见 docs/third-party/HGhub-Noncommercial.md。 */
(function () {
  'use strict';
  if (window.HGControls) return;
  var video = document.getElementById('video');
  var pane = document.getElementById('playerPane');
  var player = document.getElementById('player');
  if (!video || !pane || !player) return;
  var ctl = pane.querySelector('.ctl');
  var locked = false, dialog = null, returnFocus = null;
  var gesture = null, suppressClick = false, holdTimer;
  var recoveryTimer, generation = 0, attempts = 0;
  var records = [];
  function visible() { return !player.hidden && !pane.hidden; }
  function log(event, data) {
    // 只记录固定字段，不保存媒体 URL、错误正文、访问密钥或请求头。
    var row = { at: Date.now(), event: event, time: Math.round(video.currentTime || 0),
      ready: video.readyState, paused: video.paused };
    if (data) Object.keys(data).forEach(function (key) { row[key] = data[key]; });
    records.push(row);
    if (records.length > 300) records.shift();
  }
  function notify(text) { if (typeof window.toast === 'function') window.toast(text); }
  function button(text, id, parent, fn) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'btn ghost'; b.textContent = text;
    if (id) b.id = id;
    b.onclick = fn;
    (parent || ctl).appendChild(b);
    return b;
  }
  var style = document.createElement('style');
  style.textContent = [
    ':root{--hg-screen-top:max(24px,calc(env(safe-area-inset-top,0px) + 8px));--hg-screen-right:max(20px,calc(env(safe-area-inset-right,0px) + 8px));--hg-screen-bottom:max(20px,calc(env(safe-area-inset-bottom,0px) + 8px));--hg-screen-left:max(20px,calc(env(safe-area-inset-left,0px) + 8px))}',
    'body.hg-immersive{--hg-top:var(--hg-screen-top);--hg-right:var(--hg-screen-right);--hg-bottom:var(--hg-screen-bottom);--hg-left:var(--hg-screen-left)}',
    'body.hg-immersive.hg-landscape{--hg-top:var(--hg-screen-right);--hg-right:var(--hg-screen-bottom);--hg-bottom:var(--hg-screen-left);--hg-left:var(--hg-screen-top)}',
    '#playerPane{color-scheme:dark}',
    '#playerPane .ctl{display:flex;gap:8px;flex-wrap:wrap}',
    'body.hg-immersive #playerPane .ctl{bottom:var(--hg-bottom);left:var(--hg-left);right:var(--hg-right);max-height:46%;overscroll-behavior:contain}',
    '#playerPane .ctl button,.hg-choice button{color:#f5f5f7;-webkit-text-fill-color:#f5f5f7;background:#23232c;border:1px solid #666673;min-width:48px;min-height:48px;font-size:14px;padding:8px 12px}',
    'body.hg-immersive #player:has(#playerPane:not([hidden])) #btnClosePlayer{width:48px;height:48px;top:var(--hg-top);right:var(--hg-right)}body.hg-immersive #btnBackDetail{min-height:48px;top:var(--hg-top);left:var(--hg-left)}',
    'body.hg-immersive #playerPane .ctl button{min-height:48px}',
    '#playerPane .ctl button:focus-visible,.hg-choice button:focus-visible{outline:3px solid #ffda64;outline-offset:2px}',
    '#playerPane .ctl select[hidden]{display:none}',
    '.hg-progress{display:flex;align-items:center;gap:8px;width:100%;min-width:0}',
    '.hg-progress input{flex:1;min-width:0;min-height:44px;accent-color:#ffda64}',
    '.hg-progress output{font-size:12px;white-space:nowrap;font-variant-numeric:tabular-nums}',
    '#hgPlaybackStatus{width:100%;font-size:12px;color:#eee}',
    '.hg-choice{position:absolute;z-index:12;top:calc(var(--hg-top,24px) + 56px);right:var(--hg-right,20px);bottom:var(--hg-bottom,20px);left:var(--hg-left,20px);background:#17171ff5;border:1px solid #767680;border-radius:14px;padding:16px;overflow:auto;overscroll-behavior:contain}',
    '.hg-choice h3{margin:0 0 12px;font-size:18px}.hg-choice button{display:block;width:100%;margin:8px 0;text-align:left;border-radius:9px}',
    '.hg-choice button[aria-checked=true]{border-color:#ffda64;background:#45402c}',
    '#hgLockShield{position:absolute;inset:0;z-index:8;touch-action:none}',
    '#hgUnlock{position:absolute;right:var(--hg-right,20px);top:calc(var(--hg-top,24px) + 60px);z-index:9;min-height:48px;color:white;background:#23232cf0;border:1px solid #aaa;border-radius:12px;padding:10px 16px}',
    '#hgHoldHint{position:absolute;top:80px;left:50%;transform:translateX(-50%);z-index:6;background:#111c;color:white;padding:10px;border-radius:10px;pointer-events:none}',
    '#hgLockShield[hidden],#hgUnlock[hidden],#hgHoldHint[hidden]{display:none}',
    '#playerPane.hg-locked .ctl,#playerPane.hg-locked #btnBackDetail,body.hg-immersive.hg-locked #btnClosePlayer{visibility:hidden;pointer-events:none}',
    'body.hg-immersive #video{touch-action:none}',
    '#btnClosePlayer{color:#fff!important;display:flex;align-items:center;justify-content:center}#btnClosePlayer svg{pointer-events:none;width:24px;height:24px}',
    '@media(max-height:480px){body.hg-immersive #playerPane .ctl{max-height:43%;padding:6px;gap:8px}#playerPane .ctl button{padding:6px 10px}}'
  ].join('');
  document.head.appendChild(style);
  // 原生 controls 与网页关闭区域竞争点击；只让显式“系统全屏”进入系统播放器。
  video.controls = false;
  document.getElementById('btnClosePlayer').setAttribute('aria-label', '关闭播放器');
  function closeMenu() {
    if (!dialog) return;
    dialog.remove(); dialog = null;
    if (returnFocus && returnFocus.isConnected) returnFocus.focus();
    returnFocus = null;
  }
  function choose(title, choices, current, onSelect, trigger) {
    closeMenu(); returnFocus = trigger || document.activeElement;
    dialog = document.createElement('section'); dialog.className = 'hg-choice';
    dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-label', title);
    var heading = document.createElement('h3'); heading.textContent = title; dialog.appendChild(heading);
    var group = document.createElement('div'); group.setAttribute('role', 'radiogroup'); group.setAttribute('aria-label', title);
    dialog.appendChild(group);
    choices.forEach(function (choice) {
      var b = button(choice.label, '', group, function () { onSelect(choice.value); closeMenu(); });
      b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(choice.value === current));
      b.disabled = !!choice.disabled;
    });
    var done = button('返回播放', '', dialog, closeMenu);
    pane.appendChild(dialog);
    (dialog.querySelector('[aria-checked=true]:not(:disabled)') || done).focus();
  }
  window.HGControls = { choose: choose, log: log, snapshot: function () { return records.slice(); } };
  ['speedSel', 'streamSel'].forEach(function (id) {
    var select = document.getElementById(id);
    select.hidden = true; select.tabIndex = -1;
    var label = id === 'speedSel' ? '倍速' : '线路';
    var b = button('', 'hg-' + id, null, function () {
      choose(label, Array.prototype.map.call(select.options, function (o) {
        return { value: o.value, label: o.textContent, disabled: o.disabled };
      }), select.value, function (value) {
        select.value = value; select.dispatchEvent(new Event('change')); sync();
      }, b);
    });
    function sync() { b.textContent = label + ' ' + (select.options[select.selectedIndex] || {}).textContent; }
    select.addEventListener('change', sync);
    new MutationObserver(sync).observe(select, { childList: true, subtree: true, attributes: true });
    sync();
  });
  var progress = document.createElement('div'); progress.className = 'hg-progress';
  var play = button('播放', 'hgPlayPause', progress, function () {
    if (video.paused) video.play().catch(function () { notify('请再次点播放'); }); else video.pause();
  });
  var seek = document.createElement('input'); seek.type = 'range'; seek.min = 0; seek.max = 1000; seek.value = 0;
  seek.setAttribute('aria-label', '播放进度'); progress.appendChild(seek);
  var clock = document.createElement('output'); progress.appendChild(clock);
  ctl.insertBefore(progress, ctl.firstChild);
  function format(t) { t = isFinite(t) ? Math.max(0, Math.floor(t)) : 0; return Math.floor(t / 60) + ':' + ('0' + t % 60).slice(-2); }
  var scrubbing = false;
  seek.addEventListener('input', function () { scrubbing = true; clock.textContent = format(video.duration * seek.value / 1000) + ' / ' + format(video.duration); });
  seek.addEventListener('change', function () {
    if (isFinite(video.duration) && video.duration > 0) video.currentTime = video.duration * seek.value / 1000;
    scrubbing = false; update();
  });
  var mute = button('', 'hgMute', null, function () { video.muted = !video.muted; update(); });
  button('系统全屏', 'hgSystemFullscreen', null, function () {
    try {
      if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
      else if (pane.requestFullscreen) pane.requestFullscreen().catch(function () { notify('当前环境不支持系统全屏'); });
      else notify('当前环境不支持系统全屏，请使用切换横屏');
    } catch (e) { notify('暂时无法进入系统全屏，请先播放'); }
  });
  var shield = document.createElement('div'); shield.id = 'hgLockShield'; shield.hidden = true;
  pane.appendChild(shield);
  var unlock = button('解锁控件', 'hgUnlock', pane, function () { setLocked(false); }); unlock.hidden = true;
  button('锁定控件', 'hgLock', null, function () { setLocked(true); });
  function setLocked(value) {
    endHold(); closeMenu(); locked = value;
    shield.hidden = unlock.hidden = !value;
    pane.classList.toggle('hg-locked', value); document.body.classList.toggle('hg-locked', value);
    if (value) unlock.focus(); else document.getElementById('hgLock').focus();
  }
  shield.addEventListener('click', function (event) { event.stopPropagation(); });
  function update() {
    play.textContent = video.paused ? '播放' : '暂停'; play.setAttribute('aria-label', play.textContent);
    mute.textContent = video.muted ? '开启声音' : '静音'; mute.setAttribute('aria-pressed', String(video.muted));
    seek.disabled = !isFinite(video.duration) || video.duration <= 0;
    if (!scrubbing) { seek.value = seek.disabled ? 0 : video.currentTime / video.duration * 1000; clock.textContent = format(video.currentTime) + ' / ' + format(video.duration); }
  }
  ['play', 'pause', 'timeupdate', 'durationchange', 'volumechange', 'loadedmetadata', 'emptied'].forEach(function (name) { video.addEventListener(name, update); });
  update();
  var hint = document.createElement('div'); hint.id = 'hgHoldHint'; hint.hidden = true; hint.textContent = '临时 2× · 松开恢复'; pane.appendChild(hint);
  function endHold() {
    clearTimeout(holdTimer);
    if (gesture && gesture.holding) { video.playbackRate = gesture.rate; suppressClick = true; }
    gesture = null; if (!hint.hidden) hint.hidden = true;
  }
  video.addEventListener('pointerdown', function (e) {
    if (locked || !visible() || e.button !== 0) return;
    if (gesture || !e.isPrimary) { endHold(); return; }
    gesture = { id: e.pointerId, x: e.clientX, y: e.clientY, rate: video.playbackRate, holding: false };
    if (video.setPointerCapture) video.setPointerCapture(e.pointerId);
    holdTimer = setTimeout(function () {
      if (!gesture || video.paused) return;
      gesture.holding = true; video.playbackRate = 2; hint.hidden = false;
    }, 380);
  });
  video.addEventListener('pointermove', function (e) { if (gesture && (Math.abs(e.clientX - gesture.x) > 12 || Math.abs(e.clientY - gesture.y) > 12)) endHold(); });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (name) { video.addEventListener(name, endHold); });
  video.addEventListener('contextmenu', function (e) { e.preventDefault(); });
  video.addEventListener('click', function (e) {
    if (suppressClick) { suppressClick = false; e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  window.addEventListener('blur', endHold);
  document.addEventListener('visibilitychange', function () { if (document.hidden) endHold(); });
  document.addEventListener('keydown', function (e) {
    if (!visible()) return;
    if (locked) {
      if (e.target === unlock && (e.key === 'Enter' || e.key === ' ')) return;
      e.preventDefault(); e.stopImmediatePropagation(); unlock.focus(); return;
    }
    if (!dialog) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeMenu(); }
    if (e.key === 'Tab') {
      var items = Array.prototype.slice.call(dialog.querySelectorAll('button:not(:disabled)'));
      var i = items.indexOf(document.activeElement);
      e.preventDefault(); items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
    }
  }, true);
  // 保留有界的媒体诊断；仅点击导出时才生成文件。
  ['loadstart', 'loadedmetadata', 'playing', 'pause', 'waiting', 'stalled', 'seeking', 'seeked', 'ended', 'error'].forEach(function (name) {
    video.addEventListener(name, function () { log(name, { code: video.error ? video.error.code : 0 }); });
  });
  button('导出诊断', 'hgExportDiagnostics', null, function () {
    var blob = new Blob([JSON.stringify({ version: 1, events: records }, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = 'hghub-playback.json'; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 10000);
  });
  var status = document.createElement('div'); status.id = 'hgPlaybackStatus'; status.setAttribute('role', 'status'); status.hidden = true; ctl.appendChild(status);
  function cancelRecovery() { clearTimeout(recoveryTimer); recoveryTimer = null; generation++; endHold(); }
  function failed() { status.textContent = '播放恢复失败，请重新选集或切换线路'; status.hidden = false; notify(status.textContent); }
  window.hgRecoverHls = function (instance, data, tried) {
    if (!data || !data.fatal) return false;
    if (attempts >= 4) { if (tried) failed(); return false; }
    var types = window.Hls && Hls.ErrorTypes;
    var network = types && data.type === types.NETWORK_ERROR;
    var media = types && data.type === types.MEDIA_ERROR;
    if (!network && !media) { if (tried) failed(); return false; }
    if (recoveryTimer) return true;
    attempts++;
    var token = generation;
    status.textContent = '正在恢复播放（' + attempts + '/4）'; status.hidden = false;
    log('recover', { attempt: attempts, kind: network ? 'network' : 'media' });
    recoveryTimer = setTimeout(function () {
      recoveryTimer = null;
      if (token !== generation || !visible() || window.hls !== instance) return;
      try { if (network) instance.startLoad(video.currentTime || -1); else instance.recoverMediaError(); }
      catch (e) { failed(); }
    }, 250 * attempts);
    return true;
  };
  if (typeof window.setPlayerSource === 'function') {
    var originalSource = window.setPlayerSource;
    window.setPlayerSource = function (src, tried) {
      cancelRecovery(); if (!tried) attempts = 0;
      status.hidden = true;
      return originalSource.apply(this, arguments);
    };
  }
  video.addEventListener('playing', function () { status.hidden = true; });
  new MutationObserver(function () {
    if (!visible()) { cancelRecovery(); closeMenu(); if (locked) setLocked(false); }
  }).observe(player, { attributes: true, subtree: true, attributeFilter: ['hidden'] });
})();
