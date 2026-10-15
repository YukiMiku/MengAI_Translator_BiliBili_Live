# -*- coding: utf-8 -*-
"""以「调试模式」单独启动浏览器（可以当成日常启动方式）。

为什么需要它：
    浏览器的调试通道只在启动那一刻生效，无法事后加到已经开着的浏览器上。
    所以如果你的浏览器是普通方式打开的，本程序看不到它、也就没法在它里面开标签页。

用法：
    双击 `以调试模式启动浏览器.bat` 运行本脚本，
    它会用你日常的浏览器配置（带登录状态）启动浏览器并打开调试通道。
    之后本程序就只是在这个浏览器里**新开 / 复用一个标签页**，
    不会再关闭你的浏览器，也不需要反复重启。
"""
import sys

from browser import BrowserSession, find_browser


def main():
    print('=' * 62)
    exe, name = find_browser()
    if not exe:
        print('没有找到可用的浏览器（需要 Microsoft Edge 或 Google Chrome）。')
        print('（Firefox 不支持调试协议）')
        return 1
    print(f'浏览器：{name}')
    print(f'路径　：{exe}')
    print('-' * 62)

    sess = BrowserSession('deepseek_web', log=lambda m: print('  ' + m))
    try:
        sess.ensure()
    except Exception as e:
        print()
        print('启动失败：')
        for line in str(e).splitlines():
            print('  ' + line)
        return 1

    print('-' * 62)
    print(f'已就绪：调试端口 {sess.port}，浏览器保持打开即可（可以最小化）。')
    print('之后在程序里点「打开网页端登录」或直接连接直播间，')
    print('程序只会在这个浏览器里新开 / 复用一个标签页，不会再关闭它。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
