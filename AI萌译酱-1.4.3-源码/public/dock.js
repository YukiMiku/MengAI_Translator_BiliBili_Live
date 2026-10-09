/* 停靠页前端（1.4.0）
   新增：
     · 原文用原生 <ruby> 逐字注音（拼音由 Python 侧算好一起广播，浏览器不需要拼音库）
     · 下方礼物区：只显示最近 N 条（默认 30），滚到顶部或用「载入更早」往前翻历史
     · 字号 / 拼音开关由 /api/settings 下发，落到 CSS 变量上
*/
const $ = id => document.getElementById(id);
const messages = new Map();
let lang = 'zh';
const I18N = {
  zh: { title: 'AI萌译酱 主播监控', sub: '仅供主播监控 · 原文 + 日语翻译', disconnected: '未连接', ja: '日语', pending: '待翻译', wait: '翻译中…', err: '翻译错误', gift: '礼物', more: '载入更早', noMore: '没有更早的了' },
  ja: { title: '萌AIちゃん 配信者モニター', sub: '配信者専用 · 原文 + 日本語訳', disconnected: '未接続', ja: '日本語', pending: '翻訳待ち', wait: '翻訳中…', err: '翻訳エラー', gift: 'ギフト', more: 'もっと読み込む', noMore: 'これより前はありません' }
};
function t(k) { return I18N[lang][k] || I18N.zh[k] || k; }

let showPinyin = true;
let giftLimit = 30;
let oldestGiftId = null;
let giftTotal = 0;
let giftLoading = false;
let giftNoMore = false;

/* ---------------------------------------------------------------- 注音 */
function rubify(units, fallbackText) {
  const frag = document.createDocumentFragment();
  if (!units || !units.length) {
    frag.appendChild(document.createTextNode(fallbackText || ''));
    return frag;
  }
  for (const u of units) {
    const txt = u[0], py = u[1];
    if (!py || !showPinyin) { frag.appendChild(document.createTextNode(txt)); continue; }
    const rb = document.createElement('ruby');
    rb.appendChild(document.createTextNode(txt));
    const rt = document.createElement('rt');
    rt.textContent = py;
    rb.appendChild(rt);
    frag.appendChild(rb);
  }
  return frag;
}

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
  const raw = el.querySelector('.raw');
  raw.textContent = '';
  raw.appendChild(rubify(item.pinyin, item.text));
  const tr = el.querySelector('.tr');
  tr.textContent = item.translation ? ('→ ' + item.translation) : (item.japanese ? '' : t('wait'));
  tr.className = 'tr ' + (item.error ? 'error' : (item.japanese || item.translation ? '' : 'pending'));
  if (item.error) tr.textContent = '⚠ ' + t('err') + ': ' + item.error;
  messages.set(item.id, item);
  while ($('feed').children.length > 200) $('feed').removeChild($('feed').firstChild);
  $('feed').scrollTop = $('feed').scrollHeight;
}

/* ---------------------------------------------------------------- 礼物 */
function giftNode(g, prepend) {
  const el = document.createElement('div');
  el.className = 'gift' + (g.free ? ' free' : '');
  const time = g.ts ? new Date(g.ts).toLocaleTimeString('ja-JP', { hour12: false }) : '';
  const meta = document.createElement('div');
  meta.className = 'gmeta';
  meta.textContent = time + '  ' + (g.user || '') + '  ' + t('gift');
  el.appendChild(meta);
  if (showPinyin && g.pinyin) {
    const py = document.createElement('div');
    py.className = 'gpy';
    py.textContent = g.pinyin;
    el.appendChild(py);
  }
  const line = document.createElement('div');
  const nm = document.createElement('span');
  nm.className = 'gname';
  nm.textContent = g.gift || '';
  const num = document.createElement('span');
  num.className = 'gnum';
  num.textContent = '×' + (g.total || 1);
  line.appendChild(nm);
  line.appendChild(num);
  el.appendChild(line);
  return el;
}

function applyGiftLimit() {
  const list = $('giftList');
  while (list.children.length > giftLimit) list.removeChild(list.firstChild);
  if (list.children.length) oldestGiftId = list.firstChild.dataset.gid;
  $('giftCount').textContent = list.children.length + ' / ' + giftTotal + ' 件';
}

function addGift(g) {
  const list = $('giftList');
  const exist = g.id !== undefined ? list.querySelector('[data-gid="' + g.id + '"]') : null;
  giftTotal++;
  if (exist) {                       /* 同一连击：原地更新数目 */
    const num = exist.querySelector('.gnum');
    if (num) num.textContent = '×' + (g.total || 1);
    $('giftCount').textContent = list.children.length + ' / ' + giftTotal + ' 件';
    return;
  }
  const node = giftNode(g, false);
  node.dataset.gid = (g.id !== undefined ? g.id : '');
  list.appendChild(node);
  applyGiftLimit();
  $('gifts').scrollTop = $('gifts').scrollHeight;
}

async function loadEarlierGifts() {
  if (giftLoading || giftNoMore || oldestGiftId === null) return;
  giftLoading = true;
  try {
    const r = await fetch('/api/gifts?before=' + encodeURIComponent(oldestGiftId) + '&limit=' + giftLimit);
    const j = await r.json();
    const rows = (j && j.gifts) || [];
    if (!rows.length) { giftNoMore = true; $('giftMore').textContent = t('noMore'); return; }
    const list = $('giftList');
    const box = $('gifts');
    const keep = box.scrollHeight - box.scrollTop;
    const frag = document.createDocumentFragment();
    for (const g of rows) {
      const n = giftNode(g, true);
      n.dataset.gid = (g.id !== undefined ? g.id : '');
      frag.appendChild(n);
    }
    list.insertBefore(frag, list.firstChild);
    if (list.children.length) oldestGiftId = list.firstChild.dataset.gid;
    box.scrollTop = box.scrollHeight - keep;   /* 保持视觉位置不跳 */
  } catch (e) {
  } finally {
    giftLoading = false;
  }
}

$('gifts').addEventListener('scroll', () => { if ($('gifts').scrollTop <= 4) loadEarlierGifts(); });
$('giftMore').addEventListener('click', loadEarlierGifts);

/* ---------------------------------------------------------------- 设置 */
function applySettings(s) {
  if (!s) return;
  if (s.uiLanguage) lang = s.uiLanguage === 'ja' ? 'ja' : 'zh';
  if (s.showPinyin !== undefined) showPinyin = s.showPinyin !== false;
  const root = document.documentElement.style;
  if (s.fontRaw) root.setProperty('--f-raw', s.fontRaw + 'px');
  if (s.fontPinyin) root.setProperty('--f-py', s.fontPinyin + 'px');
  if (s.fontTrans) root.setProperty('--f-tr', s.fontTrans + 'px');
  if (s.giftLimit) giftLimit = s.giftLimit;
  $('title').textContent = t('title');
  $('sub').textContent = t('sub');
  $('giftTitle').textContent = t('gift');
  if (!giftNoMore) $('giftMore').textContent = t('more');
  $('status').textContent = $('status').textContent || t('disconnected');
  applyGiftLimit();
}

async function init() {
  try {
    const s = await fetch('/api/settings').then(r => r.json());
    applySettings(s);
  } catch (e) {
    try {
      const c = await fetch('/api/language').then(r => r.json());
      if (c && c.uiLanguage) lang = c.uiLanguage === 'ja' ? 'ja' : 'zh';
    } catch (e2) {}
    $('title').textContent = t('title');
    $('sub').textContent = t('sub');
    $('giftTitle').textContent = t('gift');
    $('giftMore').textContent = t('more');
    $('status').textContent = t('disconnected');
  }
}

const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if (m.type === 'console_message') renderItem(m.item);
  else if (m.type === 'translation') { const i = messages.get(m.id) || { id: m.id }; i.translation = m.translation; renderItem(i); }
  else if (m.type === 'translation_error') { const i = messages.get(m.id) || { id: m.id }; i.error = m.error; renderItem(i); }
  else if (m.type === 'status') { $('status').textContent = m.status.message || t('disconnected'); }
  else if (m.type === 'clear_messages') { messages.clear(); $('feed').innerHTML = ''; }
  else if (m.type === 'gift') addGift(m.gift || {});
  else if (m.type === 'settings') applySettings(m.settings);
};
init();
