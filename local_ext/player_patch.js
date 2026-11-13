/* 复用上游播放器、系统全屏控件、hg_progress 和观看历史，只增强布局与续播。 */
(function () {
  'use strict';
  if (window.__hgPlayerPatch) return;
  window.__hgPlayerPatch = true;
  var video = document.getElementById('video');
  var pane = document.getElementById('playerPane');
  var player = document.getElementById('player');
  if (!video || !pane || !player) return;

  var style = document.createElement('style');
  style.textContent = [
    ':root{--page-shift:0px}',
    'body.hg-immersive .bottomnav{display:none}',
    'body.hg-immersive #player:has(#playerPane:not([hidden])){padding:0;height:100vh;height:100dvh;overflow:hidden;background:#000}',
    'body.hg-immersive #player:has(#playerPane:not([hidden])) .box{position:absolute;left:50%;top:50%;width:100%;height:100%;max-width:none;transform:translate(-50%,-50%)}',
    'body.hg-immersive.hg-landscape #player:has(#playerPane:not([hidden])) .box{width:var(--hg-stage-width);height:var(--hg-stage-height);transform:translate(-50%,-50%) rotate(90deg)}',
    'body.hg-immersive #playerPane{display:block;position:relative;width:100%;height:100%}',
    'body.hg-immersive #playerPane #video{display:block;width:100%;height:100%;max-height:none;object-fit:contain;border-radius:0}',
    'body.hg-immersive #btnBackDetail{position:absolute;top:max(12px,env(safe-area-inset-top));left:max(12px,env(safe-area-inset-left));z-index:3;margin:0;padding:10px;min-height:44px;background:#0009;border-radius:10px}',
    'body.hg-immersive #player .close{position:absolute;top:max(12px,env(safe-area-inset-top));right:max(12px,env(safe-area-inset-right));width:44px;height:44px;z-index:4}',
    // 给视频已有的原生进度条和全屏按钮留出底部操作空间。
    'body.hg-immersive #playerPane .ctl{position:absolute;bottom:max(72px,calc(env(safe-area-inset-bottom) + 60px));left:max(12px,env(safe-area-inset-left));right:max(12px,env(safe-area-inset-right));z-index:3;margin:0;padding:10px;background:#000a;border-radius:12px;max-height:40%;overflow-y:auto}',
    'body.hg-immersive #playerPane .ctl button,body.hg-immersive #playerPane .ctl select{min-height:44px}',
    'body.hg-immersive.hg-ui-hidden #playerPane .ctl,body.hg-immersive.hg-ui-hidden #btnBackDetail,body.hg-immersive.hg-ui-hidden #btnClosePlayer{opacity:0;visibility:hidden;pointer-events:none}',
    '.hg-history-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}',
    '.hg-history-actions button{min-height:44px}'
  ].join('');
  document.head.appendChild(style);

  var immersive = false;
  var hideTimer;
  var rotate = document.createElement('button');
  rotate.id = 'hgRotate';
  rotate.type = 'button';
  rotate.className = 'btn ghost';
  rotate.textContent = '切换横屏';
  rotate.setAttribute('aria-pressed', 'false');
  pane.querySelector('.ctl').appendChild(rotate);
  function stageSize() {
    player.style.setProperty('--hg-stage-width', window.innerHeight + 'px');
    player.style.setProperty('--hg-stage-height', window.innerWidth + 'px');
  }
  function reveal() {
    document.body.classList.remove('hg-ui-hidden');
    clearTimeout(hideTimer);
    if (immersive && !video.paused) hideTimer = setTimeout(function () {
      var focused = document.activeElement;
      if (pane.contains(focused) && focused !== video &&
          (focused.tagName === 'SELECT' || focused.matches(':focus-visible'))) return;
      document.body.classList.add('hg-ui-hidden');
    }, 3000);
  }
  function syncPlayer() {
    var visible = !player.hidden && !pane.hidden;
    if (visible === immersive) return;
    immersive = visible;
    document.body.classList.toggle('hg-immersive', visible);
    if (!visible) {
      document.body.classList.remove('hg-landscape', 'hg-ui-hidden');
      rotate.textContent = '切换横屏';
      rotate.setAttribute('aria-pressed', 'false');
      clearTimeout(hideTimer);
    } else reveal();
    // iOS 仅在播放页隐藏状态栏，保持原有系统视频全屏入口。
    var bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.hgPlayer;
    if (bridge) bridge.postMessage(visible);
  }
  rotate.onclick = function () {
    var landscape = document.body.classList.toggle('hg-landscape');
    stageSize();
    rotate.textContent = landscape ? '切回竖屏' : '切换横屏';
    rotate.setAttribute('aria-pressed', String(landscape));
    reveal();
  };
  pane.addEventListener('pointerdown', reveal);
  pane.addEventListener('focusin', reveal);
  pane.addEventListener('focusout', reveal);
  video.addEventListener('play', reveal);
  video.addEventListener('pause', reveal);
  window.addEventListener('resize', stageSize); // 只调整尺寸，不根据设备旋转切换方向。
  new MutationObserver(syncPlayer).observe(player, { attributes: true, subtree: true, attributeFilter: ['hidden'] });
  stageSize();
  syncPlayer();

  // 布局测试或不兼容的上游页面可以只使用布局增强，不创建另一套播放器。
  if (typeof window.playVideo !== 'function' || typeof window.store === 'undefined') return;
  window.__hgResumeManaged = true;
  var originalPlay = window.playVideo;
  var originalSource = window.setPlayerSource;
  var originalRenderMe = window.renderMe;
  var originalSave = window.saveProgress;
  var originalOpenDetail = window.openDetail;
  var originalShowDetail = window.showDetailPane;
  var originalClose = window.closePlayer;
  var active = null;
  var cancelRestore = function () {};

  function writeProgress(id, ep, t, duration, completed) {
    var records = store.get('hg_progress', {});
    records[id] = { ep: ep, t: Math.floor(t), dur: Math.floor(duration || 0), at: Date.now(), completed: !!completed };
    store.set('hg_progress', records);
  }
  function save() {
    if (!active || !active.ready || active.finished || active.restoring ||
        active.id !== curVideo || active.ep !== curEp || !isFinite(video.duration) || video.duration <= 0) return;
    writeProgress(active.id, active.ep, video.currentTime, video.duration, false);
  }
  // 原有 timeupdate 调用仍保留；补存开头十秒、切后台及退出页面的进度。
  video.removeEventListener('pause', originalSave);
  window.saveProgress = save;
  video.addEventListener('pause', save);
  window.addEventListener('pagehide', save);
  document.addEventListener('visibilitychange', function () { if (document.hidden) save(); });

  function leaveVideo() {
    save();
    cancelRestore();
    active = null; // 后续旧媒体的 pause/load 事件不能覆盖已保存位置。
  }
  window.openDetail = function () {
    leaveVideo();
    return originalOpenDetail.apply(this, arguments);
  };
  window.showDetailPane = function () {
    leaveVideo();
    return originalShowDetail.apply(this, arguments);
  };
  window.closePlayer = function () {
    leaveVideo(); // pause 事件可能异步到达，必须在上游清空 src 之前保存。
    return originalClose.apply(this, arguments);
  };
  ['btnClosePlayer', 'btnBackFeed'].forEach(function (id) {
    var button = document.getElementById(id);
    if (button && button.onclick === originalClose) button.onclick = window.closePlayer;
  });

  window.playVideo = function (id, ep) {
    save();
    cancelRestore();
    active = { id: id, ep: ep || 1, ready: false, finished: false, restoring: false };
    return originalPlay.apply(this, arguments);
  };
  window.setPlayerSource = function () {
    save();
    cancelRestore();
    if (!active || active.id !== curVideo || active.ep !== curEp) {
      active = { id: curVideo, ep: curEp, finished: false };
    }
    var session = active;
    session.ready = false;
    session.restoring = true;
    var progress = getProgress(curVideo);
    var target = progress && progress.ep === curEp && !progress.completed ? (+progress.t || 0) : 0;
    function restore() {
      if (session !== active || !isFinite(video.duration) || video.duration <= 0 || video.readyState < 1) return;
      session.ready = true;
      var time = Math.max(0, Math.min(target, video.duration - 0.1));
      try {
        if (time > 0 && Math.abs(video.currentTime - time) > 0.5) video.currentTime = time;
        if (!video.seeking && Math.abs(video.currentTime - time) <= 0.5) {
          session.restoring = false;
          cancelRestore();
        }
      } catch (e) { /* 尚不能 seek，等 loadeddata/canplay/seeked 再试。 */ }
    }
    var events = ['loadedmetadata', 'loadeddata', 'canplay', 'seeked'];
    events.forEach(function (name) { video.addEventListener(name, restore); });
    cancelRestore = function () {
      events.forEach(function (name) { video.removeEventListener(name, restore); });
      cancelRestore = function () {};
    };
    return originalSource.apply(this, arguments);
  };
  // 先记录完成/下一集起点，再让上游原有 ended 处理器自动下一集。
  video.addEventListener('ended', function () {
    if (!active || !active.ready || active.id !== curVideo || active.ep !== curEp) return;
    active.finished = true;
    var total = curDetail && +(curDetail.episode_count || curDetail.total_episodes);
    var finalEpisode = !!total && curEp >= total;
    writeProgress(curVideo, finalEpisode ? curEp : curEp + 1,
      finalEpisode ? video.duration : 0, finalEpisode ? video.duration : 0, finalEpisode);
  }, true);

  window.renderMe = function () {
    var result = originalRenderMe.apply(this, arguments);
    var headings = document.querySelectorAll('#meBox .mebox > h3');
    Array.prototype.forEach.call(headings, function (heading) {
      if (heading.textContent.indexOf('观看历史') !== 0) return;
      Array.prototype.forEach.call(heading.parentNode.querySelectorAll('.rankrow[data-id]'), function (row) {
        var id = +row.getAttribute('data-id');
        var progress = getProgress(id);
        var content = row.querySelector('div');
        var label = content && content.querySelector('p');
        if (label && progress) label.textContent = progress.completed ? '已看完' :
          ('第 ' + progress.ep + ' 集 · 播放到 ' + fmtDur(progress.t));
        async function resume() {
          await openDetail(id);
          if (curVideo !== id || !curDetail || +curDetail.id !== id) return;
          var latest = getProgress(id);
          if (!latest || !latest.completed) playVideo(id, latest ? latest.ep : curEp || 1);
        }
        row.onclick = resume;
        var actions = document.createElement('div');
        actions.className = 'hg-history-actions';
        var details = document.createElement('button');
        details.className = 'btn ghost';
        details.textContent = '查看详情';
        details.onclick = function (event) { event.stopPropagation(); openDetail(id); };
        actions.appendChild(details);
        if (content) content.appendChild(actions);
      });
    });
    return result;
  };
})();
