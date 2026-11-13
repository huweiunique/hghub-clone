"""统一控制层与画质增强的离线浏览器验证，不连接真实上游。"""
from test_player_layout import BrowserFixture, ROOT


class PlayerControlsTests(BrowserFixture):
    load_player_patch = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.evaluate("""
          const saved={};Object.defineProperty(window,'localStorage',{configurable:true,value:{
            getItem:k=>saved[k]??null,setItem:(k,v)=>saved[k]=String(v)}});
          window.setPlayerSource=()=>{};
        """)
        for name in ['player_patch.js', 'player_controls.js', 'video_enhance.js']:
            cls.evaluate((ROOT / 'local_ext' / name).read_text(encoding='utf-8'))

    def setUp(self):
        self.evaluate("""
          document.querySelector('#player').hidden=false;
          document.querySelector('#playerPane').hidden=false;
          document.querySelector('#detailPane').hidden=true;
          if(document.querySelector('#hgUnlock:not([hidden])'))document.querySelector('#hgUnlock').click();
          document.querySelectorAll('.hg-choice button').forEach(b=>{if(b.textContent==='返回播放')b.click()});
          setPlayerSource('fixture');
        """)

    def test_speed_and_stream_have_readable_labels_and_choice_keeps_binding(self):
        self.assertIn('1x', self.evaluate("document.querySelector('#hg-speedSel').textContent"))
        self.assertIn('主线', self.evaluate("document.querySelector('#hg-streamSel').textContent"))
        self.evaluate("document.querySelector('#hg-speedSel').click();[...document.querySelectorAll('.hg-choice [role=radio]')].find(b=>b.textContent==='1.5x').click()")
        self.assertEqual(self.evaluate("document.querySelector('#speedSel').value"), '1.5')
        self.assertEqual(self.evaluate("document.querySelector('#hg-speedSel').textContent"), '倍速 1.5x')
        self.assertFalse(self.evaluate("document.querySelector('#video').controls"))

    def test_lock_intercepts_hit_targets_and_allows_unlock(self):
        result = self.evaluate("""(()=>{
          document.querySelector('#hgLock').click();
          const close=document.querySelector('#btnClosePlayer').getBoundingClientRect();
          return {hidden:getComputedStyle(document.querySelector('#btnClosePlayer')).visibility,
            hit:document.elementFromPoint(close.x+close.width/2,close.y+close.height/2).id,
            unlock:!document.querySelector('#hgUnlock').hidden};
        })()""")
        self.assertEqual(result['hidden'], 'hidden', result)
        self.assertEqual(result['hit'], 'hgLockShield', result)
        self.assertTrue(result['unlock'])
        self.evaluate("document.querySelector('#hgUnlock').click()")
        self.assertTrue(self.evaluate("document.querySelector('#hgLockShield').hidden"))

    def test_temporary_double_speed_restores_original_rate(self):
        rates = self.evaluate("""(async()=>{
          const v=document.querySelector('#video');v.playbackRate=1.5;
          // captureStream 属于实时流，浏览器会固定实际倍速；模拟可调倍速的点播边界。
          let rate=1.5;Object.defineProperty(v,'playbackRate',{configurable:true,get:()=>rate,set:r=>rate=r});
          // 合成指针事件不能持有真实指针捕获，隔离该浏览器边界。
          const capture=v.setPointerCapture;v.setPointerCapture=()=>{};
          v.dispatchEvent(new PointerEvent('pointerdown',{pointerId:7,isPrimary:true,button:0,clientX:20,clientY:20}));
          await new Promise(r=>setTimeout(r,410));const during=v.playbackRate;
          v.dispatchEvent(new PointerEvent('pointerup',{pointerId:7,isPrimary:true}));
          v.setPointerCapture=capture;const after=v.playbackRate;delete v.playbackRate;return {during,after};
        })()""")
        self.assertEqual(rates, {'during': 2, 'after': 1.5})

    def test_default_natural_and_shared_feed_choice_persist(self):
        self.assertEqual(self.evaluate('HGEnhance.getMode()'), 'natural')
        self.evaluate("document.querySelector('#feed').innerHTML='<div class=\"slide active\"><video class=\"bgvid\"></video><div class=\"acts\"></div></div>'")
        self.evaluate("new Promise(r=>setTimeout(r,0))")
        self.evaluate("document.querySelector('.hg-sr-feed').click();[...document.querySelectorAll('.hg-feed-choice [role=radio]')].find(b=>b.textContent==='影院质感').click()")
        self.assertEqual(self.evaluate('HGEnhance.getMode()'), 'cinema')
        self.assertIn('影院质感', self.evaluate("document.querySelector('#playerPane [data-hg-enhance]').textContent"))
        self.assertEqual(self.evaluate("JSON.parse(localStorage.getItem('hg_sr_mode'))"), 'cinema')
        self.evaluate("HGEnhance.setMode('natural')")

    def test_recovery_has_a_hard_limit_and_does_not_leak_secrets(self):
        # 用真实扩展与可控 HLS 边界验证预算，不等待真实网络错误。
        result = self.evaluate("""(async()=>{
          window.Hls={ErrorTypes:{NETWORK_ERROR:'network',MEDIA_ERROR:'media'}};
          window.hls={startLoad:()=>calls++,recoverMediaError:()=>calls++};let calls=0;
          const data={fatal:true,type:'network',url:'https://secret.test/?key=PRIVATE',details:'PRIVATE'};
          for(let i=0;i<4;i++){hgRecoverHls(hls,data,true);await new Promise(r=>setTimeout(r,260*(i+1)));}
          const last=hgRecoverHls(hls,data,true);
          return {calls,last,text:document.querySelector('#hgPlaybackStatus').textContent,
            log:JSON.stringify(HGControls.snapshot())};
        })()""")
        self.assertEqual(result['calls'], 4)
        self.assertFalse(result['last'])
        self.assertIn('恢复失败', result['text'])
        self.assertNotIn('PRIVATE', result['log'])
        self.assertNotIn('secret.test', result['log'])

    def test_leaving_player_cancels_delayed_recovery(self):
        result = self.evaluate("""(async()=>{
          window.Hls={ErrorTypes:{NETWORK_ERROR:'network'}};let calls=0;
          window.hls={startLoad:()=>calls++};hgRecoverHls(hls,{fatal:true,type:'network'},false);
          document.querySelector('#playerPane').hidden=true;
          await new Promise(r=>setTimeout(r,1100));return calls;
        })()""")
        self.assertEqual(result, 0)

    def test_gpu_or_fallback_never_hides_original_video(self):
        self.evaluate("HGEnhance.setMode('natural')")
        result = self.evaluate("""(async()=>{
          await new Promise(r=>setTimeout(r,120));const v=document.querySelector('#video');
          return {visible:getComputedStyle(v).display,opacity:getComputedStyle(v).opacity,
            count:document.querySelectorAll('.hg-enhance-canvas').length,state:HGEnhance.getState()};
        })()""")
        self.assertNotEqual(result['visible'], 'none', result)
        self.assertEqual(result['opacity'], '1', result)
        self.assertLessEqual(result['count'], 1)
        self.assertTrue(result['state']['active'])
        self.assertTrue(result['state']['ready'] or result['state']['fallback'], result)

    def test_close_hit_target_is_separate_from_mute_and_large_enough(self):
        result = self.evaluate("""(()=>{
          const close=document.querySelector('#btnClosePlayer'),mute=document.querySelector('#hgMute');
          const r=close.getBoundingClientRect(),m=mute.getBoundingClientRect();
          return {w:r.width,h:r.height,muteHeight:m.height,
            hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2).closest('button').id,
            overlap:!(r.right<=m.left||r.left>=m.right||r.bottom<=m.top||r.top>=m.bottom)};
        })()""")
        self.assertGreaterEqual(result['w'], 48, result)
        self.assertGreaterEqual(result['h'], 48, result)
        self.assertGreaterEqual(result['muteHeight'], 48, result)
        self.assertEqual(result['hit'], 'btnClosePlayer', result)
        self.assertFalse(result['overlap'], result)

    def test_top_buttons_avoid_corners_and_rotate_safe_insets(self):
        self.ws.call('Emulation.setDeviceMetricsOverride', {'width':430,'height':932,'deviceScaleFactor':1,'mobile':True})
        self.evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        self.evaluate("""
          for(const [side,value] of Object.entries({top:60,left:28,right:28,bottom:34}))
            document.documentElement.style.setProperty('--hg-screen-'+side,value+'px');
        """)
        try:
            for rotated in [False, True]:
                self.evaluate('document.body.classList.toggle("hg-landscape",' + str(rotated).lower() + ')')
                rects = self.evaluate("""(()=>{
                  return ['#btnBackDetail','#btnClosePlayer'].map(s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};});
                })()""")
                for rect in rects:
                    self.assertGreaterEqual(rect['x'], 28, rects)
                    self.assertGreaterEqual(rect['y'], 60, rects)
                    self.assertLessEqual(rect['right'], 430-28, rects)
                    self.assertLessEqual(rect['bottom'], 932-34, rects)
        finally:
            self.evaluate("document.body.classList.remove('hg-landscape');for(const s of ['top','left','right','bottom'])document.documentElement.style.removeProperty('--hg-screen-'+s)")

    def test_texture_read_failure_returns_to_visible_original_with_fallback(self):
        result = self.evaluate("""(()=>{
          const canvas=document.querySelector('.hg-enhance-canvas'),v=document.querySelector('#video');
          const gl=canvas.getContext('webgl2');
          if(!gl)return {unsupported:true,state:HGEnhance.getState()};
          const upload=gl.texImage2D;gl.texImage2D=()=>{throw new Error('SECRET_CDN_URL');};
          try { v.dispatchEvent(new Event('loadstart'));HGEnhance.setMode('crisp');
            return {state:HGEnhance.getState(),canvas:getComputedStyle(canvas).opacity,
              display:getComputedStyle(v).display,log:JSON.stringify(HGControls.snapshot())};
          } finally { gl.texImage2D=upload;v.dispatchEvent(new Event('loadstart'));HGEnhance.setMode('natural'); }
        })()""")
        self.assertTrue(result['state']['fallback'], result)
        if not result.get('unsupported'):
            self.assertEqual(result['canvas'], '0', result)
            self.assertNotEqual(result['display'], 'none', result)
            self.assertNotIn('SECRET_CDN_URL', result['log'])
