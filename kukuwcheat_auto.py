# -*- coding: utf-8 -*-
"""
KUKUWCheat · 在线打字测试自动打字脚本（https://dazi.kukuw.com/）

这是命令行版（也是给图形界面版复用的核心模块）：自己开浏览器、选文章、按真人节奏逐字敲。

原理
----
1. 用 Selenium 打开 https://dazi.kukuw.com/ ，选择"测试类型 / 文章 / 时间"后点击"开始测试"；
2. 实时读取测试页面的源代码（driver.page_source），解析出每一行需要打的文字：
   每行是 <div id="i_N" class="typing">，里面的隐藏 input 的 value 就是该行目标文本；
3. 一个字一个字地敲进当前激活的输入框（不是整行粘贴）。

注意
----
站点在 typing.js 里写死了 `document.body.onpaste = function(){return!1}`（禁止粘贴/复制/剪切），
真正的 Ctrl+V 会被浏览器取消，所以脚本改用"合成 keydown -> input -> keyup 事件"的方式打字，
并且在事件里补上 keyCode，避免站点脚本取值时报错导致无法换行。

用法
----
    pip install selenium
    python kukuwcheat_auto.py                          # 中文打字，5 分钟，默认文章（游客身份）
    python kukuwcheat_auto.py --type en                # 英文打字
    python kukuwcheat_auto.py --type group --art 271373        # 竞赛（ID 见首页竞赛列表）
    python kukuwcheat_auto.py --type group2 --code 邀请码       # 竞赛（邀请码）
    python kukuwcheat_auto.py --user 名字 --password 密码   # 先登录，成绩记到账号上
    python kukuwcheat_auto.py --type cn --art 5 --minutes 3
    python kukuwcheat_auto.py --interval 0.3 --jitter 0.1   # 每字 0.3±0.1 秒（约 200 字/分钟）
    python kukuwcheat_auto.py --error-rate 1.5         # 每 100 字故意打错 1.5 个再退格改回来
    python kukuwcheat_auto.py --headless --close       # 无界面运行，跑完自动关闭

打字节奏
--------
不是整行灌进去，而是一个字一个字地敲：每个字都补出 keydown -> input -> keyup 三种事件
（打中文时还会先敲一遍拼音字母），字与字之间的间隔在"平均值 ± 浮动范围"里随机取值
（--interval / --jitter）。默认还会偶发打错字并自己退格改回来（--error-rate，默认 1%），
站点的"退格次数"就和人一样不是 0。

注意测试时间要够：字数 × 平均间隔就是大概要用的时长，时间到了站点会按已打的内容直接结算。

登录说明
--------
站点用 my_typing.php?do=index 上的表单登录（user / pass / action=login）。
注意：只要 cookie 里有身份（哪怕只是游客），站点就不再显示登录表单，所以登录前会先清 cookie。
本脚本给浏览器用了固定的用户目录（.browser_profile），登录状态跨次运行有效，不用每次重登。
游客身份（游客xxxxxxx）不计入账号数据。
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from html.parser import HTMLParser


def app_dir():
    """程序所在目录：脚本方式运行时是脚本目录，打包成 exe 后是 exe 所在目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """放浏览器用户目录和登录备份的地方。

    绿色版（exe 放在桌面等可写位置）就直接放在 exe 旁边，整个目录拷走也能用；
    装到 Program Files 这类普通用户没有写权限的位置时，退到 %LOCALAPPDATA%\\KUKUWCheat，
    否则用户目录建不起来，登录状态也留不住。
    """
    base = app_dir()
    if os.access(base, os.W_OK):
        return base
    fallback = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'KUKUWCheat')
    os.makedirs(fallback, exist_ok=True)
    return fallback


# 同目录下的 _libs 是随脚本一起放的 selenium 依赖；如果已经 pip install selenium 可以把它删掉
_LIBS = os.path.join(app_dir(), '_libs')
if os.path.isdir(_LIBS):
    sys.path.insert(0, _LIBS)

from selenium import webdriver  # noqa: E402
from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException, WebDriverException  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

HOME = 'https://dazi.kukuw.com/'
LOGIN_PAGE = HOME + 'my_typing.php?do=index'      # 登录表单所在页，POST 到 ?do=index
TYPING_READY = (By.CSS_SELECTOR, '#content div.typing')
GUEST_PREFIX = '游客'                              # 首页上游客身份的写法：游客1234567
_DATA_DIR = data_dir()
PROFILE_DIR = os.path.join(_DATA_DIR, '.browser_profile')       # 浏览器用户目录（登录状态）
COOKIE_FILE = os.path.join(_DATA_DIR, '.login_cookies.json')    # 登录 cookie 备份

# 首页上"竞赛"列表：每个竞赛是一个 <a id="jingsai_a_<id>" onclick="select_art(this,<id>,<分钟>)">
COMPETITIONS_JS = r"""
var out = [], links = document.querySelectorAll('#select_v_group a');
for (var i = 0; i < links.length; i++) {
    var a = links[i];
    var m = /select_art\(this,(\d+),(\d+)\)/.exec(a.getAttribute('onclick') || '');
    if (!m) continue;
    var first = a.childNodes[0];
    var name = (first && first.nodeValue ? first.nodeValue : a.textContent).trim();
    var span = a.getElementsByTagName('span')[0];
    out.push({id: m[1], minutes: parseInt(m[2], 10), name: name, info: span ? span.textContent.trim() : ''});
}
return out;
"""

# 选中指定的竞赛（等价于点击它的链接）
PICK_COMPETITION_JS = r"""
var a = document.getElementById('jingsai_a_' + arguments[0]);
if (!a) return 'NOT_FOUND';
var m = /select_art\(this,(\d+),(\d+)\)/.exec(a.getAttribute('onclick') || '');
select_art(a, arguments[0], m ? m[2] : '');
var b = document.getElementById('select_b');     // select_art 会把选择面板展开，挡住"开始测试"，这里收起来
if (b && b.className == 'select_b_on') select_art_show();
return 'OK';
"""

# 往当前行里"敲"一个字：按真实键盘的顺序补出 keydown -> input -> keyup 三种事件，
# 让站点的计时/按键统计（typing.js 里的 w 数组，会随成绩提交）看起来是真人在敲。
#
# 中文还要多一步：真人是用输入法打拼音再上屏的，站点的按键统计只认字母键码，
# 汉字用的 229 会被它整个忽略（统计字段会是空的，这本身就是个破绽）。
# 所以这里先按页面自带的拼音数据把拼音字母敲一遍（只按键、不产生字符），再"上屏"这个字。
TYPE_CHAR_JS = r"""
var divs = document.querySelectorAll('#content div.typing');   // 注意：input 也带 typing 类，必须限定 div
var box = null, lineIdx = -1;
for (var i = 0; i < divs.length; i++) {
    // 站点用 "typing_on" 标记当前正在输入的那一行（写完的行仍然可编辑，不能只看 readOnly）
    if (divs[i].className.indexOf('typing_on') >= 0) {
        box = divs[i].getElementsByTagName('input')[1];
        lineIdx = i;
        break;
    }
}
if (!box) return 'NONE';
var ch = arguments[0];
function fire(type, code, key) {
    var e = new KeyboardEvent(type, {bubbles: true, cancelable: true, key: key});
    Object.defineProperty(e, 'keyCode', {get: function () { return code; }});
    Object.defineProperty(e, 'which', {get: function () { return code; }});
    box.dispatchEvent(e);
}
// 中文先敲拼音字母（页面自带的 pinyin 数据按"行-字位置"给出拼音，带声调，先去声调）
var isCn = ch.charCodeAt(0) > 127;
if (isCn && typeof pinyin !== 'undefined' && pinyin[lineIdx]) {
    var py = pinyin[lineIdx][box.value.length] || '';
    py = py.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/ɡ/g, 'g');
    for (var i = 0; i < py.length; i++) {
        var c = py.charCodeAt(i);
        if (c < 97 || c > 122) continue;                 // 只处理 a-z
        fire('keydown', c - 32, py[i]);
        fire('keyup', c - 32, py[i]);
    }
}
// 上屏这个字（中文走输入法键码 229，英文字母用它自己的键码）
var code = isCn ? 229 : ch.toUpperCase().charCodeAt(0);
fire('keydown', code, ch);              // 按下
box.value = box.value + ch;             // 字进到输入框
var ie = new Event('input', {bubbles: true});
Object.defineProperty(ie, 'keyCode', {get: function () { return code; }});
Object.defineProperty(ie, 'which', {get: function () { return code; }});
box.dispatchEvent(ie);
fire('keyup', code, ch);                // 抬起
return 'OK';
"""

# 按退格键删掉刚打的那个字（真实键盘顺序：keydown -> 值少一个字 -> input -> keyup）
BACKSPACE_JS = r"""
var divs = document.querySelectorAll('#content div.typing');
var box = null;
for (var i = 0; i < divs.length; i++) {
    if (divs[i].className.indexOf('typing_on') >= 0) {
        box = divs[i].getElementsByTagName('input')[1];
        break;
    }
}
if (!box || !box.value.length) return 'NONE';
function fireBS(type) {
    var e = new KeyboardEvent(type, {bubbles: true, cancelable: true, key: 'Backspace'});
    Object.defineProperty(e, 'keyCode', {get: function () { return 8; }});
    Object.defineProperty(e, 'which', {get: function () { return 8; }});
    box.dispatchEvent(e);
}
fireBS('keydown');
box.value = box.value.substring(0, box.value.length - 1);
var ie = new Event('input', {bubbles: true});
Object.defineProperty(ie, 'keyCode', {get: function () { return 8; }});
Object.defineProperty(ie, 'which', {get: function () { return 8; }});
box.dispatchEvent(ie);
fireBS('keyup');
return 'OK';
"""

# 给这个位置挑一个"看起来像打错"的字：
#   中文 —— 优先找同音字（用页面自带的拼音数据），像选错了候选字；
#   英文 —— 挑键盘上挨着的键，这是最常见的打字错误。
# 找不到合适的就返回空字符串（这次不打错）。
TYPO_CHAR_JS = r"""
var target = arguments[0];
var divs = document.querySelectorAll('#content div.typing');
var box = null, lineIdx = -1;
for (var i = 0; i < divs.length; i++) {
    if (divs[i].className.indexOf('typing_on') >= 0) {
        box = divs[i].getElementsByTagName('input')[1];
        lineIdx = i;
        break;
    }
}
if (!box) return '';
if (target.charCodeAt(0) > 127) {
    if (typeof pinyin === 'undefined' || !pinyin[lineIdx]) return '';
    var want = pinyin[lineIdx][box.value.length];
    if (!want) return '';
    var wantBase = want.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    var looser = '';
    for (var k in pinyin) {
        var row = pinyin[k];
        if (!row) continue;
        for (var p in row) {
            var py = row[p];
            if (!py) continue;
            var sameTone = (py === want);
            var sameBase = (py.normalize('NFD').replace(/[\u0300-\u036f]/g, '') === wantBase);
            if (!sameTone && !sameBase) continue;
            var text = divs[k].getElementsByTagName('input')[0].value;
            var ch = text.charAt(parseInt(p, 10));
            if (!ch || ch === target || ch.charCodeAt(0) <= 127) continue;
            if (sameTone) return ch;             // 完全同音最像真人选错候选字
            if (!looser) looser = ch;            // 声调不同的先留着当备选
        }
    }
    return looser;
}
var NEIGH = {
    a: 'sqzw', b: 'vghn', c: 'xdfv', d: 'serfcx', e: 'wsdr', f: 'drtgvc', g: 'ftyhbv',
    h: 'gyujnb', i: 'ujko', j: 'huikmn', k: 'jiolm', l: 'kop', m: 'njk', n: 'bhjm',
    o: 'iklp', p: 'ol', q: 'wa', r: 'edft', s: 'awedxz', t: 'rfgy', u: 'yhj',
    v: 'cfgb', w: 'qase', x: 'zsdc', y: 'tghu', z: 'asx'
};
var near = NEIGH[target.toLowerCase()];
if (!near) return '';
var pick = near.charAt(Math.floor(Math.random() * near.length));
return (target === target.toUpperCase() && /[A-Z]/.test(target)) ? pick.toUpperCase() : pick;
"""

# 当前正在输入的行号（没有则为 -1）
ACTIVE_LINE_JS = r"""
var d = document.querySelectorAll('#content div.typing');
for (var i = 0; i < d.length; i++) {
    if (d[i].className.indexOf('typing_on') >= 0) return i;
}
return -1;
"""


class LineParser(HTMLParser):
    """从测试页源码中取出每一行的目标文本（隐藏 input 的 value / 展示出来的 span 文本）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self._cur = None
        self._in_span = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'div':
            cls = (a.get('class') or '').split()
            div_id = a.get('id') or ''
            if 'typing' in cls and div_id.startswith('i_') and div_id[2:].isdigit():
                self._cur = {'value': None, 'text': ''}
                self.lines.append(self._cur)
        elif self._cur is not None and tag == 'input':
            if a.get('type') == 'hidden' and self._cur['value'] is None:
                self._cur['value'] = a.get('value') or ''
            elif 'typing' in (a.get('class') or '').split():
                self._cur = None  # 该行结束
        elif self._cur is not None and tag == 'span':
            self._in_span = True

    def handle_endtag(self, tag):
        if tag == 'span':
            self._in_span = False

    def handle_data(self, data):
        if self._cur is not None and self._in_span:
            self._cur['text'] += data


def parse_lines(page_source):
    p = LineParser()
    p.feed(page_source)
    return [(item['value'] if item['value'] else item['text']) for item in p.lines if (item['value'] or item['text'])]


def run_powershell(script, timeout=30):
    """跑一段 PowerShell 脚本，返回 CompletedProcess。

    用 -EncodedCommand（Base64/UTF-16LE）而不是 -Command：路径里带中文时，
    -Command 在部分控制台代码页下会被 PowerShell 解码错（乱码成别的路径），
    命令会悄悄做错事甚至失败；编码后传参就不受代码页影响。
    """
    import base64
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return subprocess.run(['powershell', '-NoProfile', '-EncodedCommand', encoded],
                          capture_output=True, timeout=timeout)


def kill_profile_browsers():
    """结束还占着本项目浏览器用户目录的残留浏览器进程，返回结束掉的个数。

    只按命令行里的 .browser_profile 路径匹配 —— 也就是只动本程序自己开出来的浏览器，
    不会碰你日常在用的 Edge/Chrome（它们用的是默认用户目录）。
    """
    if os.name != 'nt':
        return 0
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
          "Write-Output 'killed' }" % PROFILE_DIR)
    try:
        out = run_powershell(ps, timeout=30)
        return len([x for x in (out.stdout or b'').decode('gbk', 'replace').splitlines() if x.strip()])
    except Exception:
        return 0


# 与打字无关的浏览器后台功能，关掉可以少起进程、少占内存和网络
BROWSER_FLAGS = [
    '--disable-gpu',                    # 打字测试用不上 GPU，省掉一个 GPU 进程
    '--disable-extensions',
    '--disable-background-networking',  # 组件更新、翻译、同步等后台请求
    '--disable-sync',
    '--no-first-run',
    '--no-default-browser-check',
    '--log-level=3',                    # 只报致命错误，少写日志
]

# 页面上的第三方统计和广告：不参与打字，但会一直跑定时器、发请求、占内存，直接拦掉。
# 只动这几个明确无关的域名，站点自己的 js / 接口（dazi.kukuw.com）一个都不碰。
BLOCKED_URLS = [
    '*://hm.baidu.com/*',      # 百度统计
    '*://*.cnzz.com/*',        # 页脚的访问统计
    '*://h1.kukuw.com/*',      # 页脚广告位
]


def block_third_party(driver):
    """让浏览器不去请求第三方统计/广告（CDP 不支持时就算了，不影响正常使用）。"""
    try:
        driver.execute_cdp_cmd('Network.enable', {})
        driver.execute_cdp_cmd('Network.setBlockedURLs', {'urls': BLOCKED_URLS})
    except WebDriverException:
        pass


def build_driver(browser, headless, log=print):
    browser = (browser or '').lower()

    def make(kind, use_profile):
        if kind == 'edge':
            from selenium.webdriver.edge.options import Options as EdgeOptions
            opts = EdgeOptions()
        else:
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            opts = ChromeOptions()
        opts.add_argument('--window-size=1440,900')
        # 用独立且固定的用户目录：登录状态（cookie）能跨次运行保留，不用每次重新登录
        if use_profile:
            opts.add_argument('--user-data-dir=' + PROFILE_DIR)
        if headless:
            opts.add_argument('--headless=new')
        for flag in BROWSER_FLAGS:
            opts.add_argument(flag)
        driver = webdriver.Edge(options=opts) if kind == 'edge' else webdriver.Chrome(options=opts)
        block_third_party(driver)
        return driver

    log = log or (lambda msg: None)
    order = ['edge', 'chrome'] if browser in ('', 'auto', 'edge') else [browser]
    last_err = None
    for kind in order:
        for use_profile in (True, False):
            # 同一个用户目录不能被两个浏览器实例同时使用：上一次的浏览器如果还在退出，
            # 等几秒重试通常就能用上（用上才能保留登录状态）
            for attempt in range(3 if use_profile else 1):
                try:
                    return make(kind, use_profile)
                except WebDriverException as e:
                    last_err = e
                    if use_profile and attempt < 2:
                        time.sleep(1.5)
            if use_profile:
                # 还占用着，多半是上次的浏览器没退干净（比如上个会话被强杀），清掉自己的残留再试一次
                killed = kill_profile_browsers()
                if killed:
                    log('提示：发现 %d 个残留浏览器进程占着用户目录（上次没退干净），已清理并重试。' % killed)
                    time.sleep(1.0)
                    try:
                        return make(kind, True)
                    except WebDriverException as e:
                        last_err = e
                log('提示：浏览器用户目录 .browser_profile 被占用，本次改用临时目录（登录状态不会保留）。'
                    '如果同时开着一个本程序窗口，关掉多余的窗口再重开即可。')
        log('启动 %s 失败：%s' % (kind, str(last_err).splitlines()[0]))
    raise SystemExit('无法启动浏览器：%s' % last_err)


def start_test(driver):
    """点击"开始测试"；偶尔会被展开的选择面板挡住，那种情况改用 JS 点击。"""
    btn = driver.find_element(By.CSS_SELECTOR, "input[name='start_button']")
    try:
        btn.click()
    except WebDriverException:
        driver.execute_script('arguments[0].click();', btn)


def wait_active_line(driver, idx, timeout=10):
    """等第 idx 行成为当前行（站点换行是在事件处理里异步做的）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cur = driver.execute_script(ACTIVE_LINE_JS)
        if cur == idx:
            return True
        if cur < 0:                       # 没有可输入的行了（打完了或超时结束）
            return False
        time.sleep(0.05)
    return False


def delay_range(avg, jitter):
    """每字间隔的随机区间 (low, high)。

    正常情况是 avg±jitter。但 jitter 比 avg 还大时，下限最低只能压到 0.01 秒，
    这时必须把上限同步压低，否则平均值会被单边撑大（设 0.1 秒却打出 0.3 秒的节奏）。
    """
    floor = 0.01
    low, high = avg - jitter, avg + jitter
    if low < floor:                     # 下限被抬高 -> 上限压回去，保住平均值
        low, high = floor, 2 * avg - floor
    if high < low:                      # avg 本身比下限还小时的兜底
        high = low
    return low, high


def char_delay(avg, jitter):
    """一个字到下个字之间的间隔：随机取值，平均值等于 avg。"""
    low, high = delay_range(avg, jitter)
    return random.uniform(low, high)


# 打错字之后"愣一下"再退格：这段时间按平均间隔的倍数随机取
TYPO_PAUSE = (2.5, 6.0)
# 每个错字比正常一个字多花的时间（按平均间隔折算）：顿一下 + 退格后补的那次间隔
TYPO_EXTRA = 1 + sum(TYPO_PAUSE) / 2

# 读网页统计的间隔。站点自己的统计（倒计时/速度/正确率/错误/总字数/退格）在 typing.js 里
# 每 100 毫秒刷一次，这里跟着它走，界面上的数字就不会一跳一跳的。
POLL_INTERVAL = 0.1


def interval_for_speed(speed, error_rate=0.0):
    """由目标速度反推每字平均间隔（秒）。

    速度按站点"速度"栏的口径算：正确字数 / 净打字时间，单位是"字/分"
    （站点把中文测试标成 WPM、英文标成 KPM，数值其实都是每分钟的字数）。

    打错字会拖慢速度 —— 每个错字要多花 TYPO_EXTRA 个字的时间，
    所以这里按打错率把间隔反向压短一点，让站点最后算出来的速度落在目标上。
    """
    p = max(0.0, error_rate) / 100.0
    return 60.0 / (speed * (1 + TYPO_EXTRA * p))


def speed_for_interval(avg, error_rate=0.0):
    """由每字平均间隔和打错率，算出站点口径的预计速度（字/分）。"""
    p = max(0.0, error_rate) / 100.0
    return 60.0 / (avg * (1 + TYPO_EXTRA * p))


def autotype(driver, lines, avg=0.3, jitter=0.1, error_rate=0.0, should_stop=None, on_char=None,
             should_pause=None, on_pause=None, poll=None):
    """逐行、逐字敲完整个文章，模拟真人：每字间隔在 avg±jitter 秒之间随机抖动。

    error_rate 是打错的概率（百分比，0 表示不打错）。打错的字会像真人那样补回来：
    敲错 -> 愣一下 -> 退格删掉 -> 重新敲对，站点的"退格次数"就会是真实数字。

    暂停：should_pause() 返回 True 时就地停住不敲字，返回 False 后再接着敲；
    进入/退出暂停各回调一次 on_pause(True/False)，方便调用方同时暂停别的东西。

    poll：每敲完一个字（含敲错/退格）立刻回调一次，另外每字之间的等待里也按
    POLL_INTERVAL 秒回调一次 —— 界面才能跟着每一个按键实时刷新，而不是等下一次轮询。
    读页面的耗时算在等待时间里，不拖慢打字节奏。

    返回 (写完的行数, 敲出的字数)。
    """
    done_lines = 0
    done_chars = 0

    def flush():
        """把网页当前状态马上读一次推给界面（每个按键之后调用）。"""
        if poll:
            poll()

    def wait(seconds):
        """等 seconds 秒。有 poll 时把等待切成小片，到点就回调一次刷新统计。"""
        end = time.time() + seconds
        while True:
            left = end - time.time()
            if poll is None or left < POLL_INTERVAL:
                if left > 0:
                    time.sleep(left)
                return
            time.sleep(POLL_INTERVAL)
            poll()

    for idx, text in enumerate(lines):
        if should_stop and should_stop():
            break
        if not wait_active_line(driver, idx):
            break
        finished = True
        for ch in text:
            if should_pause and should_pause():        # 暂停中：原地等，不敲字
                if on_pause:
                    on_pause(True)
                while should_pause() and not (should_stop and should_stop()):
                    if poll:                           # 网页上的倒计时/统计照常刷新
                        poll()
                    time.sleep(POLL_INTERVAL)
                if on_pause:
                    on_pause(False)
            if should_stop and should_stop():
                finished = False
                break
            if error_rate > 0 and random.random() * 100 < error_rate:
                wrong = driver.execute_script(TYPO_CHAR_JS, ch)
                if wrong:
                    driver.execute_script(TYPE_CHAR_JS, wrong)                 # 先敲错
                    flush()
                    wait(char_delay(avg, jitter) * random.uniform(*TYPO_PAUSE))   # 发现打错了，顿一下
                    driver.execute_script(BACKSPACE_JS)                        # 退格删掉
                    flush()
                    wait(char_delay(avg, jitter))
            if driver.execute_script(TYPE_CHAR_JS, ch) != 'OK':
                finished = False
                break
            done_chars += 1
            if on_char:
                on_char(idx, done_chars, len(text))
            flush()                                    # 敲完这个字立刻刷新，不等下一次轮询
            wait(char_delay(avg, jitter))
        if not finished:
            break
        done_lines += 1
    return done_lines, done_chars


def home_user(driver):
    """打开首页，读当前身份：游客xxxxxxx（未登录）或账号名（已登录）。"""
    driver.get(HOME)
    return home_name(driver)


def open_login_page(driver):
    """打开登录页。站点只要发现 cookie 里有身份（哪怕是游客）就不再显示登录表单，
    所以需要先清掉 cookie，登录表单才会出来。"""
    driver.get(LOGIN_PAGE)
    if not driver.find_elements(By.ID, 'pass'):
        driver.get(HOME)
        driver.delete_all_cookies()
        driver.get(LOGIN_PAGE)
    return driver.find_elements(By.ID, 'pass')


def save_cookies(driver):
    """把当前 cookie 存一份到文件。登录状态本来只存在浏览器用户目录里，
    一旦那个目录用不上（比如被上一个浏览器占着、退回了临时目录），登录就丢了；
    有了这份备份，换任何用户目录都能把登录恢复回来。"""
    try:
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            json.dump(driver.get_cookies(), f, ensure_ascii=False)
    except (OSError, WebDriverException):
        pass


def restore_cookies(driver):
    """把保存的 cookie 灌回浏览器，返回灌进去的条数。"""
    try:
        with open(COOKIE_FILE, encoding='utf-8') as f:
            cookies = json.load(f)
    except (OSError, ValueError):
        return 0
    n = 0
    for c in cookies:
        item = {k: c[k] for k in ('name', 'value', 'path', 'domain', 'secure', 'httpOnly') if k in c}
        try:
            driver.add_cookie(item)
            n += 1
        except WebDriverException:
            pass
    if n:
        driver.refresh()          # 让 cookie 生效
    return n


def home_name(driver):
    """读当前页面上的身份（首页的 #name：游客xxxx 或账号名）。"""
    try:
        return (driver.find_element(By.ID, 'name').get_attribute('value') or '').strip()
    except WebDriverException:
        return ''


def restore_login_if_needed(driver):
    """当前不是登录状态时，才用备份的 cookie 恢复，返回 (账号名, 是否用了备份)。

    已经是登录状态就绝不覆盖 —— 备份是旧的，覆盖反而可能把有效登录顶掉。
    """
    name = home_name(driver)
    if name and not name.startswith(GUEST_PREFIX):
        return name, False
    if not restore_cookies(driver):
        return name, False
    return home_name(driver), True


def login_by_password(driver, user, password):
    """账号密码登录，返回 (账号名, 提示信息)；失败时账号名为空字符串。"""
    if not open_login_page(driver):
        return '', '打不开登录表单'
    box = driver.find_element(By.ID, 'name')       # 该页的 #name 是用户名的输入框
    box.clear()
    box.send_keys(user)
    box = driver.find_element(By.ID, 'pass')
    box.clear()
    if password:
        box.send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "input[name='submit']").click()
    time.sleep(1.2)

    tips = driver.find_elements(By.CSS_SELECTOR, '.login_info')
    msg = tips[0].text.strip() if tips else ''
    name = home_user(driver)          # 回首页看身份：首页的 #name 决定成绩记到谁头上
    if name and not name.startswith(GUEST_PREFIX):
        save_cookies(driver)          # 存一份 cookie，换用户目录也能恢复登录
        return name, ''
    return '', msg or '登录失败'


def open_qr_login(driver):
    """打开"微信扫码登录"弹窗，返回二维码图片元素（需要能看见的浏览器窗口才能扫）。"""
    open_login_page(driver)
    driver.execute_script("qr_code_img('login');")
    return WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'img.qr_img')))


def wait_qr_login(driver, timeout=180, should_stop=None):
    """等扫码完成（扫完还要在浏览器里点一下【完成】），返回 (账号名, 提示信息)。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if should_stop and should_stop():
            return '', '已取消'
        try:
            # 点【完成】后会跳到 login.php?do=wxlogin，或者登录表单直接消失
            if 'wxlogin' in driver.current_url or not driver.find_elements(By.ID, 'pass'):
                time.sleep(1.0)
                name = home_user(driver)
                if name and not name.startswith(GUEST_PREFIX):
                    return name, ''
                return '', '没有检测到登录成功（扫码后需在页面里点【完成】）'
        except WebDriverException:
            pass
        time.sleep(1.5)
    return '', '扫码登录超时'


def main():
    ap = argparse.ArgumentParser(description='KUKUWCheat · dazi.kukuw.com 打字测试自动打字')
    ap.add_argument('--type', choices=['cn', 'en', 'group', 'group2'], default='cn',
                    help='cn 中文 / en 英文 / group 竞赛 / group2 竞赛(邀请码)')
    ap.add_argument('--art', default=None, help='文章 ID；--type group 时是竞赛 ID')
    ap.add_argument('--code', default=None, help='竞赛邀请码（--type group2 时必填）')
    ap.add_argument('--minutes', type=int, default=5, help='测试时间，1-50 分钟（默认 5；竞赛由竞赛本身定）')
    ap.add_argument('--interval', type=float, default=0.3, help='每个字的平均间隔秒数（默认 0.3，约 200 字/分钟）')
    ap.add_argument('--jitter', type=float, default=0.1, help='每字间隔的随机浮动范围 ±秒（默认 0.1）')
    ap.add_argument('--error-rate', type=float, default=1.0,
                    help='打错字的概率百分比（默认 1，会自动退格改回来；0 表示不故意打错）')
    ap.add_argument('--browser', default='auto', help='edge / chrome / auto（默认 auto）')
    ap.add_argument('--user', default=None, help='登录用户名（不填就是游客身份，成绩不计入账号）')
    ap.add_argument('--password', default='', help='登录密码（账号没有密码就留空）')
    ap.add_argument('--headless', action='store_true', help='无界面模式运行')
    ap.add_argument('--close', action='store_true', help='跑完后直接关闭浏览器（默认保留窗口）')
    args = ap.parse_args()

    driver = build_driver(args.browser, args.headless)
    wait = WebDriverWait(driver, 30)
    try:
        # 0. 先把上次保存的登录信息灌回去（必须在重新登录之前，否则会把刚登的覆盖掉）
        driver.get(HOME)
        who, used = restore_login_if_needed(driver)
        if used:
            print('已用上次保存的登录信息恢复身份：%s' % (who or '未成功'))

        # 0.1 需要登录时再登一次，成绩才会记到账号上
        if args.user:
            name, msg = login_by_password(driver, args.user, args.password)
            print('登录%s：%s' % ('成功' if name else '失败', name or msg))
        else:
            print('未提供账号，将以游客身份测试（成绩不计入账号）')

        # 1. 打开首页，选好类型 / 文章 / 竞赛 / 时间
        driver.get(HOME)
        wait.until(EC.element_to_be_clickable((By.ID, 'radio_' + args.type))).click()
        if args.type in ('cn', 'en'):
            if args.art:
                driver.execute_script('loading_select_text(arguments[0], arguments[1]);', args.type, str(args.art))
            time.sleep(0.3)
            driver.execute_script("document.getElementById('time').value = arguments[0];", str(args.minutes))
        elif args.type == 'group' and args.art:
            if driver.execute_script(PICK_COMPETITION_JS, str(args.art)) != 'OK':
                print(f'没找到竞赛 {args.art}（可能已结束），请核对首页竞赛列表里的 ID')
                return 1
        elif args.type == 'group2':
            if not args.code:
                print('--type group2 必须用 --code 提供邀请码')
                return 1
            box = driver.find_element(By.ID, 'group_num')
            box.clear()
            box.send_keys(args.code)
        time.sleep(0.3)
        art_name = driver.find_element(By.ID, 'select_i').text.strip()
        if args.type in ('cn', 'en'):
            print(f'类型：{"中文" if args.type == "cn" else "英文"}  文章：{art_name or args.art}  时间：{args.minutes} 分钟')
        else:
            print(f'类型：{"竞赛" if args.type == "group" else "竞赛(邀请码)"}  '
                  f'{art_name or args.art or args.code}（时长由竞赛决定，--minutes 无效）')

        # 2. 开始测试，等待测试页就绪
        start_test(driver)
        wait.until(EC.presence_of_element_located(TYPING_READY))
        time.sleep(0.5)

        # 3. 实时读取测试页源码，解析出每一行要打的文字
        lines = parse_lines(driver.page_source)
        if not lines:
            raise SystemExit('没有从页面源码里解析到任何一行文字')
        total = len(lines)
        total_chars = sum(len(x) for x in lines)
        est = total_chars * args.interval / 60
        print(f'共 {total} 行、{total_chars} 字；每字 {args.interval:g}±{args.jitter:g} 秒'
              f'（打错率 {args.error_rate:g}%），预计约 {est:.1f} 分钟')
        if est > args.minutes and args.type in ('cn', 'en'):
            print(f'提示：预计用时超过设定的 {args.minutes} 分钟，时间到了会按当时的进度结算，'
                  f'建议加大 --minutes')

        # 4. 一个字一个字地敲，间隔随机抖动，模拟真人打字
        done_lines, done_chars = autotype(driver, lines, args.interval, args.jitter, args.error_rate,
                                          on_char=lambda i, c, n: print(f'\r已敲 {c} 字（第 {i + 1} 行）',
                                                                        end='', flush=True))
        print(f'\n完成，共写入 {done_lines}/{total} 行、{done_chars} 字。')

        if args.close:
            # 打完最后一行后站点会弹成绩框并在 10 秒后自动提交，等它提交完再关窗口
            try:
                WebDriverWait(driver, 15).until(lambda d: 'typing.html' not in d.current_url)
                print('成绩已提交：' + driver.current_url)
            except TimeoutException:
                pass
        else:
            input('浏览器窗口保留中，按回车关闭...')
    except UnexpectedAlertPresentException:
        print('页面弹窗：' + (driver.switch_to.alert.text or ''))
        driver.switch_to.alert.accept()
    finally:
        if args.close:
            driver.quit()


if __name__ == '__main__':
    sys.exit(main())
