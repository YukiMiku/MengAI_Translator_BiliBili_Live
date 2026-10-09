# -*- coding: utf-8 -*-
"""AI萌译酱（日语界面：萌AIちゃん）—— 桌面窗口版。

放弃浏览器操作页面，改用 tkinter 桌面窗口；同时内置一个精简 OBS 停靠服务。
主要功能：实时弹幕抓取（未开播也能连）、API / 网页端翻译、本地词库（多词库 + 预设关联）、
打开/导入本地词库文件。行为约定：连接后只抓取实时弹幕，不读取历史弹幕。

版本号统一由 version.py 提供，切勿在别处硬编码。
"""
import os
import re
import sys
import time
import base64
import shutil
import traceback
import queue
import hashlib
import threading
import subprocess
import webbrowser
from datetime import datetime


def _setup_console():
    """让 Windows 控制台能正确显示中文（不依赖 .bat 里的 chcp，避免批处理被切碎）。"""
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


def _set_console_title(title):
    """设置控制台标题。.bat 必须保持纯 ASCII，所以中文标题只能由 Python 写。"""
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(str(title))
    except Exception:
        pass


_setup_console()

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
    TK_IMPORT_ERROR = ''
except Exception as _e:  # 常见于 Microsoft Store 版 Python（不带 tkinter）
    tk = None
    ttk = filedialog = messagebox = scrolledtext = simpledialog = None
    TK_IMPORT_ERROR = str(_e)

import netutil
import storage                      # 用于安装"配置写入失败"回调（见 _on_config_save_error）
import pinyin as Pinyin          # 1.4.0：拼音注音引擎（内嵌 pypinyin，见 lib/）
from storage import (APP_DIR, DATA_DIR, load_config, save_config, get_api_key, get_preset_api_key,
                     protect_text, resolve_glossary_path, load_glossary_file, save_glossary_file,
                     export_glossary, merge_glossary, DEFAULT_SYSTEM_PROMPT_ZH, DEFAULT_SYSTEM_PROMPT_JA,
                     BILI_COOKIE_FILE, BILI_COOKIE_TEMPLATE, load_bili_cookie,
                     ensure_bili_cookie_template,
                     preset_dir, preset_file_path, list_presets, load_preset_file,
                     save_preset_file, delete_preset_file, migrate_presets_from_config)
from providers import (PROVIDERS, provider_label, is_japanese, call_provider,
                       create_browser_session, WEB_PROVIDERS)
from browser import find_browser
from bili import DanmakuClient, verify_bili_cookie
from dockserver import DockServer
from version import APP_NAME, APP_VERSION, APP_TITLE, APP_NAME_JA, app_title

DOCK_PORT = 17890
PUBLIC_DIR = os.path.join(APP_DIR, 'public')
ERROR_LOG = os.path.join(APP_DIR, '启动错误.txt')

I18N = {
    'zh': {
        'title': 'AI萌译酱 弹幕翻译',
        'tab_connect': '连接', 'tab_translate': '翻译服务', 'tab_glossary': '词库', 'tab_presets': '预设',
        'tab_appearance': '外观',
        'themeLabel': '窗口配色', 'themeHint': '可选 白色 / 黑色 / 蓝色 / 粉色，切换后立即生效并保存。',
        'bgImageLabel': '弹幕区背景图片',
        'bgScaleLabel': '背景图缩放',
        'bgOpacityLabel': '背景图不透明度',
        'bgOffsetXLabel': '背景图水平位置',
        'bgOffsetYLabel': '背景图垂直位置',
        'bgReset': '恢复默认（缩放/透明度/位置）',
        'bgFit': '适应弹幕区',
        'glossFieldSource': '中文（原词）',
        'glossFieldTarget': '日语（译法）',
        'glossFieldPinyin': '拼音（可选，只用于注音；可写 xiao3 或 xiǎo）',
        'glossFieldNote': '备注',
        'bgPick': '选择图片', 'bgClear': '清除图片',
        'pillowInstall': '安装 / 修复 Pillow（支持 JPG）',
        'bgImageHint': '背景图固定在弹幕区（不随弹幕滚动），文字显示在其上方。\n'
                       '透明 PNG 的透明部分会露出弹幕区底色，不会变成黑底。\n'
                       '缩放 100% = 正好铺满；位置 0% = 居中，可用水平/垂直滑块微调。\n'
                       'Tk 原生只支持 PNG / GIF；装了 Pillow 还支持 JPG/WEBP 并能平滑缩放。',
        'pinyinSection': '拼音注音',
        'giftTitle': '礼物',
        'giftFilterFree': '过滤免费礼物（银瓜子）',
        'pinyinShow': '在弹幕原文上方显示拼音注音',
        'fontRawLabel': '原文字号',
        'fontPinyinLabel': '注音字号',
        'fontTransLabel': '译文字号',
        'fontHint': '三个字号会自动钳制为「原文 > 注音 ≥ 译文」。开启注音后换行由程序计算，一行能放的汉字约减少到 1/2～1/3。',
        'appearanceNote': '提示：浅色背景图配「白色 / 粉色」，深色背景图配「黑色 / 蓝色」，文字会更清晰。',
        'room_label': '直播间', 'room_hint': '输入 B 站房间号', 'connect': '连接', 'disconnect': '断开',
        'roomLabelShort': '房间', 'searchLabel': '搜索', 'logToggle': '日志', 'settingsToggle': '设置',
        'connectTabNote': '未开播也能连接。连接后只抓取实时弹幕，不读取历史弹幕。',
        'biliLoginTitle': 'B 站登录（可选，用于解决昵称打码）',
        'biliOpenFile': '打开 cookie 文件',
        'biliLoad': '载入并验证',
        'biliClear': '清除登录信息',
        'biliLoginHint': '只需要一个 SESSDATA：复制它 → 点「打开 cookie 文件」粘进去 → 「载入并验证」。\n'
                         'bili_jct / DedeUserID 都不用填（uid 程序会自己调 nav 接口取）。\n'
                         '不登录时，B 站可能把昵称返回成「首字***」且 uid=0。\n'
                         '⚠ 该文件等同于账号凭证，请不要分享给任何人。',
        'biliNotSet': '未配置登录信息（可能出现昵称打码）',
        'biliSetUid': '已读取 cookie：uid={uid}（尚未验证）',
        'biliSetSess': '已读取 SESSDATA（尚未验证，uid 会在连接时自动获取）',
        'maskWarn': '⚠ 检测到 {n} 条弹幕的昵称被 B 站打码（显示为「首字***」、uid=0）。',
        'maskWarnLogged': ' 已配置登录信息，若仍打码请检查 cookie 是否失效。',
        'test': '测试弹幕', 'clear': '清空弹幕记录', 'status_disconnected': '未连接',
        'provider_label': '翻译服务', 'base_url_label': 'API Base URL', 'model_label': 'Model',
        'api_key_label': 'API Key', 'api_key_hint_empty': '留空则保持原密钥', 'prompt_label': 'System Prompt',
        'concurrency_label': '并发翻译', 'cache_label': '开启翻译缓存', 'save': '保存设置',
        'web_login': '打开网页端登录',
        'web_hint': '网页版使用本程序专用的浏览器窗口（Chrome 136+ 已禁止在"默认配置"上开调试端口）。DeepSeek 的登录态在本地存储里、会被自动带过来；ChatGPT 的登录态是加密 Cookie，Chrome 不允许迁移——在窗口里登录一次即可，之后会一直记住。',
        'web_state_ok': '网页端浏览器：{b}', 'web_state_missing': '未找到 Edge / Chrome，网页版不可用',
        'key_configured': '● API Key 已加密保存在本机', 'key_missing': '○ 尚未保存 API Key',
        'glossary_open': '打开词库文件', 'glossary_import': '导入词库文件', 'glossary_export': '导出词库',
        'glossary_new': '新建词库', 'glossary_current': '当前词库（可与预设一一对应）',
        'glossary_new_prompt': '请输入新词库名称（会保存在 data 目录下）：',
        'glossary_exists': '词库「{n}」已存在，切换到它吗？',
        'glossary_new_note': '不同场景可用不同词库：建立词库后点「保存预设」，预设会记住当前词库；以后读取预设会自动切回对应词库。',
        'glossary_add': '添加', 'glossary_del': '删除选中', 'glossary_source': '原词', 'glossary_target': '日语译法',
        'glossary_note': '备注', 'glossary_pinyin': '拼音（注音）',
        'glossary_hint': '每行「原词 => 译法 | 拼音 # 备注」。拼音只用于弹幕注音显示，不参与翻译；“打开”用记事本/默认程序编辑；“导入”支持 TXT/CSV/JSON。',
        'preset_name': '预设名称', 'preset_save': '保存预设', 'preset_load': '读取预设', 'preset_delete': '删除预设',
        'preset_none': '— 选择预设 —', 'preset_hint': '预设会一并保存翻译服务、地址、模型、提示词、并发/缓存、API Key，以及关联的词库文件与外观、拼音、礼物设置。',
        'preset_export': '导出到文件', 'preset_import': '从文件导入',
        'preset_open_dir': '打开预设文件夹',
        'preset_dir_hint': '预设以「一个预设一个 .json 文件」保存在上面这个 data/presets/ 目录里。备份、或换版本后想快速导入旧预设，直接把这个文件夹拷过去即可。',
        'msg_preset_exported': '预设已导出。',
        'msg_preset_imported': '预设已导入：{n}',
        'msg_confirm_overwrite': '已存在同名预设「{n}」，覆盖它吗？',
        'msg_preset_broken': '这个预设文件读不出来：{n}',
        'msg_preset_migrated': '已把 {n} 个旧预设迁移到 data/presets/（以后预设就是独立文件了）。',
        'dock_copy': '复制停靠链接', 'dock_open': '打开停靠页', 'dock_hint': 'OBS：视图 → 停靠窗口 → 自定义浏览器停靠窗口。',
        'metrics_pop': '人气', 'metrics_queue': '翻译队列', 'metrics_clients': '监控客户端',
        'metrics_live': '开播状态', 'live_on': '直播中', 'live_off': '未开播', 'live_round': '轮播中',
        'metrics_provider': '当前翻译服务',
        'feed_time': '时间', 'feed_user': '用户', 'feed_raw': '原文', 'feed_trans': '翻译',
        'feedTitle': '弹幕',
        'pending': '翻译中…', 'waiting': '待翻译',
        'msg_saved': '设置已保存到本地', 'msg_connected': '已连接', 'msg_disconnected': '已断开',
        'msg_need_room': '请填写房间号', 'msg_need_preset': '请先选择预设', 'msg_need_name': '请输入预设名称',
        'msg_preset_saved': '预设已保存', 'msg_preset_loaded': '预设已读取', 'msg_preset_deleted': '预设已删除',
        'msg_confirm_delete': '确定删除这个预设吗？', 'msg_confirm_clear': '清空当前弹幕记录？',
        'msg_import_ok': '词库导入完成', 'msg_need_term': '原词和日语译法都不能为空',
        'lang_btn': '日本語',
        # ---- 启动时显示 README ----
        'readmeOpen': '说明',
        'readmeTitle': '使用说明（README）',
        'readmeClose': '关闭',
        'readmeNoMore': '不再自动显示',
        'readmeMissing': '（没找到 README 文件。请确认 README.md / README.ja.md 与程序在同一目录）',
        'readmeHint': '下次仍可从顶部「说明」按钮打开。',
    },
    'ja': {
        'title': '萌AIちゃん コメント翻訳',
        'tab_connect': '接続', 'tab_translate': '翻訳サービス', 'tab_glossary': '用語集', 'tab_presets': 'プリセット',
        'tab_appearance': '外観',
        'themeLabel': 'ウィンドウ配色', 'themeHint': 'ホワイト / ブラック / ブルー / ピンク から選択。即時反映され保存されます。',
        'bgImageLabel': 'コメント欄の背景画像',
        'bgScaleLabel': '背景画像の拡大率',
        'bgOpacityLabel': '背景画像の不透明度',
        'bgOffsetXLabel': '背景画像の水平位置',
        'bgOffsetYLabel': '背景画像の垂直位置',
        'bgReset': '初期値に戻す（拡大率/透明度/位置）',
        'bgFit': 'コメント欄に合わせる',
        'glossFieldSource': '中国語（元の語）',
        'glossFieldTarget': '日本語（訳）',
        'glossFieldPinyin': 'ピンイン（任意・ルビ表示のみ／xiao3 でも xiǎo でも可）',
        'glossFieldNote': 'メモ',
        'bgPick': '画像を選択', 'bgClear': '画像を消去',
        'pillowInstall': 'Pillow を導入 / 修復（JPG 対応）',
        'bgImageHint': '背景画像はコメント欄に固定され（スクロールしても動きません）、文字はその上に描画されます。\n'
                       '透過 PNG の透明部分はコメント欄の地色が出ます（黒くはなりません）。\n'
                       '拡大率 100% = ちょうど全面、位置 0% = 中央。水平/垂直スライダーで微調整できます。\n'
                       'Tk 標準は PNG / GIF のみ。Pillow を入れると JPG/WEBP も可能になり、滑らかに拡大縮小します。',
        'pinyinSection': 'ピンインルビ',
        'giftTitle': 'ギフト',
        'giftFilterFree': '無料ギフト（銀瓜子）を除外',
        'pinyinShow': 'コメント原文の上にピンインを表示する',
        'fontRawLabel': '原文の文字サイズ',
        'fontPinyinLabel': 'ルビの文字サイズ',
        'fontTransLabel': '訳文の文字サイズ',
        'fontHint': '3 つのサイズは自動的に「原文 > ルビ ≥ 訳文」に調整されます。ルビを表示すると 1 行に入る漢字は 1/2〜1/3 程度になります。',
        'appearanceNote': 'ヒント：明るい背景画像には「ホワイト / ピンク」、暗い背景画像には「ブラック / ブルー」が読みやすいです。',
        'room_label': '配信ルーム', 'room_hint': 'B 站ルームIDを入力', 'connect': '接続', 'disconnect': '切断',
        'roomLabelShort': 'ルーム', 'searchLabel': '検索', 'logToggle': 'ログ', 'settingsToggle': '設定',
        'connectTabNote': '未配信でも接続できます。接続後はリアルタイムのコメントのみ取得します。',
        'biliLoginTitle': 'B 站ログイン（任意・ユーザー名の伏せ字対策）',
        'biliOpenFile': 'cookie ファイルを開く',
        'biliLoad': '読み込んで確認',
        'biliClear': 'ログイン情報を消去',
        'biliLoginHint': 'SESSDATA ひとつでOK：「cookie ファイルを開く」に貼って「読み込んで確認」を押すだけ。\n'
                         'bili_jct / DedeUserID は不要です（uid は nav 接口から自動取得します）。\n'
                         '未ログインの場合、B 站はユーザー名を「頭文字***」に伏せ、uid を 0 で返すことがあります。\n'
                         '⚠ このファイルはアカウント資格情報そのものです。他人に渡さないでください。',
        'biliNotSet': 'ログイン情報なし（名前が伏せ字になる可能性があります）',
        'biliSetUid': 'cookie 読み込み済み：uid={uid}（未確認）',
        'biliSetSess': 'SESSDATA 読み込み済み（未確認。uid は接続時に自動取得します）',
        'maskWarn': '⚠ {n} 件のコメントでユーザー名が伏せ字（「頭文字***」・uid=0）になっています。',
        'maskWarnLogged': ' ログイン情報は設定済みです。まだ伏せ字なら cookie の有効期限を確認してください。',
        'test': 'テストコメント', 'clear': 'コメント履歴を消去', 'status_disconnected': '未接続',
        'provider_label': '翻訳サービス', 'base_url_label': 'API Base URL', 'model_label': 'モデル',
        'api_key_label': 'API キー', 'api_key_hint_empty': '空なら既存キーを維持', 'prompt_label': 'システムプロンプト',
        'concurrency_label': '同時翻訳数', 'cache_label': '翻訳キャッシュを有効化', 'save': '設定を保存',
        'web_login': 'Web版を開いてログイン',
        'web_hint': 'Web版は本プログラム専用のブラウザウィンドウを使います（Chrome 136+ では既定プロファイルでのデバッグが禁止）。DeepSeek のログイン情報はローカルストレージにあり自動で引き継げますが、ChatGPT は暗号化 Cookie のため引き継げません。一度だけログインしてください（以後は記憶されます）。',
        'web_state_ok': 'Web版ブラウザ：{b}', 'web_state_missing': 'Edge / Chrome が見つかりません',
        'key_configured': '● API キーは本機に暗号化保存済み', 'key_missing': '○ API キー未保存',
        'glossary_open': '用語集ファイルを開く', 'glossary_import': '用語集をインポート', 'glossary_export': '用語集をエクスポート',
        'glossary_new': '用語集を新規作成', 'glossary_current': '現在の用語集（プリセットと対応可）',
        'glossary_new_prompt': '新しい用語集の名前を入力してください（data フォルダに作成されます）：',
        'glossary_exists': '用語集「{n}」は既にあります。切り替えますか？',
        'glossary_new_note': '場面ごとに用語集を分けられます：作成後に「プリセット保存」すると、プリセットが現在の用語集を覚え、次回の読み込みで自動的に切り替わります。',
        'glossary_add': '追加', 'glossary_del': '選択を削除', 'glossary_source': '元の語', 'glossary_target': '日本語訳',
        'glossary_note': '備考', 'glossary_pinyin': 'ピンイン（ルビ）',
        'glossary_hint': '各行「元の語 => 日本語訳 | ピンイン # 備考」。ピンインはルビ表示のみに使われ、翻訳には使われません。「開く」はメモ帳/既定プログラムで編集。「インポート」は TXT/CSV/JSON 対応。',
        'preset_name': 'プリセット名', 'preset_save': 'プリセット保存', 'preset_load': 'プリセット読込', 'preset_delete': 'プリセット削除',
        'preset_none': '— プリセット選択 —', 'preset_hint': 'プリセットは翻訳サービス・URL・モデル・プロンプト・並列/キャッシュ・API キー・関連する用語集ファイルに加え、外観・ルビ・ギフトの設定も保存します。',
        'preset_export': 'ファイルへ書き出し', 'preset_import': 'ファイルから読み込み',
        'preset_open_dir': 'プリセットフォルダを開く',
        'preset_dir_hint': 'プリセットは「1 件 = 1 つの .json ファイル」として上の data/presets/ に保存されます。バックアップや、バージョンを変えたあとに旧プリセットを読み込みたいときは、このフォルダをそのままコピーするだけで済みます。',
        'msg_preset_exported': 'プリセットを書き出しました。',
        'msg_preset_imported': 'プリセットを読み込みました：{n}',
        'msg_confirm_overwrite': '同名のプリセット「{n}」があります。上書きしますか？',
        'msg_preset_broken': 'このプリセットファイルを読めません：{n}',
        'msg_preset_migrated': '{n} 件の旧プリセットを data/presets/ へ移行しました（今後プリセットは独立ファイルです）。',
        'dock_copy': 'ドックURLをコピー', 'dock_open': 'ドックを開く', 'dock_hint': 'OBS：表示 → ドック → カスタムブラウザドック。',
        'metrics_pop': '人気', 'metrics_queue': '翻訳キュー', 'metrics_clients': '監視クライアント',
        'metrics_live': '配信状態', 'live_on': '配信中', 'live_off': '未配信', 'live_round': 'リピート中',
        'metrics_provider': '現在の翻訳サービス',
        'feed_time': '時刻', 'feed_user': 'ユーザー', 'feed_raw': '原文', 'feed_trans': '翻訳',
        'feedTitle': 'コメント',
        'pending': '翻訳中…', 'waiting': '翻訳待ち',
        'msg_saved': '設定を保存しました', 'msg_connected': '接続済み', 'msg_disconnected': '切断済み',
        'msg_need_room': 'ルームIDを入力してください', 'msg_need_preset': 'プリセットを選択してください', 'msg_need_name': 'プリセット名を入力してください',
        'msg_preset_saved': 'プリセットを保存しました', 'msg_preset_loaded': 'プリセットを読み込みました', 'msg_preset_deleted': 'プリセットを削除しました',
        'msg_confirm_delete': 'このプリセットを削除しますか？', 'msg_confirm_clear': 'コメント履歴を消去しますか？',
        'msg_import_ok': '用語集をインポートしました', 'msg_need_term': '元の語と日本語訳は必須です',
        'lang_btn': '中文',
        # ---- 起動時に README を表示 ----
        'readmeOpen': '説明',
        'readmeTitle': '取扱説明（README）',
        'readmeClose': '閉じる',
        'readmeNoMore': '次回から自動表示しない',
        'readmeMissing': '（README ファイルが見つかりません。README.md / README.ja.md が本体と同じ場所にあるか確認してください）',
        'readmeHint': '次回以降も上部の「説明」ボタンから開けます。',
    },
}


# 四套预设配色（可在「外观」页切换）
THEMES = {
    'black': {
        'name': '黑色', 'name_ja': 'ブラック',
        'bg': '#0f1116', 'panel': '#161a22', 'border': '#242a35',
        'fg': '#e7ebf2', 'muted': '#8b93a3', 'field': '#10141b',
        'btn': '#212836', 'btn_hover': '#2b3446',
        'accent': '#4f6ef7', 'accent_hover': '#6380ff',
        'danger': '#6f2a33', 'danger_hover': '#8c3540',
        'ok': '#3ddc97', 'warn': '#f2b45c', 'err': '#ff7b7b',
        'raw': '#eef2f8', 'trans': '#8fd0ff', 'meta': '#7d8798', 'hl': '#4a3d1f',
        'log_bg': '#0b0e13',
    },
    'white': {
        'name': '白色', 'name_ja': 'ホワイト',
        'bg': '#f2f4f8', 'panel': '#ffffff', 'border': '#d7dde7',
        'fg': '#1b2430', 'muted': '#6a7686', 'field': '#ffffff',
        'btn': '#e6ebf3', 'btn_hover': '#d9e0ea',
        'accent': '#3b62f6', 'accent_hover': '#5179ff',
        'danger': '#b8362a', 'danger_hover': '#cf4436',
        'ok': '#12a06a', 'warn': '#a9741a', 'err': '#c0392b',
        'raw': '#1b2430', 'trans': '#1f5fd0', 'meta': '#8b95a4', 'hl': '#ffe9a8',
        'log_bg': '#eaeef4',
    },
    'blue': {
        'name': '蓝色', 'name_ja': 'ブルー',
        'bg': '#08182a', 'panel': '#0f2439', 'border': '#1c3a5b',
        'fg': '#e2eefc', 'muted': '#8cadd2', 'field': '#0d2035',
        'btn': '#16314d', 'btn_hover': '#1e4063',
        'accent': '#3d8bfd', 'accent_hover': '#5aa0ff',
        'danger': '#6b2f3a', 'danger_hover': '#8a3d4b',
        'ok': '#4cd6a4', 'warn': '#f0c05a', 'err': '#ff8f8f',
        'raw': '#eaf3ff', 'trans': '#7fd4ff', 'meta': '#7fa2c8', 'hl': '#1d4a72',
        'log_bg': '#06121f',
    },
    'pink': {
        'name': '粉色', 'name_ja': 'ピンク',
        'bg': '#fdf1f6', 'panel': '#ffffff', 'border': '#f2d0dd',
        'fg': '#3a2230', 'muted': '#9d7c8b', 'field': '#ffffff',
        'btn': '#f8dee8', 'btn_hover': '#f1cdda',
        'accent': '#e0568f', 'accent_hover': '#ef6fa3',
        'danger': '#b8362a', 'danger_hover': '#cf4436',
        'ok': '#12a06a', 'warn': '#a9741a', 'err': '#c0392b',
        'raw': '#3a2230', 'trans': '#c2417a', 'meta': '#ab8e9c', 'hl': '#ffe0ee',
        'log_bg': '#fbe9f1',
    },
}
THEME_ORDER = ['white', 'black', 'blue', 'pink']
DEFAULT_THEME = 'black'

# 当前生效的配色：切换主题时整体替换这个字典，所有 THEME['x'] 引用会自动取到新值
THEME = dict(THEMES[DEFAULT_THEME])

# 弹幕区字体
# 1.4.0：raw / pinyin / trans 三个字号可由「外观」标签页调整，
# 关系固定为「原文 > 注音 >= 译文」，由 apply_feed_fonts() 统一钳制。
FEED_FONTS = {
    'meta': ('Microsoft YaHei UI', 8),
    'pinyin': ('Microsoft YaHei UI', 11),
    'raw': ('Microsoft YaHei UI', 13),
    'trans': ('Microsoft YaHei UI', 10),
    'pending': ('Microsoft YaHei UI', 9),
    'err': ('Microsoft YaHei UI', 9),
}


def apply_feed_fonts(cfg):
    """按配置刷新弹幕区字号，返回 (原文, 注音, 译文) 实际生效值。"""
    def size(key, default, lo=6, hi=40):
        try:
            v = int(cfg.get(key, default))
        except Exception:
            v = default
        return max(lo, min(hi, v))

    raw = size('feed_font_raw', 13)
    py = max(6, min(raw - 1, size('feed_font_pinyin', 11)))
    trans = max(6, min(py, size('feed_font_trans', 10)))
    FEED_FONTS['raw'] = ('Microsoft YaHei UI', raw)
    FEED_FONTS['pinyin'] = ('Microsoft YaHei UI', py)
    FEED_FONTS['trans'] = ('Microsoft YaHei UI', trans)
    return raw, py, trans


class ColorScale(tk.Canvas):
    """自绘滑轨。

    ttk.Scale 的槽与滑块由系统主题决定，在深色/彩色预设下几乎看不见，
    所以这里完全自己画：槽用 field 色 + border 描边，已选部分与滑块用强调色，
    四套配色下都清晰可见。支持点击跳转、拖动、滚轮微调。
    """

    PAD = 10          # 两端留白（半个滑块）
    TROUGH_H = 8      # 槽的粗细
    HANDLE_R = 8      # 滑块半径

    def __init__(self, master, from_, to, value=0, step=1, command=None, height=24, **kw):
        super().__init__(master, height=height, bd=0, highlightthickness=0,
                         takefocus=0, **kw)
        self.from_ = float(from_)
        self.to = float(to)
        self.step = max(1, int(step))
        self.command = command
        self.value = self._clamp(value)
        self._drag = False
        self.colors = {
            'trough': '#10141b', 'border': '#242a35',
            'accent': '#4f6ef7', 'accent_hover': '#6380ff', 'fg': '#e7eef7',
        }
        self.bind('<Configure>', lambda e: self._redraw())
        self.bind('<Button-1>', self._on_press)
        self.bind('<B1-Motion>', self._on_drag)
        self.bind('<ButtonRelease-1>', self._on_release)
        self.bind('<MouseWheel>', self._on_wheel)

    # ---- 颜色 ----
    def apply_colors(self, c):
        self.colors = {
            'trough': c.get('field', '#10141b'),
            'border': c.get('border', '#242a35'),
            'accent': c.get('accent', '#4f6ef7'),
            'accent_hover': c.get('accent_hover', '#6380ff'),
            'fg': c.get('fg', '#ffffff'),
        }
        try:
            self.configure(bg=c.get('bg'))
        except Exception:
            pass
        self._redraw()

    # ---- 取值 / 设值 ----
    def _clamp(self, v):
        try:
            v = float(v)
        except Exception:
            v = self.from_
        return max(self.from_, min(self.to, v))

    def get(self):
        return self.value

    def set(self, value, fire=True):
        v = self._clamp(value)
        v = round(v / self.step) * self.step
        changed = (v != self.value)
        self.value = v
        self._redraw()
        if fire and changed and self.command:
            try:
                self.command(v)
            except Exception:
                pass

    # ---- 坐标换算 ----
    def _usable(self):
        return max(1, self.winfo_width() - 2 * self.PAD)

    def _x_of(self, v):
        r = (self._clamp(v) - self.from_) / max(1e-9, (self.to - self.from_))
        return self.PAD + r * self._usable()

    def _value_of(self, x):
        r = (float(x) - self.PAD) / self._usable()
        r = max(0.0, min(1.0, r))
        return self.from_ + r * (self.to - self.from_)

    # ---- 绘制 ----
    def _redraw(self):
        try:
            self.delete('all')
        except Exception:
            return
        c = self.colors
        w = max(1, self.winfo_width())
        cy = max(1, self.winfo_height()) // 2
        pad = self.PAD
        x = self._x_of(self.value)
        th = self.TROUGH_H
        r = self.HANDLE_R
        try:
            # 槽（底色 + 描边）
            self.create_line(pad, cy, w - pad, cy, width=th + 2,
                             fill=c['border'], capstyle='round')
            self.create_line(pad, cy, w - pad, cy, width=th,
                             fill=c['trough'], capstyle='round')
            # 已选部分
            if x > pad + 1:
                self.create_line(pad, cy, x, cy, width=th,
                                 fill=c['accent'], capstyle='round')
            # 滑块
            self.create_oval(x - r, cy - r, x + r, cy + r,
                             fill=c['accent_hover'] if self._drag else c['accent'],
                             outline=c['fg'], width=2)
        except Exception:
            pass

    # ---- 交互 ----
    def _set_from_event(self, event):
        v = self._value_of(event.x)
        v = round(v / self.step) * self.step
        v = self._clamp(v)
        changed = (v != self.value)
        self.value = v
        self._redraw()
        if changed and self.command:
            try:
                self.command(v)
            except Exception:
                pass

    def _on_press(self, event):
        self._drag = True
        self.focus_set()
        self._set_from_event(event)

    def _on_drag(self, event):
        if self._drag:
            self._set_from_event(event)

    def _on_release(self, event):
        self._drag = False
        self._redraw()
        if self.command:
            try:
                self.command(self.value)
            except Exception:
                pass

    def _on_wheel(self, event):
        self.set(self.value + (self.step if event.delta > 0 else -self.step))


class App:
    def __init__(self, root):
        self.root = root
        self.lang = 'ja'
        self.cfg = load_config()
        # 配置写不进去（文件被占用 / 无写权限）时只警告、不打断主流程。
        # 免安装版没有控制台，所以提示要走到日志面板上。
        self._config_err_reported = set()
        self._pending_config_error = None
        try:
            storage.config_save_hook = self._on_config_save_error
        except Exception:
            pass
        # 1.4.1：预设改为独立文件（data/presets/*.json），把旧 config.json 里的迁移出来。
        # 只迁一次，且不覆盖已有同名文件。
        self._preset_migrated = 0
        try:
            self._preset_migrated = migrate_presets_from_config(self.cfg) or 0
        except Exception:
            self._preset_migrated = 0
        # 默认日语（便携版整条链路以日语为默认）；只有明确存过 'zh' 才用中文
        self.lang = 'zh' if self.cfg.get('ui_language') == 'zh' else 'ja'
        self.glossary = []
        self.messages = {}
        self.msg_order = []          # 弹幕顺序（用于裁剪与重排）
        self.feed_items = {}         # 弹幕 id -> {'meta':id, 'raw':[(拼音项,汉字项)…], 'trans':id, 'ruby':bool}
        # 1.4.0：礼物栏（不限条数、重启清空；文字不翻译，但保留拼音注音）
        self.gifts = []
        self.gift_rows = {}          # batch_combo_id -> gifts 下标（只保留最近若干个）
        self.gift_count_var = tk.StringVar(value='')
        self.gift_filter_var = tk.BooleanVar(value=False)
        self._gift_query = ''        # 回溯查询词（普通字符串，HTTP 线程要读）
        # 礼物栏跟随滚动：粘性标志 + 节流（避免每条礼物都做一次 yview/see）
        self._gift_sticky = True
        self._gift_follow_at = 0.0
        self._gift_follow_job = None
        # 礼物栏分批重画（5 万条时分批，避免界面僵住）
        self._gift_render_job = None
        self._gift_render_gen = None
        # 增量维护的计数：避免每收一条礼物就全量重算（否则整体变成 O(n²)）
        self.gift_shown = 0          # 当前显示的条数
        self.gift_free = 0           # 免费礼物总数
        self.cache = {}
        self.gui_queue = queue.Queue()
        self.pending = queue.Queue()
        self.pump_lock = threading.Lock()
        self.active = 0
        self.web_sessions = {}
        self._web_queue = queue.Queue()
        self._web_thread = None
        self._web_error_warned = False
        self.danmaku = None
        self.closing = False
        self._bg_source = ''
        self._bg_photo = None
        self._bg_item = None
        self._bg_job = None
        self._cfg_job = None
        self._bg_slider_job = None
        self._readme_win = None
        self._wrap_labels = []
        # B 站登录（文件层面 cookie）
        self.bili_cookie = ''
        self.bili_jar = {}
        self._bili_user = None
        self.bili_file_var = None
        self.mask_count = 0

        # 应用保存的配色（必须在建界面之前，因为控件创建时会读 THEME）
        global THEME
        _tk = self.cfg.get('theme')
        THEME = dict(THEMES.get(_tk if _tk in THEMES else DEFAULT_THEME, THEMES[DEFAULT_THEME]))
        # 1.4.0：弹幕区字号（原文 > 注音 >= 译文）+ 后台预热拼音引擎
        apply_feed_fonts(self.cfg)
        Pinyin.warmup()

        self.dock = DockServer(DOCK_PORT, PUBLIC_DIR)
        self.dock.language = self.lang
        # 1.4.0：停靠页显示设置 + 礼物回溯数据源
        self.dock.gift_provider = self._dock_gifts
        self.dock.settings = self._dock_settings()

        self._build_ui()
        self._load_glossary()
        self._refresh_glossary_files()
        self._refresh_presets()
        if getattr(self, '_preset_migrated', 0):
            self._log(self.t('msg_preset_migrated').format(n=self._preset_migrated))
        self._apply_language()
        self._load_config_to_ui()
        self._refresh_bili_state()
        self._apply_bg_image()

        try:
            self.dock.start()
        except Exception as e:
            self._log(f'停靠服务启动失败：{e}')

        self.root.after(100, self._poll)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self._maybe_show_readme()

    # ------------------------------------------------------- 启动时显示 README
    def _readme_path(self, lang):
        name = 'README.ja.md' if str(lang).lower().startswith('ja') else 'README.md'
        return os.path.join(APP_DIR, name)

    def _read_readme_text(self, lang):
        """按语言读 README；日语缺失时退回中文，都没有则返回 None。"""
        for cand in (self._readme_path(lang), self._readme_path('zh')):
            try:
                with open(cand, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
            except Exception:
                continue
        return None

    def _maybe_show_readme(self):
        """版本变化时自动弹一次 README；用户点过「不再自动显示」就永不再弹。"""
        if self.cfg.get('readme_disabled'):
            return
        if str(self.cfg.get('readme_seen_version') or '') == APP_VERSION:
            return
        self.root.after(700, lambda: self._show_readme(auto=True))

    def _show_readme(self, auto=False):
        """弹出 README 窗口：可滚动、可中/日切换、可关闭或不再显示。"""
        if getattr(self, '_readme_win', None) is not None:
            try:
                self._readme_win.lift()
                self._readme_win.focus_force()
                return
            except Exception:
                self._readme_win = None

        C = THEME
        win = tk.Toplevel(self.root)
        self._readme_win = win
        win.title(self.t('readmeTitle'))
        win.configure(bg=C['bg'])
        win.geometry('860x680')
        win.minsize(560, 420)
        try:
            win.transient(self.root)
        except Exception:
            pass

        # ---- 顶栏：语言切换 + 版本 ----
        top = tk.Frame(win, bg=C['panel'])
        top.pack(fill='x', side='top')
        lab = tk.Label(top, text=self.t('readmeTitle'), bg=C['panel'], fg=C['fg'],
                       font=('Microsoft YaHei UI', 11, 'bold'))
        lab.pack(side='left', padx=12, pady=8)
        ver = tk.Label(top, text=f'v{APP_VERSION}', bg=C['panel'], fg=C['muted'],
                       font=('Consolas', 9))
        ver.pack(side='left')

        body = {'text': None, 'lang': self.lang}

        def render(lang=None):
            if lang:
                body['lang'] = lang
            txt = body['text']
            if txt is None:
                return
            txt.configure(state='normal')
            txt.delete('1.0', 'end')
            content = self._read_readme_text(body['lang'])
            if content is None:
                txt.insert('end', self.t('readmeMissing'), 'quote')
            else:
                self._render_markdown(txt, content)
            txt.configure(state='disabled')
            txt.yview_moveto(0)
            for key, b in lang_btns.items():
                active = (key == body['lang'])
                try:
                    b.configure(relief='sunken' if active else 'raised',
                                bg=C['accent'] if active else C['field'],
                                fg='#ffffff' if active else C['fg'])
                except Exception:
                    pass

        def set_lang(lang):
            render(lang)

        lang_btns = {}
        for key, label in (('ja', '日本語'), ('zh', '中文')):
            b = tk.Button(top, text=label, command=lambda k=key: set_lang(k),
                          font=('Microsoft YaHei UI', 9), bd=1, relief='raised',
                          bg=C['field'], fg=C['fg'], activebackground=C['accent'],
                          activeforeground='#ffffff', cursor='hand2', padx=12, pady=2)
            b.pack(side='right', padx=(4, 10), pady=6)
            lang_btns[key] = b

        # ---- 正文：可滚动文本框 ----
        wrap = tk.Frame(win, bg=C['bg'])
        wrap.pack(fill='both', expand=True, padx=10, pady=(8, 4))
        sb = ttk.Scrollbar(wrap, orient='vertical')
        sb.pack(side='right', fill='y')
        txt = tk.Text(wrap, wrap='word', bd=0, highlightthickness=0,
                      bg=C['panel'], fg=C['fg'], insertbackground=C['fg'],
                      font=('Microsoft YaHei UI', 10), padx=14, pady=10,
                      spacing1=1, spacing3=2, yscrollcommand=sb.set, cursor='arrow')
        txt.pack(side='left', fill='both', expand=True)
        sb.configure(command=txt.yview)
        body['text'] = txt

        base = ('Microsoft YaHei UI', 10)
        mono = ('Consolas', 9)
        # 注意：Text 的 tag 用 foreground/background，不是控件的 fg/bg
        txt.tag_configure('h1', font=('Microsoft YaHei UI', 16, 'bold'), foreground=C['accent'],
                          spacing1=10, spacing3=8)
        txt.tag_configure('h2', font=('Microsoft YaHei UI', 13, 'bold'), foreground=C['accent'],
                          spacing1=12, spacing3=6)
        txt.tag_configure('h3', font=('Microsoft YaHei UI', 11, 'bold'), foreground=C['fg'],
                          spacing1=8, spacing3=4)
        txt.tag_configure('h4', font=('Microsoft YaHei UI', 10, 'bold'), foreground=C['muted'],
                          spacing1=6, spacing3=3)
        txt.tag_configure('body', font=base, foreground=C['fg'], lmargin1=2, lmargin2=2)
        txt.tag_configure('bullet', font=base, foreground=C['fg'], lmargin1=18, lmargin2=30)
        txt.tag_configure('quote', font=('Microsoft YaHei UI', 9), foreground=C['muted'],
                          lmargin1=18, lmargin2=18, spacing1=2)
        txt.tag_configure('code', font=mono, foreground=C['fg'], background=C['field'],
                          lmargin1=18, lmargin2=18)
        txt.tag_configure('table', font=mono, foreground=C['fg'], lmargin1=2, lmargin2=2)
        txt.tag_configure('hr', font=('', 1), spacing1=6, spacing3=6)

        # ---- 底栏 ----
        bot = tk.Frame(win, bg=C['bg'])
        bot.pack(fill='x', side='bottom')
        hint = tk.Label(bot, text=self.t('readmeHint'), bg=C['bg'], fg=C['muted'],
                        font=('Microsoft YaHei UI', 8))
        hint.pack(side='left', padx=12, pady=8)

        def do_no_more():
            self.cfg['readme_disabled'] = True
            self.cfg['readme_seen_version'] = APP_VERSION
            try:
                save_config(self.cfg)
            except Exception:
                pass
            self._close_readme()

        def do_close():
            # 关掉就算看过了，下次同版本不再自动弹
            self.cfg['readme_seen_version'] = APP_VERSION
            try:
                save_config(self.cfg)
            except Exception:
                pass
            self._close_readme()

        ttk.Button(bot, text=self.t('readmeNoMore'), command=do_no_more).pack(
            side='right', padx=(6, 12), pady=8)
        ttk.Button(bot, text=self.t('readmeClose'), command=do_close,
                   style='Accent.TButton').pack(side='right', pady=8)

        win.protocol('WM_DELETE_WINDOW', do_close)
        try:
            win.bind('<Escape>', lambda e: do_close())
        except Exception:
            pass

        render(body['lang'])

        # 居中到主窗口
        try:
            win.update_idletasks()
            px, py = self.root.winfo_rootx(), self.root.winfo_rooty()
            pw, ph = self.root.winfo_width(), self.root.winfo_height()
            w, h = win.winfo_width(), win.winfo_height()
            win.geometry(f'+{max(0, px + (pw - w) // 2)}+{max(0, py + (ph - h) // 3)}')
        except Exception:
            pass
        win.lift()

    def _close_readme(self):
        win = getattr(self, '_readme_win', None)
        self._readme_win = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    @staticmethod
    def _render_markdown(widget, text):
        """把 README 的 markdown 粗渲染进 Text（标题/列表/引用/代码块/表格分别上色）。"""
        in_code = False
        for raw in str(text).replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            line = raw.rstrip()
            if line.strip().startswith('```'):
                in_code = not in_code
                continue
            if in_code:
                widget.insert('end', line + '\n', 'code')
                continue
            s = line.strip()
            if not s:
                widget.insert('end', '\n')
                continue
            if set(s) <= set('-*_=') and len(s) >= 3:
                widget.insert('end', '─' * 60 + '\n', 'hr')
                continue
            if s.startswith('#### '):
                widget.insert('end', App._inline(s[5:]) + '\n', 'h4')
            elif s.startswith('### '):
                widget.insert('end', App._inline(s[4:]) + '\n', 'h3')
            elif s.startswith('## '):
                widget.insert('end', App._inline(s[3:]) + '\n', 'h2')
            elif s.startswith('# '):
                widget.insert('end', App._inline(s[2:]) + '\n', 'h1')
            elif s.startswith('> '):
                widget.insert('end', App._inline(s[2:]) + '\n', 'quote')
            elif s.startswith('>'):
                widget.insert('end', '\n', 'quote')
            elif s.startswith('- ') or s.startswith('* '):
                widget.insert('end', '  • ' + App._inline(s[2:]) + '\n', 'bullet')
            elif s.startswith('|'):
                widget.insert('end', App._inline(s) + '\n', 'table')
            elif s[:2].isdigit() or (s[:3].isdigit() and s[3:5] in ('. ', '．')):
                widget.insert('end', '  ' + App._inline(s) + '\n', 'bullet')
            else:
                widget.insert('end', App._inline(s) + '\n', 'body')

    @staticmethod
    def _inline(s):
        """去掉行内 markdown 记号，让纯文本更好读。"""
        s = s.replace('**', '').replace('`', '')
        # [文字](链接) -> 文字（链接）
        out = []
        i = 0
        while i < len(s):
            if s[i] == '[':
                j = s.find(']', i)
                k = s.find('(', j) if j >= 0 else -1
                if j > 0 and k > 0:
                    m = s.find(')', k)
                    if m > 0:
                        out.append(f'{s[i + 1:j]}（{s[k + 1:m]}）')
                        i = m + 1
                        continue
            out.append(s[i])
            i += 1
        return ''.join(out)

    # ------------------------------------------------------------------ UI
    # 深色主题：参照 LAPLACE Chat 控制台的观感（深底 + 靛蓝强调色 + 译文紧跟原文下方）
    def _apply_theme(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass
        C = THEME
        self.root.configure(bg=C['bg'])
        style.configure('.', background=C['bg'], foreground=C['fg'],
                        fieldbackground=C['field'], bordercolor=C['border'],
                        lightcolor=C['panel'], darkcolor=C['bg'], troughcolor=C['bg'])
        style.configure('TFrame', background=C['bg'])
        style.configure('Panel.TFrame', background=C['panel'])
        style.configure('Bar.TFrame', background=C['bg'])
        style.configure('TLabel', background=C['bg'], foreground=C['fg'])
        style.configure('Head.TLabel', background=C['bg'], foreground=C['muted'], font=('', 9))
        style.configure('Metric.TLabel', background=C['bg'], foreground=C['fg'], font=('', 10, 'bold'))
        style.configure('Panel.TLabel', background=C['panel'], foreground=C['fg'])
        style.configure('PanelMuted.TLabel', background=C['panel'], foreground=C['muted'], font=('', 9))
        style.configure('PanelHead.TLabel', background=C['panel'], foreground=C['fg'], font=('', 10, 'bold'))
        style.configure('TButton', background=C['btn'], foreground=C['fg'], borderwidth=0,
                        focusthickness=0, focuscolor=C['btn'], padding=(10, 5))
        style.map('TButton',
                  background=[('active', C['btn_hover']), ('disabled', C['panel'])],
                  foreground=[('disabled', C['muted'])])
        style.configure('Accent.TButton', background=C['accent'], foreground='#ffffff')
        style.map('Accent.TButton', background=[('active', C['accent_hover'])],
                  foreground=[('disabled', C['muted'])])
        style.configure('Danger.TButton', background=C['danger'], foreground='#ffffff')
        style.map('Danger.TButton', background=[('active', C['danger_hover'])])
        style.configure('Small.TButton', padding=(7, 3))
        style.configure('TEntry', fieldbackground=C['field'], foreground=C['fg'],
                        insertcolor=C['fg'], borderwidth=0, padding=5)
        style.map('TEntry', fieldbackground=[('readonly', C['field'])])
        style.configure('TCombobox', fieldbackground=C['field'], background=C['btn'],
                        foreground=C['fg'], arrowcolor=C['muted'], borderwidth=0, padding=4)
        style.map('TCombobox',
                  fieldbackground=[('readonly', C['field'])],
                  foreground=[('readonly', C['fg'])],
                  background=[('active', C['btn_hover'])])
        style.configure('TCheckbutton', background=C['bg'], foreground=C['fg'], focuscolor=C['bg'])
        style.map('TCheckbutton', background=[('active', C['bg'])])
        style.configure('Panel.TCheckbutton', background=C['panel'], foreground=C['fg'], focuscolor=C['panel'])
        style.map('Panel.TCheckbutton', background=[('active', C['panel'])])
        style.configure('TSpinbox', fieldbackground=C['field'], foreground=C['fg'],
                        arrowcolor=C['muted'], borderwidth=0)
        style.configure('TNotebook', background=C['bg'], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure('TNotebook.Tab', background=C['bg'], foreground=C['muted'],
                        padding=(11, 7), borderwidth=0)
        style.map('TNotebook.Tab', background=[('selected', C['panel'])],
                  foreground=[('selected', C['fg'])])
        style.configure('Treeview', background=C['panel'], fieldbackground=C['panel'],
                        foreground=C['fg'], borderwidth=0, rowheight=24)
        style.map('Treeview', background=[('selected', C['accent'])], foreground=[('selected', '#ffffff')])
        style.configure('Treeview.Heading', background=C['bg'], foreground=C['muted'],
                        borderwidth=0, relief='flat', padding=4)
        style.configure('Vertical.TScrollbar', background=C['panel'], troughcolor=C['bg'],
                        bordercolor=C['bg'], arrowcolor=C['muted'], borderwidth=0)
        style.configure('Sash', background=C['border'], sashthickness=6, gripcount=0)
        self.root.option_add('*TCombobox*Listbox.background', C['panel'])
        self.root.option_add('*TCombobox*Listbox.foreground', C['fg'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', C['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')

        # 非 ttk 控件（Text / Canvas / Label）需要手动上色
        panes = getattr(self, 'panes', None)
        if panes is not None:
            panes.configure(bg=C['bg'])
        feed = getattr(self, 'feed', None)
        if feed is not None:
            feed.configure(bg=C['panel'])
        logt = getattr(self, 'log_text', None)
        if logt is not None:
            logt.configure(bg=C['log_bg'], fg=C['muted'], insertbackground=C['fg'])
        dot = getattr(self, 'dot', None)
        if dot is not None:
            dot.configure(bg=C['bg'])
        # 自绘滑轨要手动换色（ttk 样式管不到 Canvas）
        for attr in ('bg_scale', 'bg_opacity', 'bg_ox', 'bg_oy'):
            sl = getattr(self, attr, None)
            if sl is not None:
                try:
                    sl.apply_colors(C)
                except Exception:
                    pass

    def _btn(self, parent, key, cmd, style=None, side='left', pad=(0, 0), width=None):
        b = ttk.Button(parent, text='', command=cmd, style=style or 'TButton')
        if width:
            b.configure(width=width)
        b.pack(side=side, padx=pad)
        setattr(b, '_i18n', key)
        return b

    def _metric(self, parent, key, var):
        f = ttk.Frame(parent, style='Bar.TFrame')
        f.pack(side='left', padx=(0, 14))
        lbl = ttk.Label(f, text='', style='Head.TLabel')
        lbl.pack(side='left')
        setattr(lbl, '_i18n', key)
        ttk.Label(f, textvariable=var, style='Metric.TLabel').pack(side='left', padx=(5, 0))
        return lbl

    def _build_ui(self):
        self.root.title(app_title(self.lang))
        # 1.4.0：小屏（如 1366x768）上原来固定 1320x820 会把右侧设置面板挤出屏幕，
        # 那里正好放着新的「拼音注音 / 字号」控件，所以按屏幕尺寸夹一下。
        try:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            _w = min(1320, max(900, sw - 40))
            _h = min(820, max(560, sh - 90))
        except Exception:
            _w, _h = 1320, 820
        self.root.geometry(f'{_w}x{_h}')
        self.root.minsize(1060, 660)
        self._apply_theme()

        self.pop_var = tk.StringVar(value='0')
        self.queue_var = tk.StringVar(value='0')
        self.clients_var = tk.StringVar(value='0')
        self.live_var = tk.StringVar(value='—')
        self.provider_metric_var = tk.StringVar(value='—')
        self.status_var = tk.StringVar(value='未连接')
        self.search_var = tk.StringVar()
        self.feed_count_var = tk.StringVar(value='')

        # ===================== 顶部工具栏 =====================
        bar = ttk.Frame(self.root, style='Bar.TFrame')
        bar.pack(fill='x', padx=12, pady=(10, 8))

        self.toolbar_room_label = ttk.Label(bar, text='', style='Head.TLabel')
        self.toolbar_room_label.pack(side='left')
        setattr(self.toolbar_room_label, '_i18n', 'roomLabelShort')

        self.room_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.room_var, width=11).pack(side='left', padx=(6, 6))
        self.btn_connect = self._btn(bar, 'connect', self._connect, 'Accent.TButton')
        self.btn_disconnect = self._btn(bar, 'disconnect', self._disconnect, pad=(6, 0))
        self.btn_test = self._btn(bar, 'test', self._test, pad=(6, 0))
        self.btn_clear = self._btn(bar, 'clear', self._clear, pad=(6, 0))

        st = ttk.Frame(bar, style='Bar.TFrame')
        st.pack(side='left', padx=(12, 0))
        self.dot = tk.Label(st, text='●', fg='#5b6273', bg=THEME['bg'], font=('', 10))
        self.dot.pack(side='left')
        ttk.Label(st, textvariable=self.status_var, style='Head.TLabel').pack(side='left', padx=(4, 0))

        # 右侧：搜索 + 面板开关
        self.btn_log = self._btn(bar, 'logToggle', self._toggle_log, 'Small.TButton', side='right', pad=(6, 0))
        self.btn_settings = self._btn(bar, 'settingsToggle', self._toggle_settings, 'Small.TButton',
                                      side='right', pad=(6, 0))
        self.btn_lang = self._btn(bar, 'lang_btn', self._toggle_lang, 'Small.TButton', side='right', pad=(6, 0))
        self.btn_readme = self._btn(bar, 'readmeOpen', self._show_readme,
                                    'Small.TButton', side='right', pad=(6, 0))
        self.search_entry = ttk.Entry(bar, textvariable=self.search_var, width=16)
        self.search_entry.pack(side='right', padx=(0, 6))
        self.search_entry.bind('<KeyRelease>', lambda e: self._feed_rerender())
        self.toolbar_search_label = ttk.Label(bar, text='', style='Head.TLabel')
        self.toolbar_search_label.pack(side='right')
        setattr(self.toolbar_search_label, '_i18n', 'searchLabel')

        # 指标行
        metros = ttk.Frame(self.root, style='Bar.TFrame')
        metros.pack(fill='x', padx=12, pady=(0, 8))
        self.metric_0 = self._metric(metros, 'metrics_live', self.live_var)
        self.metric_1 = self._metric(metros, 'metrics_provider', self.provider_metric_var)
        self.metric_2 = self._metric(metros, 'metrics_pop', self.pop_var)
        self.metric_3 = self._metric(metros, 'metrics_queue', self.queue_var)
        self.metric_4 = self._metric(metros, 'metrics_clients', self.clients_var)

        # 打码提示横幅（只在检测到打码时出现）
        self.mask_bar = ttk.Frame(self.root, style='Bar.TFrame')
        self.mask_var = tk.StringVar(value='')
        self.mask_label = tk.Label(self.mask_bar, textvariable=self.mask_var, bg=THEME['warn'],
                                   fg='#1b1b1b', font=('Microsoft YaHei UI', 9), padx=10, pady=4,
                                   anchor='w', justify='left')
        self.mask_label.pack(side='left', fill='x', expand=True)
        self.btn_mask_fix = tk.Button(self.mask_bar, text='去登录', command=self._goto_bili_login,
                                      bg=THEME['accent'], fg='#ffffff', bd=0, padx=12, pady=3,
                                      activebackground=THEME['accent_hover'], activeforeground='#ffffff',
                                      font=('Microsoft YaHei UI', 9), cursor='hand2')
        self.btn_mask_fix.pack(side='right')

        # ===================== 主体：可拖拽双栏 =====================
        self.panes = tk.PanedWindow(self.root, orient='horizontal', bg=THEME['bg'],
                                    sashwidth=6, sashrelief='flat', bd=0,
                                    showhandle=False, opaqueresize=True)
        self.panes.pack(fill='both', expand=True, padx=12, pady=(0, 8))

        self._build_feed_panel()
        self._settings_visible = True
        self._settings_width = 384
        self._build_settings_panel()

        # ===================== 底部日志 =====================
        self.log_frame = ttk.Frame(self.root, style='Bar.TFrame')
        self.log_frame.pack(fill='x', padx=12, pady=(0, 6))
        self.log_text = tk.Text(self.log_frame, height=5, bg='#0b0e13', fg=THEME['muted'],
                                bd=0, highlightthickness=0, padx=10, pady=6,
                                font=('Consolas', 9), wrap='none')
        lsb = ttk.Scrollbar(self.log_frame, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lsb.set, state='disabled')
        lsb.pack(side='right', fill='y')
        self.log_text.pack(side='left', fill='both', expand=True)

    def _build_feed_panel(self):
        """弹幕区：用 Canvas 绘制，这样才能在文字后面垫一张自定义背景图。"""
        C = THEME
        left = ttk.Frame(self.panes, style='Panel.TFrame')
        self.panes.add(left, minsize=460, stretch='always')

        head = ttk.Frame(left, style='Panel.TFrame')
        head.pack(fill='x')
        self.feed_title = ttk.Label(head, text='', style='PanelHead.TLabel')
        self.feed_title.pack(side='left', padx=(12, 8), pady=8)
        setattr(self.feed_title, '_i18n', 'feedTitle')
        ttk.Label(head, textvariable=self.feed_count_var, style='PanelMuted.TLabel').pack(side='left')

        # 1.4.0：下半部分划给礼物栏，中间的分隔条可以拖动
        body = tk.PanedWindow(left, orient='vertical', bg=C['panel'], bd=0,
                              sashwidth=5, sashrelief='flat', showhandle=False)
        body.pack(fill='both', expand=True)
        top = ttk.Frame(body, style='Panel.TFrame')
        body.add(top, minsize=160, stretch='always')

        self.feed = tk.Canvas(top, bd=0, highlightthickness=0, bg=C['panel'], takefocus=1)
        self.feed_sb = ttk.Scrollbar(top, orient='vertical', command=self._feed_yview)
        self.feed.configure(yscrollcommand=self.feed_sb.set)
        self.feed_sb.pack(side='right', fill='y')
        self.feed.pack(side='left', fill='both', expand=True)
        self.feed.bind('<Configure>', self._on_feed_configure)
        self.feed.bind('<MouseWheel>', self._on_feed_wheel)
        self.feed.bind('<Prior>', lambda e: self._feed_scroll(-1))
        self.feed.bind('<Next>', lambda e: self._feed_scroll(1))

        self._feed_h = 0.0
        self._msg_y = {}
        self._msg_h = {}

        self._build_gift_panel(body)

    def _build_gift_panel(self, parent):
        """礼物栏（1.4.0）：在弹幕区下部，文字**不翻译**，但保留拼音注音。"""
        C = THEME
        box = ttk.Frame(parent, style='Panel.TFrame')
        parent.add(box, minsize=90, stretch='never')
        try:
            parent.paneconfigure(box, height=int(self.cfg.get('gift_pane_height') or 170))
        except Exception:
            pass

        head = ttk.Frame(box, style='Panel.TFrame')
        head.pack(fill='x')
        self.gift_title = ttk.Label(head, text='', style='PanelHead.TLabel')
        self.gift_title.pack(side='left', padx=(12, 8), pady=(5, 3))
        setattr(self.gift_title, '_i18n', 'giftTitle')
        ttk.Label(head, textvariable=self.gift_count_var, style='PanelMuted.TLabel').pack(side='left')
        # 回溯查询：按 用户名 / 礼物名 过滤（不限条数时用来翻历史）
        self.gift_search_var = tk.StringVar()
        ent = ttk.Entry(head, textvariable=self.gift_search_var, width=18)
        ent.pack(side='right', padx=(0, 12))
        ent.bind('<KeyRelease>', self._on_gift_search)
        # 免费礼物过滤（默认不过滤，对小主播友好）
        self.chk_gift_free = ttk.Checkbutton(head, text='', variable=self.gift_filter_var,
                                             command=self._on_gift_filter_change)
        self.chk_gift_free.pack(side='right', padx=(0, 10))
        setattr(self.chk_gift_free, '_i18n', 'giftFilterFree')

        wrap = ttk.Frame(box, style='Panel.TFrame')
        wrap.pack(fill='both', expand=True)
        self.gift_text = tk.Text(wrap, bd=0, highlightthickness=0, wrap='word',
                                 bg=C['panel'], fg=C['fg'], padx=12, pady=2,
                                 font=FEED_FONTS['trans'], state='disabled',
                                 cursor='arrow')
        gsb = ttk.Scrollbar(wrap, orient='vertical', command=self.gift_text.yview)
        self.gift_text.configure(yscrollcommand=gsb.set)
        gsb.pack(side='right', fill='y')
        self.gift_text.pack(side='left', fill='both', expand=True)
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            try:
                self.gift_text.bind(seq, self._gift_on_wheel, add='+')
            except Exception:
                pass
        self._apply_gift_fonts()

    def _apply_gift_fonts(self):
        """礼物栏的字体标签（改字号 / 换配色后重新配置，不用重建内容）。"""
        C = THEME
        t = self.gift_text
        t.configure(font=FEED_FONTS['trans'], bg=C['panel'], fg=C['fg'])
        t.tag_configure('meta', font=FEED_FONTS['meta'], foreground=C['meta'])
        t.tag_configure('pinyin', font=FEED_FONTS['pinyin'], foreground=self._pinyin_color())
        t.tag_configure('gift', font=FEED_FONTS['raw'], foreground=C['raw'])
        t.tag_configure('num', font=FEED_FONTS['pinyin'], foreground=C['trans'])
        t.tag_configure('hit', background=C.get('field') or C['panel'])

    def _build_settings_panel(self):
        self.settings_pane = ttk.Frame(self.panes, style='TFrame')
        self.panes.add(self.settings_pane, minsize=320, width=self._settings_width, stretch='never')
        # 面板宽度变化时（拖动分隔条 / 缩放窗口）让说明文字重新换行
        self.settings_pane.bind('<Configure>', self._reflow_wraplabels)
        self.nb = ttk.Notebook(self.settings_pane)
        self.nb.pack(fill='both', expand=True)

        self.tab_connect = ttk.Frame(self.nb)
        self.tab_translate = ttk.Frame(self.nb)
        self.tab_glossary = ttk.Frame(self.nb)
        self.tab_presets = ttk.Frame(self.nb)
        self.tab_appearance = ttk.Frame(self.nb)
        self.nb.add(self.tab_connect, text='连接')
        self.nb.add(self.tab_translate, text='翻译服务')
        self.nb.add(self.tab_glossary, text='词库')
        self.nb.add(self.tab_presets, text='预设')
        self.nb.add(self.tab_appearance, text='外观')

        self._build_connect_tab()
        self._build_translate_tab()
        self._build_glossary_tab()
        self._build_presets_tab()
        self._build_appearance_tab()

    def _toggle_settings(self):
        if getattr(self, '_settings_visible', True):
            try:
                self._settings_width = self.settings_pane.winfo_width() or self._settings_width
            except Exception:
                pass
            self.panes.forget(self.settings_pane)
            self._settings_visible = False
        else:
            self.panes.add(self.settings_pane, minsize=320, width=self._settings_width, stretch='never')
            self._settings_visible = True

    def _goto_bili_login(self):
        """点横幅上的按钮：切到「连接」页并打开 cookie 文件。"""
        try:
            self.nb.select(self.tab_connect)
            if not self._settings_visible:
                self._toggle_settings()
        except Exception:
            pass
        self._bili_open_cookie_file()

    def _update_mask_bar(self):
        """按当前打码条数显示/隐藏横幅。"""
        try:
            if self.mask_count > 0:
                tip = self.t('maskWarn').format(n=self.mask_count)
                if self.bili_cookie:
                    tip += self.t('maskWarnLogged')
                self.mask_var.set(tip)
                # 用 winfo_manager 判断是否已布局（winfo_ismapped 在窗口未映射时会误判）
                if not self.mask_bar.winfo_manager():
                    self.mask_bar.pack(fill='x', padx=12, pady=(0, 8), before=self.panes)
            else:
                if self.mask_bar.winfo_manager():
                    self.mask_bar.pack_forget()
        except Exception:
            pass

    def _toggle_log(self):
        if self.log_frame.winfo_manager():
            self.log_frame.pack_forget()
        else:
            self.log_frame.pack(fill='x', padx=12, pady=(0, 6))

    def _label(self, parent, text_key, **kw):
        l = ttk.Label(parent, text='')
        l.pack(**kw)
        setattr(l, '_i18n', text_key)
        self._wrap_labels.append(l)      # 参与"随窗口宽度自动换行"
        return l

    def _wrap_label(self, label):
        """把用 textvariable 的说明性标签也纳入自动换行。"""
        try:
            self._wrap_labels.append(label)
        except Exception:
            pass
        return label

    def _reflow_wraplabels(self, event=None):
        """按设置面板的当前宽度，重设所有说明文字的换行宽度。

        - 覆盖面板内**全部** ttk.Label（含用 textvariable 的状态/提示标签）
        - 只有换行宽度真的变化时才 configure，避免 <Configure> 自激
        """
        try:
            width = self.settings_pane.winfo_width()
        except Exception:
            return
        if width is None or width <= 40:
            return
        want = max(120, width - 36)
        for w in self._all_widgets(self.settings_pane):
            if not isinstance(w, ttk.Label):
                continue
            try:
                cur = w.cget('wraplength')
                cur = int(cur) if str(cur).strip() else 0
            except Exception:
                cur = -1
            if cur == want:
                continue
            try:
                w.configure(wraplength=want, justify='left')
            except Exception:
                pass

    def _scroll_tab(self, tab):
        """把标签页内容放进可滚动容器（1.4.0）。

        设置项越加越多，小屏（如 1366x768）上「翻译服务 / 词库 / 外观」的
        内容高度会超过 Notebook 的可用高度，导致底部控件点不到。这里统一
        加一层 Canvas + 滚动条，内容超高时即可滚动。
        """
        outer = ttk.Frame(tab)
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, bd=0, highlightthickness=0,
                           bg=THEME.get('bg') or THEME.get('panel'))
        sb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _sync(_e=None):
            try:
                canvas.configure(scrollregion=canvas.bbox('all'))
                canvas.itemconfigure(win, width=canvas.winfo_width())
            except Exception:
                pass

        def _wheel(e):
            try:
                canvas.yview_scroll(-2 if e.delta > 0 else 2, 'units')
            except Exception:
                pass
            return 'break'

        inner.bind('<Configure>', _sync)
        canvas.bind('<Configure>', _sync)
        canvas.bind('<MouseWheel>', _wheel)
        inner.bind('<MouseWheel>', _wheel)
        canvas.after(120, _sync)      # 首次布局完成后再同步一次宽度
        return inner

    def _build_connect_tab(self):
        p = self.tab_connect
        pad = {'padx': 10, 'pady': 6, 'fill': 'x'}
        self._label(p, 'room_label').pack(anchor='w', padx=10, pady=(12, 0))
        self.room_entry = ttk.Entry(p, textvariable=self.room_var)
        self.room_entry.pack(**pad)
        self._label(p, 'room_hint').pack(anchor='w', padx=10)
        self._label(p, 'connectTabNote').pack(anchor='w', padx=10, pady=(8, 0))

        sr = ttk.Frame(p)
        sr.pack(**pad)
        self.status_label = ttk.Label(sr, textvariable=self.status_var, font=('', 9))
        self.status_label.pack(side='left')

        # ---- B 站登录（可选，文件层面读取 cookie）----
        ttk.Separator(p, orient='horizontal').pack(fill='x', padx=10, pady=(14, 4))
        self._label(p, 'biliLoginTitle').pack(anchor='w', padx=10)
        self.bili_state_var = tk.StringVar(value='')
        self.bili_file_var = tk.StringVar(value='')
        ttk.Label(p, textvariable=self.bili_state_var, style='PanelMuted.TLabel',
                  wraplength=320, justify='left').pack(anchor='w', padx=10, pady=(2, 0))

        row = ttk.Frame(p)
        row.pack(**pad)
        self.btn_bili_file = ttk.Button(row, text='', command=self._bili_open_cookie_file)
        self.btn_bili_file.pack(side='left')
        setattr(self.btn_bili_file, '_i18n', 'biliOpenFile')
        self.btn_bili_load = ttk.Button(row, text='', command=self._bili_load_cookie, style='Accent.TButton')
        self.btn_bili_load.pack(side='left', padx=(6, 0))
        setattr(self.btn_bili_load, '_i18n', 'biliLoad')
        self.btn_bili_clear = ttk.Button(row, text='', command=self._bili_clear_cookie)
        self.btn_bili_clear.pack(side='left', padx=(6, 0))
        setattr(self.btn_bili_clear, '_i18n', 'biliClear')

        ttk.Label(p, textvariable=self.bili_file_var, style='PanelMuted.TLabel',
                  wraplength=320, justify='left').pack(anchor='w', padx=10, pady=(2, 0))
        self._label(p, 'biliLoginHint').pack(anchor='w', padx=10, pady=(6, 10))

    # ------------------------------------------------- B 站登录（文件层面 cookie）
    def _refresh_bili_state(self):
        """读取 cookie 文件，更新界面状态（不联网）。"""
        cookie, jar, err = load_bili_cookie()
        self.bili_cookie = cookie
        self.bili_jar = jar or {}
        self.bili_file_var.set(BILI_COOKIE_FILE)
        if err:
            self.bili_state_var.set(f'⚠ {err}')
            return
        if not cookie:
            self.bili_state_var.set(self.t('biliNotSet'))
            return
        uid = self.bili_jar.get('DedeUserID')
        if uid:
            self.bili_state_var.set(self.t('biliSetUid').format(uid=uid))
        else:
            self.bili_state_var.set(self.t('biliSetSess'))

    def _bili_open_cookie_file(self):
        path = ensure_bili_cookie_template()
        try:
            if os.name == 'nt':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
            self._log(f'已打开 cookie 文件：{path}')
        except Exception as e:
            messagebox.showerror('Error', str(e))

    def _bili_load_cookie(self):
        self._refresh_bili_state()
        if not self.bili_cookie:
            messagebox.showwarning(self.t('biliLoad'),
                                   f'没有读到有效的 SESSDATA。\n\n请把 B 站 cookie 粘进：\n{BILI_COOKIE_FILE}\n\n'
                                   '（点「打开 cookie 文件」会用记事本打开，里面有详细步骤）')
            return
        self._log('正在验证 B 站登录状态…')
        self._set_status('正在验证 B 站登录…', ok=False)
        threading.Thread(target=self._bili_verify_task, args=(self.bili_cookie,),
                         daemon=True, name='bili-verify').start()

    def _bili_verify_task(self, cookie):
        try:
            uid, uname = verify_bili_cookie(cookie)
            self.gui_queue.put(('bili_verify_result', True, uid, uname, ''))
        except Exception as e:
            self.gui_queue.put(('bili_verify_result', False, 0, '', str(e)))

    def _on_bili_verify_result(self, ok, uid, uname, err):
        if ok:
            self._bili_user = (uid, uname)
            self._bili_uid = uid
            self.bili_state_var.set(f'✅ 已登录：{uname}（uid={uid}）')
            self._log(f'B 站登录有效：{uname}（uid={uid}）。重新点「连接」即可用登录态抓弹幕。')
            self._set_status(f'B 站已登录：{uname}。请重新连接直播间', ok=True)
            messagebox.showinfo(self.t('biliLoad'),
                                f'登录有效 ✅\n\n账号：{uname}\nuid：{uid}\n\n'
                                '请重新点一次「连接」，之后弹幕就会带完整昵称和真实 UID。')
        else:
            self._bili_user = None
            self.bili_state_var.set(f'❌ 登录无效：{err}')
            self._log(f'B 站登录验证失败：{err}')
            self._set_status('B 站登录验证失败，详见日志', ok=False)
            messagebox.showerror(self.t('biliLoad'),
                                 f'cookie 验证失败：\n{err}\n\n'
                                 f'可能是复制不全或已过期，请重新从浏览器复制 SESSDATA 到：\n{BILI_COOKIE_FILE}')

    def _bili_clear_cookie(self):
        if not messagebox.askyesno(self.t('biliClear'), '确定要清空 cookie 文件里的登录信息吗？'):
            return
        try:
            with open(BILI_COOKIE_FILE, 'w', encoding='utf-8') as f:
                f.write(BILI_COOKIE_TEMPLATE)
        except Exception as e:
            messagebox.showerror('Error', str(e))
            return
        self.bili_cookie = ''
        self.bili_jar = {}
        self._bili_user = None
        self._refresh_bili_state()
        self._log('已清除 B 站登录信息（cookie 文件已重置为模板）。')

    def _build_translate_tab(self):
        p = self._scroll_tab(self.tab_translate)
        pad = {'padx': 10, 'pady': 6, 'fill': 'x'}
        self._label(p, 'provider_label').pack(anchor='w', padx=10, pady=(12, 0))
        self.provider_var = tk.StringVar()
        self.provider_combo = ttk.Combobox(p, textvariable=self.provider_var, state='readonly')
        self.provider_combo.pack(**pad)
        self.provider_combo.bind('<<ComboboxSelected>>', lambda e: self._on_provider_change())

        self._label(p, 'base_url_label').pack(anchor='w', padx=10)
        self.base_url_var = tk.StringVar()
        ttk.Entry(p, textvariable=self.base_url_var).pack(**pad)
        self._label(p, 'model_label').pack(anchor='w', padx=10)
        self.model_var = tk.StringVar()
        ttk.Entry(p, textvariable=self.model_var).pack(**pad)
        self._label(p, 'api_key_label').pack(anchor='w', padx=10)
        self.api_key_var = tk.StringVar()
        ttk.Entry(p, textvariable=self.api_key_var, show='*').pack(**pad)
        self.key_state_var = tk.StringVar()
        self.key_state_label = ttk.Label(p, textvariable=self.key_state_var, font=('', 8))
        self.key_state_label.pack(anchor='w', padx=10)
        self._label(p, 'prompt_label').pack(anchor='w', padx=10)
        self.prompt_text = tk.Text(p, height=6, wrap='word')
        self.prompt_text.pack(padx=10, pady=(0, 6), fill='x')

        row = ttk.Frame(p)
        row.pack(**pad)
        self._label(row, 'concurrency_label').pack(side='left')
        self.concurrency_var = tk.StringVar(value='3')
        ttk.Spinbox(row, from_=1, to=8, width=5, textvariable=self.concurrency_var).pack(side='left', padx=(6, 12))
        self.cache_var = tk.BooleanVar(value=True)
        self.cache_cb = ttk.Checkbutton(row, text='', variable=self.cache_var)
        self.cache_cb.pack(side='left')
        setattr(self.cache_cb, '_i18n', 'cache_label')

        self.btn_web_login = ttk.Button(p, text='', command=self._web_login)
        self.btn_web_login.pack(**pad)
        setattr(self.btn_web_login, '_i18n', 'web_login')
        self.web_state_var = tk.StringVar()
        self.web_state_label = ttk.Label(p, textvariable=self.web_state_var, font=('', 8))
        self.web_state_label.pack(anchor='w', padx=10)
        self._label(p, 'web_hint').pack(anchor='w', padx=10)

        self._label(p, 'dock_hint').pack(anchor='w', padx=10, pady=(8, 0))
        dock_row = ttk.Frame(p)
        dock_row.pack(**pad)
        self.btn_copy_dock = ttk.Button(dock_row, text='', command=self._copy_dock)
        self.btn_copy_dock.pack(side='left')
        setattr(self.btn_copy_dock, '_i18n', 'dock_copy')
        self.btn_open_dock = ttk.Button(dock_row, text='', command=self._open_dock)
        self.btn_open_dock.pack(side='left', padx=(6, 0))
        setattr(self.btn_open_dock, '_i18n', 'dock_open')
        self.dock_url_var = tk.StringVar(value=f'http://127.0.0.1:{DOCK_PORT}/dock')
        ttk.Label(p, textvariable=self.dock_url_var, font=('', 8)).pack(anchor='w', padx=10)

        self.btn_save = ttk.Button(p, text='', command=self._save, style='Accent.TButton')
        self.btn_save.pack(**pad)
        setattr(self.btn_save, '_i18n', 'save')

    def _build_glossary_tab(self):
        p = self._scroll_tab(self.tab_glossary)
        pad = {'padx': 10, 'pady': 6, 'fill': 'x'}
        row = ttk.Frame(p)
        row.pack(**pad)
        self.btn_gloss_new = ttk.Button(row, text='', command=self._glossary_new)
        self.btn_gloss_new.pack(side='left')
        setattr(self.btn_gloss_new, '_i18n', 'glossary_new')
        self.btn_gloss_open = ttk.Button(row, text='', command=self._glossary_open)
        self.btn_gloss_open.pack(side='left', padx=(6, 0))
        setattr(self.btn_gloss_open, '_i18n', 'glossary_open')
        row2 = ttk.Frame(p)
        row2.pack(**pad)
        self.btn_gloss_import = ttk.Button(row2, text='', command=self._glossary_import)
        self.btn_gloss_import.pack(side='left')
        setattr(self.btn_gloss_import, '_i18n', 'glossary_import')
        self.btn_gloss_export = ttk.Button(row2, text='', command=self._glossary_export)
        self.btn_gloss_export.pack(side='left', padx=(6, 0))
        setattr(self.btn_gloss_export, '_i18n', 'glossary_export')

        # 当前词库：下拉可切换（配合预设，实现"不同场景用不同词库"）
        self._label(p, 'glossary_current').pack(anchor='w', padx=10)
        self._glossary_file_map = {}
        self.glossary_file_var = tk.StringVar()
        self.glossary_combo = ttk.Combobox(p, textvariable=self.glossary_file_var, state='readonly')
        self.glossary_combo.pack(**pad)
        self.glossary_combo.bind('<<ComboboxSelected>>', lambda e: self._glossary_switch())
        self.glossary_path_var = tk.StringVar()
        ttk.Label(p, textvariable=self.glossary_path_var, font=('', 8)).pack(anchor='w', padx=10)

        form = ttk.Frame(p)
        form.pack(padx=10, pady=(8, 0), fill='x')
        self.gloss_source_var = tk.StringVar()
        self.gloss_target_var = tk.StringVar()
        self.gloss_pinyin_var = tk.StringVar()
        self.gloss_note_var = tk.StringVar()
        self._label(form, 'glossFieldSource').pack(anchor='w')
        ttk.Entry(form, textvariable=self.gloss_source_var).pack(fill='x', pady=(0, 4))
        self._label(form, 'glossFieldTarget').pack(anchor='w')
        ttk.Entry(form, textvariable=self.gloss_target_var).pack(fill='x', pady=(0, 4))
        self._label(form, 'glossFieldPinyin').pack(anchor='w')
        ttk.Entry(form, textvariable=self.gloss_pinyin_var).pack(fill='x', pady=(0, 4))
        self._label(form, 'glossFieldNote').pack(anchor='w')
        ttk.Entry(form, textvariable=self.gloss_note_var).pack(fill='x', pady=(0, 4))
        bf = ttk.Frame(form)
        bf.pack(fill='x')
        self.btn_gloss_add = ttk.Button(bf, text='', command=self._glossary_add)
        self.btn_gloss_add.pack(side='left')
        setattr(self.btn_gloss_add, '_i18n', 'glossary_add')
        self.btn_gloss_del = ttk.Button(bf, text='', command=self._glossary_del)
        self.btn_gloss_del.pack(side='left', padx=(6, 0))
        setattr(self.btn_gloss_del, '_i18n', 'glossary_del')

        self.gloss_tree = ttk.Treeview(p, columns=('src', 'dst', 'py', 'note'), show='headings', height=12)
        self.gloss_tree.heading('src', text='原词')
        self.gloss_tree.heading('dst', text='译法')
        self.gloss_tree.heading('py', text='拼音')
        self.gloss_tree.heading('note', text='备注')
        self.gloss_tree.column('src', width=78, anchor='w')
        self.gloss_tree.column('dst', width=78, anchor='w')
        self.gloss_tree.column('py', width=118, anchor='w')
        self.gloss_tree.column('note', width=66, anchor='w')
        gsb = ttk.Scrollbar(p, orient='vertical', command=self.gloss_tree.yview)
        self.gloss_tree.configure(yscrollcommand=gsb.set)
        self.gloss_tree.pack(side='left', fill='both', expand=True, padx=(10, 0), pady=6)
        gsb.pack(side='left', fill='y', pady=6)
        self.gloss_tree.tag_configure('off', foreground='#8d98a8')

        self._label(p, 'glossary_hint').pack(anchor='w', padx=10, pady=(6, 4))
        self._label(p, 'glossary_new_note').pack(anchor='w', padx=10, pady=(0, 6))

    def _build_presets_tab(self):
        p = self.tab_presets
        pad = {'padx': 10, 'pady': 6, 'fill': 'x'}
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(p, textvariable=self.preset_var, state='readonly')
        self.preset_combo.pack(**pad)
        self.preset_combo.bind('<<ComboboxSelected>>', lambda e: None)
        self.preset_name_var = tk.StringVar()
        self._label(p, 'preset_name').pack(anchor='w', padx=10)
        ttk.Entry(p, textvariable=self.preset_name_var).pack(**pad)
        row = ttk.Frame(p)
        row.pack(**pad)
        self.btn_preset_save = ttk.Button(row, text='', command=self._preset_save)
        self.btn_preset_save.pack(side='left')
        setattr(self.btn_preset_save, '_i18n', 'preset_save')
        self.btn_preset_load = ttk.Button(row, text='', command=self._preset_load)
        self.btn_preset_load.pack(side='left', padx=(6, 0))
        setattr(self.btn_preset_load, '_i18n', 'preset_load')
        self.btn_preset_del = ttk.Button(row, text='', command=self._preset_delete)
        self.btn_preset_del.pack(side='left', padx=(6, 0))
        setattr(self.btn_preset_del, '_i18n', 'preset_delete')
        # 1.4.1：预设是独立文件，方便备份 / 换版本测试时导入
        row2 = ttk.Frame(p)
        row2.pack(**pad)
        self.btn_preset_export = ttk.Button(row2, text='', command=self._preset_export)
        self.btn_preset_export.pack(side='left')
        setattr(self.btn_preset_export, '_i18n', 'preset_export')
        self.btn_preset_import = ttk.Button(row2, text='', command=self._preset_import)
        self.btn_preset_import.pack(side='left', padx=(6, 0))
        setattr(self.btn_preset_import, '_i18n', 'preset_import')
        self.btn_preset_dir = ttk.Button(p, text='', command=self._preset_open_dir)
        self.btn_preset_dir.pack(**pad)
        setattr(self.btn_preset_dir, '_i18n', 'preset_open_dir')
        self.preset_dir_var = tk.StringVar()
        ttk.Label(p, textvariable=self.preset_dir_var, font=('', 8),
                  wraplength=330, justify='left').pack(anchor='w', padx=10)
        self._label(p, 'preset_dir_hint').pack(anchor='w', padx=10, pady=(4, 6))
        self._label(p, 'preset_hint').pack(anchor='w', padx=10)

    def _build_appearance_tab(self):
        p = self._scroll_tab(self.tab_appearance)
        pad = {'padx': 10, 'pady': 6, 'fill': 'x'}

        self._label(p, 'themeLabel').pack(anchor='w', padx=10, pady=(12, 0))
        self.theme_var = tk.StringVar()
        self.theme_combo = ttk.Combobox(p, textvariable=self.theme_var, state='readonly')
        self.theme_combo.pack(**pad)
        self.theme_combo.bind('<<ComboboxSelected>>', lambda e: self._on_theme_pick())
        self._label(p, 'themeHint').pack(anchor='w', padx=10)

        self._label(p, 'bgImageLabel').pack(anchor='w', padx=10, pady=(16, 0))
        row = ttk.Frame(p)
        row.pack(**pad)
        self.btn_bg_pick = ttk.Button(row, text='', command=self._pick_bg_image)
        self.btn_bg_pick.pack(side='left')
        setattr(self.btn_bg_pick, '_i18n', 'bgPick')
        self.btn_bg_clear = ttk.Button(row, text='', command=self._clear_bg_image)
        self.btn_bg_clear.pack(side='left', padx=(6, 0))
        setattr(self.btn_bg_clear, '_i18n', 'bgClear')
        self.bg_path_var = tk.StringVar()
        ttk.Label(p, textvariable=self.bg_path_var, font=('', 8),
                  wraplength=330, justify='left').pack(anchor='w', padx=10, pady=(4, 0))
        self.img_support_var = tk.StringVar()
        ttk.Label(p, textvariable=self.img_support_var, font=('', 8),
                  wraplength=330, justify='left').pack(anchor='w', padx=10, pady=(4, 0))
        self.btn_pillow = ttk.Button(p, text='', command=self._install_pillow)
        self.btn_pillow.pack(**pad)
        setattr(self.btn_pillow, '_i18n', 'pillowInstall')
        self._refresh_image_support()

        # ---- 背景图缩放（自绘滑轨 + 数值输入）----
        self.bg_scale_var = tk.StringVar(value='100')
        self.bg_scale = self._bg_slider_row(p, 'bgScaleLabel', self.bg_scale_var,
                                            10, 400, self._on_bg_scale, first=True)
        # ---- 背景图不透明度 ----
        self.bg_opacity_var = tk.StringVar(value='100')
        self.bg_opacity = self._bg_slider_row(p, 'bgOpacityLabel', self.bg_opacity_var,
                                              0, 100, self._on_bg_opacity)
        # ---- 背景图位置 X / Y ----
        self.bg_ox_var = tk.StringVar(value='0')
        self.bg_ox = self._bg_slider_row(p, 'bgOffsetXLabel', self.bg_ox_var,
                                         -100, 100, self._on_bg_ox)
        self.bg_oy_var = tk.StringVar(value='0')
        self.bg_oy = self._bg_slider_row(p, 'bgOffsetYLabel', self.bg_oy_var,
                                         -100, 100, self._on_bg_oy)

        rb = ttk.Frame(p)
        rb.pack(**pad)
        self.btn_bg_reset = ttk.Button(rb, text='', command=self._reset_bg_adjust)
        self.btn_bg_reset.pack(side='left')
        setattr(self.btn_bg_reset, '_i18n', 'bgReset')
        self.btn_bg_fit = ttk.Button(rb, text='', command=self._fit_bg_to_feed)
        self.btn_bg_fit.pack(side='left', padx=(6, 0))
        setattr(self.btn_bg_fit, '_i18n', 'bgFit')

        self._label(p, 'bgImageHint').pack(anchor='w', padx=10, pady=(8, 0))

        # ---- 1.4.0：拼音注音 + 弹幕区字号（原文 > 注音 >= 译文）----
        self._label(p, 'pinyinSection').pack(anchor='w', padx=10, pady=(16, 0))
        self.pinyin_var = tk.BooleanVar(value=True)
        self.chk_pinyin = ttk.Checkbutton(p, text='', variable=self.pinyin_var,
                                          command=self._on_pinyin_toggle)
        self.chk_pinyin.pack(anchor='w', padx=10)
        setattr(self.chk_pinyin, '_i18n', 'pinyinShow')
        fs = ttk.Frame(p)
        fs.pack(**pad)
        self.font_raw_var = tk.StringVar(value='13')
        self.font_pinyin_var = tk.StringVar(value='11')
        self.font_trans_var = tk.StringVar(value='10')
        for key, var in (('fontRawLabel', self.font_raw_var),
                         ('fontPinyinLabel', self.font_pinyin_var),
                         ('fontTransLabel', self.font_trans_var)):
            fr = ttk.Frame(fs)
            fr.pack(fill='x', pady=1)
            self._label(fr, key).pack(side='left')
            sp = ttk.Spinbox(fr, from_=6, to=40, width=4, textvariable=var,
                             command=self._on_feed_fonts)
            sp.pack(side='right')
            sp.bind('<Return>', lambda e: self._on_feed_fonts())
            sp.bind('<FocusOut>', lambda e: self._on_feed_fonts())
        self._label(p, 'fontHint').pack(anchor='w', padx=10, pady=(4, 0))

        self._label(p, 'appearanceNote').pack(anchor='w', padx=10, pady=(14, 0))

    def _bg_slider_row(self, parent, label_key, var, lo, hi, handler, first=False):
        """一行「标签 + 数值输入框 + 自绘滑轨」。

        数值框可以直接输入（回车或失焦生效），滑轨用自绘的 ColorScale，
        保证在四套配色下都清晰可见。
        """
        row = ttk.Frame(parent)
        row.pack(fill='x', padx=10, pady=(12 if first else 10, 0))
        lab = ttk.Label(row, text='')
        lab.pack(side='left')
        setattr(lab, '_i18n', label_key)
        self._wrap_labels.append(lab)
        ttk.Label(row, text='%').pack(side='right')
        spin = ttk.Spinbox(row, from_=lo, to=hi, width=6, justify='right',
                           textvariable=var, command=lambda: self._on_bg_spin(handler, var, lo, hi))
        spin.pack(side='right', padx=(0, 3))
        for seq in ('<Return>', '<FocusOut>'):
            spin.bind(seq, lambda e, h=handler, v=var: self._on_bg_spin(h, v, lo, hi))
        sl = ColorScale(parent, from_=lo, to=hi, value=0, step=1,
                        command=lambda v, h=handler: h(v))
        sl.pack(fill='x', padx=10, pady=(2, 0))
        sl.bind('<ButtonRelease-1>', lambda e: self._apply_bg_now(), add='+')
        sl._spin = spin
        return sl

    def _on_bg_spin(self, handler, var, lo, hi):
        """数值输入框提交：夹到范围内、同步滑轨、刷新画面。"""
        try:
            v = int(round(float(str(var.get()).strip().replace('%', ''))))
        except Exception:
            return
        v = max(lo, min(hi, v))
        var.set(str(v))
        handler(v)
        self._apply_bg_now()

    # ------------------------------------------------------------- 语言/配置
    def t(self, key):
        return I18N[self.lang].get(key, I18N['zh'].get(key, key))

    def _apply_language(self):
        # 窗口标题与控制台标题随界面语言切换
        #   中文界面 -> AI萌译酱 vX.Y.Z
        #   日语界面 -> 萌AIちゃん vX.Y.Z
        try:
            title = app_title(self.lang)
            self.root.title(title)
            _set_console_title(title)
        except Exception:
            pass
        self.nb.tab(self.tab_connect, text=self.t('tab_connect'))
        self.nb.tab(self.tab_translate, text=self.t('tab_translate'))
        self.nb.tab(self.tab_glossary, text=self.t('tab_glossary'))
        self.nb.tab(self.tab_presets, text=self.t('tab_presets'))
        self.nb.tab(self.tab_appearance, text=self.t('tab_appearance'))
        # 带 _i18n 标记的控件
        for w in self._all_widgets(self.root):
            key = getattr(w, '_i18n', None)
            if key:
                w.configure(text=self.t(key))
        self.gloss_tree.heading('src', text=self.t('glossary_source'))
        self.gloss_tree.heading('dst', text=self.t('glossary_target'))
        self.gloss_tree.heading('py', text=self.t('glossary_pinyin'))
        self.gloss_tree.heading('note', text=self.t('glossary_note'))
        if not self.status_var.get() or self.status_var.get() in ('未连接', '未接続'):
            self.status_var.set(self.t('status_disconnected'))
        self.dock.language = self.lang
        self._fill_provider_combo()
        self._refresh_key_state()
        self._refresh_presets()
        self._refresh_web_state()
        self._refresh_theme_combo()

    def _all_widgets(self, w):
        yield w
        for c in w.winfo_children():
            yield from self._all_widgets(c)

    def _fill_provider_combo(self):
        self._provider_label_map = {}
        labels = []
        for key in PROVIDERS:
            lab = provider_label(key, self.lang)
            labels.append(lab)
            self._provider_label_map[lab] = key
        self.provider_combo['values'] = labels
        cur_key = self.cfg.get('provider') or 'deepseek'
        cur_label = provider_label(cur_key, self.lang)
        if cur_label in self._provider_label_map:
            self.provider_var.set(cur_label)
        self._on_provider_change()

    def _load_config_to_ui(self):
        self.room_var.set(self.cfg.get('room_id') or '')
        self.base_url_var.set(self.cfg.get('base_url') or '')
        self.model_var.set(self.cfg.get('model') or '')
        self.concurrency_var.set(str(self.cfg.get('max_concurrent') or 3))
        self.cache_var.set(self.cfg.get('cache_enabled', True) is not False)
        self.prompt_text.delete('1.0', 'end')
        self.prompt_text.insert('1.0', self.cfg.get('system_prompt') or DEFAULT_SYSTEM_PROMPT_ZH)
        self._fill_provider_combo()
        self._refresh_key_state()
        # 外观
        self._bg_source = self.cfg.get('feed_bg_image') or ''
        if hasattr(self, 'bg_path_var'):
            self.bg_path_var.set(self._bg_source)
        self._refresh_theme_combo()
        if hasattr(self, 'bg_scale'):
            s = self._cfg_int('feed_bg_scale', 100, 10, 400)
            o = self._cfg_int('feed_bg_opacity', 100, 0, 100)
            ox = self._cfg_int('feed_bg_offset_x', 0, -100, 100)
            oy = self._cfg_int('feed_bg_offset_y', 0, -100, 100)
            for sl, v in ((self.bg_scale, s), (self.bg_opacity, o),
                          (self.bg_ox, ox), (self.bg_oy, oy)):
                try:
                    sl.set(v, fire=False)
                except Exception:
                    pass
            self.bg_scale_var.set(str(s))
            self.bg_opacity_var.set(str(o))
            self.bg_ox_var.set(str(ox))
            self.bg_oy_var.set(str(oy))
        # 拼音注音开关 + 三个字号 + 礼物过滤开关
        if hasattr(self, 'pinyin_var'):
            self.pinyin_var.set(self.cfg.get('show_pinyin', True) is not False)
            raw, py, trans = apply_feed_fonts(self.cfg)
            self.font_raw_var.set(str(raw))
            self.font_pinyin_var.set(str(py))
            self.font_trans_var.set(str(trans))
        if hasattr(self, 'gift_filter_var'):
            self.gift_filter_var.set(self.cfg.get('gift_filter_free', False) is True)
            self._apply_gift_fonts()
            self._gift_render_all()

    def _refresh_key_state(self):
        if get_api_key(self.cfg):
            self.key_state_var.set(self.t('key_configured'))
        else:
            self.key_state_var.set(self.t('key_missing'))

    def _on_provider_change(self):
        key = self._provider_label_map.get(self.provider_var.get(), 'deepseek')
        is_web = key in WEB_PROVIDERS
        self.btn_web_login.configure(state='normal' if is_web else 'disabled')
        self.concurrency_var.set('1' if is_web else str(self.cfg.get('max_concurrent') or 3))
        info = PROVIDERS.get(key, {})
        self.provider_metric_var.set(provider_label(key, self.lang))
        if info.get('kind') in ('api', 'ollama') and not self.base_url_var.get().strip():
            self.base_url_var.set(info.get('base', ''))
        if not self.model_var.get().strip() and info.get('model'):
            self.model_var.set(info['model'])
        # 立即生效：避免"切换了翻译服务但没点保存，翻译仍然走旧服务"（会报 401 之类）
        if self.cfg.get('provider') != key:
            self.cfg['provider'] = key
            try:
                save_config(self.cfg)
            except Exception:
                pass
            self._log(f'翻译服务已切换为「{provider_label(key, self.lang)}」，立即生效。')
            if is_web:
                self._log('提示：网页版不需要 API Key，点「打开网页端登录」完成浏览器登录即可。')
            elif key in ('deepseek', 'openai') and not get_api_key(self.cfg):
                self._log(f'提示：「{provider_label(key, self.lang)}」需要填写 API Key，否则会返回 401。')

    # ------------------------------------------------------------- 词库
    def _glossary_path(self):
        return resolve_glossary_path(self.cfg)

    def _list_glossary_files(self):
        """列出 data 目录下所有词库文件（供下拉切换）。"""
        out = []
        skip = {'config.json', 'browser_state.json'}
        try:
            for fn in sorted(os.listdir(DATA_DIR)):
                if fn in skip or fn.startswith('browser_') or fn.startswith('.'):
                    continue
                if fn.lower().endswith(('.txt', '.csv', '.json')):
                    out.append(os.path.join(DATA_DIR, fn))
        except Exception:
            pass
        cur = self._glossary_path()
        if cur not in out and os.path.exists(cur):
            out.append(cur)
        return out

    def _refresh_glossary_files(self):
        files = self._list_glossary_files()
        self._glossary_file_map = {}
        labels = []
        for f in files:
            label = os.path.relpath(f, APP_DIR).replace('\\', '/')
            self._glossary_file_map[label] = f
            labels.append(label)
        self.glossary_combo['values'] = labels
        cur = self._glossary_path()
        cur_label = os.path.relpath(cur, APP_DIR).replace('\\', '/')
        if cur_label in self._glossary_file_map:
            self.glossary_file_var.set(cur_label)
        self.glossary_path_var.set(cur)

    def _switch_glossary_file(self, path):
        try:
            rel = os.path.relpath(path, APP_DIR)
        except Exception:
            rel = path
        self.cfg['glossary_file'] = rel
        save_config(self.cfg)
        self._load_glossary()
        self._render_glossary()
        self._refresh_glossary_files()

    def _glossary_new(self):
        """新建一个词库文件并切换过去（配合预设实现"不同场景不同词库"）。"""
        name = simpledialog.askstring(self.t('glossary_new'), self.t('glossary_new_prompt'),
                                      parent=self.root)
        if not name or not name.strip():
            return
        name = re.sub(r'[\\/:*?"<>|\s]+', '_', name.strip())
        if not name:
            return
        if not name.lower().endswith(('.txt', '.csv', '.json')):
            name += '.txt'
        path = os.path.join(DATA_DIR, name)
        if os.path.exists(path):
            if not messagebox.askyesno(self.t('glossary_new'), self.t('glossary_exists').format(n=name)):
                return
        else:
            save_glossary_file(path, [])
        self._switch_glossary_file(path)
        self._log(f'已新建 / 切换到词库：{name}（共 {len(self.glossary)} 条）')
        self._log('建议接着点「保存预设」，这样这个预设就会记住当前词库。')

    def _glossary_switch(self):
        label = self.glossary_file_var.get()
        path = self._glossary_file_map.get(label)
        if not path:
            return
        self._switch_glossary_file(path)
        self._log(f'已切换词库：{label}（共 {len(self.glossary)} 条）')

    def _load_glossary(self):
        p = self._glossary_path()
        if not os.path.exists(p):
            save_glossary_file(p, [])
        self.glossary = load_glossary_file(p)
        # 1.4.0：词表里的拼音是注音的「覆盖层」，优先于引擎结果
        Pinyin.set_overrides(self.glossary)

    def _render_glossary(self):
        self.gloss_tree.delete(*self.gloss_tree.get_children())
        for it in self.glossary:
            tags = () if it.get('enabled', True) is not False else ('off',)
            self.gloss_tree.insert('', 'end',
                                   values=(it.get('source', ''), it.get('target', ''),
                                           it.get('pinyin', ''), it.get('note', '')),
                                   tags=tags)

    def _persist_glossary(self):
        save_glossary_file(self._glossary_path(), self.glossary)
        Pinyin.set_overrides(self.glossary)
        self._render_glossary()
        self._refresh_glossary_files()
        # 覆盖层变了，弹幕区要用新的注音重画一遍
        self._feed_rerender()

    def _glossary_open(self):
        p = self._glossary_path()
        if not os.path.exists(p):
            save_glossary_file(p, [])
        try:
            if os.name == 'nt':
                os.startfile(p)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', p])
            else:
                subprocess.Popen(['xdg-open', p])
        except Exception as e:
            messagebox.showerror('Error', str(e))

    def _glossary_import(self):
        path = filedialog.askopenfilename(title=self.t('glossary_import'),
                                          filetypes=[('词库文件', '*.txt *.csv *.json'), ('全部文件', '*.*')])
        if not path:
            return
        try:
            incoming = load_glossary_file(path)
        except Exception as e:
            messagebox.showerror('Error', str(e))
            return
        self.glossary = merge_glossary(self.glossary, incoming)
        self._persist_glossary()
        self._log(f'已导入 {len(incoming)} 条词库条目')
        messagebox.showinfo(self.t('glossary_import'), self.t('msg_import_ok'))

    def _glossary_export(self):
        path = filedialog.asksaveasfilename(title=self.t('glossary_export'), defaultextension='.txt',
                                            filetypes=[('文本', '*.txt'), ('CSV', '*.csv'), ('JSON', '*.json')])
        if not path:
            return
        export_glossary(path, self.glossary)
        self._log(f'词库已导出到 {path}')

    def _glossary_add(self):
        source = self.gloss_source_var.get().strip()
        target = self.gloss_target_var.get().strip()
        note = self.gloss_note_var.get().strip()
        # 拼音统一转成符号声调（允许 xiao3 / xiao3xin1 / xiǎo 混写）
        pinyin = Pinyin.normalize(self.gloss_pinyin_var.get())
        if not source or not target:
            messagebox.showwarning(self.t('glossary_add'), self.t('msg_need_term'))
            return
        self.glossary = merge_glossary(self.glossary, [{'source': source, 'target': target,
                                                        'note': note, 'enabled': True,
                                                        'pinyin': pinyin}])
        self._persist_glossary()
        self.gloss_source_var.set('')
        self.gloss_target_var.set('')
        self.gloss_pinyin_var.set('')
        self.gloss_note_var.set('')

    def _glossary_del(self):
        sel = self.gloss_tree.selection()
        if not sel:
            return
        selected = {self.gloss_tree.item(i, 'values')[0] for i in sel}
        self.glossary = [g for g in self.glossary if str(g.get('source', '')) not in selected]
        self._persist_glossary()

    # ------------------------------------------------------------- 预设
    def _refresh_presets(self):
        """列出 data/presets/ 下的预设文件（1.4.1 起预设是独立文件）。"""
        self._preset_paths = {}
        labels = []
        for pname, path in list_presets():
            p = load_preset_file(path) or {}
            gl = os.path.basename(p.get('glossary_file') or '') or '默认词库'
            lbl = (f"{p.get('name') or pname} · "
                   f"{provider_label(p.get('provider', 'deepseek'), self.lang)} · 词库:{gl}")
            if lbl in self._preset_paths:
                lbl = f'{lbl}（{pname}）'
            self._preset_paths[lbl] = path
            labels.append(lbl)
        self.preset_combo['values'] = labels
        if labels and self.preset_var.get() not in labels:
            self.preset_var.set(labels[0])
        elif not labels:
            self.preset_var.set('')
        if hasattr(self, 'preset_dir_var'):
            try:
                self.preset_dir_var.set(preset_dir())
            except Exception:
                pass

    def _preset_save(self):
        name = self.preset_name_var.get().strip()
        if not name:
            messagebox.showwarning(self.t('preset_save'), self.t('msg_need_name'))
            return
        provider = self._provider_label_map.get(self.provider_var.get(), 'deepseek')
        item = {
            'id': hashlib.sha1(f'{name}|{time.time()}'.encode()).hexdigest()[:12],
            'name': name,
            'provider': provider,
            'base_url': self.base_url_var.get().strip(),
            'model': self.model_var.get().strip(),
            'system_prompt': self.prompt_text.get('1.0', 'end').strip(),
            'max_concurrent': int(self.concurrency_var.get() or 3),
            'cache_enabled': self.cache_var.get(),
            'glossary_file': self.cfg.get('glossary_file'),
            # 外观也一并存进预设（配色 / 背景图 / 缩放 / 不透明度 / 位置）
            'theme': self.cfg.get('theme'),
            'feed_bg_image': self.cfg.get('feed_bg_image') or '',
            'feed_bg_scale': self._cfg_int('feed_bg_scale', 100, 10, 400),
            'feed_bg_opacity': self._cfg_int('feed_bg_opacity', 100, 0, 100),
            'feed_bg_offset_x': self._cfg_int('feed_bg_offset_x', 0, -100, 100),
            'feed_bg_offset_y': self._cfg_int('feed_bg_offset_y', 0, -100, 100),
            # 拼音注音 / 字号 / 礼物过滤也一起存，换版本测试时行为一致
            'show_pinyin': self.cfg.get('show_pinyin', True) is not False,
            'feed_font_raw': self.cfg.get('feed_font_raw', 13),
            'feed_font_pinyin': self.cfg.get('feed_font_pinyin', 11),
            'feed_font_trans': self.cfg.get('feed_font_trans', 10),
            'gift_filter_free': self.cfg.get('gift_filter_free', False) is True,
        }
        key = self.api_key_var.get().strip()
        if key:
            item['api_key_encrypted'] = protect_text(key)
        elif get_api_key(self.cfg):
            item['api_key_encrypted'] = self.cfg.get('api_key_encrypted', '')

        path = preset_file_path(name)
        if os.path.exists(path):
            if not messagebox.askyesno(self.t('preset_save'),
                                       self.t('msg_confirm_overwrite').format(n=name)):
                return
            old = load_preset_file(path) or {}
            item['id'] = old.get('id', item['id'])
        try:
            save_preset_file(path, item)
        except Exception as e:
            messagebox.showerror(self.t('preset_save'), str(e))
            return
        save_config(self.cfg)
        self._refresh_presets()
        self.preset_var.set(next((k for k, v in self._preset_paths.items() if v == path), ''))
        self._log(f'预设已保存：{os.path.basename(path)}')
        messagebox.showinfo(self.t('preset_save'), self.t('msg_preset_saved'))

    def _preset_selected_path(self):
        return self._preset_paths.get(self.preset_var.get())

    def _preset_load(self):
        path = self._preset_selected_path()
        if not path:
            messagebox.showwarning(self.t('preset_load'), self.t('msg_need_preset'))
            return
        p = load_preset_file(path)
        if not p:
            messagebox.showerror(self.t('preset_load'),
                                 self.t('msg_preset_broken').format(n=os.path.basename(path)))
            return
        self.cfg['provider'] = p.get('provider', 'deepseek')
        self.cfg['base_url'] = p.get('base_url', '')
        self.cfg['model'] = p.get('model', '')
        self.cfg['system_prompt'] = p.get('system_prompt', '')
        self.cfg['max_concurrent'] = int(p.get('max_concurrent') or 3)
        self.cfg['cache_enabled'] = p.get('cache_enabled', True) is not False
        self.cfg['api_key_encrypted'] = p.get('api_key_encrypted', '')
        if p.get('glossary_file'):
            self.cfg['glossary_file'] = p['glossary_file']
        # 外观：配色 / 背景图 / 缩放 / 不透明度
        if p.get('theme'):
            self.cfg['theme'] = p['theme']
        self.cfg['feed_bg_image'] = p.get('feed_bg_image', '') or ''
        self.cfg['feed_bg_scale'] = self._clamp_int(p.get('feed_bg_scale'), 100, 10, 400)
        self.cfg['feed_bg_opacity'] = self._clamp_int(p.get('feed_bg_opacity'), 100, 0, 100)
        self.cfg['feed_bg_offset_x'] = self._clamp_int(p.get('feed_bg_offset_x'), 0, -100, 100)
        self.cfg['feed_bg_offset_y'] = self._clamp_int(p.get('feed_bg_offset_y'), 0, -100, 100)
        # 1.4.1：拼音注音与礼物相关的设置也随预设走
        if 'show_pinyin' in p:
            self.cfg['show_pinyin'] = p.get('show_pinyin') is not False
        for k, d in (('feed_font_raw', 13), ('feed_font_pinyin', 11), ('feed_font_trans', 10)):
            if k in p:
                self.cfg[k] = self._clamp_int(p.get(k), d, 6, 40)
        if 'gift_filter_free' in p:
            self.cfg['gift_filter_free'] = p.get('gift_filter_free') is True
        save_config(self.cfg)
        # 先把配色切过去（会重建弹幕区），再载入配置与背景图
        if self.cfg.get('theme') in THEMES:
            global THEME
            THEME = dict(THEMES[self.cfg['theme']])
            self._apply_theme()
        apply_feed_fonts(self.cfg)
        self._load_config_to_ui()
        self._bg_source = self.cfg.get('feed_bg_image') or ''
        self._feed_rerender()
        self._gift_render_all()
        self._apply_bg_image()
        self._load_glossary()
        self._render_glossary()
        self._refresh_glossary_files()
        self._refresh_key_state()
        self._push_dock_settings()
        name = p.get('name', '')
        g = os.path.basename(self._glossary_path())
        th = THEMES.get(self.cfg.get('theme') or '', {}).get('name') or '默认'
        bg = os.path.basename(self.cfg.get('feed_bg_image') or '') or '无'
        self._log(f'预设已读取：{name}（词库：{g}，共 {len(self.glossary)} 条；'
                  f'配色：{th}；背景图：{bg} {self.cfg.get("feed_bg_scale")}%'
                  f'/不透明度 {self.cfg.get("feed_bg_opacity")}%）')
        messagebox.showinfo(self.t('preset_load'), self.t('msg_preset_loaded'))

    def _preset_delete(self):
        path = self._preset_selected_path()
        if not path:
            messagebox.showwarning(self.t('preset_delete'), self.t('msg_need_preset'))
            return
        name = os.path.splitext(os.path.basename(path))[0]
        if not messagebox.askyesno(self.t('preset_delete'),
                                   self.t('msg_confirm_delete').format(n=name)):
            return
        delete_preset_file(path)
        self._refresh_presets()
        self._log(f'预设已删除：{os.path.basename(path)}')
        messagebox.showinfo(self.t('preset_delete'), self.t('msg_preset_deleted'))

    # ------------------------------------- 1.4.1：预设的导出 / 导入 / 打开文件夹
    def _preset_export(self):
        """把选中的预设另存到任意位置（备份用）。"""
        path = self._preset_selected_path()
        if not path:
            messagebox.showwarning(self.t('preset_export'), self.t('msg_need_preset'))
            return
        name = os.path.splitext(os.path.basename(path))[0]
        out = filedialog.asksaveasfilename(
            title=self.t('preset_export'), defaultextension='.json',
            initialfile=name + '.json',
            filetypes=[('预设文件', '*.json'), ('全部文件', '*.*')])
        if not out:
            return
        try:
            shutil.copyfile(path, out)
        except Exception as e:
            messagebox.showerror(self.t('preset_export'), str(e))
            return
        self._log(f'预设已导出到 {out}')
        messagebox.showinfo(self.t('preset_export'), self.t('msg_preset_exported'))

    def _preset_import(self):
        """从任意位置导入一个预设文件到 data/presets/。"""
        src = filedialog.askopenfilename(
            title=self.t('preset_import'),
            filetypes=[('预设文件', '*.json'), ('全部文件', '*.*')])
        if not src:
            return
        p = load_preset_file(src)
        if not p:
            messagebox.showerror(self.t('preset_import'),
                                 self.t('msg_preset_broken').format(n=os.path.basename(src)))
            return
        name = str(p.get('name') or '').strip() or \
            os.path.splitext(os.path.basename(src))[0]
        path = preset_file_path(name)
        if os.path.exists(path):
            if not messagebox.askyesno(self.t('preset_import'),
                                       self.t('msg_confirm_overwrite').format(n=name)):
                return
            old = load_preset_file(path) or {}
            p['id'] = old.get('id', p.get('id'))
        p['name'] = name
        try:
            save_preset_file(path, p)
        except Exception as e:
            messagebox.showerror(self.t('preset_import'), str(e))
            return
        self._refresh_presets()
        self.preset_var.set(next((k for k, v in self._preset_paths.items() if v == path), ''))
        self._log(f'预设已导入：{os.path.basename(path)}')
        messagebox.showinfo(self.t('preset_import'), self.t('msg_preset_imported').format(n=name))

    def _preset_open_dir(self):
        """打开 data/presets/ 文件夹（拷进拷出最省事）。"""
        try:
            d = preset_dir()
            if os.name == 'nt':
                os.startfile(d)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', d])
            else:
                subprocess.Popen(['xdg-open', d])
        except Exception as e:
            messagebox.showerror(self.t('preset_open_dir'), str(e))

    # ------------------------------------------------------------- 连接
    def _connect(self):
        room = self.room_var.get().strip()
        # 先写日志再干活：这样"点了没反应"和"点了但失败了"能一眼区分开
        self._log(f'开始连接直播间：{room or "（房间号为空）"}')
        if not room:
            self._set_status(self.t('msg_need_room'))
            return
        self.cfg['room_id'] = room
        save_config(self.cfg)
        self._disconnect_client()
        # 每次连接前重读 cookie 文件（用户可能刚编辑过）
        self._refresh_bili_state()
        if self.bili_cookie:
            self._log(f'已加载 B 站登录信息（uid={self.bili_jar.get("DedeUserID") or "未知"}），'
                      '弹幕将带完整昵称与真实 UID。')
        else:
            self._log('未配置 B 站登录信息：若出现昵称打码，请到「连接」页配置 cookie。')
        self.mask_count = 0
        self._update_mask_bar()
        self._set_status('正在连接直播间…', ok=False)
        self.danmaku = DanmakuClient(
            room,
            on_danmaku=lambda d: self.gui_queue.put(('danmaku', d)),
            on_status=lambda s: self.gui_queue.put(('status', s)),
            on_popularity=lambda v: self.gui_queue.put(('popularity', v)),
            on_log=lambda lv, m: self.gui_queue.put(('log', lv, m)),
            on_gift=lambda g: self.gui_queue.put(('gift', g)),
            cookie=self.bili_cookie,
            uid=getattr(self, '_bili_uid', 0) or 0,
        )
        self.danmaku.start()

    def _disconnect(self):
        self._disconnect_client()
        self.gui_queue.put(('status', {'connected': False, 'live': False, 'message': self.t('msg_disconnected'), 'room_id': self.cfg.get('room_id', '')}))

    def _disconnect_client(self):
        if self.danmaku:
            try:
                self.danmaku.stop()
            except Exception:
                pass
            self.danmaku = None

    def _test(self):
        tests = [
            ('中文观众', '主播今天也很可爱！'), ('EnglishUser', 'That was amazing!'),
            ('한국팬', '오늘 정말 귀여워요!'), ('日本人', '今日もかわいい！'),
            ('User123', '666666'), ('旅行者', '请问下次什么时候直播？'),
        ]
        for user, text in tests:
            self.gui_queue.put(('danmaku', {'user': user, 'text': text, 'uid': None, 'ts': int(time.time() * 1000)}))

    def _clear(self):
        if not messagebox.askyesno(self.t('clear'), self.t('msg_confirm_clear')):
            return
        self.messages.clear()
        self.msg_order.clear()
        self.cache.clear()
        self.feed.delete('all')
        self.feed_items.clear()
        self._msg_y.clear()
        self._msg_h.clear()
        self._bg_item = None
        self._feed_h = 0.0
        if self._bg_photo:
            self._draw_bg_image()
        self._feed_relayout(0)
        self._feed_count()
        while True:
            try:
                self.pending.get_nowait()
            except queue.Empty:
                break
        self.dock.broadcast({'type': 'clear_messages'})

    # ------------------------------------------------------------- 保存/语言
    def _save(self):
        provider = self._provider_label_map.get(self.provider_var.get(), 'deepseek')
        self.cfg['room_id'] = self.room_var.get().strip()
        self.cfg['provider'] = provider
        self.cfg['base_url'] = self.base_url_var.get().strip()
        self.cfg['model'] = self.model_var.get().strip()
        self.cfg['system_prompt'] = self.prompt_text.get('1.0', 'end').strip()
        # 网页版固定并发为 1，不覆盖用户的并发设置
        if provider not in ('deepseek_web', 'chatgpt_web'):
            self.cfg['max_concurrent'] = int(self.concurrency_var.get() or 3)
        self.cfg['cache_enabled'] = self.cache_var.get()
        self.cfg['ui_language'] = self.lang
        key = self.api_key_var.get().strip()
        if key:
            self.cfg['api_key_encrypted'] = protect_text(key)
            self.api_key_var.set('')
        save_config(self.cfg)
        self._refresh_key_state()
        self._set_status(self.t('msg_saved'))

    def _toggle_lang(self):
        prev = self.lang
        self.lang = 'ja' if self.lang == 'zh' else 'zh'
        cur = self.prompt_text.get('1.0', 'end').strip()
        if prev == 'zh' and cur == DEFAULT_SYSTEM_PROMPT_ZH:
            self.prompt_text.delete('1.0', 'end')
            self.prompt_text.insert('1.0', DEFAULT_SYSTEM_PROMPT_JA)
        elif prev == 'ja' and cur == DEFAULT_SYSTEM_PROMPT_JA:
            self.prompt_text.delete('1.0', 'end')
            self.prompt_text.insert('1.0', DEFAULT_SYSTEM_PROMPT_ZH)
        self.cfg['ui_language'] = self.lang
        self._apply_language()

    # ------------------------------------------------------------- 停靠
    def _copy_dock(self):
        url = f'http://127.0.0.1:{DOCK_PORT}/dock'
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self._log('停靠链接已复制')

    def _open_dock(self):
        webbrowser.open(f'http://127.0.0.1:{DOCK_PORT}/dock')

    # ------------------------------------------------------------- 网页端
    def _browser_info(self):
        """返回 (可执行文件路径, 显示名)，找不到返回 (None, '')。"""
        try:
            return find_browser()
        except Exception:
            return None, ''

    def _refresh_web_state(self):
        if getattr(self, 'web_state_var', None) is None:
            return
        exe, name = self._browser_info()
        if exe:
            self.web_state_var.set(self.t('web_state_ok').replace('{b}', name))
        else:
            self.web_state_var.set(self.t('web_state_missing'))

    def _ensure_web_thread(self):
        if self._web_thread is None or not self._web_thread.is_alive():
            self._web_thread = threading.Thread(target=self._web_loop, daemon=True, name='web-session')
            self._web_thread.start()

    def _web_loop(self):
        """所有浏览器操作都在这一个线程里执行，避免并发操作同一个页面。"""
        while True:
            try:
                task = self._web_queue.get()
            except Exception:
                return
            if task is None:
                return
            kind, payload = task
            try:
                if kind == 'login':
                    sess = self._get_web_session(payload)
                    sess.ensure()
                    sess.bring_to_front()
                    self.gui_queue.put(('web_login_result', sess.is_ready(), None, sess.profile_mode))
                elif kind == 'translate':
                    item, provider = payload
                    cfg, items = self._snapshot()
                    key = f"{cfg.get('provider')}|{cfg.get('base_url', '')}|{cfg.get('model', '')}|{item['text']}"
                    if cfg.get('cache_enabled', True) and key in self.cache:
                        self.gui_queue.put(('translation', item['id'], self.cache[key], True))
                        continue
                    sess = self._get_web_session(provider)
                    result = (call_provider(cfg, item['text'], items, sess) or '').strip()
                    if cfg.get('cache_enabled', True):
                        self.cache[key] = result
                    self.gui_queue.put(('translation', item['id'], result, False))
                elif kind == 'close':
                    for sess in list(self.web_sessions.values()):
                        try:
                            sess.close()
                        except Exception:
                            pass
                    self.web_sessions.clear()
                    return
            except Exception as e:
                if kind == 'login':
                    self.gui_queue.put(('web_login_result', False, str(e)))
                else:
                    self.gui_queue.put(('translation_error', payload[0]['id'], str(e)))

    def _web_login(self):
        provider = self._provider_label_map.get(self.provider_var.get(), 'deepseek')
        if provider not in WEB_PROVIDERS:
            messagebox.showinfo('网页端',
                                '请先在上方「翻译服务」中选择「DeepSeek 网页版」或「ChatGPT 网页版」，再点这个按钮。')
            return
        exe, name = self._browser_info()
        if not exe:
            messagebox.showerror('找不到浏览器',
                                 '没有找到可用的浏览器（需要 Microsoft Edge 或 Google Chrome）。\n\n'
                                 'Windows 10 / 11 一般自带 Edge；如果没有，请先安装一个。\n'
                                 '注意：Firefox 不支持调试协议，不能用于网页版翻译。')
            return

        sess = self._get_web_session(provider)
        sess.allow_kill_browser = False
        sess.allow_isolated = False
        self._set_status(f'正在启动「{name}」，请稍候…', ok=True)
        self._log(f'正在启动「{name}」浏览器…（首次可能需要十几秒）')
        self._ensure_web_thread()
        self._web_queue.put(('login', provider))

    def _on_web_login_result(self, ok, err, mode=''):
        if err:
            self._log(f'打开网页端失败：{err}')
            messagebox.showerror('网页端启动失败', err)
            self._set_status('网页端启动失败，详情见下方日志', ok=False)
            return
        if ok:
            self._web_error_warned = False
            if mode == 'isolated':
                self._set_status('网页端已就绪（独立空白配置）', ok=True)
                self._log('注意：当前用的是独立空白配置。')
            else:
                self._set_status('网页端已就绪（本程序专用窗口，翻译会走它）', ok=True)
                self._log('网页端已就绪。翻译会通过这个专用浏览器窗口进行。')
        else:
            self._set_status('浏览器已打开：请登录并停留在聊天页，然后保存设置', ok=True)
            self._log('浏览器已打开。请在其中登录 DeepSeek / ChatGPT，登录后停留在聊天页面（只需登录这一次）。')

    # ------------------------------------------------------------- 翻译线程
    def _snapshot(self):
        return dict(self.cfg), list(self.glossary)

    def _concurrency(self):
        if self.cfg.get('provider') in ('deepseek_web', 'chatgpt_web'):
            return 1
        return max(1, int(self.cfg.get('max_concurrent') or 3))

    def _get_web_session(self, provider):
        if provider not in self.web_sessions:
            self.web_sessions[provider] = create_browser_session(
                provider, log=lambda m: self.gui_queue.put(('log', 'info', m)))
        return self.web_sessions[provider]

    def _enqueue(self, item):
        provider = self.cfg.get('provider')
        if provider in ('deepseek_web', 'chatgpt_web'):
            self._ensure_web_thread()
            self._web_queue.put(('translate', ({'id': item['id'], 'text': item['text']}, provider)))
            return
        self.pending.put({'id': item['id'], 'text': item['text']})
        self._pump()

    def _pump(self):
        with self.pump_lock:
            limit = self._concurrency()
            while self.active < limit:
                try:
                    task = self.pending.get_nowait()
                except queue.Empty:
                    break
                self.active += 1
                threading.Thread(target=self._translate_task, args=(task,), daemon=True).start()

    def _translate_task(self, task):
        try:
            cfg, items = self._snapshot()
            key = f"{cfg.get('provider')}|{cfg.get('base_url', '')}|{cfg.get('model', '')}|{task['text']}"
            if cfg.get('cache_enabled', True) and key in self.cache:
                self.gui_queue.put(('translation', task['id'], self.cache[key], True))
                return
            provider = cfg.get('provider')
            if provider in ('deepseek_web', 'chatgpt_web'):
                # 网页版必须在线程内串行使用 Playwright
                self._ensure_web_thread()
                self._web_queue.put(('translate', ({'id': task['id'], 'text': task['text']}, provider)))
                return
            result = (call_provider(cfg, task['text'], items, None) or '').strip()
            if cfg.get('cache_enabled', True):
                self.cache[key] = result
            self.gui_queue.put(('translation', task['id'], result, False))
        except Exception as e:
            self.gui_queue.put(('translation_error', task['id'], str(e)))
        finally:
            with self.pump_lock:
                self.active -= 1
            self._pump()

    # ------------------------------------------------------------- 渲染
    # 每个 tick 最多处理多少条消息。礼物刷屏时队列里可能一口气堆上千条，
    # 原来用 while True 抽干会把 UI 线程占住（1000 条 × ~1ms ≈ 1 秒假死），
    # 这里限量处理：没抽空就 1ms 后再来一轮，界面始终有机会响应。
    POLL_INTERVAL = 100
    POLL_BATCH = 60

    def _poll(self):
        if self.closing:
            return
        if not getattr(self, '_tk_hook_installed', False):
            # 免安装版是 --noconsole 的：Tk 默认把回调异常打到 stderr，等于彻底消失，
            # 用户看到的就是"点了没反应"。所以第一件事就是把它接到日志上。
            self._tk_hook_installed = True
            try:
                self.root.report_callback_exception = self._on_tk_exception
            except Exception:
                pass
        n = 0
        more = False
        try:
            try:
                while n < self.POLL_BATCH:
                    self._handle_msg(self.gui_queue.get_nowait())
                    n += 1
            except queue.Empty:
                pass
            else:
                more = True          # 没取空 -> 还有积压，尽快再跑一轮
        except Exception:
            # 关键：这里绝不能把异常放出去。
            # 重新排期在下面，一旦抛出就再也不会排期，整条界面更新管道永久死掉 ——
            # 窗口还能动、按钮还能点，但从此刻起日志/状态/弹幕全都不再更新。
            self._report_exception('处理消息时出错')
            more = False             # 用正常节奏继续，别空转
        try:
            self.queue_var.set(str(self.pending.qsize() + self.active + self._web_queue.qsize()))
            self.clients_var.set(str(len(self.dock.clients)))
            # 配置写入失败的提示（启动早期还没日志面板，先缓存下来）
            pend = getattr(self, '_pending_config_error', None)
            if pend and hasattr(self, 'log_text'):
                self._pending_config_error = None
                self._log(pend)
        except Exception:
            self._report_exception('刷新状态栏时出错')
        finally:
            self.root.after(1 if more else self.POLL_INTERVAL, self._poll)

    def _on_config_save_error(self, path, err):
        """配置写不进去时的提示（同一种原因只报一次，避免刷屏）。"""
        if err in getattr(self, '_config_err_reported', set()):
            return
        try:
            self._config_err_reported.add(err)
        except Exception:
            pass
        msg = (f'⚠ 配置无法保存：{path}\n'
               f'    原因：{err}\n'
               f'    常见原因：这个文件正被编辑器 / 杀毒软件 / 另一个程序占用，'
               f'或者所在文件夹没有写权限。\n'
               f'    程序会继续正常运行，但这次的设置不会被保存；'
               f'关掉占用它的程序（或把整个文件夹挪到有写权限的位置）后重开即可恢复。')
        try:
            if hasattr(self, 'log_text'):
                self._log(msg)
            else:
                self._pending_config_error = msg
        except Exception:
            print(msg)

    def _on_tk_exception(self, exc, val, tb):
        """Tk 回调异常的统一出口（按钮、定时器、事件绑定都走这里）。"""
        self._report_exception('界面回调出错',
                               ''.join(traceback.format_exception(exc, val, tb)))

    def _report_exception(self, where, exc_text=None):
        """把异常写到日志面板和 data/error.log —— 用户看得见的地方。"""
        text = exc_text or traceback.format_exc()
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        head = f'【内部错误】{where}（{stamp}）'
        try:
            self._log(head)
            for line in text.rstrip().split('\n')[-14:]:
                self._log('    ' + line)
            self._log('    以上已写入 data/error.log，反馈问题时请附上。')
        except Exception:
            print(head)
            print(text)
        try:
            with open(os.path.join(DATA_DIR, 'error.log'), 'a', encoding='utf-8') as f:
                f.write(f'\n===== {head} =====\n{text}\n')
        except Exception:
            pass

    def _handle_msg(self, msg):
        kind = msg[0]
        if kind == 'danmaku':
            self._on_danmaku(msg[1])
        elif kind == 'translation':
            self._on_translation(msg[1], msg[2], msg[3])
        elif kind == 'translation_error':
            self._on_translation_error(msg[1], msg[2])
        elif kind == 'status':
            self._on_status(msg[1])
        elif kind == 'popularity':
            self.pop_var.set(str(msg[1]))
            self.dock.broadcast({'type': 'popularity', 'value': msg[1]})
        elif kind == 'log':
            self._log(f"[{msg[1]}] {msg[2]}")
        elif kind == 'gift':
            self._on_gift(msg[1])
        elif kind == 'web_login_result':
            self._on_web_login_result(msg[1], msg[2], msg[3] if len(msg) > 3 else '')
        elif kind == 'refresh_web_state':
            self._refresh_web_state()
        elif kind == 'pillow_done':
            self._on_pillow_done(msg[1])
        elif kind == 'bili_verify_result':
            self._on_bili_verify_result(msg[1], msg[2], msg[3], msg[4])

    def _on_danmaku(self, d):
        item = {
            'id': hashlib.sha1(f"{d.get('uid') or ''}|{d.get('text')}|{d.get('ts')}|{time.time()}".encode()).hexdigest()[:20],
            'ts': d.get('ts') or int(time.time() * 1000),
            'user': str(d.get('user') or '匿名用户'),
            'text': str(d.get('text') or ''),
            'japanese': is_japanese(str(d.get('text') or '')),
            'translation': None,
            'error': None,
            'translating': False,
        }
        # 打码检测：B 站对未登录/被判为机器人的连接会把昵称变成 “首字***” 且 uid=0
        user = item['user'] or ''
        if ('*' in user or '＊' in user) and not (d.get('uid') or 0):
            self.mask_count += 1
            self._update_mask_bar()
        self.messages[item['id']] = item
        self.msg_order.append(item['id'])
        if not item['japanese']:
            item['translating'] = True
        self._render_item(item)
        # 1.4.0：把注音单元一起广播，停靠页用原生 <ruby> 渲染
        py_units = None
        if self.cfg.get('show_pinyin', True):
            py_units = [[u[0], u[1]] for u in Pinyin.annotate(item['text'])]
        self.dock.broadcast({'type': 'console_message',
                             'item': {'id': item['id'], 'ts': item['ts'], 'user': item['user'],
                                      'text': item['text'], 'japanese': item['japanese'],
                                      'pinyin': py_units}})
        if not item['japanese']:
            self._enqueue(item)

    def _on_translation(self, iid, translation, cached):
        item = self.messages.get(iid)
        if not item:
            return
        item['translation'] = translation
        item['translating'] = False
        item['error'] = None
        self._render_item(item)
        self.dock.broadcast({'type': 'translation', 'id': iid, 'translation': translation})

    def _on_translation_error(self, iid, error):
        item = self.messages.get(iid)
        if not item:
            return
        item['error'] = error
        item['translating'] = False
        self._render_item(item)
        self.dock.broadcast({'type': 'translation_error', 'id': iid, 'error': error})
        # 网页版相关错误只弹一次提示，避免每条弹幕都弹窗
        low = str(error).lower()
        if not getattr(self, '_web_error_warned', False) and ('网页端' in str(error) or '浏览器' in str(error) or '输入框' in str(error)):
            self._web_error_warned = True
            messagebox.showwarning('网页端提示',
                                   f'{error}\n\n请点击「打开网页端登录」，在弹出的浏览器里登录并停留在聊天页。')

    def _on_status(self, s):
        self.status_var.set(s.get('message') or '')
        ok = s.get('connected') or s.get('monitoring') or s.get('live')
        self.dot.configure(fg=THEME['ok'] if ok else '#5b6273')
        ls = s.get('live_status')
        if ls is None:
            ls = 1 if s.get('live') else 0
        try:
            ls = int(ls)
        except Exception:
            ls = 0
        self.live_var.set({1: self.t('live_on'), 2: self.t('live_round')}.get(ls, self.t('live_off')))
        self.dock.broadcast({'type': 'status', 'status': s})

    # --------------------------------------------------- 弹幕流（Canvas 绘制）
    # 用 Canvas 而不是 Text，才能在文字后面垫一张自定义背景图。
    FEED_PAD_X = 14
    FEED_GAP = 3
    FEED_BLOCK_GAP = 9

    def _trans_display(self, item):
        """返回 (要显示的译文文本, 角色名)。"""
        if item.get('error'):
            return '⚠ ' + str(item['error']).splitlines()[0][:180], 'err'
        if item.get('translation'):
            return '→ ' + item['translation'], 'trans'
        if item.get('japanese'):
            return '', 'trans'
        if item.get('translating'):
            return self.t('pending'), 'pending'
        return self.t('waiting'), 'pending'

    def _role_color(self, role):
        C = THEME
        return {'trans': C['trans'], 'pending': C['warn'], 'err': C['err']}.get(role, C['raw'])

    def _feed_wrap(self):
        return max(160, self.feed.winfo_width() - self.FEED_PAD_X * 2 - 16)

    def _feed_should_show(self, item):
        q = self.search_var.get().strip().lower()
        if not q:
            return True
        hay = f"{item.get('user','')} {item.get('text','')} {item.get('translation') or ''}".lower()
        return q in hay

    RUBY_LINE_GAP = 2        # 注音行与汉字行之间的额外间距

    def _pinyin_color(self):
        C = THEME
        return C.get('pinyin') or C.get('meta') or C.get('raw')

    def _feed_should_pinyin(self, item):
        """这条弹幕要不要显示注音（开关 + 引擎可用 + 文本里有中文）。"""
        if not self.cfg.get('show_pinyin', True):
            return False
        if not Pinyin.available():
            return False
        return any(Pinyin.is_cjk(ch) for ch in str(item.get('text') or ''))

    def _feed_make_items(self, item):
        """创建一条弹幕的文字项（位置稍后由 _feed_relayout 统一排）。

        原文有两套结构，统一存成 feed_items[iid]['raw'] = [(拼音项, 汉字项), …]：
          · 不开注音：[(None, 原文项)]        —— 一个项，交给 Canvas 自动折行
          · 开注音  ：[(拼音项, 汉字项), …]    —— 逐字对齐，手工折行
        注音模式下每个单元用**两个**文字项，因为 Tk 的一个文字项只能有一种字体，
        而注音字号小于原文字号。
        """
        C = THEME
        wrap = self._feed_wrap()
        ts = datetime.fromtimestamp(item['ts'] / 1000).strftime('%H:%M:%S')
        txt, role = self._trans_display(item)
        meta = self.feed.create_text(0, 0, anchor='nw', text=f'{ts}  {item["user"]}',
                                     font=FEED_FONTS['meta'], fill=C['meta'], width=wrap)
        raw_text = str(item.get('text') or '')
        ruby = self._feed_should_pinyin(item)
        if ruby:
            pairs = []
            for unit, py in Pinyin.annotate(raw_text):
                py_id = None
                if py:
                    py_id = self.feed.create_text(0, 0, anchor='nw', text=py,
                                                  justify='center',
                                                  font=FEED_FONTS['pinyin'],
                                                  fill=self._pinyin_color())
                han_id = self.feed.create_text(0, 0, anchor='nw', text=unit,
                                               justify='center',
                                               font=FEED_FONTS['raw'], fill=C['raw'])
                pairs.append((py_id, han_id))
        else:
            pairs = [(None, self.feed.create_text(
                0, 0, anchor='nw', text=raw_text,
                font=FEED_FONTS['raw'], fill=C['raw'], width=wrap))]
        trans = self.feed.create_text(0, 0, anchor='nw', text=txt,
                                      font=FEED_FONTS.get(role, FEED_FONTS['trans']),
                                      fill=self._role_color(role), width=wrap)
        self.feed_items[item['id']] = {'meta': meta, 'raw': pairs,
                                       'trans': trans, 'ruby': ruby}

    def _feed_canvas_ids(self, iid):
        """一条弹幕涉及的全部 Canvas 项 id。"""
        d = self.feed_items.get(iid)
        if not d:
            return
        if d.get('meta'):
            yield d['meta']
        for py_id, han_id in d.get('raw') or []:
            if py_id:
                yield py_id
            if han_id:
                yield han_id
        if d.get('trans'):
            yield d['trans']

    def _feed_place_ruby(self, pairs, x0, y, wrap):
        """逐字注音排布：每个单元一个格子，拼音居中在汉字的正上方。

        没有拼音的单元（标点 / 字母 / 数字 / 表情）只放汉字项，纵向落在
        「汉字行」上，所以基线与邻居天然一致，不会上浮错位。
        """
        h_py = h_han = 0
        for py_id, han_id in pairs:
            if py_id and not h_py:
                b = self.feed.bbox(py_id)
                if b:
                    h_py = b[3] - b[1]
            if not h_han:
                b = self.feed.bbox(han_id)
                if b:
                    h_han = b[3] - b[1]
        line_h = h_py + h_han
        x = x0
        base = y
        for py_id, han_id in pairs:
            b = self.feed.bbox(han_id)
            w_han = (b[2] - b[0]) if b else 0
            w_py = 0
            if py_id:
                b2 = self.feed.bbox(py_id)
                w_py = (b2[2] - b2[0]) if b2 else 0
            cell = max(w_py, w_han) + 2
            if x > x0 and x + cell > x0 + wrap:
                x = x0
                base += line_h + self.RUBY_LINE_GAP
            if py_id:
                self.feed.coords(py_id, x + (cell - w_py) / 2.0, base)
            self.feed.coords(han_id, x + (cell - w_han) / 2.0, base + h_py)
            x += cell
        # 返回本条原文占用的**高度**，由调用方加到逻辑 y 上
        return (base - y) + line_h + self.FEED_GAP

    def _feed_set_scrollregion(self):
        """只在真的变化时才 configure(scrollregion)。

        坐标用**绝对值**、不做整体上移：上移会让全部 Canvas 项失效并重绘
        （3400 项约 150ms），而且一旦"逻辑坐标已经减了、Canvas 项还没移"，
        后续摆放就会和已有内容错位重叠（实测过这个 bug）。
        所以滚动区的顶端跟着第一条弹幕走，坐标随直播时长增长也没关系
        （Tk 用双精度，且只重绘可见区域）。
        """
        top = 0.0
        for iid in self.msg_order:
            if iid in self._msg_y and iid in self.feed_items:
                top = max(0.0, self._msg_y[iid] - self.FEED_PAD_X)
                break
        want = (0, top, self.feed.winfo_width(),
                max(self._feed_h, self.feed.winfo_height(), top + 1))
        if want != getattr(self, '_feed_sr', None):
            self._feed_sr = want
            self.feed.configure(scrollregion=want)

    def _feed_place(self, iid, y):
        d = self.feed_items[iid]
        wrap = self._feed_wrap()
        x0 = self.FEED_PAD_X
        self.feed.itemconfigure(d['meta'], width=wrap)
        self.feed.coords(d['meta'], x0, y)
        b = self.feed.bbox(d['meta'])
        if b:
            y += (b[3] - b[1]) + self.FEED_GAP
        if d.get('ruby'):
            y += self._feed_place_ruby(d['raw'], x0, y, wrap)
        else:
            han = d['raw'][0][1]
            self.feed.itemconfigure(han, width=wrap)
            self.feed.coords(han, x0, y)
            b = self.feed.bbox(han)
            if b:
                y += (b[3] - b[1]) + self.FEED_GAP
        self.feed.itemconfigure(d['trans'], width=wrap)
        self.feed.coords(d['trans'], x0, y)
        b = self.feed.bbox(d['trans'])
        if b:
            y += (b[3] - b[1]) + self.FEED_GAP
        return y + self.FEED_BLOCK_GAP

    def _feed_relayout(self, start_index=0, y=None):
        if not self.msg_order:
            self._feed_h = 0.0
            self._feed_set_scrollregion()
            return
        if start_index <= 0:
            start_index = 0
            y = 10.0
        elif y is None:
            y = self._msg_y.get(self.msg_order[start_index], 10.0)
        for j in range(start_index, len(self.msg_order)):
            iid = self.msg_order[j]
            if iid not in self.feed_items:
                continue
            self._msg_y[iid] = y
            y = self._feed_place(iid, y)
            self._msg_h[iid] = y - self._msg_y[iid]
        self._feed_h = y
        self._feed_set_scrollregion()
        self._bg_reposition()

    def _feed_add(self, item):
        before_h = self._feed_h
        self._feed_make_items(item)
        if self._bg_item is not None:
            self.feed.tag_lower(self._bg_item)
        self._feed_relayout(len(self.msg_order) - 1, y=before_h)
        self.feed.yview_moveto(1.0)
        self._bg_reposition()

    def _feed_update(self, item):
        iid = item['id']
        if iid not in self.feed_items:
            return
        txt, role = self._trans_display(item)
        self.feed.itemconfigure(self.feed_items[iid]['trans'], text=txt,
                                font=FEED_FONTS.get(role, FEED_FONTS['trans']),
                                fill=self._role_color(role))
        try:
            idx = self.msg_order.index(iid)
        except ValueError:
            return
        # 译文长度可能变化，需要把这条及其后面的重新排一遍
        self._feed_relayout(idx, y=self._msg_y.get(iid, 10.0))

    def _feed_rerender(self):
        self.feed.delete('all')
        self.feed_items.clear()
        self._msg_y.clear()
        self._msg_h.clear()
        self._bg_item = None
        self._feed_h = 0.0
        if self._bg_photo:
            self._draw_bg_image()
        for iid in list(self.msg_order):
            it = self.messages.get(iid)
            if it and self._feed_should_show(it):
                self._feed_make_items(it)
        self._feed_relayout(0)
        self.feed.yview_moveto(1.0)
        self._bg_reposition()
        self._feed_count()

    def _feed_count(self, _shown=None):
        total = len(self.msg_order)
        shown = len(self.feed_items)
        q = self.search_var.get().strip()
        self.feed_count_var.set(f'{shown} / {total} 条' + ('　🔍' if q else ''))

    def _feed_trim(self):
        limit = int(self.cfg.get('console_max_messages') or 300)
        removed = []
        dy = 0.0
        while len(self.msg_order) > limit:
            old = self.msg_order.pop(0)
            self.messages.pop(old, None)
            # 高度必须在 pop 之前取出来。原先是先 pop(_msg_h) 再 sum(_msg_h...),
            # 于是 dy 恒为 0：既不做整体上移，也不修正 _msg_y/_feed_h，
            # 结果是 Canvas 坐标一路增长（实测 200 条就涨到 5.6 万 px），
            # 滚动区域越来越大、每次重绘越来越慢。这是 v1.3.0 就有的老问题。
            h = self._msg_h.pop(old, None) or 0.0
            if old in self.feed_items:
                for it in self._feed_canvas_ids(old):
                    self.feed.delete(it)
                self.feed_items.pop(old, None)
                self._msg_y.pop(old, None)
                removed.append(old)
                dy += h
        if not removed:
            return
        # 坐标用绝对值，**不做整体上移**：
        #   · Canvas 上移会让全部项失效并重绘（3400 项约 150ms）；
        #   · 更要命的是，一旦"逻辑坐标已经减了、Canvas 项还没移"，
        #     后续新增的弹幕就会按新的偏移摆放，和已有内容错位重叠
        #     （实测 200 条时会重叠 180px）。
        # 坐标会随直播时长增长，但 Tk 用双精度、只重绘可见区域，实测无影响。
        self._feed_set_scrollregion()
        self._bg_reposition()

    # --------------------------------------------------- 礼物栏（1.4.0）
    @staticmethod
    def _gift_is_free(g):
        """银瓜子 / 价格为 0 视为免费礼物。"""
        if str(g.get('coin_type') or '').lower() == 'silver':
            return True
        try:
            return int(g.get('price') or 0) <= 0
        except Exception:
            return False

    def _gift_should_show(self, g):
        """免费礼物过滤 + 回溯查询过滤（按 用户名 / 礼物名 匹配）。

        注意：这里只用普通属性 _gift_query，不碰 Tk 变量 —— 停靠页的
        /api/gifts 会在 HTTP 工作线程里调用它，而 Tk 不是线程安全的。
        """
        if self.cfg.get('gift_filter_free') and self._gift_is_free(g):
            return False
        q = self._gift_query
        if not q:
            return True
        return q in f"{g.get('user', '')} {g.get('gift', '')}".lower()

    def _gift_write(self, g, want_mark=False):
        """写一条礼物：元信息 / 拼音 / 礼物×数量 三行。礼物名不翻译，只加注音。

        ×数量 的位置用 **Text mark** 记下来（为了之后原地更新连击数目）。
        这里刻意**不用 tag**：每条礼物一个独有 tag 会让 Tk 的 tag 表无限增长。
        同样地，mark 也**只给可能需要更新数目的行（连击）建**，而且数量有上限
        （见 _gift_rows_trim）—— 每条都建的话 mark 会泄漏，几千条之后 Tk 会崩。
        """
        t = self.gift_text
        ts = datetime.fromtimestamp((g.get('ts') or 0) / 1000).strftime('%H:%M:%S')
        action = g.get('action') or '投喂'
        t.insert('end', f"{ts}  {g.get('user', '')}  {action}\n", ('meta',))
        if self.cfg.get('show_pinyin', True):
            py = ' '.join(u[1] for u in Pinyin.annotate(g.get('gift') or '') if u[1])
            if py:
                t.insert('end', py + '\n', ('pinyin',))
        t.insert('end', g.get('gift') or '', ('gift',))
        txt = f"  ×{g.get('total') or 1}"
        if want_mark:
            mname = 'giftm%d' % g['_i']
            t.mark_set(mname, 'end-1c')
            t.mark_gravity(mname, 'left')   # 之后在该位置增删，标记本身不动
            g['_mark'] = mname
        t.insert('end', txt, ('num',))
        t.insert('end', '\n', ('meta',))
        g['_mlen'] = len(txt)

    def _gift_follow(self):
        """让礼物栏跟随到底部 —— **节流**执行。

        原来每收一条礼物就做一次 yview() + see()，实测占单条渲染成本的约 70%
        （约 0.9ms/条）。改成：最多每 250ms 跟一次，期间有新增就补一次定时跟随。
        是否跟随由"粘性"标志决定（用户往上翻看历史时不要把他拽回底部）。
        """
        now = time.time()
        if now - self._gift_follow_at < 0.25:
            if self._gift_follow_job is None:
                try:
                    self._gift_follow_job = self.root.after(260, self._gift_follow_now)
                except Exception:
                    pass
            return
        self._gift_follow_now()

    def _gift_follow_now(self):
        self._gift_follow_job = None
        self._gift_follow_at = time.time()
        if not self._gift_sticky:
            return
        try:
            self.gift_text.see('end')
        except Exception:
            pass

    def _gift_on_wheel(self, event=None):
        """用户滚动礼物栏时更新"粘性"：在底部就继续跟随，翻上去就不打扰。"""
        try:
            self._gift_sticky = self.gift_text.yview()[1] > 0.999
        except Exception:
            self._gift_sticky = True

    # 分批重画的粒度：一段大约 100~150ms 的工作量，5 万条时分批进行。
    GIFT_RENDER_CHUNK = 250

    def _gift_render_all(self):
        """整块重画（拼音开关 / 过滤条件变化时用；改名或改字号不用重画）。

        分批写：每批 GIFT_RENDER_CHUNK 条就 after(1) 让出事件循环，直到画完。
        这样即使 5 万条，界面也不会僵住，计数标签会实时显示进度。
        """
        t = self.gift_text
        try:
            if self._gift_render_job:
                self.root.after_cancel(self._gift_render_job)
        except Exception:
            pass
        self._gift_render_job = None
        t.configure(state='normal')
        t.delete('1.0', 'end')
        # 内容被清空后旧的 mark 一并失效，这里同步清掉索引并重新计数
        self.gift_rows.clear()
        for g in self.gifts:
            g.pop('_mark', None)
        self._gift_render_gen = self._gift_render_iter()
        self._gift_render_step()

    def _gift_render_iter(self):
        """生成器：每次 yield 表示"已画够一批"，最后 yield None 表示画完。"""
        shown = 0
        free = 0
        for g in self.gifts:
            if self._gift_is_free(g):
                free += 1
            if not self._gift_should_show(g):
                continue
            self._gift_write(g)
            shown += 1
            if shown % self.GIFT_RENDER_CHUNK == 0:
                yield (shown, free)
        yield None

    def _gift_render_step(self):
        gen = getattr(self, '_gift_render_gen', None)
        if gen is None:
            return
        try:
            res = next(gen)
        except StopIteration:
            res = None
        except Exception:
            res = None
        if res is None:
            self._gift_render_gen = None
            self._gift_render_job = None
            try:
                self.gift_text.configure(state='disabled')
                self.gift_text.see('end')
            except Exception:
                pass
            self._gift_follow_at = time.time()
            self._gift_update_count()
            return
        shown, free = res
        self.gift_shown = shown
        self.gift_free = free
        self._gift_update_count(shown)
        try:
            self._gift_render_job = self.root.after(1, self._gift_render_step)
        except Exception:
            self._gift_render_job = None

    def _gift_render_busy(self):
        return getattr(self, '_gift_render_gen', None) is not None

    def _gift_update_count(self, shown=None):
        """计数标签。**必须 O(1)**：它是每收一条礼物都会被调用的。"""
        total = len(self.gifts)
        s = self.gift_shown if shown is None else shown
        tail = f'（免费 {self.gift_free}）' if self.gift_free else ''
        busy = '　…' if self._gift_render_busy() else ''
        self.gift_count_var.set(f'{s} / {total} 件{tail}'
                                + ('　🔍' if self._gift_query else '') + busy)

    # 只保留最近这么多轮连击用于原地更新。连击都在数秒内完成，
    # 保留几百个足够；否则 combo_id -> 下标的表会随着直播时长无限增长。
    GIFT_COMBO_KEEP = 400

    def _gift_rows_trim(self):
        while len(self.gift_rows) > self.GIFT_COMBO_KEEP:
            k = next(iter(self.gift_rows))
            idx = self.gift_rows.pop(k, None)
            if idx is None or idx >= len(self.gifts):
                continue
            g = self.gifts[idx]
            m = g.pop('_mark', None)
            g.pop('_mlen', None)
            if m:
                try:
                    self.gift_text.mark_unset(m)
                except Exception:
                    pass

    def _on_gift(self, d):
        """收到礼物：同一连击原地更新数目；不同时间送的同一个礼物各占一行。"""
        combo = str(d.get('combo_id') or '')
        idx = self.gift_rows.get(combo) if combo else None
        if idx is not None and idx < len(self.gifts):
            g = self.gifts[idx]
            try:
                # 只保留最终数目；取较大值，避免乱序推送把数字改小
                g['total'] = max(int(g.get('total') or 1), int(d.get('total') or 1))
            except Exception:
                pass
            g['ts'] = d.get('ts') or g.get('ts')
            if self._gift_should_show(g):
                self._gift_update_row(g)
            if combo:
                # 重新放到末尾，避免活跃的连击被 _gift_rows_trim 淘汰
                self.gift_rows.pop(combo, None)
                self.gift_rows[combo] = idx
        else:
            if d.get('merge_only'):
                return          # COMBO_SEND 没有对应行时不新建，避免与 SEND_GIFT 重复
            g = dict(d)
            g['_i'] = len(self.gifts)
            self.gifts.append(g)
            if self._gift_is_free(g):
                self.gift_free += 1
            shown = self._gift_should_show(g)
            if shown and not self._gift_render_busy():
                # 正在分批重画时不直接写 Text —— 那个生成器会遍历到这条新礼物，
                # 这里再写一次就会重复。
                t = self.gift_text
                t.configure(state='normal')
                self._gift_write(g, want_mark=bool(combo))
                t.configure(state='disabled')
                self._gift_follow()
                self.gift_shown += 1
            if combo:
                self.gift_rows[combo] = g['_i']
                self._gift_rows_trim()
            self._gift_update_count()
        try:
            self.dock.broadcast({'type': 'gift', 'gift': {
                'id': g['_i'], 'ts': g.get('ts'), 'user': g.get('user'),
                'gift': g.get('gift'), 'total': g.get('total'),
                'pinyin': ' '.join(u[1] for u in Pinyin.annotate(g.get('gift') or '') if u[1]),
                'free': self._gift_is_free(g)}})
        except Exception:
            pass

    def _gift_update_row(self, g):
        """连击更新：只改那一行的 ×数量，不重排整块（O(1)，与已有条数无关）。"""
        m = g.get('_mark')
        if not m:
            return
        t = self.gift_text
        try:
            start = t.index(m)
        except Exception:
            return                      # 重画过（mark 已失效），跳过即可
        end = f'{m} + {max(0, int(g.get("_mlen") or 0))} chars'
        txt = f"  ×{g.get('total') or 1}"
        t.configure(state='normal')
        t.delete(start, end)
        t.insert(start, txt, ('num',))
        g['_mlen'] = len(txt)
        t.configure(state='disabled')

    def _on_gift_search(self, _e=None):
        # 用普通字符串快照，供 HTTP 线程（停靠页回溯）安全读取
        self._gift_query = self.gift_search_var.get().strip().lower()
        self._gift_render_all()

    def _on_gift_filter_change(self):
        self.cfg['gift_filter_free'] = bool(self.gift_filter_var.get())
        save_config(self.cfg)
        self._gift_render_all()

    def _render_item(self, item):
        """新增或更新一条弹幕。"""
        if item['id'] not in self.feed_items:
            if not self._feed_should_show(item):
                self._feed_count()
                return
            self._feed_add(item)
            self._feed_trim()
            self._feed_count()
        else:
            self._feed_update(item)

    # --------------------------------------------------- 滚动 / 尺寸
    def _feed_yview(self, *args):
        self.feed.yview(*args)
        self._bg_reposition()

    def _feed_scroll(self, units):
        self.feed.yview_scroll(units, 'units')
        self._bg_reposition()

    def _on_feed_wheel(self, event):
        self.feed.yview_scroll(-3 if event.delta > 0 else 3, 'units')
        self._bg_reposition()

    def _on_feed_configure(self, event=None):
        if self._cfg_job:
            try:
                self.root.after_cancel(self._cfg_job)
            except Exception:
                pass
        self._cfg_job = self.root.after(150, self._after_feed_resize)

    def _after_feed_resize(self):
        self._cfg_job = None
        self._feed_relayout(0)
        if self._bg_source:
            self._apply_bg_image()

    # --------------------------------------------------- 背景图
    def _bg_reposition(self):
        """背景图固定在可视区域（不随弹幕滚动），并应用 X/Y 位置偏移。

        位置滑块 -100 ~ 100 表示 ±(画布尺寸/2)：0 = 居中，±100 = 平移到半个画布外。
        """
        if self._bg_item is None:
            return
        try:
            cw = self.feed.winfo_width()
            ch = self.feed.winfo_height()
            iw = self._bg_photo.width() if self._bg_photo else 0
            ih = self._bg_photo.height() if self._bg_photo else 0
            ox = self._cfg_int('feed_bg_offset_x', 0, -100, 100) / 200.0 * cw
            oy = self._cfg_int('feed_bg_offset_y', 0, -100, 100) / 200.0 * ch
            x = (cw - iw) / 2.0 + ox
            y = self.feed.canvasy(0) + (ch - ih) / 2.0 + oy
            self.feed.coords(self._bg_item, x, y)
        except Exception:
            pass

    def _draw_bg_image(self):
        if not self._bg_photo:
            return
        if self._bg_item is None:
            self._bg_item = self.feed.create_image(0, 0, anchor='nw', image=self._bg_photo)
        else:
            self.feed.itemconfigure(self._bg_item, image=self._bg_photo)
        self.feed.tag_lower(self._bg_item)
        self._bg_reposition()

    def _pil_state(self):
        """返回 ('ok' | 'broken' | 'missing', 说明文字)。"""
        try:
            from PIL import Image, ImageTk  # noqa: F401
            return 'ok', 'Pillow 可用：支持 JPG/WEBP，且能平滑缩放'
        except Exception as e:
            try:
                import PIL  # noqa: F401
                return 'broken', ('Pillow 已安装但不可用（%s）→ 只能 PNG/GIF。'
                                  '修复：python -m pip install --force-reinstall pillow' % e)
            except Exception:
                return 'missing', ('未安装 Pillow → 只能 PNG/GIF。'
                                   '想用 JPG：python -m pip install pillow')

    def _refresh_image_support(self):
        if not hasattr(self, 'img_support_var'):
            return
        _state, text = self._pil_state()
        self.img_support_var.set(text)

    # --------------------------------------------------- 背景图：缩放 / 位置 / 不透明度
    @staticmethod
    def _panel_rgb():
        h = THEME['panel'].lstrip('#')
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _tk_has_alpha(img):
        """粗略检测是否存在透明像素（网格抽样，避免逐像素 Tcl 调用）。"""
        try:
            w, h = img.width(), img.height()
            step = max(1, min(w, h) // 24)
            for y in range(0, h, step):
                for x in range(0, w, step):
                    if img.transparency_get(x, y):
                        return True
            return False
        except Exception:
            return False

    @classmethod
    def _flatten_tk_alpha(cls, img):
        """把 Tk 图的透明区压平到面板底色上。

        透明 PNG 直接导出成 PPM 时，透明像素的 RGB 就是 (0,0,0)，会变成黑底。
        这里先铺一层面板色、再把图 copy 上去（实测 Tk 的 copy 会做 alpha 合成），
        视觉上等同"完全透明"（下面本来就是弹幕区底色），也不会出现黑边。
        """
        try:
            if not cls._tk_has_alpha(img):
                return img
            w, h = img.width(), img.height()
            flat = tk.PhotoImage(width=w, height=h)
            flat.put(THEME['panel'], to=(0, 0, w, h))
            flat.tk.call(flat, 'copy', img, '-to', 0, 0)
            return flat
        except Exception:
            return img

    @staticmethod
    def _tk_crop(img, left, top, cw, ch):
        """从 PhotoImage 里裁一块（Tk 没有 crop，用 image copy 实现）。"""
        iw, ih = img.width(), img.height()
        cw = max(1, min(cw, iw))
        ch = max(1, min(ch, ih))
        left = max(0, min(left, iw - cw))
        top = max(0, min(top, ih - ch))
        if cw == iw and ch == ih and left == 0 and top == 0:
            return img
        sub = tk.PhotoImage()
        sub.tk.call(sub, 'copy', img, '-from', left, top, left + cw, top + ch, '-to', 0, 0)
        return sub

    @classmethod
    def _tk_resize_cover(cls, img, tw, th):
        """缩放到「不小于目标尺寸」，再居中裁剪到**精确**的目标尺寸。

        Tk 只能整数倍缩放，所以先用整数倍放大/缩小保证不小于目标，再用裁剪精确落位。
        """
        iw, ih = img.width(), img.height()
        if iw < 1 or ih < 1:
            return img
        ratio = max(tw / float(iw), th / float(ih))
        if ratio > 1:
            f = int(ratio)
            if float(f) < ratio:
                f += 1
            if f > 1:
                img = img.zoom(f, f)
        elif ratio < 1:
            f = int(1.0 / ratio)
            if f > 1:
                img = img.subsample(f, f)
        iw, ih = img.width(), img.height()
        return cls._tk_crop(img, (iw - tw) // 2, (ih - th) // 2, tw, th)

    @staticmethod
    def _blend_opacity(img, opacity, bg_hex):
        """把图片按不透明度与底色混合。

        Tk 的 PhotoImage 没有 alpha 通道，所以导出成 PPM 做像素级混合再装回去：
        逐通道用 bytes.translate 做查表，整段切片赋值 —— 纯 C 速度，一张 760x420 只要几毫秒。
        """
        try:
            a = max(0.0, min(100.0, float(opacity))) / 100.0
            if a >= 1.0:
                return img
            br = int(str(bg_hex)[1:3], 16)
            bg = (br, int(str(bg_hex)[3:5], 16), int(str(bg_hex)[5:7], 16))
            tmp = os.path.join(DATA_DIR, '_bg_blend.ppm')
            try:
                img.write(tmp, format='ppm')
                with open(tmp, 'rb') as f:
                    data = f.read()
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            if not data.startswith(b'P6'):
                return img
            pos = 2
            fields = []
            while len(fields) < 3 and pos < len(data):
                while pos < len(data) and data[pos:pos + 1].isspace():
                    pos += 1
                if data[pos:pos + 1] == b'#':
                    while pos < len(data) and data[pos:pos + 1] != b'\n':
                        pos += 1
                    continue
                start = pos
                while pos < len(data) and not data[pos:pos + 1].isspace():
                    pos += 1
                fields.append(int(data[start:pos]))
            pos += 1
            if len(fields) != 3:
                return img
            body = bytearray(data[pos:])
            if len(body) < 3:
                return img
            tables = [bytes(int(v * a + bg[c] * (1 - a) + 0.5) for v in range(256)) for c in range(3)]
            out = bytearray(body)
            out[0::3] = body[0::3].translate(tables[0])
            out[1::3] = body[1::3].translate(tables[1])
            out[2::3] = body[2::3].translate(tables[2])
            # PPM 要按原始字节传（base64 会被当成 PNG 校验而失败）
            return tk.PhotoImage(data=data[:pos] + bytes(out))
        except Exception:
            return img

    def _load_bg_photo(self, path):
        """加载背景图：按缩放倍率缩放**原始图片**（100% = 原图 1:1，绝不裁剪），
        透明区压平到面板底色，最后按不透明度与底色混合。

        超出弹幕区的部分交给画布自然裁掉（位置滑块需要用到画布外的区域），
        所以这里不会把图"裁成某个尺寸"。
        """
        # 注意：不能用 `int(x or 100)` —— 不透明度 0 是合法值但为 falsy，会被误当成 100
        scale_pct = self._cfg_int('feed_bg_scale', 100, 10, 400)
        opacity = self._cfg_int('feed_bg_opacity', 100, 0, 100)
        scale = scale_pct / 100.0
        panel_rgb = self._panel_rgb()

        # 1) 优先 Pillow（平滑缩放 + JPG/WEBP + 正确的 alpha 处理）
        try:
            from PIL import Image, ImageTk
            im = Image.open(path)
            # 关键：透明 PNG 要压平到面板底色，而不是 convert('RGB')（那样透明区会变黑）
            if im.mode in ('RGBA', 'LA', 'P', 'PA'):
                im = im.convert('RGBA')
                base = Image.new('RGBA', im.size, panel_rgb + (255,))
                im = Image.alpha_composite(base, im)
            im = im.convert('RGB')
            iw, ih = im.size
            # 目标尺寸 = 原图尺寸 × 缩放（等比，不裁剪）
            want_w = max(16, int(round(iw * scale)))
            want_h = max(16, int(round(ih * scale)))
            im = im.resize((want_w, want_h), Image.LANCZOS)
            if opacity < 100:
                a = max(0.0, min(100.0, float(opacity))) / 100.0
                im = Image.blend(im, Image.new('RGB', im.size, panel_rgb), 1.0 - a)
            self._bg_photo = ImageTk.PhotoImage(im)
            return True, f'Pillow 平滑缩放 {scale_pct}%（原图 {iw}x{ih}）· 不透明度 {opacity}%'
        except Exception:
            pass

        # 2) Tk 原生：压平透明 -> 缩放到原图×倍率（不裁剪）-> 像素混合
        try:
            img = tk.PhotoImage(file=path)
            if img.width() < 2 or img.height() < 2:
                return False, '图片尺寸异常'
            src_w, src_h = img.width(), img.height()
            want_w = max(16, int(round(src_w * scale)))
            want_h = max(16, int(round(src_h * scale)))
            img = self._flatten_tk_alpha(img)     # 透明 PNG 不能直接导出 PPM（会变黑）
            img = self._tk_resize_cover(img, want_w, want_h)
            if opacity < 100:
                img = self._blend_opacity(img, opacity, THEME['panel'])
            self._bg_photo = img
            extra = '' if opacity >= 100 else f' · 不透明度 {opacity}%'
            way = '缩小' if scale_pct < 100 else ('放大' if scale_pct > 100 else '原始大小')
            return True, f'Tk 原生缩放 · {way} {scale_pct}%（原图 {src_w}x{src_h}）{extra}'
        except Exception as e:
            _s, adv = self._pil_state()
            return False, f'{e}　|　{adv}'

    def _apply_bg_image(self):
        self._bg_job = None
        path = self._bg_source
        if not path:
            if self._bg_item is not None:
                try:
                    self.feed.delete(self._bg_item)
                except Exception:
                    pass
                self._bg_item = None
            self._bg_photo = None
            return
        ok, msg = self._load_bg_photo(path)
        if not ok:
            self._log(f'背景图加载失败：{msg}')
            if hasattr(self, 'bg_path_var'):
                self.bg_path_var.set(f'{path}\n加载失败：{msg}')
            return
        self._draw_bg_image()
        if hasattr(self, 'bg_path_var'):
            self.bg_path_var.set(f'{path}\n[{msg}]')

    # ---- 背景图滑块（缩放 / 不透明度）----
    @staticmethod
    def _clamp_int(value, default, lo=None, hi=None):
        """把值转成范围内的整数（注意 0 是合法值，不能被当成"空"）。"""
        try:
            v = int(value)
        except Exception:
            v = default
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    def _cfg_int(self, key, default, lo=None, hi=None):
        """读整数配置并钳制范围。

        不能写成 int(cfg.get(key) or default)：像不透明度 0 这种合法但 falsy 的值会被吃掉。
        """
        try:
            v = int(self.cfg.get(key, default))
        except Exception:
            v = default
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    def _bg_sync(self, attr, var, key, value, lo, hi):
        """统一的滑块/数值框同步：更新变量、滑轨位置、配置，并防抖重绘。"""
        pct = self._clamp_int(value, 0, lo, hi)
        var.set(str(pct))
        sl = getattr(self, attr, None)
        if sl is not None:
            try:
                sl.set(pct, fire=False)
            except Exception:
                pass
        self.cfg[key] = pct
        self._bg_slider_changed()
        return pct

    def _on_bg_scale(self, value):
        self._bg_sync('bg_scale', self.bg_scale_var, 'feed_bg_scale', value, 10, 400)

    def _on_bg_opacity(self, value):
        self._bg_sync('bg_opacity', self.bg_opacity_var, 'feed_bg_opacity', value, 0, 100)

    def _on_bg_ox(self, value):
        self._bg_sync('bg_ox', self.bg_ox_var, 'feed_bg_offset_x', value, -100, 100)

    def _on_bg_oy(self, value):
        self._bg_sync('bg_oy', self.bg_oy_var, 'feed_bg_offset_y', value, -100, 100)

    def _fit_bg_to_feed(self):
        """把缩放设为「整张图刚好放进弹幕区」（不裁剪、不放大）。"""
        if not self._bg_source:
            messagebox.showinfo(self.t('bgFit'), '请先选择一张背景图。')
            return
        size = self._image_size(self._bg_source)
        if not size:
            return
        w, h = size
        cw = max(self.feed.winfo_width(), 200)
        ch = max(self.feed.winfo_height(), 200)
        pct = self._clamp_int(min(cw / float(w), ch / float(h)) * 100, 100, 10, 400)
        self._on_bg_scale(pct)
        self._apply_bg_now()
        self._log(f'已按「适应弹幕区」设置为 {pct}%（原图 {w}x{h}）。')

    def _image_size(self, path):
        """取图片原始像素尺寸。"""
        try:
            from PIL import Image
            with Image.open(path) as im:
                return im.size
        except Exception:
            pass
        try:
            img = tk.PhotoImage(file=path)
            return img.width(), img.height()
        except Exception:
            return None

    def _bg_slider_changed(self):
        """拖动过程中防抖重绘（缩放+混合一次约几十毫秒，防抖后手感顺滑）。"""
        if self._bg_slider_job:
            try:
                self.root.after_cancel(self._bg_slider_job)
            except Exception:
                pass
        self._bg_slider_job = self.root.after(150, self._apply_bg_now)

    def _apply_bg_now(self):
        self._bg_slider_job = None
        try:
            save_config(self.cfg)
        except Exception:
            pass
        if self._bg_source:
            self._apply_bg_image()

    def _reset_bg_adjust(self):
        """把缩放 / 不透明度 / 位置全部恢复默认。"""
        for name, val in (('bg_scale', 100), ('bg_opacity', 100), ('bg_ox', 0), ('bg_oy', 0)):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.set(val, fire=False)
                except Exception:
                    pass
        self._on_bg_scale(100)
        self._on_bg_opacity(100)
        self._on_bg_ox(0)
        self._on_bg_oy(0)
        self._apply_bg_now()
        self._log('背景图缩放 / 不透明度 / 位置已恢复默认。')

    def _pick_bg_image(self):
        path = filedialog.askopenfilename(
            title=self.t('bgPick'),
            filetypes=[('图片', '*.png *.gif *.jpg *.jpeg *.bmp *.webp'), ('全部文件', '*.*')])
        if not path:
            return
        self.cfg['feed_bg_image'] = path
        self._bg_source = path
        # 按图片原始尺寸决定初始缩放：
        #   放得下 -> 100%（原图 1:1，不缩放不裁剪）
        #   放不下 -> 等比缩到刚好放得下（保证一进来就能看到整张图，不被裁掉）
        size = self._image_size(path)
        note = ''
        if size:
            w, h = size
            cw = max(self.feed.winfo_width(), 200)
            ch = max(self.feed.winfo_height(), 200)
            if w > cw or h > ch:
                pct = self._clamp_int(min(cw / float(w), ch / float(h)) * 100, 100, 10, 400)
                note = f'原图 {w}x{h}，已缩放到 {pct}% 以便整张可见（未裁剪）'
            else:
                pct = 100
                note = f'原图 {w}x{h}，按原始大小（100%）显示'
            self.cfg['feed_bg_scale'] = pct
            self.bg_scale_var.set(str(pct))
            try:
                self.bg_scale.set(pct, fire=False)
            except Exception:
                pass
        save_config(self.cfg)
        self._apply_bg_image()
        self._log(f'已设置弹幕区背景图：{path}' + (f'（{note}）' if note else ''))

    def _clear_bg_image(self):
        self.cfg['feed_bg_image'] = ''
        save_config(self.cfg)
        self._bg_source = ''
        self._apply_bg_image()
        if hasattr(self, 'bg_path_var'):
            self.bg_path_var.set('')
        self._log('已清除弹幕区背景图。')

    # --------------------------------------------------- 可选：修复 Pillow（支持 JPG）
    @staticmethod
    def _pip_available():
        try:
            import pip  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _site_packages_dir():
        """当前解释器的 site-packages 目录（便携版内嵌运行时也能正确定位）。"""
        try:
            import site
            for p in (site.getsitepackages() or []):
                if 'site-packages' in p:
                    return p
        except Exception:
            pass
        import sysconfig
        try:
            return sysconfig.get_paths()['purelib']
        except Exception:
            return os.path.join(APP_DIR, 'python', 'Lib', 'site-packages')

    def _install_pillow(self):
        if getattr(self, '_pillow_busy', False):
            messagebox.showinfo(self.t('pillowInstall'), '正在安装，请稍候…（进度见下方日志）')
            return
        if self._pip_available():
            how = ('将执行：\n    python -m pip install --force-reinstall pillow\n\n'
                   '（约 3MB，需要联网）')
        else:
            how = ('当前是**便携版**（内嵌运行时没有 pip）。\n'
                   '程序会直接从 PyPI 下载适配本机 Python 的 Pillow 轮子（.whl），\n'
                   '解压到内置的 site-packages 里（不改动系统）。\n\n'
                   '（约 3–5MB，需要联网）')
        if not messagebox.askyesno(
                self.t('pillowInstall'),
                how + '\n安装后可支持 JPG 背景图并做平滑缩放。\n只用 PNG / GIF 的话不需要装。\n\n现在安装吗？'):
            return
        self._pillow_busy = True
        self._log('=== 开始安装 / 修复 Pillow ===')
        threading.Thread(target=self._pillow_task, daemon=True, name='pillow-install').start()

    def _pillow_task(self):
        if self._pip_available():
            rc = self._pillow_via_pip()
        else:
            rc = self._pillow_via_wheel()
        self._pillow_busy = False
        self.gui_queue.put(('pillow_done', rc == 0))

    def _pillow_via_pip(self):
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        cmd = [sys.executable, '-m', 'pip', 'install', '--force-reinstall', 'pillow']
        self.gui_queue.put(('log', 'info', '$ ' + ' '.join(cmd)))
        rc = -1
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding='utf-8', errors='replace',
                                 creationflags=flags)
            for line in p.stdout:
                line = line.rstrip()
                if line:
                    self.gui_queue.put(('log', 'info', line))
            p.wait()
            rc = p.returncode
        except Exception as e:
            self.gui_queue.put(('log', 'info', f'安装出错：{e}'))
        return rc

    def _pillow_via_wheel(self):
        """便携版：从 PyPI 下载对应平台的 whl，解压到 site-packages（无需 pip）。

        注意 ABI 必须精确匹配：普通解释器要 cp314-cp314，自由线程版是 cp314-cp314t。
        名字里只判断 'cp314' 会误选到 cp314t 的轮子，解压后 _imaging 导入失败
        （这就是"Pillow 已安装但不可用"的典型成因）。
        """
        import io
        import sysconfig
        import shutil
        import zipfile
        import urllib.request
        try:
            maj, minr = sys.version_info.major, sys.version_info.minor
            py_tag = f'cp{maj}{minr}'
            free_threaded = bool(sysconfig.get_config_var('Py_GIL_DISABLED'))
            abi_tag = py_tag + ('t' if free_threaded else '')
            self.gui_queue.put(('log', 'info', f'查询 PyPI 上适配 {py_tag}/{abi_tag} win_amd64 的 Pillow 轮子…'))
            j = netutil.get_json('https://pypi.org/pypi/pillow/json', timeout=30)
            urls = j.get('urls') or []

            want = f'-{py_tag}-{abi_tag}-win_amd64.whl'
            pick = next((u for u in urls if (u.get('filename') or '').endswith(want)), None)
            if pick is None:
                def _ok(fn):
                    if not fn.endswith('.whl') or 'win_amd64' not in fn or py_tag not in fn:
                        return False
                    # 非自由线程解释器要排除 cpXXXt 的轮子
                    if not free_threaded and f'{py_tag}t' in fn:
                        return False
                    return True
                pick = next((u for u in urls if _ok(u.get('filename') or '')), None)
            if pick is None:
                self.gui_queue.put(('log', 'info',
                                    f'没有找到适配 {py_tag}/{abi_tag} 的 Pillow 轮子。'))
                return 1

            url = pick['url']
            self.gui_queue.put(('log', 'info', f'下载 {pick.get("filename")}'
                                               f'（{int(pick.get("size") or 0) / 1048576:.1f} MB）…'))
            req = urllib.request.Request(url, headers={'User-Agent': 'AI-MengYiJiang'})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            self.gui_queue.put(('log', 'info', f'已下载 {len(data) / 1048576:.1f} MB，开始解压…'))

            dest = self._site_packages_dir()
            os.makedirs(dest, exist_ok=True)
            # 先清掉旧的 PIL / 元数据，避免新旧混在一起（等价于 pip --force-reinstall）
            try:
                old = os.path.join(dest, 'PIL')
                if os.path.isdir(old):
                    shutil.rmtree(old, ignore_errors=True)
                for n in os.listdir(dest):
                    if n.lower().startswith('pillow') and n.endswith('.dist-info'):
                        shutil.rmtree(os.path.join(dest, n), ignore_errors=True)
            except Exception:
                pass
            self.gui_queue.put(('log', 'info', f'解压到 {dest}'))
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if n.endswith('/') or n.endswith('.dist-info/RECORD'):
                        continue
                    z.extract(n, dest)
            self.gui_queue.put(('log', 'info', '解压完成。'))
            return 0
        except Exception as e:
            self.gui_queue.put(('log', 'info', f'安装出错：{e}'))
            return 1

    def _on_pillow_done(self, ok):
        self._refresh_image_support()
        if ok:
            self._log('Pillow 安装完成。')
            messagebox.showinfo(self.t('pillowInstall'),
                                'Pillow 安装完成。\n请重新点「选择图片」挑一次背景图即可生效。')
        else:
            self._log('Pillow 安装失败，详见上方日志。PNG / GIF 不受影响。')
            messagebox.showerror(self.t('pillowInstall'),
                                 'Pillow 安装失败，详见日志。\n只用 PNG / GIF 的话不受影响。')

    # --------------------------------------------------- 配色切换
    def _theme_name(self, key):
        t = THEMES.get(key) or THEMES[DEFAULT_THEME]
        return t['name_ja'] if self.lang == 'ja' else t['name']

    def _refresh_theme_combo(self, key=None):
        if not hasattr(self, 'theme_combo'):
            return
        self.theme_combo['values'] = [self._theme_name(k) for k in THEME_ORDER]
        k = key or self.cfg.get('theme')
        if k not in THEMES:
            k = DEFAULT_THEME
        self.theme_var.set(self._theme_name(k))

    def _set_theme(self, key, save=True):
        global THEME
        if key not in THEMES:
            key = DEFAULT_THEME
        THEME = dict(THEMES[key])
        if save:
            self.cfg['theme'] = key
            save_config(self.cfg)
        self._apply_theme()
        self._feed_rerender()
        self._apply_bg_image()
        self._refresh_theme_combo(key)

    def _on_theme_pick(self):
        label = self.theme_var.get()
        key = next((k for k in THEME_ORDER if self._theme_name(k) == label), DEFAULT_THEME)
        self._set_theme(key)
        self._log(f'窗口配色已切换为「{self._theme_name(key)}」')

    # ------------------------------------- 1.4.0：拼音注音与字号
    def _dock_settings(self):
        """下发给停靠页的显示设置（拼音 / 字号 / 礼物条数）。"""
        raw, py, trans = apply_feed_fonts(self.cfg)
        try:
            gift_limit = int(self.cfg.get('dock_gift_limit') or 30)
        except Exception:
            gift_limit = 30
        return {'uiLanguage': self.lang,
                'showPinyin': bool(self.cfg.get('show_pinyin', True)),
                'fontRaw': raw, 'fontPinyin': py, 'fontTrans': trans,
                'giftLimit': gift_limit}

    def _push_dock_settings(self):
        try:
            self.dock.settings = self._dock_settings()
            self.dock.broadcast({'type': 'settings', 'settings': self.dock.settings})
        except Exception:
            pass

    def _dock_gifts(self, before, limit):
        """停靠页回溯查询：返回 before（不含）之前最近的 limit 件礼物，时间正序。"""
        try:
            limit = max(1, min(200, int(limit or 30)))
        except Exception:
            limit = 30
        end = len(self.gifts) if before is None or before < 0 else min(int(before), len(self.gifts))
        start = max(0, end - limit)
        out = []
        for g in self.gifts[start:end]:
            if not self._gift_should_show(g):
                continue
            out.append({'id': g.get('_i'), 'ts': g.get('ts'), 'user': g.get('user'),
                        'gift': g.get('gift'), 'total': g.get('total'),
                        'pinyin': ' '.join(u[1] for u in Pinyin.annotate(g.get('gift') or '') if u[1]),
                        'free': self._gift_is_free(g)})
        return out

    def _on_pinyin_toggle(self):
        self.cfg['show_pinyin'] = bool(self.pinyin_var.get())
        save_config(self.cfg)
        self._feed_rerender()
        self._gift_render_all()
        self._push_dock_settings()
        self._log('拼音注音已' + ('开启' if self.cfg['show_pinyin'] else '关闭'))

    def _on_feed_fonts(self):
        """三个字号输入框的变化：钳制成「原文 > 注音 >= 译文」后立即生效。"""
        for key, var in (('feed_font_raw', self.font_raw_var),
                         ('feed_font_pinyin', self.font_pinyin_var),
                         ('feed_font_trans', self.font_trans_var)):
            try:
                self.cfg[key] = int(str(var.get()).strip())
            except Exception:
                pass
        raw, py, trans = apply_feed_fonts(self.cfg)
        self.font_raw_var.set(str(raw))
        self.font_pinyin_var.set(str(py))
        self.font_trans_var.set(str(trans))
        save_config(self.cfg)
        self._feed_rerender()
        self._apply_gift_fonts()
        self._push_dock_settings()

    def _set_status(self, msg, ok=False):
        self.status_var.set(msg)
        self.dot.configure(fg=THEME['ok'] if ok else '#5b6273')

    def _log(self, msg):
        self.log_text.configure(state='normal')
        self.log_text.insert('end', msg + '\n')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
        print(msg)

    # ------------------------------------------------------------- 退出
    def _on_close(self):
        self.closing = True
        self._close_readme()
        self._disconnect_client()
        try:
            if self._web_thread is not None and self._web_thread.is_alive():
                self._web_queue.put(('close', None))
            else:
                for sess in self.web_sessions.values():
                    try:
                        sess.close()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self.dock.stop()
        except Exception:
            pass
        self.root.destroy()


def _show_fatal(title, message):
    """在无控制台（pythonw）时也能让用户看到错误。"""
    try:
        print(f'{title}\n{message}', file=sys.stderr)
    except Exception:
        pass
    try:
        with open(ERROR_LOG, 'w', encoding='utf-8') as f:
            f.write(f'{title}\n{message}\n')
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def main():
    if not tk:
        _show_fatal('AI萌译酱 启动失败：缺少 tkinter',
                    '当前 Python 没有 tkinter 图形库，无法启动桌面窗口。\n\n'
                    f'错误信息：{TK_IMPORT_ERROR}\n\n'
                    '解决办法：\n'
                    '1) 卸载 Microsoft Store 版 Python；\n'
                    '2) 到 https://www.python.org/downloads/windows/ 下载官方安装包；\n'
                    '3) 安装时勾选 “tcl/tk and IDLE” 与 “Add python.exe to PATH”；\n'
                    '4) 重新双击 start.bat。')
        return 1
    try:
        root = tk.Tk()
    except Exception as e:
        _show_fatal('AI萌译酱 启动失败：无法创建窗口',
                    f'{e}\n\n请确认使用的是 python.org 官方版 Python（含 tkinter）。')
        return 1
    try:
        ttk.Style().theme_use('clam')
    except Exception:
        pass
    try:
        App(root)
        root.mainloop()
    except Exception:
        detail = traceback.format_exc()
        _show_fatal('AI萌译酱 运行时错误', detail[-3000:])
        return 1
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        # 只验证能否正常启动（不显示窗口），用于排查问题：python app.py --selftest
        try:
            _root = tk.Tk()
            _root.withdraw()
            _app = App(_root)
            _root.update()
            _app._on_close()
            print(f'SELFTEST OK - {APP_TITLE} / {APP_NAME_JA} 可以正常启动')
            sys.exit(0)
        except Exception:
            _show_fatal('AI萌译酱 自检失败', traceback.format_exc()[-3000:])
            sys.exit(1)
    sys.exit(main())
