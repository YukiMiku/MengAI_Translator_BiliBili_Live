# -*- coding: utf-8 -*-
"""环境自检：双击「诊断.bat」运行，用于排查无法启动的问题。

会检查 Python 版本、标准库、tkinter、工程文件、端口占用、数据目录写入权限。
"""
import os
import sys
import socket
import traceback
import importlib


def _setup_console():
    """让 Windows 控制台能正确显示中文（不依赖 .bat 里的 chcp）。"""
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


_setup_console()

HERE = os.path.dirname(os.path.abspath(__file__))
OK = '[OK]  '
BAD = '[FAIL]'


def line(title, ok, detail=''):
    print(f'{OK if ok else BAD} {title}' + (f'  -> {detail}' if detail else ''))
    return ok


def main():
    print('=' * 64)
    try:
        from version import APP_TITLE, APP_VERSION, APP_NAME, APP_NAME_JA, APP_NAME_EN
    except Exception:
        APP_TITLE, APP_VERSION = 'AI萌译酱', '?'
        APP_NAME, APP_NAME_JA = 'AI萌译酱', '萌AIちゃん'
        APP_NAME_EN = 'AI-MengYiJiang'
    print(f'{APP_TITLE}（日语界面：{APP_NAME_JA}）  环境自检')
    print('=' * 64)
    print('程序版本   :', APP_VERSION)
    print('Python 版本 :', sys.version.replace('\n', ' '))
    print('解释器路径 :', sys.executable)
    print('脚本目录   :', HERE)
    print('当前目录   :', os.getcwd())
    print('-' * 64)

    all_ok = True

    # 0. 目录名检查
    #    两种合法形态：
    #      · 源码/绿色版目录：名字里带版本号，如 AI萌译酱-v1.2.0
    #      · 便携版（自带运行时）目录：固定叫 AI萌译酱，不带版本号 —— 否则桌面快捷方式会随版本失效
    #    所以这里只要求"含产品名或版本号之一"，版本号本身一律以 version.py 为准。
    folder = os.path.basename(HERE.rstrip('\\/'))
    want_ver = f'v{APP_VERSION}'
    names = [APP_NAME, APP_NAME_JA, APP_NAME_EN]
    if want_ver in folder:
        line('目录名检查', True, f'{folder}  含版本号 {want_ver}')
    elif any(n and n in folder for n in names):
        line('目录名检查', True,
             f'{folder}  （固定名，不带版本号；当前版本 {APP_VERSION} 见 version.py 与窗口标题）')
    else:
        all_ok = False
        line('目录名检查', False,
             f'目录名是「{folder}」，既不含版本号「{want_ver}」也不含产品名之一'
             f'（{"/".join(n for n in names if n)}）')
    line('程序版本', True, f'{APP_VERSION}（{APP_TITLE}）')

    print('-' * 64)

    # 1. 标准库
    for mod in ['json', 'zlib', 'socket', 'ssl', 'threading', 'hashlib',
                'base64', 'struct', 'ctypes', 'csv', 'urllib.request',
                'http.server', 'tkinter']:
        try:
            importlib.import_module(mod)
            line(f'import {mod}', True)
        except Exception as e:
            all_ok = False
            line(f'import {mod}', False, repr(e))

    print('-' * 64)

    # 2. tkinter 可用性
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        r.destroy()
        line('创建 tkinter 窗口', True)
    except Exception as e:
        all_ok = False
        line('创建 tkinter 窗口', False, repr(e))
        print('    提示：Microsoft Store 版 Python 不带 tkinter，'
              '请改用 python.org 官方安装包并勾选 “tcl/tk and IDLE”。')

    print('-' * 64)

    # 2.5 拼音注音引擎（1.4.0：内嵌 pypinyin，放在 lib\ 下，离线可用）
    try:
        import pinyin as _pinyin
        if not _pinyin.available():
            all_ok = False
            line('拼音注音引擎（内嵌 pypinyin）', False,
                 f'不可用：{_pinyin.engine_error() or "未知原因"}；'
                 '请确认 lib\\pypinyin 完整（重新解压 zip）')
        else:
            _pinyin.warmup()
            demo = _pinyin.annotate_text('音乐 银行 小心心')
            good = ('yīn' in demo) and ('háng' in demo)
            if not good:
                all_ok = False
            line('拼音注音引擎（内嵌 pypinyin）', good, f'多音字示例：音乐 银行 -> {demo}')
            units = _pinyin.annotate('你好，世界！')
            ok_units = ''.join(u[0] for u in units) == '你好，世界！'
            if not ok_units:
                all_ok = False
            line('注音单元切分（逐字对齐用）', ok_units, f'{len(units)} 个单元')
            norm = _pinyin.normalize('xiao3 xin1 xin1')
            if norm != 'xiǎo xīn xīn':
                all_ok = False
            line('拼音声调归一化', norm == 'xiǎo xīn xīn', f'xiao3 xin1 xin1 -> {norm}')
    except Exception as e:
        all_ok = False
        line('拼音注音引擎（内嵌 pypinyin）', False, repr(e))
        traceback.print_exc()

    print('-' * 64)

    # 3. 工程文件
    #    必需文件：两种发布形态（源码版 / 便携版）都必须有
    for name in ['app.py', 'version.py', 'bili.py', 'providers.py', 'browser.py',
                 'storage.py', 'dockserver.py', 'pinyin.py',
                 'netutil.py', 'wsclient.py', 'public/dock.html', 'public/dock.js']:
        p = os.path.join(HERE, name.replace('/', os.sep))
        line(f'文件 {name}', os.path.isfile(p), '' if os.path.isfile(p) else '缺失！请重新完整解压 zip')

    #    pypinyin：注音功能的数据（1.4.0 起随包附带，不需要联网装）
    _py_dir = os.path.join(HERE, 'lib', 'pypinyin')
    line('拼音数据 lib\\pypinyin', os.path.isdir(_py_dir),
         '' if os.path.isdir(_py_dir) else '缺失！注音功能将不可用（重新解压 zip 即可）')

    #    可选文件：只在源码版里有意义（便携版自带运行时，不需要这些启动脚本）
    for name in ['launch_browser.py', 'start.bat', 'check.bat']:
        p = os.path.join(HERE, name.replace('/', os.sep))
        if os.path.isfile(p):
            line(f'文件 {name}', True, '（可选，已存在）')
        else:
            print(f'  [--]   文件 {name}  （可选，便携版不需要，跳过）')

    #    README：启动时弹窗要读它们。中文必需，日语缺了就自动退回中文
    for name, must in (('README.md', True), ('README.ja.md', False)):
        p = os.path.join(HERE, name)
        if os.path.isfile(p):
            line(f'文件 {name}', True, f'{os.path.getsize(p)} 字节')
        elif must:
            line(f'文件 {name}', False, '缺失！启动时的说明弹窗会没有内容')
        else:
            print(f'  [--]   文件 {name}  （可选，缺失时弹窗自动显示中文版）')

    print('-' * 64)

    # 4. 导入本项目模块
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    os.chdir(HERE)
    for mod in ['netutil', 'wsclient', 'storage', 'version', 'providers', 'browser', 'bili',
                'dockserver', 'pinyin']:
        try:
            importlib.import_module(mod)
            line(f'导入 {mod}', True)
        except Exception as e:
            all_ok = False
            line(f'导入 {mod}', False, repr(e))
            traceback.print_exc()

    # 5. 数据目录可写
    try:
        data = os.path.join(HERE, 'data')
        os.makedirs(data, exist_ok=True)
        probe = os.path.join(data, '_write_test.tmp')
        with open(probe, 'w', encoding='utf-8') as f:
            f.write('ok')
        os.remove(probe)
        line('data 目录可写', True, data)
    except Exception as e:
        all_ok = False
        line('data 目录可写', False, repr(e))

    # 6. 停靠端口（只做提示，不算失败）
    #    真实停靠服务是 ThreadingHTTPServer（自带 allow_reuse_address），
    #    实测即使端口上有残留监听，它依然能正常绑定并返回 200，
    #    所以"已有实例在跑"或"上次留下的 TIME_WAIT"都不影响本次启动。
    listening = False
    try:
        _c = socket.create_connection(('127.0.0.1', 17890), timeout=0.8)
        _c.close()
        listening = True
    except Exception:
        listening = False
    if listening:
        line('端口 17890 已有服务在监听', True,
             '可能是本程序已开着一个，或上次运行的残留。不影响启动；'
             '若 OBS 停靠页异常，先关掉旧的程序窗口再重开。')
    else:
        try:
            s = socket.socket()
            s.settimeout(1)
            s.bind(('127.0.0.1', 17890))
            s.close()
            line('端口 17890 可用', True)
        except Exception:
            line('端口 17890 暂时不可绑定', True,
                 '多为上次运行的 TIME_WAIT 残留，稍后会自动释放；不影响主窗口。')

    print('-' * 64)

    # 7. 网页版（DeepSeek / ChatGPT）：直接使用系统浏览器，不需要安装任何组件
    try:
        from browser import find_browser
        exe, name = find_browser()
    except Exception as e:
        exe, name = None, f'检测失败：{e}'
    if exe:
        line('网页版可用（直接使用系统浏览器）', True, f'{name}  ->  {exe}')
    else:
        all_ok = False
        line('未找到 Edge / Chrome，网页版不可用', False,
             '请安装 Microsoft Edge 或 Google Chrome（Firefox 不支持调试协议）')

    print('-' * 64)
    if getattr(sys, 'frozen', False):
        # 免安装 exe 版：exe 本身就是启动器
        how = '可以双击「萌AIちゃん.exe」'
    elif os.path.isfile(os.path.join(HERE, 'launch.bat')):
        how = '可以双击「launch.bat」（或桌面快捷方式）'
    elif os.path.isfile(os.path.join(HERE, 'start.bat')):
        how = '可以双击「start.bat」'
    else:
        how = '可以用 python app.py 启动'
    if getattr(sys, 'frozen', False):
        # 免安装 exe 版：exe 本身就是启动器
        how = '可以双击「萌AIちゃん.exe」'
    elif os.path.isfile(os.path.join(HERE, 'launch.bat')):
        how = '可以双击「launch.bat」（或桌面快捷方式）'
    elif os.path.isfile(os.path.join(HERE, 'start.bat')):
        how = '可以双击「start.bat」'
    else:
        how = '可以用 python app.py 启动'
    print('自检结果：', f'全部通过，{how}' if all_ok
          else '存在失败项，请把上面的内容截图反馈。')
    print('=' * 64)
    return 0 if all_ok else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        input('按回车键退出...')
        sys.exit(1)
