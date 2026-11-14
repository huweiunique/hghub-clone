"""生成仅供开发的离线界面样本：复用真实页面、渲染函数及本地扩展。"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = (ROOT / 'web/index.html').read_text(encoding='utf-8')
    main = next(s for s in re.findall(r'<script\b[^>]*>(.*?)</script>', source, re.S) if 'var UP =' in s)
    main = main.replace('loadHotTags();\nloadHome();\nhandleDeepLink();', '')
    page = re.sub(r'<script\b[^>]*>.*?</script>', '', source, flags=re.S)
    setup = """
      window.fetch=async()=>({ok:true,status:200,json:async()=>({data:{items:[],ips:[]}})});
    """
    scripts = setup + '\n' + main
    for name in ['web_patch.js', 'player_patch.js', 'player_controls.js', 'video_enhance.js', 'viewing_ui.js']:
        scripts += '\n' + (ROOT / 'local_ext' / name).read_text(encoding='utf-8')
    demo = dict(id=12,title='重逢之后',description='那些错过的时光，终于有了答案。',episode_count=80,collect_count=1284,comment_count=1)
    worst = dict(id=13,title='重返二十年前：这一次我会守护所有重要的人与约定',description='一段跨越二十年的重逢，牵动三代人的秘密与选择。'*25,episode_count=1000,collect_count=987654321,comment_count=0,author={'name':'Christopher Alexander Montgomery III'})
    scripts += '\nconst demo=' + json.dumps(demo,ensure_ascii=False) + ',worst=' + json.dumps(worst,ensure_ascii=False) + ';'
    scripts += """
      const switcher=document.createElement('div');
      switcher.id='fixture-switcher';
      switcher.style='position:fixed;bottom:4px;left:50%;transform:translateX(-50%);z-index:3000;display:flex;gap:2px;max-width:100%;background:#333;padding:3px;border-radius:8px';
      for(const [key,label] of [['demo','普通'],['worst','长文极值'],['empty','空'],['one','单条'],['many','千条'],['player','播放器']]){
        const b=document.createElement('button');b.textContent=label;b.style='padding:4px;font-size:11px;white-space:nowrap;background:#333;color:white;border:1px solid #777;border-radius:6px';
        b.onclick=()=>{location.hash=key;renderFixture(key)};switcher.append(b);
      }
      document.body.append(switcher);
      function renderFixture(key){
        closePlayer();document.body.dataset.view='home';
        document.querySelector('#view-home').hidden=false;
        const count=key==='empty'?0:key==='many'?1000:1;
        feedItems=Array.from({length:count},(_,i)=>({...((key==='worst')?worst:demo),id:12+i}));
        document.querySelector('#feed').innerHTML=count?feedItems.map(slideHtml).join(''):'<div class="empty">暂无短剧，轻点显示导航</div>';
        document.querySelector('#feed .slide')?.classList.add('active');
        bindClicks(document.querySelector('#feed'));setTimeout(()=>HGViewing.reveal(),0);
        if(key==='player'){
          document.body.classList.add('modal-open');document.querySelector('#player').hidden=false;
          document.querySelector('#detailPane').hidden=true;document.querySelector('#playerPane').hidden=false;
        }
      }
      renderFixture(location.hash.slice(1)||'demo');
    """
    out = ROOT / '.test-tmp/viewing-ui.html'
    out.parent.mkdir(exist_ok=True)
    out.write_text(page.replace('</body>', '<script>' + scripts.replace('</script>', '<\\/script>') + '</script></body>'),encoding='utf-8')
    print(out)


if __name__ == '__main__':
    build()
