"""沉浸观看的真实 Chromium 离线回归，不依赖上游网络。"""
from test_player_layout import BrowserFixture, ROOT
from viewing_ui_fixture import build


class ViewingUITests(BrowserFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.evaluate("window.pauseCalls=0;window.toggleSlidePause=()=>pauseCalls++")
        cls.evaluate((ROOT / 'local_ext/viewing_ui.js').read_text(encoding='utf-8'))

    def test_compact_toolbar_and_long_menu_at_small_and_desktop_sizes(self):
        for width, height in [(320,568),(667,375),(768,1024),(1440,900)]:
            self.ws.call('Emulation.setDeviceMetricsOverride', dict(width=width,height=height,deviceScaleFactor=1,mobile=False))
            result = self.evaluate("""(async()=>{
              document.body.classList.remove('hg-ui-hidden','hg-landscape');
              const more=document.querySelector('#hgMore');more.open=true;
              document.querySelector('#hg-streamSel').textContent='线路 超高清 HEVC 备用线路（自动选择）';
              await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
              const r=more.querySelector('div').getBoundingClientRect(),c=document.querySelector('.ctl').getBoundingClientRect();
              return {x:r.x,right:r.right,y:r.y,bottom:r.bottom,height:c.height,
                count:document.querySelectorAll('#playerPane [data-hg-enhance]').length};
            })()""")
            self.assertGreaterEqual(result['x'],0,result)
            self.assertLessEqual(result['right'],width,result)
            self.assertGreaterEqual(result['y'],0,result)
            self.assertLessEqual(result['bottom'],height,result)
            self.assertLessEqual(result['height'],130,result)
            self.assertEqual(result['count'],1,result)
        self.evaluate("document.querySelector('#hgMore').open=false")

    def test_home_is_full_height_and_revealing_does_not_resize_video(self):
        self.ws.call('Emulation.setDeviceMetricsOverride',dict(width=390,height=844,deviceScaleFactor=1,mobile=True))
        self.ws.call('Emulation.setTouchEmulationEnabled',{'enabled':True})
        self.addCleanup(lambda:self.ws.call('Emulation.setTouchEmulationEnabled',{'enabled':False}))
        result=self.evaluate("""(()=>{
          document.querySelector('#player').hidden=true;document.body.classList.remove('modal-open');
          document.body.dataset.view='home';HGViewing.clean(true);
          const h=document.querySelector('#view-home').getBoundingClientRect().height;
          const hidden=getComputedStyle(document.querySelector('#bottomNav')).visibility;
          toggleSlidePause(12);
          return {h,hidden,shown:getComputedStyle(document.querySelector('#bottomNav')).visibility,
            after:document.querySelector('#view-home').getBoundingClientRect().height,
            search:!!document.querySelector('#bottomNav [data-view=search]'),calls:pauseCalls};
        })()""")
        self.assertEqual(result,dict(h=844,after=844,hidden='hidden',shown='visible',search=True,calls=0))

    def test_real_update_banner_never_reserves_home_height(self):
        result=self.evaluate("""(()=>{
          const banner=document.querySelector('#newBanner');banner.textContent='有 5 部新更新，点击查看';banner.hidden=false;
          document.body.dataset.view='home';HGViewing.clean(true);
          const top=feed.getBoundingClientRect().top,height=feed.clientHeight,hidden=getComputedStyle(banner).visibility;
          HGViewing.reveal();
          const result={top,height,hidden,afterTop:feed.getBoundingClientRect().top,afterHeight:feed.clientHeight,shown:getComputedStyle(banner).visibility};
          banner.hidden=true;return result;
        })()""")
        self.assertEqual(result['top'],0,result)
        self.assertEqual(result['afterTop'],0,result)
        self.assertEqual(result['height'],result['afterHeight'],result)
        self.assertEqual(result['hidden'],'hidden',result)
        self.assertEqual(result['shown'],'visible',result)

    def test_pip_uses_system_api_and_reports_failure(self):
        result=self.evaluate("""(async()=>{
          let calls=0;window.toast=t=>window.pipMessage=t;
          Object.defineProperty(document,'pictureInPictureEnabled',{configurable:true,value:true});
          const v=document.querySelector('#video');v.requestPictureInPicture=async()=>{calls++};
          await document.querySelector('#hgPip').onclick();
          v.requestPictureInPicture=async()=>{throw Error('not allowed')};
          await document.querySelector('#hgPip').onclick();
          return {calls,message:pipMessage};
        })()""")
        self.assertEqual(result['calls'],1)
        self.assertIn('权限',result['message'])

    def test_ios_pip_has_a_separate_capability_path(self):
        result=self.evaluate("""(async()=>{
          let mode;const v=document.querySelector('#video');
          v.webkitSupportsPresentationMode=m=>m==='picture-in-picture';
          v.webkitSetPresentationMode=m=>mode=m;
          await document.querySelector('#hgPip').onclick();
          delete v.webkitSupportsPresentationMode;delete v.webkitSetPresentationMode;
          return mode;
        })()""")
        self.assertEqual(result,'picture-in-picture')

    def test_common_icons_remain_in_toolbar_and_keep_labels(self):
        result=self.evaluate("""(()=>{
          return ['hgMute','hgRotate'].map(id=>{const b=document.getElementById(id);return {
            direct:b.parentElement.classList.contains('ctl'),icon:!!b.querySelector('svg'),label:b.getAttribute('aria-label')};});
        })()""")
        for button in result:
            self.assertTrue(button['direct'])
            self.assertTrue(button['icon'])
            self.assertTrue(button['label'])

    def test_player_does_not_hide_while_paused_or_dragging(self):
        self.evaluate("(async()=>{document.querySelector('#player').hidden=false;document.querySelector('#playerPane').hidden=false;await new Promise(r=>setTimeout(r,0));})()")
        result=self.evaluate("""(()=>{
          const nativeTimeout=window.setTimeout,callbacks=[];
          window.setTimeout=(fn,ms,...args)=>ms===4000?(callbacks.push(fn),-1):nativeTimeout(fn,ms,...args);
          const v=document.querySelector('#video');let paused=false;
          Object.defineProperty(v,'paused',{configurable:true,get:()=>paused});
          document.querySelector('#player').hidden=false;document.querySelector('#playerPane').hidden=false;
          document.querySelector('#hgMore').open=false;
          try{
            v.dispatchEvent(new Event('play'));paused=true;callbacks.pop()();
            const pauseVisible=!document.body.classList.contains('hg-ui-hidden');
            paused=false;v.dispatchEvent(new Event('play'));
            document.querySelector('.ctl').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
            callbacks.pop()();const dragVisible=!document.body.classList.contains('hg-ui-hidden');
            window.dispatchEvent(new PointerEvent('pointerup'));callbacks.pop()();
            return {pauseVisible,dragVisible,hidden:document.body.classList.contains('hg-ui-hidden')};
          }finally{window.setTimeout=nativeTimeout;delete v.paused;v.dispatchEvent(new Event('pause'));}
        })()""")
        self.assertEqual(result,dict(pauseVisible=True,dragVisible=True,hidden=True))


class ViewingDataBoundaryTests(BrowserFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        build()
        cls.ws.call('Page.navigate',{'url':(ROOT / '.test-tmp/viewing-ui.html').as_uri()})
        cls.evaluate("new Promise((resolve,reject)=>{let n=0;const id=setInterval(()=>{if(window.HGViewing){clearInterval(id);resolve()}else if(++n>100){clearInterval(id);reject(Error('样本加载超时'))}},30)})")

    def test_real_single_tap_double_like_and_bottom_search(self):
        result=self.evaluate("""(async()=>{
          renderFixture('demo');await new Promise(r=>setTimeout(r,30));HGViewing.clean(true);
          const s=document.querySelector('#feed .slide');s.click();await new Promise(r=>setTimeout(r,330));
          const shown=!document.body.classList.contains('hg-feed-clean');
          s.click();s.click();
          const liked=isLiked(12);
          document.querySelector('#bottomNav [data-view=search]').click();
          await new Promise(r=>setTimeout(r,10));
          return {shown,liked,view:document.body.dataset.view,header:getComputedStyle(document.querySelector('header')).display};
        })()""")
        self.assertTrue(result['shown'])
        self.assertTrue(result['liked'])
        self.assertEqual(result['view'],'search')
        self.assertNotEqual(result['header'],'none')

    def test_real_renderer_empty_one_long_and_many(self):
        for width,height in [(320,568),(768,1024),(1440,900)]:
            self.ws.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=height,deviceScaleFactor=1,mobile=False))
            for state,count in [('empty',0),('one',1),('worst',1),('many',1000)]:
                result=self.evaluate("""(async()=>{
                  renderFixture(%r);await new Promise(r=>setTimeout(r,40));
                  return {count:document.querySelectorAll('#feed .slide').length,
                    overflow:document.documentElement.scrollWidth>innerWidth,
                    search:getComputedStyle(document.querySelector('[data-view=search]')).visibility};
                })()""" % state)
                self.assertEqual(result['count'],count,(state,result))
                self.assertFalse(result['overflow'],(state,result))
                self.assertEqual(result['search'],'visible',(state,result))

    def test_feed_paused_and_progress_interaction_prevent_auto_hide(self):
        result=self.evaluate("""(()=>{
          renderFixture('demo');
          const nativeTimeout=window.setTimeout,callbacks=[];
          window.setTimeout=(fn,ms,...args)=>ms===4000?(callbacks.push(fn),-1):nativeTimeout(fn,ms,...args);
          const v=document.querySelector('#feed video');let paused=true;
          Object.defineProperty(v,'paused',{configurable:true,get:()=>paused});
          try{
            HGViewing.reveal();callbacks.pop()();const pauseVisible=!document.body.classList.contains('hg-feed-clean');
            paused=false;
            document.querySelector('#feed .prog').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
            callbacks.pop()();const dragVisible=!document.body.classList.contains('hg-feed-clean');
            window.dispatchEvent(new PointerEvent('pointerup'));callbacks.pop()();
            return {pauseVisible,dragVisible,hidden:document.body.classList.contains('hg-feed-clean'),fit:getComputedStyle(v).objectFit};
          }finally{window.setTimeout=nativeTimeout;delete v.paused;HGViewing.clean(true);}
        })()""")
        self.assertEqual(result,dict(pauseVisible=True,dragVisible=True,hidden=True,fit='contain'))

    def test_desktop_navigation_stays_visible_while_video_controls_hide(self):
        try:
            # 同一浏览器验证桌面、触屏、恢复桌面，防止只在开发机上碰巧通过。
            for touch in (False, True, False):
                with self.subTest(touch=touch):
                    self.ws.call('Emulation.setTouchEmulationEnabled',{'enabled':touch})
                    result=self.evaluate("""(()=>{document.body.dataset.view='home';HGViewing.clean(true);return {
                      desktop:matchMedia('(hover:hover) and (pointer:fine)').matches,
                      touch:matchMedia('(hover:none) and (pointer:coarse)').matches,
                      nav:getComputedStyle(document.querySelector('#bottomNav')).visibility,
                      actions:getComputedStyle(document.querySelector('#feed .acts')).visibility};})()""")
                    self.assertEqual(result['desktop'],not touch,result)
                    self.assertEqual(result['touch'],touch,result)
                    self.assertEqual(result['nav'],'hidden' if touch else 'visible',result)
                    self.assertEqual(result['actions'],'hidden',result)
        finally:
            self.ws.call('Emulation.setTouchEmulationEnabled',{'enabled':False})
