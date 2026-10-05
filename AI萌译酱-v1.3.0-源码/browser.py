# -*- coding: utf-8 -*-
"""零依赖浏览器驱动：用系统自带的 Chrome / Edge 的 DevTools 协议（CDP）操作网页端。

完全不依赖 playwright / selenium，只用 Python 标准库（netutil + wsclient）。

默认**直接使用你日常使用的浏览器配置**（同样的书签、扩展、登录状态），
所以打开的就是你平时那个浏览器，而不是一个空白的临时窗口。

原理：
1. 用 `--remote-debugging-port=xxxx` 启动浏览器（复用你日常的 User Data 目录）；
2. 通过 HTTP 查询调试端口，拿到 WebSocket 调试地址；
3. 用标准库 WebSocket 连接，用 CDP 的 Runtime.evaluate 执行 JS：
   - 找到输入框 -> 填入文字 -> 点击发送 / 模拟回车；
   - 轮询读取最后一条回复，直到内容稳定。
"""
import os
import re
import sys
import json
import time
import socket
import shutil
import subprocess
import threading

import netutil
import wsclient

# 两个网页版共用**同一个浏览器实例**（同一个调试端口），各自使用自己的标签页。
# 这样不会出现"两份浏览器配置互相抢锁"的问题，也符合"就在我这个浏览器里开个标签页"的用法。
BROWSER_PORT = 9333

SITE_URL = {
    'deepseek_web': 'https://chat.deepseek.com/',
    'chatgpt_web': 'https://chatgpt.com/',
    'bilibili': 'https://www.bilibili.com/',
}

_CHROMIUM_HINTS = ('chrome', 'msedge', 'chromium', 'brave', 'vivaldi', 'opera', 'thorium', 'yandex')

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0


def _is_chromium(exe):
    name = os.path.basename(str(exe)).lower()
    return any(h in name for h in _CHROMIUM_HINTS)


def _product_name(exe):
    name = os.path.basename(str(exe)).lower()
    table = (('msedge', 'Microsoft Edge'), ('chrome', 'Google Chrome'), ('chromium', 'Chromium'),
             ('brave', 'Brave'), ('vivaldi', 'Vivaldi'), ('opera', 'Opera'),
             ('thorium', 'Thorium'), ('yandex', 'Yandex'))
    for key, label in table:
        if key in name:
            return label
    return os.path.basename(str(exe))


def _from_registry():
    """读取 Windows 默认浏览器（https 关联）的可执行文件路径。"""
    if os.name != 'nt':
        return None
    try:
        import winreg
        key = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            prog_id = winreg.QueryValueEx(k, 'ProgId')[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r'\shell\open\command') as k:
            cmd = winreg.QueryValueEx(k, '')[0]
        m = re.search(r'"([^"]+\.exe)"', cmd) or re.search(r'([^\s"]+\.exe)', cmd)
        if m and os.path.isfile(m.group(1)):
            return m.group(1)
    except Exception:
        pass
    return None


def find_browser():
    """返回 (可执行文件路径, 显示名)。优先使用系统默认浏览器。"""
    default = _from_registry()
    if default and _is_chromium(default):
        return default, f'系统默认浏览器（{_product_name(default)}）'

    pf = os.environ.get('ProgramFiles', r'C:\Program Files')
    pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
    local = os.environ.get('LOCALAPPDATA', '')
    candidates = [
        (os.path.join(pf86, r'Microsoft\Edge\Application\msedge.exe'), 'Microsoft Edge'),
        (os.path.join(pf, r'Microsoft\Edge\Application\msedge.exe'), 'Microsoft Edge'),
        (os.path.join(pf, r'Google\Chrome\Application\chrome.exe'), 'Google Chrome'),
        (os.path.join(pf86, r'Google\Chrome\Application\chrome.exe'), 'Google Chrome'),
        (os.path.join(local, r'Microsoft\Edge\Application\msedge.exe'), 'Microsoft Edge'),
        (os.path.join(local, r'Google\Chrome\Application\chrome.exe'), 'Google Chrome'),
    ]
    for path, name in candidates:
        if path and os.path.isfile(path):
            return path, name
    for name in ('msedge', 'chrome', 'chromium', 'brave'):
        p = shutil.which(name)
        if p:
            return p, _product_name(p)
    return None, ''


def browser_user_data_dir(exe):
    """返回该浏览器日常使用的 User Data 目录。"""
    low = os.path.basename(str(exe)).lower()
    local = os.environ.get('LOCALAPPDATA', '')
    if not local:
        return None
    if 'msedge' in low:
        return os.path.join(local, 'Microsoft', 'Edge', 'User Data')
    if 'chrome' in low:
        return os.path.join(local, 'Google', 'Chrome', 'User Data')
    if 'brave' in low:
        return os.path.join(local, 'BraveSoftware', 'Brave-Browser', 'User Data')
    if 'vivaldi' in low:
        return os.path.join(local, 'Vivaldi', 'User Data')
    if 'chromium' in low:
        return os.path.join(local, 'Chromium', 'User Data')
    if 'opera' in low:
        return os.path.join(local, 'Programs', 'Opera')
    return None


def last_used_profile(user_data_dir):
    """读取最近使用的配置文件目录名，并确认它真的存在。

    注意：如果目录名不存在（Local State 读失败 / 配置文件被删），
    绝不能凭一个不存在的名字去启动，否则 Chrome 会开出一个"空白配置"的窗口。
    """
    name = ''
    try:
        with open(os.path.join(user_data_dir, 'Local State'), 'r', encoding='utf-8') as f:
            data = json.load(f)
        name = (data.get('profile') or {}).get('last_used') or ''
    except Exception:
        name = ''
    if name and os.path.isdir(os.path.join(user_data_dir, name)):
        return name
    if os.path.isdir(os.path.join(user_data_dir, 'Default')):
        return 'Default'
    try:
        for d in sorted(os.listdir(user_data_dir)):
            if d.startswith('Profile ') and os.path.isdir(os.path.join(user_data_dir, d)):
                return d
    except Exception:
        pass
    return 'Default'


def browser_running(exe):
    """判断该浏览器当前是否有进程在运行。"""
    name = os.path.basename(str(exe))
    if not name or os.name != 'nt':
        return False
    try:
        r = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}', '/NH'],
                           capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=15)
        return name.lower() in (r.stdout or '').lower()
    except Exception:
        return False


def kill_browser(exe, wait=15):
    """结束该浏览器的所有进程（用于让调试端口能生效）。"""
    name = os.path.basename(str(exe))
    if not name or os.name != 'nt':
        return True
    try:
        subprocess.run(['taskkill', '/IM', name, '/F', '/T'],
                       capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=25)
    except Exception:
        pass
    deadline = time.time() + wait
    while time.time() < deadline:
        if not browser_running(exe):
            return True
        time.sleep(0.5)
    return not browser_running(exe)


def find_free_port(preferred):
    try:
        s = socket.socket()
        s.bind(('127.0.0.1', preferred))
        s.close()
        return preferred
    except Exception:
        pass
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _copy_sqlite(src, dst):
    """用 sqlite 备份 API 复制数据库（源文件被浏览器占用时也能复制）。"""
    try:
        import sqlite3
        tmp = dst + '.tmp'
        if os.path.exists(tmp):
            os.remove(tmp)
        con = sqlite3.connect(f'file:{src}?mode=ro', uri=True, timeout=5)
        try:
            out = sqlite3.connect(tmp)
            try:
                con.backup(out)
            finally:
                out.close()
        finally:
            con.close()
        os.replace(tmp, dst)
        return True
    except Exception:
        try:
            shutil.copy2(src, dst)
            return True
        except Exception:
            return False


def clone_login_data(src_user_data, src_profile, dst_user_data, log=None):
    """把日常浏览器里的**登录数据**复制到本程序专用目录（尽力而为）。

    为什么需要：
        Chrome 136 起禁止在"默认数据目录"上开启调试端口，
        所以只能用非标准目录；为了免去重新登录，这里把 Cookie / 本地存储搬过去。
    """
    log = log or (lambda m: None)
    src_prof = os.path.join(src_user_data, src_profile or 'Default')
    dst_prof = os.path.join(dst_user_data, 'Default')
    os.makedirs(dst_prof, exist_ok=True)
    copied = []

    # 1) Local State —— 里面装着 Cookie 的解密密钥，必须一起搬
    try:
        shutil.copy2(os.path.join(src_user_data, 'Local State'),
                     os.path.join(dst_user_data, 'Local State'))
        copied.append('Local State')
    except Exception as e:
        log(f'复制 Local State 失败：{e}')

    # 2) Cookie 数据库
    src_cookie = os.path.join(src_prof, 'Network', 'Cookies')
    if not os.path.exists(src_cookie):
        src_cookie = os.path.join(src_prof, 'Cookies')
    if os.path.exists(src_cookie):
        dst_cookie = os.path.join(dst_prof, 'Network', 'Cookies')
        os.makedirs(os.path.dirname(dst_cookie), exist_ok=True)
        if _copy_sqlite(src_cookie, dst_cookie):
            copied.append('Cookies')
        else:
            log('Cookie 数据库正被浏览器占用，这次没能导入（下次会自动重试，或直接登录一次即可）')
    else:
        log('未找到 Cookie 数据库（浏览器版本可能不同）')

    # 3) 本地存储（有些站点把登录态放在这里）
    for name in ('Local Storage', 'Session Storage'):
        s = os.path.join(src_prof, name)
        if os.path.isdir(s):
            d = os.path.join(dst_prof, name)
            try:
                shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d, dirs_exist_ok=True)
                copied.append(name)
            except Exception as e:
                log(f'复制 {name} 失败：{e}')

    # 4) 其它可选文件
    for name in ('Preferences', 'Login Data', 'Web Data'):
        s = os.path.join(src_prof, name)
        if os.path.isfile(s):
            try:
                shutil.copy2(s, os.path.join(dst_prof, name))
                copied.append(name)
            except Exception:
                pass

    log('已导入日常浏览器的登录数据：' + ('、'.join(copied) if copied else '（没有可导入的数据）'))
    return copied


# --------------------------------------------------------------------------
# 页面操作用的 JS 片段
# --------------------------------------------------------------------------
JS_FIND_INPUT = r"""
(function(){
  function visible(e){var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}
  var tas=document.querySelectorAll('textarea');
  for(var i=0;i<tas.length;i++){if(visible(tas[i])&&!tas[i].disabled)return true;}
  var ces=document.querySelectorAll('div[contenteditable="true"],[contenteditable="true"]');
  for(var k=0;k<ces.length;k++){if(visible(ces[k]))return true;}
  return false;
})()
"""

JS_FOCUS_CLEAR = r"""
(function(){
  function visible(e){var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}
  var cands=[];
  var tas=document.querySelectorAll('textarea');
  for(var i=0;i<tas.length;i++){if(visible(tas[i])&&!tas[i].disabled)cands.push(tas[i]);}
  if(!cands.length){
    var ces=document.querySelectorAll('div[contenteditable="true"],[contenteditable="true"]');
    for(var k=0;k<ces.length;k++){if(visible(ces[k]))cands.push(ces[k]);}
  }
  if(!cands.length) return 'NO_INPUT';
  var el=cands[cands.length-1];
  var tag=el.tagName;
  if(tag==='TEXTAREA'||tag==='INPUT'){
    var proto=(tag==='TEXTAREA')?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
    var d=Object.getOwnPropertyDescriptor(proto,'value');
    if(d&&d.set){ d.set.call(el,''); } else { el.value=''; }
    el.dispatchEvent(new Event('input',{bubbles:true}));
  } else {
    el.innerText='';
    try{ el.dispatchEvent(new InputEvent('input',{bubbles:true,data:'',inputType:'deleteContentBackward'})); }
    catch(e){ el.dispatchEvent(new Event('input',{bubbles:true})); }
  }
  try{ el.focus(); }catch(e){}
  return 'CLEARED:'+tag;
})()
"""

JS_INPUT_TEXT = r"""
(function(){
  function visible(e){var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}
  var cands=[];
  var tas=document.querySelectorAll('textarea');
  for(var i=0;i<tas.length;i++){if(visible(tas[i])&&!tas[i].disabled)cands.push(tas[i]);}
  if(!cands.length){
    var ces=document.querySelectorAll('div[contenteditable="true"],[contenteditable="true"]');
    for(var k=0;k<ces.length;k++){if(visible(ces[k]))cands.push(ces[k]);}
  }
  if(!cands.length) return '';
  var el=cands[cands.length-1];
  var v = (el.value!==undefined && el.value!==null) ? el.value : (el.innerText||'');
  return String(v).trim();
})()
"""

JS_TYPE = r"""
(function(){
  var text = %s;
  function visible(e){var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}
  var cands=[];
  var tas=document.querySelectorAll('textarea');
  for(var i=0;i<tas.length;i++){if(visible(tas[i])&&!tas[i].disabled)cands.push(tas[i]);}
  if(!cands.length){
    var ces=document.querySelectorAll('div[contenteditable="true"],[contenteditable="true"]');
    for(var k=0;k<ces.length;k++){if(visible(ces[k]))cands.push(ces[k]);}
  }
  if(!cands.length) return 'NO_INPUT';
  var el=cands[cands.length-1];
  try{ el.focus(); }catch(e){}
  var tag=el.tagName;
  if(tag==='TEXTAREA'||tag==='INPUT'){
    var proto=(tag==='TEXTAREA')?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
    var d=Object.getOwnPropertyDescriptor(proto,'value');
    if(d&&d.set){ d.set.call(el,text); } else { el.value=text; }
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
    return 'TYPED_TEXTAREA';
  }
  var sel=window.getSelection();
  var range=document.createRange();
  range.selectNodeContents(el);
  sel.removeAllRanges(); sel.addRange(range);
  var ok=false;
  try{ ok=document.execCommand('insertText',false,text); }catch(e){ ok=false; }
  if(!ok || (el.innerText||'').indexOf(text) === -1){
    el.innerText=text;
    try{ el.dispatchEvent(new InputEvent('input',{bubbles:true,data:text,inputType:'insertText'})); }
    catch(e){ el.dispatchEvent(new Event('input',{bubbles:true})); }
  }
  return 'TYPED_EDITABLE';
})()
"""

JS_SEND = r"""
(function(){
  function visible(e){var r=e.getBoundingClientRect();return r.width>8&&r.height>8;}
  var sels=['button[data-testid="send-button"]',
            'button[aria-label*="发送"]','button[aria-label*="Send"]','button[aria-label*="send"]',
            'div[role="button"][aria-label*="发送"]','div[role="button"][aria-label*="Send"]'];
  for(var i=0;i<sels.length;i++){
    var b=document.querySelector(sels[i]);
    if(b&&visible(b)&&!b.disabled){ b.click(); return 'CLICK:'+sels[i]; }
  }
  function visibleInput(e){var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}
  var inputs=[];
  var tas=document.querySelectorAll('textarea');
  for(var a=0;a<tas.length;a++){ if(visibleInput(tas[a])&&!tas[a].disabled) inputs.push(tas[a]); }
  if(!inputs.length){
    var ces=document.querySelectorAll('div[contenteditable="true"],[contenteditable="true"]');
    for(var c=0;c<ces.length;c++){ if(visibleInput(ces[c])) inputs.push(ces[c]); }
  }
  var el=inputs.length?inputs[inputs.length-1]:null;
  if(el){
    var box=el.getBoundingClientRect();
    var btns=document.querySelectorAll('button,div[role="button"]');
    var best=null,bestD=1e9;
    for(var j=0;j<btns.length;j++){
      var b2=btns[j];
      if(b2.disabled) continue;
      var rb=b2.getBoundingClientRect();
      if(rb.width<8||rb.height<8) continue;
      if(rb.left < box.left + box.width*0.5) continue;
      var d=Math.abs(rb.top-box.top)+Math.abs(rb.left-box.right);
      if(d<bestD){bestD=d;best=b2;}
    }
    if(best&&bestD<160){ best.click(); return 'CLICK_NEAR'; }
  }
  return 'NO_SEND';
})()
"""

# 读取最后一条"回答"。关键：跳过 DeepSeek 的"深度思考"块，否则会把思考过程当成译文。
JS_READ_LAST = r"""
(function(){
  function textOf(el){ return (el.innerText||'').trim(); }
  function inThinking(el){
    var p = el;
    var depth = 0;
    while (p && p !== document.body && depth < 12) {
      var cls = ((p.className && p.className.toString) ? p.className.toString() : '').toLowerCase();
      if (cls.indexOf('think') >= 0 || cls.indexOf('reason') >= 0) return true;
      var head = (p.innerText || '').slice(0, 24);
      if (head.indexOf('思考') === 0 || head.indexOf('已深度思考') === 0 ||
          head.indexOf('Thought') === 0 || head.indexOf('Thinking') === 0) return true;
      p = p.parentElement; depth++;
    }
    return false;
  }
  // 1) ChatGPT：直接用 role 标记
  var nodes = document.querySelectorAll('[data-message-author-role="assistant"]');
  for (var i = nodes.length - 1; i >= 0; i--) {
    var t = textOf(nodes[i]);
    if (t) return t;
  }
  // 2) DeepSeek / 通用：取最后一个非思考块的 markdown 容器
  var sels = ['.ds-markdown', 'div[class*="markdown"]'];
  for (var s = 0; s < sels.length; s++) {
    var list = document.querySelectorAll(sels[s]);
    for (var j = list.length - 1; j >= 0; j--) {
      if (inThinking(list[j])) continue;
      var tx = textOf(list[j]);
      if (tx) return tx;
    }
  }
  return '';
})()
"""

# 是否仍在生成中（有"停止生成"按钮）
JS_GENERATING = r"""
(function(){
  var kws=['停止生成','停止','Stop generating','Stop streaming','Stop'];
  var bs=document.querySelectorAll('button,div[role="button"]');
  for(var i=0;i<bs.length;i++){
    var t=(bs[i].innerText||'').trim();
    if(!t) continue;
    for(var k=0;k<kws.length;k++){ if(t===kws[k]) return true; }
  }
  return false;
})()
"""


class BrowserSession:
    """一个网页版会话：启动/复用系统浏览器，并用 CDP 完成翻译。"""

    def __init__(self, provider, log=None):
        self.provider = provider
        self.log = log or (lambda msg: None)
        self.port = BROWSER_PORT
        self.url = SITE_URL.get(provider, '')
        # 独立配置目录仅作为「日常配置不可用」时的兜底（两个网页版共用）
        self.profile_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'data', 'browser_profile')
        self.use_own_profile = True
        self.allow_isolated = False      # 只有用户明确选择才会用独立空白配置
        self.allow_kill_browser = False  # 只有用户明确同意才会关闭在运行的浏览器
        self.profile_mode = ''
        self.exe = ''
        self.browser_name = ''
        self.proc = None
        self.ws = None
        self.session_id = None
        self.target_id = None
        self._msg_id = 0
        self._lock = threading.Lock()
        self._state_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'data', 'browser_state.json')

    # ---------------- 连接 ----------------
    def _load_state(self):
        try:
            with open(self._state_file, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save_state(self, ws_url=''):
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            old = self._load_state()
            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump({'port': self.port, 'ws': ws_url or old.get('ws', ''),
                           'mode': self.profile_mode}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def _endpoint_info(port):
        try:
            info = netutil.get_json(f'http://127.0.0.1:{port}/json/version', timeout=2)
            return info if info.get('Browser') else None
        except Exception:
            return None

    def own_endpoint_alive(self):
        """只有当端口上跑的是**本程序启动的**浏览器时才返回信息。

        两种认领方式：
        1) 与上次记录的调试地址（每次启动唯一的 UUID）完全一致；
        2) 记录丢失（例如换了解压目录）但本程序固定端口上确实有调试浏览器
           —— 直接复用，避免"又开一个浏览器"（这正是出现白色浏览器的根源）。
        """
        st = self._load_state()
        port = st.get('port')
        ws_url = st.get('ws')
        if port:
            info = self._endpoint_info(port)
            if info and (not ws_url or info.get('webSocketDebuggerUrl') == ws_url):
                self.port = port
                self.profile_mode = st.get('mode', '')
                return info
        if int(port or 0) != BROWSER_PORT:
            info = self._endpoint_info(BROWSER_PORT)
            if info:
                self.port = BROWSER_PORT
                self.profile_mode = st.get('mode', '')
                return info
        return None

    def is_connected(self):
        return self.ws is not None

    def ensure(self):
        """确保浏览器已启动且 CDP 已连接。"""
        with self._lock:
            if self.ws is not None:
                return
            if self.own_endpoint_alive() is None:
                self._launch()
            self._connect()

    def _launch_with(self, exe, data_dir, profile_directory, timeout):
        os.makedirs(data_dir, exist_ok=True)
        args = [
            exe,
            f'--remote-debugging-port={self.port}',
            f'--user-data-dir={data_dir}',
            '--no-first-run',
            '--no-default-browser-check',
            '--new-window',
        ]
        if profile_directory:
            args.append(f'--profile-directory={profile_directory}')
        args.append(self.url or 'about:blank')
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._endpoint_info(self.port):
                return True
            time.sleep(0.5)
        return False

    def _kill_own_profile_browser(self):
        """只结束"本程序专用目录"残留的浏览器进程，绝不动你日常的浏览器。"""
        if os.name != 'nt':
            return
        marker = self.profile_dir.replace("'", "''")
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='msedge.exe'\" | "
              "Where-Object { $_.CommandLine -like '*" + marker + "*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        try:
            subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                           capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW)
        except Exception:
            pass

    def _prepare_profile(self):
        """首次使用时，把日常浏览器的登录数据导入本程序专用目录。

        重要：**只在专用目录还没被使用过时才导入**，导入后无论成功与否都写下标记。
        否则"每次启动都重新导入"会把用户后来在专用窗口里登录的会话覆盖掉。
        """
        os.makedirs(self.profile_dir, exist_ok=True)
        marker = os.path.join(self.profile_dir, '.login-imported')
        used_before = os.path.exists(os.path.join(self.profile_dir, 'Default', 'Preferences'))

        def mark():
            try:
                with open(marker, 'w', encoding='utf-8') as f:
                    f.write('done')
            except Exception:
                pass

        if os.path.exists(marker) or used_before:
            # 这个专用目录已经用过了（可能用户已经在里面登录过），绝不覆盖
            if not os.path.exists(marker):
                mark()
            return

        exe, name = find_browser()
        src = browser_user_data_dir(exe) if exe else None
        if src and os.path.isdir(src):
            prof = last_used_profile(src)
            self.log(f'首次使用：正在尝试导入「{name}」的登录数据（配置文件 {prof}）…')
            try:
                clone_login_data(src, prof, self.profile_dir, log=self.log)
            except Exception as e:
                self.log(f'导入登录数据失败：{e}')
            self.log('说明：本地存储类的登录态（如 DeepSeek）可以带过来；'
                     'Cookie 类的（如 ChatGPT）受 Chrome「应用绑定加密」保护，无法迁移，'
                     '需要在这个窗口里登录一次，之后会一直记住。')
        else:
            self.log('未能定位日常浏览器配置目录，将使用全新配置（需要登录一次）。')
        mark()

    def _launch(self):
        exe, name = find_browser()
        if not exe:
            raise RuntimeError(
                '没有找到可用的浏览器。请安装 Microsoft Edge 或 Google Chrome 后重试。\n'
                '（Firefox 不支持调试协议，无法用于网页版翻译）')
        self.exe = exe
        self.browser_name = name

        # 注意（重要）：Chrome 136 起禁止在"默认数据目录"上开启调试端口，
        # 因此这里**只能**使用本程序自己的目录（非标准目录），
        # 并通过导入登录数据来免去重新登录。
        self._kill_own_profile_browser()
        self._prepare_profile()

        self.port = find_free_port(BROWSER_PORT)
        self.log(f'正在启动「{name}」（本程序专用窗口）…')
        if not self._launch_with(exe, self.profile_dir, 'Default', 30):
            raise RuntimeError(
                '浏览器调试端口没有就绪（超时）。\n'
                '常见原因：安全软件拦截、浏览器启动特别慢，或本程序专用目录被占用。\n'
                '可先双击「以调试模式启动浏览器.bat」看具体提示。\n'
                f'（端口 {self.port}；可手动访问 http://127.0.0.1:{self.port}/json/version 检查）')
        self.profile_mode = 'dedicated'
        self._save_state('')
        self.log(f'已启动「{name}」。')

    def _site_host(self):
        try:
            return self.url.split('//', 1)[1].split('/', 1)[0]
        except Exception:
            return ''

    def ensure_tab(self, force_new=False):
        """确保浏览器里有一个目标站点的标签页。

        - 已经开着该站点的标签页 -> 直接复用（不会开一堆重复标签页）
        - 没有 -> 新建一个标签页
        返回 targetId。
        """
        targets = (self._call('Target.getTargets').get('result') or {}).get('targetInfos') or []
        pages = [t for t in targets if t.get('type') == 'page']
        host = self._site_host()
        pick = None
        if not force_new:
            pick = next((t for t in pages if host and host in (t.get('url') or '')), None)
        if pick is not None:
            self.log('已复用浏览器里已打开的标签页。')
            return pick['targetId']
        created = self._call('Target.createTarget', {'url': self.url or 'about:blank'})
        tid = (created.get('result') or {}).get('targetId')
        if not tid:
            raise RuntimeError('无法新建标签页。')
        self.log(f'已在「{self.browser_name or "浏览器"}」中新开一个标签页。')
        time.sleep(1.5)
        return tid

    def bring_to_front(self):
        try:
            self._call('Page.bringToFront', timeout=10)
        except Exception:
            pass

    def _connect(self):
        info = None
        st = self._load_state()
        if st.get('port'):
            cand = self._endpoint_info(st['port'])
            if cand and cand.get('webSocketDebuggerUrl') == st.get('ws'):
                info = cand
        if info is None:
            info = self._endpoint_info(self.port)
        if not info:
            raise RuntimeError('无法读取浏览器调试信息。')
        ws_url = info.get('webSocketDebuggerUrl')
        if not ws_url:
            raise RuntimeError('浏览器未提供调试 WebSocket 地址。')
        self.ws = wsclient.WebSocketClient(ws_url, timeout=60)
        self.ws.connect()
        self._msg_id = 0
        tid = self.ensure_tab()
        att = self._call('Target.attachToTarget', {'targetId': tid, 'flatten': True})
        self.session_id = (att.get('result') or {}).get('sessionId')
        if not self.session_id:
            raise RuntimeError('无法附加到浏览器页面（attachToTarget 失败）。')
        self.target_id = tid
        self._save_state(ws_url)
        self.log('已连接浏览器调试协议。')

    def _pick_target(self):
        return self.ensure_tab()

    # ---------------- CDP 调用 ----------------
    def _call(self, method, params=None, timeout=30, browser=False):
        if self.ws is None:
            raise RuntimeError('浏览器尚未连接')
        self._msg_id += 1
        mid = self._msg_id
        msg = {'id': mid, 'method': method}
        if params:
            msg['params'] = params
        # 浏览器级域（Storage / Browser / Target）不能带 sessionId
        if self.session_id and not browser:
            msg['sessionId'] = self.session_id
        try:
            self.ws.send(json.dumps(msg), opcode=1)
        except Exception as e:
            self._reset()
            raise RuntimeError(f'向浏览器发送命令失败（{method}）：{e}')
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                _op, payload = self.ws.recv_message()
            except Exception as e:
                self._reset()
                raise RuntimeError(f'读取浏览器响应失败（{method}）：{e}')
            try:
                data = json.loads(payload.decode('utf-8', 'ignore'))
            except Exception:
                continue
            if data.get('id') == mid:
                if data.get('error'):
                    raise RuntimeError(f'浏览器返回错误（{method}）：{data["error"].get("message")}')
                return data
        raise RuntimeError(f'浏览器命令超时（{method}）')

    def _reset(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        self.ws = None
        self.session_id = None
        self.target_id = None

    # ---------------- 页面操作 ----------------
    def eval_js(self, expression, timeout=30, retries=3):
        last = None
        for _ in range(max(1, retries)):
            try:
                r = self._call('Runtime.evaluate', {
                    'expression': expression,
                    'returnByValue': True,
                    'awaitPromise': True,
                }, timeout=timeout)
                res = r.get('result') or {}
                if res.get('exceptionDetails'):
                    raise RuntimeError('页面脚本执行出错：' +
                                       str(res['exceptionDetails'].get('text'))[:200])
                return (res.get('result') or {}).get('value')
            except Exception as e:
                last = e
                msg = str(e)
                if 'Execution context was destroyed' in msg or 'Cannot find context' in msg:
                    time.sleep(1.0)
                    continue
                raise
        raise last

    def navigate(self, url):
        try:
            self._call('Page.navigate', {'url': url}, timeout=30)
        except Exception:
            pass
        time.sleep(2.0)

    def wait_input(self, timeout=40):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.eval_js(JS_FIND_INPUT, timeout=15, retries=1):
                    return True
            except Exception:
                pass
            time.sleep(1.5)
        return False

    def is_ready(self):
        try:
            self.ensure()
            return bool(self.eval_js(JS_FIND_INPUT, timeout=15, retries=1))
        except Exception:
            return False

    # ---------------- 翻译 ----------------
    # ---------------- 输入 / 发送（用浏览器原生输入事件，React 才认） ----------------
    def input_text(self):
        try:
            return str(self.eval_js(JS_INPUT_TEXT, timeout=15, retries=1) or '')
        except Exception:
            return ''

    def _focus_clear(self):
        try:
            return self.eval_js(JS_FOCUS_CLEAR, timeout=15, retries=1)
        except Exception:
            return ''

    def _press_enter(self):
        """发送真正的回车按键事件（比 JS 合成事件可靠得多）。"""
        base = {'key': 'Enter', 'code': 'Enter',
                'windowsVirtualKeyCode': 13, 'nativeVirtualKeyCode': 13}
        try:
            self._call('Input.dispatchKeyEvent', dict(base, type='rawKeyDown'), timeout=15)
            self._call('Input.dispatchKeyEvent', dict(base, type='char', text='\r'), timeout=15)
            self._call('Input.dispatchKeyEvent', dict(base, type='keyUp'), timeout=15)
            return True
        except Exception as e:
            self.log(f'发送回车失败：{e}')
            return False

    def _type_prompt(self, prompt):
        """先用 CDP 原生插入文本；失败再退回 JS 赋值。"""
        self._focus_clear()
        time.sleep(0.35)
        try:
            self._call('Input.insertText', {'text': prompt}, timeout=30)
            time.sleep(0.4)
            if self.input_text():
                return 'native'
        except Exception as e:
            self.log(f'原生输入失败，改用脚本输入：{e}')
        r = self.eval_js(JS_TYPE % json.dumps(prompt), timeout=20, retries=1)
        if r == 'NO_INPUT':
            raise RuntimeError('找不到输入框，无法输入文字。')
        time.sleep(0.4)
        return 'script'

    def _send_prompt(self):
        """确保消息真的发出去：回车 -> 点按钮 -> 再回车；用"输入框是否清空"判定。"""
        self._press_enter()
        time.sleep(1.0)
        if not self.input_text():
            return 'ENTER'
        try:
            r = self.eval_js(JS_SEND, timeout=15, retries=1)
        except Exception as e:
            r = f'ERR:{e}'
        time.sleep(1.0)
        if not self.input_text():
            return f'CLICK({r})'
        self._press_enter()
        time.sleep(1.2)
        if not self.input_text():
            return 'ENTER2'
        return 'FAILED'

    # ---------------- 翻译 ----------------
    def translate(self, prompt, timeout=240):
        self.ensure()
        try:
            cur = self.eval_js('location.href', timeout=15, retries=1) or ''
        except Exception:
            cur = ''
        host = self.url.split('//', 1)[1].split('/', 1)[0] if '//' in self.url else ''
        if host and host not in str(cur):
            self.log(f'正在打开 {self.url} …')
            self.navigate(self.url)
        if not self.wait_input(40):
            raise RuntimeError('网页端尚未登录，或页面结构变化（找不到输入框）。\n'
                               '请点「打开网页端登录」，在弹出的浏览器中登录后重试。')

        before = ''
        try:
            before = str(self.eval_js(JS_READ_LAST, timeout=15, retries=1) or '')
        except Exception:
            before = ''

        mode = self._type_prompt(prompt)
        sent = self._send_prompt()
        self.log(f'发送方式：输入={mode}，提交={sent}')
        if sent == 'FAILED':
            raise RuntimeError('消息没有发送出去（输入框仍非空）。\n'
                               '可能是网页端输入框结构变化，请把日志发我。')

        deadline = time.time() + timeout
        start = time.time()
        last = ''
        stable = 0
        last_log = time.time()
        while time.time() < deadline:
            time.sleep(1.2)
            if time.time() - last_log > 20:
                last_log = time.time()
                self.log(f'等待网页端回复中…（已 {int(time.time() - start)} 秒）')
            try:
                cur = str(self.eval_js(JS_READ_LAST, timeout=15, retries=1) or '').strip()
            except Exception:
                continue
            try:
                generating = bool(self.eval_js(JS_GENERATING, timeout=15, retries=1))
            except Exception:
                generating = False
            if cur and cur != before:
                if cur == last and not generating:
                    stable += 1
                    if stable >= 2:
                        return cur
                else:
                    stable = 0
                    last = cur
        if last:
            return last
        raise RuntimeError('等待网页端回复超时。\n'
                           '若网页端开着「深度思考 / 联网搜索」，回复会明显变慢，'
                           '建议在浏览器里把这两个开关关掉再试。')

    def close(self):
        self._reset()
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None
