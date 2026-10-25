from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright, Error as PlaywrightError

from malm_bridge.client import BridgeClient
from malm_bridge.service import build_service
from malm_bridge.types import ClientIdentity, ExecutionContext, MemorySpaceIdentity


HTML = r'''<!doctype html><html><body>
<form data-chatgpt-composer data-composer-placement="thread">
  <div id="composer" contenteditable="true" role="textbox" data-composer-markdown></div>
  <button id="send" type="submit">Send</button>
</form>
<div id="turns"></div>
<script>
window.submissions=[];
const f=document.querySelector('form');
const c=document.querySelector('#composer');
f.addEventListener('submit',e=>{
  e.preventDefault();
  const text=c.innerText;
  window.submissions.push(text);
  const u=document.createElement('div');u.dataset.turnKey='u'+window.submissions.length;
  const ub=document.createElement('div');ub.dataset.userMessageBubble='true';ub.innerText=text;u.appendChild(ub);document.querySelector('#turns').appendChild(u);
  c.innerText='';c.dispatchEvent(new InputEvent('input',{bubbles:true}));
  setTimeout(()=>{
    const a=document.createElement('div');a.dataset.turnKey='a'+window.submissions.length;
    const body=document.createElement('div');body.setAttribute('data-markdown-text-style','assistant-message');body.innerText='ack '+window.submissions.length;
    a.appendChild(body);document.querySelector('#turns').appendChild(a);
  },150);
});
c.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();f.requestSubmit();}});
</script>
</body></html>'''


class FakeSiteHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        data=HTML.encode('utf-8')
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self,*args):
        return


def log(msg):
    print(msg, flush=True)


async def main():
    package_root=Path(__file__).resolve().parents[2]
    production_ext=package_root/'browser-extension'
    identity=json.loads((production_ext/'config'/'extension-identity.json').read_text())
    with tempfile.TemporaryDirectory() as td:
        base=Path(td)
        # Test-only copy: production code/key remain byte-identical; only localhost admission/match is added.
        ext=base/'extension'
        shutil.copytree(production_ext,ext)
        fake=ThreadingHTTPServer(('127.0.0.1',0),FakeSiteHandler)
        fake_thread=threading.Thread(target=fake.serve_forever,daemon=True); fake_thread.start()
        fake_url=f'http://127.0.0.1:{fake.server_port}'
        manifest=json.loads((ext/'manifest.json').read_text())
        manifest['content_scripts'][0]['matches'].append(fake_url+'/*')
        (ext/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        chat_path=ext/'src'/'site-chatgpt.js'
        chat=chat_path.read_text()
        chat=chat.replace('matches: (loc) => /(^|\\.)chatgpt\\.com$/.test(loc.hostname) || /(^|\\.)chat\\.openai\\.com$/.test(loc.hostname),',
                          'matches: (loc) => loc.hostname === "127.0.0.1" || /(^|\\.)chatgpt\\.com$/.test(loc.hostname) || /(^|\\.)chat\\.openai\\.com$/.test(loc.hostname),')
        chat_path.write_text(chat)

        service=build_service({
            'memory_space_ids':['personal'],
            'state_dir':str(base/'state'),
            'primary':{'type':'sqlite','path':str(base/'memory.db')},
            'peers':[],
            'sync':{'interval_seconds':60},
            'http':{'host':'127.0.0.1','port':18790},
            'browser_bootstrap':{
                'enabled':True,
                'identity_files':[str(production_ext/'config'/'extension-identity.json')],
                'memory_spaces':['personal'],
                'scopes':['user','project'],
                'default_memory_space':{'space_id':'personal','owner_id':'local-user','kind':'personal'},
            },
        })
        service.start(); log('STAGE=SERVICE_STARTED')
        try:
            seed_id=ClientIdentity('seed','cli','seed-machine')
            seed_cred=service.auth.provision(seed_id,scopes=['user'],memory_spaces=['personal'])['token']
            seed=BridgeClient(service.base_url,seed_cred,seed_id,MemorySpaceIdentity('personal','local-user'),ExecutionContext(surface='cli'))
            out=seed.capture('請記住紫色','ok',session_id='seed',transaction_id='seed-tx',explicit_remember_request=True)
            assert out['decision']=='COMMIT'; log('STAGE=SEED_COMMITTED')

            async with async_playwright() as p:
                context=await p.chromium.launch_persistent_context(
                    str(base/'profile'), executable_path='/usr/bin/chromium', headless=True,
                    args=[f'--disable-extensions-except={ext}',f'--load-extension={ext}','--no-sandbox'],
                    ignore_default_args=['--disable-extensions'],
                )
                try:
                    log('STAGE=CHROMIUM_LAUNCHED')
                    page=await context.new_page()
                    try:
                        await page.goto(fake_url+'/',wait_until='domcontentloaded',timeout=10000)
                    except PlaywrightError as exc:
                        if 'ERR_BLOCKED_BY_ADMINISTRATOR' in str(exc):
                            print('CHROMIUM_PAGE_NAVIGATION=BLOCKED_BY_ENVIRONMENT')
                            print('PAGE_LEVEL_EXTENSION_E2E=UNPROVEN')
                            return
                        raise
                    log('STAGE=PAGE_LOADED')
                    await page.wait_for_function("document.documentElement.dataset.malmRuntimeOwner === 'chatgpt'",timeout=10000); log('STAGE=CONTENT_SCRIPT_OWNS_DOCUMENT')
                    assert await page.evaluate("document.documentElement.dataset.malmRuntimeBuild")=='0.3.0'; log('STAGE=BUILD_MATCH')

                    await page.locator('#composer').fill('紫色')
                    await page.locator('#composer').press('Enter')
                    await page.wait_for_function('window.submissions.length >= 1',timeout=10000)
                    first=await page.evaluate('window.submissions[0]')
                    assert '<local_memory_context>' in first,first
                    assert '[{}] 紫色'.format(out['committed_memory_ids'][0]) in first,first
                    assert '<current_user_message>\n紫色\n</current_user_message>' in first,first
                    log('STAGE=RECALL_INJECTED')
                    await asyncio.sleep(3.0)

                    await page.locator('#composer').fill('請記住我也喜歡黑色')
                    await page.locator('#composer').press('Enter')
                    await page.wait_for_function('window.submissions.length >= 2',timeout=10000)
                    await asyncio.sleep(3.2)
                    items=service.core.storage.search('我也喜歡黑色',{'memory_space_ids':['personal'],'namespaces':['user'],'include_lifecycle':['ACTIVE','CONFLICT']},20)
                    assert any(x.content=='我也喜歡黑色' for x in items),[x.content for x in items]
                    log('STAGE=CAPTURE_COMMITTED')

                    workers=context.service_workers
                    if not workers:
                        try: workers=[await context.wait_for_event('serviceworker',timeout=3000)]
                        except Exception: pass
                    assert workers,'extension service worker did not start'
                    origin=workers[0].url.split('/src/')[0]
                    assert origin==identity['origin'],(origin,identity['origin']); log('STAGE=EXTENSION_ID_MATCH')
                    print('CHROMIUM_EXTENSION_RUNTIME=PASS')
                    print('AUTO_BROWSER_BOOTSTRAP=PASS')
                    print('FAKE_CHATGPT_RECALL_INJECTION=PASS')
                    print('FAKE_CHATGPT_CAPTURE=PASS')
                    print('STABLE_EXTENSION_ID=PASS')
                finally:
                    await context.close()
        finally:
            service.stop(); fake.shutdown(); fake.server_close()


if __name__=='__main__':
    asyncio.run(asyncio.wait_for(main(), timeout=50))
