/* 沉浸首页与紧凑播放控件；网页、Android、iOS 和桌面浏览器共用。 */
(function () {
  'use strict';
  if (window.HGViewing) return;
  var body = document.body, feed = document.getElementById('feed');
  var pane = document.getElementById('playerPane'), video = document.getElementById('video');
  if (!pane || !feed) return;
  var style = document.createElement('style');
  style.textContent = `
    body[data-view=home]{overflow:hidden}
    body[data-view=home] header{display:none}
    body[data-view=home] main{padding:0;max-width:none;margin:0}
    body[data-view=home] #view-home{height:100vh;height:100dvh}
    body[data-view=home] #feed{background:#000}
    body[data-view=home] .slide video.bgvid,body[data-view=home] .slide img.cover{object-fit:contain}
    body[data-view=home] .bottomnav{background:#0e0e11ed}
    body[data-view=home] .slide .info{bottom:calc(var(--hg-nav-height,64px) + 4px);max-height:45%;overflow:auto}
    body[data-view=home] .slide .acts{bottom:calc(var(--hg-nav-height,64px) + 24px)!important;max-height:65%;overflow:auto;gap:12px}
    body[data-view=home] .slide .prog{bottom:var(--hg-nav-height,64px)}
    body[data-view=home] .slide .info h3{overflow-wrap:anywhere}
    body[data-view=home] .slide .info p.syn.expanded{max-height:22vh;overflow:auto}
    body[data-view=home] .slide{opacity:1;transform:none;transition:none;will-change:auto}
    body[data-view=home].hg-feed-clean .bottomnav,
    body[data-view=home].hg-feed-clean .slide :is(.info,.acts,.mutebtn,.prog,.shade){visibility:hidden;pointer-events:none}
    #hgFeedHint{position:fixed;left:50%;bottom:max(24px,env(safe-area-inset-bottom));transform:translateX(-50%);z-index:5;color:#fff;background:#0009;border-radius:20px;padding:8px 14px;font-size:12px;pointer-events:none;white-space:nowrap}
    body:not([data-view=home]) #hgFeedHint,body:not(.hg-feed-clean) #hgFeedHint,body.modal-open #hgFeedHint{display:none}
    #playerPane .ctl{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:2px;padding:6px;background:#141419d9;border:1px solid #ffffff24;border-radius:12px}
    body.hg-immersive #playerPane .ctl{max-height:none;overflow:visible;max-width:640px;margin-inline:auto}
    #playerPane .hg-progress,#playerPane #hgPlaybackStatus{grid-column:1/-1}
    #playerPane .ctl button{min-width:0;min-height:44px;padding:6px 8px;border-color:transparent;background:transparent;font-size:13px;overflow-wrap:anywhere}
    body.hg-immersive #playerPane .ctl>button{min-height:44px;padding:4px;font-size:12px}
    #hgMute svg,#hgRotate svg{width:20px!important;height:20px!important;vertical-align:middle}
    #playerPane .hg-progress{gap:4px}
    #playerPane .hg-progress output{font-size:11px}
    #hgMore{position:relative;min-width:0}
    #hgMore summary{min-height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:13px;list-style:none;border-radius:8px}
    #hgMore summary::-webkit-details-marker{display:none}
    #hgMore summary:focus-visible,#hgPip:focus-visible{outline:3px solid #ffda64;outline-offset:2px}
    #hgMorePanel{position:absolute;bottom:calc(100% + 64px);right:0;width:min(360px,calc(100vw - 48px));max-height:calc(100dvh - 230px);overflow:auto;overscroll-behavior:contain;padding:8px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;background:#1a1a1ff5;border:1px solid #666673;border-radius:14px;box-shadow:0 8px 32px #0008}
    #hgMore:not([open]) #hgMorePanel{display:none}
    #hgMorePanel button{white-space:normal;text-align:left}
    #hgPip{position:absolute;top:var(--hg-top,24px);left:calc(var(--hg-left,20px) + 80px);z-index:4;min-height:48px;padding:8px 12px;border-radius:22px;background:#17171fcc;border:1px solid #ffffff50;color:white;font-size:13px}
    body.hg-ui-hidden #hgPip,body.hg-locked #hgPip{visibility:hidden;pointer-events:none}
    #playerPane .ctl button:active,#hgMore summary:active,#hgPip:active{background:#ffffff26}
    @media(hover:hover) and (pointer:fine){#playerPane .ctl button:hover,#hgMore summary:hover,#hgPip:hover{background:#ffffff18}}
    @media(hover:hover) and (pointer:fine){body[data-view=home].hg-feed-clean .bottomnav{visibility:visible;pointer-events:auto}body[data-view=home] #hgFeedHint{display:none}}
    @media(min-width:900px){body[data-view=home] #feed{max-width:560px;width:100%;margin-inline:auto}body[data-view=home] .slide video.bgvid,body[data-view=home] .slide img.cover{object-fit:contain}body[data-view=home] .bottomnav{left:50%;right:auto;transform:translateX(-50%);width:560px}}
    body.hg-landscape #hgMorePanel{max-height:calc(var(--hg-stage-height) - 230px)}
    @media(max-height:480px){#hgMorePanel{max-height:calc(100dvh - 200px);bottom:calc(100% + 48px)}#playerPane .ctl{padding:4px}.hg-progress input{min-height:28px}}
  `;
  document.head.appendChild(style);
  var back = document.getElementById('btnBackDetail');
  if (back) { back.textContent = '‹ 选集'; back.setAttribute('aria-label','返回详情与选集'); }
  var ctl = pane.querySelector('.ctl');
  var more = document.createElement('details'); more.id = 'hgMore';
  var summary = document.createElement('summary'); summary.textContent = '更多 ···'; more.appendChild(summary);
  var panel = document.createElement('div'); panel.id = 'hgMorePanel'; more.appendChild(panel);
  function compact() {
    Array.from(ctl.children).forEach(function (el) {
      if (el === more || el.matches('.hg-progress,#hg-speedSel,#btnNextEp,#hgMute,#hgRotate,#hgPlaybackStatus,select')) return;
      panel.appendChild(el);
    });
  }
  compact(); ctl.appendChild(more);
  ['btnNextEp','hg-speedSel','hgMute','hgRotate'].forEach(function(id){var b=document.getElementById(id);if(b)ctl.insertBefore(b,more);});
  ['hgMute','hgRotate'].forEach(function(id){var b=document.getElementById(id);if(b)b.dataset.hgIcon='true';});
  // 复用原有状态同步，图标更新后仍保留完整的辅助标签。
  video.dispatchEvent(new Event('volumechange'));
  var rotateButton=document.getElementById('hgRotate');
  if(rotateButton)rotateButton.dispatchEvent(new Event('hg-icon-ready'));
  new MutationObserver(compact).observe(ctl, {childList:true});
  more.addEventListener('toggle', function () { if (more.open) body.classList.remove('hg-ui-hidden'); });
  document.addEventListener('pointerdown', function (e) { if (!more.contains(e.target)) more.open = false; });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && more.open) { more.open = false; summary.focus(); } });
  new MutationObserver(function () { if (pane.hidden) more.open = false; }).observe(pane, {attributes:true,attributeFilter:['hidden']});

  var pip = document.createElement('button'); pip.id = 'hgPip'; pip.type = 'button'; pip.textContent = '小窗';
  pip.setAttribute('aria-label','画中画悬浮播放'); pane.appendChild(pip);
  pip.onclick = async function () {
    try {
      // iOS 的系统画中画与 Chromium/Windows 分别使用各自的能力检测。
      if (video.webkitSupportsPresentationMode && video.webkitSupportsPresentationMode('picture-in-picture')) {
        video.webkitSetPresentationMode(video.webkitPresentationMode === 'picture-in-picture' ? 'inline' : 'picture-in-picture');
      } else if (document.pictureInPictureElement) await document.exitPictureInPicture();
      else if (document.pictureInPictureEnabled && video.requestPictureInPicture) await video.requestPictureInPicture();
      else if (typeof window.toast === 'function') window.toast('当前设备不支持系统小窗，可尝试“更多 → 系统全屏”');
    } catch (_) { if (typeof window.toast === 'function') window.toast('暂时无法开启小窗，请先播放，或检查系统画中画权限'); }
  };

  var nav = document.getElementById('bottomNav');
  if (nav && !nav.querySelector('[data-view=search]')) {
    var search = document.createElement('button'); search.type = 'button'; search.dataset.view = 'search';
    search.innerHTML = '<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg></span>搜索';
    nav.insertBefore(search,nav.lastElementChild);
    // 原页面已有 data-view 的文档级导航委托。
    search.addEventListener('click',function () { setTimeout(function () { var q=document.getElementById('q'); if(q)q.focus(); },0); });
  }
  var hint = document.createElement('div'); hint.id = 'hgFeedHint'; hint.textContent = '轻点显示操作 · 上下滑切换'; body.appendChild(hint);
  setTimeout(function () { hint.hidden = true; },5000);
  var timer, feedInteracting = false;
  function clean(value) { body.classList.toggle('hg-feed-clean',value); clearTimeout(timer); }
  function scheduleHide() { clearTimeout(timer); timer = setTimeout(function () {
    var active=feed.querySelector('.slide.active video.bgvid');
    var focused=document.activeElement;
    if (body.classList.contains('modal-open') || document.querySelector('.hg-feed-choice') ||
        feedInteracting || active && (active.paused || active.seeking) ||
        focused && focused.matches(':focus-visible') && (feed.contains(focused) || nav && nav.contains(focused))) {
      scheduleHide(); return;
    }
    clean(true);
  },4000); }
  function reveal() { clean(false); scheduleHide(); }
  // 保留原双击点赞计时；单击仅显隐操作，暂停改为明确按钮，避免唤出导航时误暂停。
  var originalPause = window.toggleSlidePause;
  if (originalPause) window.toggleSlidePause = function () { if (body.classList.contains('hg-feed-clean')) reveal(); else clean(true); };
  function feedButtons() {
    feed.querySelectorAll('.slide .acts').forEach(function (acts) {
      if (acts.querySelector('.hg-feed-pause')) return;
      var b = document.createElement('button'); b.className = 'hg-feed-pause'; b.type = 'button';
      function syncPause() {
        var v=acts.closest('.slide').querySelector('video.bgvid'),paused=!v || v.paused;
        b.setAttribute('aria-label',paused?'播放':'暂停');
        b.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'+(paused?'<path d="m9 5 11 7-11 7z"/>':'<path d="M8 5v14M16 5v14"/>')+'</svg>';
      }
      var media=acts.closest('.slide').querySelector('video.bgvid');
      if(media){media.addEventListener('play',syncPause);media.addEventListener('pause',syncPause);}
      syncPause();
      b.onclick = function (e) { e.stopPropagation(); if(originalPause) originalPause(+acts.closest('.slide').dataset.id); reveal(); };
      acts.insertBefore(b,acts.firstChild);
    });
  }
  feedButtons(); new MutationObserver(feedButtons).observe(feed,{subtree:true,childList:true});
  feed.addEventListener('pointerdown',function(){feedInteracting=true;if(!body.classList.contains('hg-feed-clean'))scheduleHide();});
  function endFeedInteraction(){if(!feedInteracting)return;feedInteracting=false;if(!body.classList.contains('hg-feed-clean'))scheduleHide();}
  window.addEventListener('pointerup',endFeedInteraction);
  window.addEventListener('pointercancel',endFeedInteraction);
  window.addEventListener('blur',endFeedInteraction);
  feed.addEventListener('pointermove',function(e){if(e.pointerType==='mouse')reveal();});
  feed.addEventListener('pause',function(e){if(e.target.matches('video.bgvid') && e.target.closest('.slide.active'))reveal();},true);
  ['play','seeking','seeked'].forEach(function(name){feed.addEventListener(name,function(e){
    if(e.target.matches('video.bgvid') && !body.classList.contains('hg-feed-clean'))reveal();
  },true);});
  feed.addEventListener('scroll',function () { clean(true); },{passive:true});
  feed.addEventListener('click',function (e) { if(!e.target.closest('.slide,button,a'))reveal(); });
  document.addEventListener('keydown',function (e) {
    if(body.dataset.view !== 'home' || body.classList.contains('modal-open')) return;
    if(e.key === 'Tab') reveal();
    if(e.target.matches('input,textarea,button,select,summary')) return;
    if(e.key === ' '){e.preventDefault();var s=feed.querySelector('.slide.active');if(s && originalPause)originalPause(+s.dataset.id);reveal();}
    if(e.key === 'ArrowDown' || e.key === 'ArrowUp'){e.preventDefault();feed.scrollBy({top:(e.key === 'ArrowDown'?1:-1)*feed.clientHeight,behavior:'instant'});}
    if(e.key === 'Escape')clean(true);
  });
  if(nav)nav.addEventListener('focusin',reveal);
  new MutationObserver(function () { clean(true); }).observe(body,{attributes:true,attributeFilter:['data-view']});
  clean(true);
  window.HGViewing = {reveal:reveal,clean:clean};
})();
