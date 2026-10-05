const $ = id => document.getElementById(id);
const messages = new Map();
let lang = 'zh';
const I18N = {
  zh: { title: 'AI萌译酱 主播监控', sub: '仅供主播监控 · 原文 + 日语翻译', disconnected: '未连接', ja: '日语', pending: '待翻译', wait: '翻译中…', err: '翻译错误' },
  ja: { title: '萌AIちゃん 配信者モニター', sub: '配信者専用 · 原文 + 日本語訳', disconnected: '未接続', ja: '日本語', pending: '翻訳待ち', wait: '翻訳中…', err: '翻訳エラー' }
};
function t(k) { return I18N[lang][k] || I18N.zh[k] || k; }

function renderItem(item) {
  let el = document.getElementById('m-' + item.id);
  if (!el) {
    el = document.createElement('div');
    el.className = 'msg';
    el.id = 'm-' + item.id;
    el.innerHTML = '<div class="meta"><span class="user"></span><span class="tag"></span></div><div class="raw"></div><div class="tr"></div>';
    $('feed').appendChild(el);
  }
  el.querySelector('.user').textContent = item.user;
  el.querySelector('.meta .tag').textContent = item.japanese ? t('ja') : (item.translation ? '' : t('pending'));
  el.querySelector('.raw').textContent = item.text;
  const tr = el.querySelector('.tr');
  tr.textContent = item.translation ? ('→ ' + item.translation) : (item.japanese ? '' : t('wait'));
  tr.className = 'tr ' + (item.error ? 'error' : (item.japanese || item.translation ? '' : 'pending'));
  if (item.error) tr.textContent = '⚠ ' + t('err') + ': ' + item.error;
  messages.set(item.id, item);
  while ($('feed').children.length > 200) $('feed').removeChild($('feed').firstChild);
  $('feed').scrollTop = $('feed').scrollHeight;
}

async function init() {
  try {
    const c = await fetch('/api/language').then(r => r.json());
    lang = (c && c.uiLanguage) === 'ja' ? 'ja' : 'zh';
  } catch (e) {}
  $('title').textContent = t('title');
  $('sub').textContent = t('sub');
  $('status').textContent = t('disconnected');
}

const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if (m.type === 'console_message') renderItem(m.item);
  else if (m.type === 'translation') { const i = messages.get(m.id) || { id: m.id }; i.translation = m.translation; renderItem(i); }
  else if (m.type === 'translation_error') { const i = messages.get(m.id) || { id: m.id }; i.error = m.error; renderItem(i); }
  else if (m.type === 'status') { $('status').textContent = m.status.message || t('disconnected'); }
  else if (m.type === 'clear_messages') { messages.clear(); $('feed').innerHTML = ''; }
};
init();
