"""执行真实上游业务脚本和本地增强，媒体加载与联网接口使用可控边界。"""
import re
from test_player_layout import BrowserFixture, ROOT


class PlaybackBehaviorTests(BrowserFixture):
    load_player_patch = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.evaluate(r"""
          const values={};
          Object.defineProperty(window,'localStorage',{configurable:true,value:{
            getItem:k=>values[k]??null,setItem:(k,v)=>values[k]=String(v),
            removeItem:k=>delete values[k],clear:()=>Object.keys(values).forEach(k=>delete values[k])}});
          document.querySelector('#video').pause();
          document.querySelector('#video').srcObject.getTracks().forEach(t=>t.stop());
          document.querySelector('#video').srcObject=null;
          window.fetch=async(url)=>({ok:true,status:200,json:async()=>{
            const match=String(url).match(/\/api\/videos\/(\d+)$/);
            if(match)return {data:{id:+match[1],title:'测试剧'+match[1],episode_count:3,is_finished:true}};
            if(String(url)==='/api/play')return {data:{streams:{main:'fixture'}}};
            return {data:{items:[],ips:[]}};
          }});
        """)
        html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
        main = next(s for s in re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S) if "var UP =" in s)
        # 仅关闭页面启动时联网加载；保留所有点击、选集、自动下一集与存储逻辑。
        main = main.replace('loadHotTags();\nloadHome();\nhandleDeepLink();', '')
        cls.evaluate(main)
        cls.evaluate("""
          window.media={time:0,duration:100,ready:0,paused:true,autoReady:true};
          const v=document.querySelector('#video');
          Object.defineProperties(v,{
            currentTime:{configurable:true,get:()=>media.time,set:t=>media.time=t},
            duration:{configurable:true,get:()=>media.duration},
            readyState:{configurable:true,get:()=>media.ready},
            paused:{configurable:true,get:()=>media.paused}});
          v.play=async()=>{media.paused=false;v.dispatchEvent(new Event('play'));};
          v.pause=()=>{media.paused=true;v.dispatchEvent(new Event('pause'));};
          v.load=()=>{};
          window.setPlayerSource=()=>{
            media.time=0;media.ready=0;
            if(media.autoReady)queueMicrotask(()=>{
              media.ready=1;v.dispatchEvent(new Event('loadedmetadata'));v.play();
            });
          };
        """)
        cls.evaluate((ROOT / 'local_ext/player_patch.js').read_text(encoding='utf-8'))
        cls.evaluate((ROOT / 'local_ext/player_controls.js').read_text(encoding='utf-8'))
        cls.evaluate((ROOT / 'local_ext/video_enhance.js').read_text(encoding='utf-8'))

    def setUp(self):
        self.evaluate("""
          localStorage.clear();curVideo=null;curDetail=null;curEp=1;
          media.time=0;media.duration=100;media.ready=0;media.paused=true;media.autoReady=true;
        """)

    def play(self, episode=1):
        self.evaluate(f"(async()=>{{await openDetail(12);await playVideo(12,{episode});}})()")

    def test_first_seconds_pause_and_exit_are_saved_then_resumed(self):
        self.play()
        self.evaluate("media.time=5;document.querySelector('#video').pause()")
        self.assertEqual(self.evaluate('getProgress(12).t'), 5)
        self.evaluate("media.time=7;window.dispatchEvent(new Event('pagehide'))")
        self.assertEqual(self.evaluate('getProgress(12).t'), 7)
        self.evaluate('closePlayer()')
        self.play()
        self.assertEqual(self.evaluate('media.time'), 7)

    def test_new_episode_loading_does_not_save_old_video_time(self):
        self.play()
        self.evaluate('media.time=42;saveProgress();media.autoReady=false')
        self.evaluate('playVideo(12,2)')
        self.evaluate("media.time=42;document.querySelector('#video').dispatchEvent(new Event('pause'));window.dispatchEvent(new Event('pagehide'))")
        progress = self.evaluate('getProgress(12)')
        self.assertEqual((progress['ep'], progress['t']), (1, 42))

    def test_completed_episode_immediately_records_next_start_and_final_completion(self):
        self.play(1)
        self.evaluate("media.autoReady=false;media.time=100;document.querySelector('#video').dispatchEvent(new Event('ended'))")
        progress = self.evaluate('getProgress(12)')
        self.assertEqual((progress['ep'], progress['t'], progress['completed']), (2, 0, False))
        self.evaluate("window.dispatchEvent(new Event('pagehide'))")
        self.assertEqual(self.evaluate('getProgress(12).ep'), 2)
        self.evaluate('media.autoReady=true')
        self.play(3)
        self.evaluate("media.time=100;document.querySelector('#video').dispatchEvent(new Event('ended'))")
        self.assertTrue(self.evaluate('getProgress(12).completed'))
        self.assertEqual(self.evaluate('curEp'), 3)

    def test_history_stays_in_place_shows_seconds_and_click_resumes(self):
        self.evaluate("store.set('hg_progress',{12:{ep:2,t:33,dur:100,at:1}});store.set('hg_history',[{id:12,title:'测试剧',cover:'',ep:2,t:1}]);renderMe()")
        headings = self.evaluate("[...document.querySelectorAll('#meBox .mebox>h3')].map(h=>h.textContent)")
        self.assertTrue(headings[1].startswith('我的收藏'))
        self.assertTrue(headings[2].startswith('观看历史'))
        self.assertIn('第 2 集', self.evaluate("document.querySelector('#meBox .rankrow p').textContent"))
        self.assertIn('0:33', self.evaluate("document.querySelector('#meBox .rankrow p').textContent"))
        self.evaluate("document.querySelector('#meBox .rankrow').click()")
        self.evaluate('new Promise(r=>setTimeout(r,10))')
        self.assertEqual(self.evaluate('curEp'), 2)
        self.assertEqual(self.evaluate('media.time'), 33)
        self.assertFalse(self.evaluate("document.querySelector('#playerPane').hidden"))
        self.evaluate("document.querySelector('#meBox .hg-history-actions button').click()")
        self.evaluate('new Promise(r=>setTimeout(r,10))')
        self.assertTrue(self.evaluate("document.querySelector('#playerPane').hidden"))

    def test_restore_waits_for_media_and_old_timer_cannot_rewind_playback(self):
        self.evaluate("store.set('hg_progress',{12:{ep:1,t:45,dur:100}});media.autoReady=false")
        self.play()
        self.assertEqual(self.evaluate('getProgress(12).t'), 45)
        self.evaluate("media.ready=1;document.querySelector('#video').dispatchEvent(new Event('loadedmetadata'))")
        self.assertEqual(self.evaluate('media.time'), 45)
        self.evaluate('media.time=49;new Promise(r=>setTimeout(r,900))')
        self.assertEqual(self.evaluate('media.time'), 49)

    def test_finished_history_does_not_automatically_replay_final_episode(self):
        self.evaluate("store.set('hg_progress',{12:{ep:3,t:100,dur:100,completed:true}});store.set('hg_history',[{id:12,title:'测试剧',ep:3,t:1}]);renderMe()")
        self.assertEqual(self.evaluate("document.querySelector('#meBox .rankrow p').textContent"), '已看完')
        self.evaluate("document.querySelector('#meBox .rankrow').click()")
        self.evaluate('new Promise(r=>setTimeout(r,10))')
        self.assertTrue(self.evaluate("document.querySelector('#playerPane').hidden"))
        self.assertTrue(self.evaluate('getProgress(12).completed'))

    def test_returning_to_detail_cannot_overwrite_saved_position_with_reset_media(self):
        self.play(2)
        self.evaluate("media.time=31;showDetailPane();media.time=0;document.querySelector('#video').dispatchEvent(new Event('pause'))")
        self.assertEqual(self.evaluate('getProgress(12).t'), 31)
        self.play(2)
        self.assertEqual(self.evaluate('media.time'), 31)

    def test_close_button_saves_before_source_is_cleared_even_when_pause_is_async(self):
        self.play(1)
        self.evaluate("""
          window.savedPause=document.querySelector('#video').pause;
          window.savedLoad=document.querySelector('#video').load;
          document.querySelector('#video').pause=()=>{media.paused=true;};
          document.querySelector('#video').load=()=>{media.time=0;media.ready=0;media.duration=NaN;};
          media.time=37;
        """)
        try:
            self.evaluate("document.querySelector('#btnClosePlayer').click()")
            self.assertEqual(self.evaluate('getProgress(12).t'), 37)
        finally:
            self.evaluate("document.querySelector('#video').pause=window.savedPause;document.querySelector('#video').load=window.savedLoad")


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)
