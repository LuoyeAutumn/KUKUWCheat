# -*- coding: utf-8 -*-
"""
KUKUWCheat · 在线打字测试自动打字（可视化窗口版）

界面
----
上部：账号登录；测试参数 —— 中文/英文/竞赛/竞赛(邀请码)、文章、目标速度、波动幅度、打错率、时间
中部：实时测试界面 —— 与网页同步显示每一行文字，已输入的字着色，当前行高亮
下部：站点自己算出来的倒计时/速度/正确率/错误/总字数/退格，按站点自己的刷新节奏
（typing.js 里每 100 毫秒一次）实时刷新，以及运行日志

打字方式
--------
逐字敲：每个字都补出 keydown -> input -> keyup 三种事件（打中文时先敲一遍拼音字母），
字与字之间的间隔在"平均值 ± 波动幅度"里取值；默认还会有 1% 左右的字先打错、
停一下再退格改回来，站点的"退格次数"就和人一样不是 0。不是整行一次性写入。

速度换算
--------
"目标速度"填的是站点"速度"栏那个数（每分钟正确字数，中文测试栏位写作 WPM、英文写作 KPM）。
程序按 目标速度 → 每字间隔 = 60 / (速度 × (1 + 打错补偿)) 反推间隔，打错率越高间隔压得越短，
站点最后算出来的速度就落在目标上；"波动幅度"是间隔的 ±百分比，间隔一变它跟着变。
反过来手动改"每字间隔"也行，这时目标速度会跟着重算。改动打错率会同步刷新速度预估。

关于"实时测试界面"
------------------
tkinter 没有内置浏览器控件，网页没法原样嵌进这个窗口，所以这里用"实时镜像"的方式还原：
文字、进度、计数全部实时从网页里读回来显示。想看真正的网页界面，勾上"显示浏览器窗口"，
程序会额外开一个真实的浏览器窗口，两边内容是一致的。

登录状态
--------
浏览器用固定的用户目录 `.browser_profile` 保留登录；同时登录成功后会把 cookie 备份到
`.login_cookies.json`。所以就算那个目录被别的残留浏览器占着、退回了临时目录，登录也不会丢。

用法
----
    双击 kukuwcheat_gui.py 即可（会自动用 pythonw 重启，不带命令行黑窗口）
    python kukuwcheat_gui.py --console      # 想保留命令行窗口看输出时用这个
"""

import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kukuwcheat_auto  # noqa: E402  该模块会把同目录 _libs 加入 sys.path（selenium 依赖）
from kukuwcheat_auto import (COMPETITIONS_JS, GUEST_PREFIX, HOME, PICK_COMPETITION_JS, POLL_INTERVAL,  # noqa: E402
                             TYPING_READY, autotype, build_driver, delay_range, interval_for_speed,
                             login_by_password, open_qr_login, parse_lines, restore_login_if_needed,
                             save_cookies, speed_for_interval, start_test, wait_qr_login)
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402
from selenium.common.exceptions import UnexpectedAlertPresentException, WebDriverException  # noqa: E402

# 读取首页的 系统文章 / 我的文章 列表
ARTICLES_JS = r"""
var out = {cn: [], en: []};
for (var k in out) {
    if (typeof art_sys !== 'undefined' && art_sys[k]) {
        for (var i = 0; i < art_sys[k].length; i++) out[k].push([art_sys[k][i][0], art_sys[k][i][1]]);
    }
    if (typeof art_my !== 'undefined' && art_my[k]) {
        for (var g in art_my[k]) {
            for (var j = 0; j < art_my[k][g].length; j++) out[k].push([art_my[k][g][j][0], art_my[k][g][j][1]]);
        }
    }
}
return out;
"""

# 实时读取测试页状态：每行已输入的内容、当前行、站点统计
READ_STATE_JS = r"""
var divs = document.querySelectorAll('#content div.typing');
var vals = [], act = -1;
for (var i = 0; i < divs.length; i++) {
    var ins = divs[i].getElementsByTagName('input');
    vals.push(ins[1] ? ins[1].value : '');
    if (divs[i].className.indexOf('typing_on') >= 0) act = i;
}
var info = document.getElementById('typing_info_li');
var box = document.getElementById('window_box');
return {
    vals: vals,
    act: act,
    stat: info ? info.innerText.replace(/\s+/g, ' ').trim() : '',
    url: location.href,
    over: !!(box && box.style.display === 'block')
};
"""

STAT_PATTERNS = {
    'left': r'倒计时\s*([\d:]+)',
    'speed': r'速\s*度：\s*([\d.]+)\s*(\w+)',
    'acc': r'正确率：\s*([\d.]+)',
    'err': r'错\s*误：\s*(\d+)',
    'chars': r'总字数：\s*(\d+)',
    'back': r'退\s*格：\s*(\d+)',
}

LOG_MAX_LINES = 400       # 日志最多留这么多行，长会话时不会一直涨内存
PUMP_INTERVAL = 30        # 界面取事件队列的间隔（毫秒），敲一个字界面就有反应


# 暂停网页上的测试（站点自己的暂停按钮），避免停止后倒计时继续跑、到点自动交一份低分
PAUSE_TEST_JS = r"""
var a = document.getElementById('pause_a');
if (a && a.className == 'pause') { dazi_pause(a); return 'PAUSED'; }
return 'NO';
"""

# 继续网页上的测试：暂停后站点会把按钮的 class 换成 pause2、文字变成"继续"
RESUME_TEST_JS = r"""
var a = document.getElementById('pause_a');
if (a && a.className == 'pause2') { dazi_pause(a); return 'RESUMED'; }
return 'NO';
"""


class Worker(threading.Thread):
    """独占管理浏览器：读文章列表、跑测试、把网页状态推给界面。"""

    def __init__(self, cmd_q, ev_q):
        super().__init__(daemon=True)
        self.cmd_q = cmd_q
        self.ev_q = ev_q
        self.driver = None
        self.headless = None
        self.stop_flag = threading.Event()
        self.quit_flag = threading.Event()
        self.pause_flag = threading.Event()      # 暂停出字（由界面直接置位，不走命令队列）
        self.pause_web = False                   # 暂停时是否连网页上的测试一起暂停

    # ---------- 基础 ----------
    def emit(self, kind, **kw):
        kw['type'] = kind
        self.ev_q.put(kw)

    def is_alive(self):
        """浏览器窗口被手动关掉后 driver 对象还在、会话已经失效，这里探一下。"""
        try:
            self.driver.current_url
            return True
        except WebDriverException:
            return False

    def log_line(self, text):
        """给 kukuwcheat_auto 里的函数当 log 回调用（不然提示只打到控制台，界面里看不到）。"""
        self.emit('log', text=text)

    def ensure_driver(self, headless):
        if self.driver is not None and self.headless == headless and self.is_alive():
            return self.driver
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self.driver = build_driver('auto', headless, log=self.log_line)
        self.headless = headless
        self.driver.get(HOME)
        who, used = restore_login_if_needed(self.driver)   # 用户目录没带上登录时用备份 cookie 恢复
        if used:
            self.emit('log', text='已用备份的登录信息恢复身份：%s' % (who or '未成功'))
        return self.driver

    def read_state(self, d):
        try:
            return d.execute_script(READ_STATE_JS)
        except UnexpectedAlertPresentException:
            d.switch_to.alert.accept()
            return {'vals': [], 'act': -1, 'stat': '', 'url': d.current_url, 'over': False}

    # ---------- 线程主体 ----------
    def run(self):
        self.emit('log', text='正在启动浏览器（首次运行会自动下载驱动，请稍候）…')
        try:
            self.ensure_driver(headless=True)
            self.emit('log', text='浏览器就绪，读取文章/竞赛列表…')
            self.emit('articles', arts=self.driver.execute_script(ARTICLES_JS))
            self.emit('competitions', list=self.read_competitions())
            name = self.read_user()
            if name and not name.startswith(GUEST_PREFIX):
                save_cookies(self.driver)        # 顺手刷新登录备份
            self.emit('login_state', name=name)
            self.emit('log', text='准备完毕，选好参数后点【开始测试】。')
        except (Exception, SystemExit) as e:      # 连 SystemExit 也接住，否则工作线程会直接死掉、界面变砖
            self.emit('log', text='启动浏览器失败：%s' % (e or ''))

        while not self.quit_flag.is_set():
            try:
                cmd = self.cmd_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if cmd[0] == 'start':
                    self.handle_start(cmd[1])
                elif cmd[0] == 'login':
                    self.handle_login(*cmd[1])
                elif cmd[0] == 'qr_login':
                    self.handle_qr_login()
                elif cmd[0] == 'quit':
                    break
            except UnexpectedAlertPresentException:
                try:
                    self.emit('log', text='网页弹窗：' + (self.driver.switch_to.alert.text or ''))
                    self.driver.switch_to.alert.accept()
                except WebDriverException:
                    pass
            except WebDriverException as e:
                # 浏览器窗口被关掉/会话失效：丢掉这个 driver，下次自动重开
                self.driver = None
                msg = str(e).splitlines()[0][:120]
                self.emit('log', text='浏览器窗口被关掉或已失效（%s）。再点一次【开始测试】会自动重新打开。' % msg)
            except SystemExit as e:
                self.emit('log', text='操作失败：%s' % (e or ''))
                self.emit('idle')
            except Exception:
                self.emit('log', text='出错：\n' + traceback.format_exc())
                self.emit('idle')
        try:
            if self.driver is not None:
                self.driver.quit()
        except Exception:
            pass

    def read_user(self):
        """读当前页面上的身份（首页的 #name：游客xxxx 或账号名）。"""
        try:
            return (self.driver.find_element(By.ID, 'name').get_attribute('value') or '').strip()
        except WebDriverException:
            return ''

    def read_competitions(self):
        try:
            return self.driver.execute_script(COMPETITIONS_JS) or []
        except WebDriverException:
            return []

    def handle_login(self, user, password):
        self.emit('busy')
        try:
            d = self.ensure_driver(self.headless)
            self.emit('log', text='正在登录：%s …' % user)
            name, msg = login_by_password(d, user, password)
            if name:
                self.emit('log', text='登录成功，当前账号：%s' % name)
            else:
                self.emit('log', text='登录失败：%s' % msg)
            self.emit('login_state', name=name, msg=msg)
            self.emit('articles', arts=d.execute_script(ARTICLES_JS))   # 登录后"我的文章"会出来
            self.emit('competitions', list=self.read_competitions())    # 登录后能看到更多竞赛
        finally:
            self.emit('idle')

    def handle_qr_login(self):
        self.emit('busy')
        try:
            d = self.ensure_driver(False)      # 扫码必须看得见窗口
            self.emit('log', text='已打开浏览器窗口，请用微信扫码，扫完在页面里点【完成】…')
            open_qr_login(d)
            name, msg = wait_qr_login(d, timeout=180, should_stop=self.quit_flag.is_set)
            if name:
                self.emit('log', text='扫码登录成功，当前账号：%s' % name)
            else:
                self.emit('log', text='扫码登录未完成：%s' % msg)
            self.emit('login_state', name=name, msg=msg)
            self.emit('articles', arts=d.execute_script(ARTICLES_JS))
        finally:
            self.emit('idle')

    def on_pause_changed(self, paused):
        """进入/退出"暂停出字"时被调用一次：按需把网页上的测试也一起暂停/继续。"""
        try:
            if paused:
                msg = '已暂停出字'
                if self.pause_web:
                    if self.driver is not None and self.driver.execute_script(PAUSE_TEST_JS) == 'PAUSED':
                        msg += '，网页上的测试也暂停了（倒计时和成绩都停住）'
                    else:
                        msg += '（网页测试当前不是运行状态，没有重复暂停）'
                else:
                    msg += '（网页倒计时仍在走，会按时间到时的进度结算）'
                self.emit('log', text=msg)
            else:
                if self.stop_flag.is_set():
                    return          # 是被【停止】打断的，不用播报"已继续"
                msg = '已继续出字'
                if self.pause_web and self.driver is not None:
                    if self.driver.execute_script(RESUME_TEST_JS) == 'RESUMED':
                        msg += '，网页上的测试也继续了'
                self.emit('log', text=msg)
        except WebDriverException as e:
            self.emit('log', text='暂停时操作网页失败：%s' % str(e).splitlines()[0][:100])

    def handle_start(self, cfg):
        self.stop_flag.clear()
        self.pause_flag.clear()          # 上一局残留的暂停状态不要带进来
        self.emit('busy')
        try:
            d = self.ensure_driver(cfg['headless'])
            self.emit('log', text='打开首页，选择测试内容…')
            d.get(HOME)
            WebDriverWait(d, 30).until(EC.element_to_be_clickable((By.ID, 'radio_' + cfg['type']))).click()
            if cfg['type'] in ('cn', 'en'):
                if cfg['art']:
                    d.execute_script('loading_select_text(arguments[0], arguments[1]);', cfg['type'], str(cfg['art']))
                time.sleep(0.3)
                d.execute_script("document.getElementById('time').value = arguments[0];", str(cfg['minutes']))
            elif cfg['type'] == 'group':
                if cfg['art']:
                    if d.execute_script(PICK_COMPETITION_JS, str(cfg['art'])) != 'OK':
                        self.emit('log', text='没找到这个竞赛（可能已结束），请在列表里重新选。')
                        return
            elif cfg['type'] == 'group2':
                box = d.find_element(By.ID, 'group_num')
                box.clear()
                box.send_keys(cfg['code'])
            time.sleep(0.3)
            name = d.find_element(By.ID, 'select_i').text.strip() or str(cfg['art'] or cfg.get('code') or '')
            if cfg['type'] in ('cn', 'en'):
                self.emit('log', text='开始测试：%s，时间 %d 分钟' % (name, cfg['minutes']))
            else:
                self.emit('log', text='开始%s：%s' % ('竞赛' if cfg['type'] == 'group' else '竞赛(邀请码)', name))

            start_test(d)
            WebDriverWait(d, 30).until(EC.presence_of_element_located(TYPING_READY))
            time.sleep(0.4)

            lines = parse_lines(d.page_source)
            if not lines:
                self.emit('log', text='没有从页面源码里解析到文字，文章可能不存在。')
                return
            total = len(lines)
            total_chars = sum(len(x) for x in lines)
            self.emit('lines', lines=lines)
            speed = cfg.get('speed') or round(speed_for_interval(cfg['avg'], cfg['error_rate']))
            est = total_chars / max(speed, 1)          # 预估用时已经把打错率算进去了
            self.emit('log', text='共 %d 行、%d 字；目标约 %d 字/分（站点"速度"口径），每字 %.3f±%.3f 秒、'
                                  '打错率 %.1f%%，预计约 %.1f 分钟（测试时间 %d 分钟）。'
                      % (total, total_chars, speed, cfg['avg'], cfg['jitter'], cfg['error_rate'],
                         est, cfg['minutes']))
            if est > cfg['minutes'] and cfg['type'] in ('cn', 'en'):
                self.emit('log', text='提示：预计用时超过设定时间，会按时间到时的进度结算，建议加大测试时间。')

            def poll():
                """读一次网页状态推给界面：每敲完一个字会被立刻调用一次，
                每字之间的等待里也按站点刷新节奏（100 毫秒）调用，界面才跟得上。"""
                self.emit('state', **self.read_state(d))

            done_lines, done_chars = autotype(d, lines, cfg['avg'], cfg['jitter'], cfg['error_rate'],
                                              should_stop=self.stop_flag.is_set, poll=poll,
                                              should_pause=self.pause_flag.is_set,
                                              on_pause=self.on_pause_changed)
            self.emit('state', **self.read_state(d))
            self.emit('log', text='已写完 %d/%d 行、%d 字。' % (done_lines, total, done_chars))

            if done_lines >= total:
                # 站点会弹成绩框并在 10 秒后自动提交，这里等它提交完
                deadline = time.time() + 20
                while time.time() < deadline and not self.quit_flag.is_set():
                    st = self.read_state(d)
                    self.emit('state', **st)
                    if 'typing.html' not in st['url']:
                        self.emit('log', text='成绩已提交：' + st['url'])
                        break
                    time.sleep(POLL_INTERVAL)
            elif self.stop_flag.is_set():
                # 中途停止：顺手暂停网页上的测试，免得倒计时跑完自动交一份低分
                if d.execute_script(PAUSE_TEST_JS) == 'PAUSED':
                    self.emit('log', text='已在网页上暂停测试（在浏览器里点【继续】可接着打）。')
        finally:
            self.emit('idle')


class App:
    def __init__(self, root):
        self.root = root
        self.cmd_q = queue.Queue()
        self.ev_q = queue.Queue()
        self.articles = {'cn': [], 'en': []}
        self.competitions = []
        self.lines = []
        self.rows = []
        self.prev_vals = []
        self.cur_row = None
        self.running = False
        self.login_name = ''
        self.build_ui()

        self.worker = Worker(self.cmd_q, self.ev_q)
        self.worker.start()
        self.root.after(PUMP_INTERVAL, self.pump)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    # ---------- 界面 ----------
    def build_ui(self):
        self.root.title('KUKUWCheat · 在线打字测试自动打字')
        self.root.geometry('960x820')
        # 最小尺寸按各区域实际需要定（参数区约 705px），再窄就不让缩，免得控件被裁掉
        self.root.minsize(720, 560)
        font_ui = ('Microsoft YaHei UI', 10)
        font_text = ('Microsoft YaHei UI', 12)

        # 账号（两行：上面输入，下面状态，避免窄窗口时状态被挤掉）
        login = ttk.LabelFrame(self.root, text='账号', padding=6)
        login.pack(fill='x', padx=8, pady=(8, 0))
        ttk.Label(login, text='用户名：', font=font_ui).grid(row=0, column=0, sticky='w')
        self.user_entry = ttk.Entry(login, width=16, font=font_ui)
        self.user_entry.grid(row=0, column=1, sticky='w')
        ttk.Label(login, text='密码：', font=font_ui).grid(row=0, column=2, sticky='e', padx=(10, 0))
        self.pass_entry = ttk.Entry(login, width=16, font=font_ui, show='*')
        self.pass_entry.grid(row=0, column=3, sticky='w')
        ttk.Button(login, text='登录', width=8, command=self.on_login).grid(row=0, column=4, padx=8)
        ttk.Button(login, text='微信扫码登录', width=14, command=self.on_qr_login).grid(row=0, column=5)
        self.login_var = tk.StringVar(value='未登录（游客身份，成绩不计入账号数据）')
        self.login_label = ttk.Label(login, textvariable=self.login_var, font=font_ui, foreground='#b06000')
        self.login_label.grid(row=1, column=0, columnspan=6, sticky='w', pady=(4, 0))

        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill='x')
        top.columnconfigure(1, weight=1)     # 文章下拉框所在列可伸缩

        # 0: 测试类型
        ttk.Label(top, text='测试类型：', font=font_ui).grid(row=0, column=0, sticky='w')
        self.type_var = tk.StringVar(value='cn')
        for col, (val, text) in enumerate([('cn', '中文打字'), ('en', '英文打字'),
                                           ('group', '竞赛'), ('group2', '竞赛(邀请码)')]):
            ttk.Radiobutton(top, text=text, value=val, variable=self.type_var,
                            command=self.refresh_art_list).grid(row=0, column=1 + col, sticky='w')

        # 1: 文章 / 邀请码
        ttk.Label(top, text='选择文章：', font=font_ui).grid(row=1, column=0, sticky='w', pady=(6, 0))
        self.art_combo = ttk.Combobox(top, width=30, font=font_ui, state='readonly')
        self.art_combo.grid(row=1, column=1, columnspan=3, sticky='ew', pady=(6, 0))
        self.art_combo.bind('<<ComboboxSelected>>', lambda e: self.sync_competition_time())
        ttk.Button(top, text='随机选', width=8, command=self.pick_random
                   ).grid(row=1, column=4, padx=4, pady=(6, 0))
        ttk.Label(top, text='邀请码：', font=font_ui).grid(row=1, column=5, sticky='e', pady=(6, 0))
        self.code_entry = ttk.Entry(top, width=12, font=font_ui, state='disabled')
        self.code_entry.grid(row=1, column=6, columnspan=2, sticky='w', pady=(6, 0))

        # 2: 目标速度（站点"速度"栏的口径：字/分）+ 波动幅度 + 打错率
        ttk.Label(top, text='目标速度：', font=font_ui).grid(row=2, column=0, sticky='w', pady=(6, 0))
        self.speed_var = tk.StringVar(value='190')
        self.speed_box = ttk.Spinbox(top, from_=10, to=999, increment=5, width=6,
                                     textvariable=self.speed_var, font=font_ui)
        self.speed_box.grid(row=2, column=1, sticky='w', pady=(6, 0))
        self.unit_label = ttk.Label(top, text='', font=font_ui, foreground='#666666')
        self.unit_label.grid(row=2, column=2, columnspan=2, sticky='w', pady=(6, 0), padx=(4, 0))
        ttk.Label(top, text='波动幅度(%)：', font=font_ui).grid(row=2, column=4, sticky='e', pady=(6, 0))
        self.wobble_var = tk.StringVar(value='33')
        ttk.Spinbox(top, from_=0, to=100, increment=1, width=5, textvariable=self.wobble_var,
                    font=font_ui).grid(row=2, column=5, sticky='w', pady=(6, 0))
        ttk.Label(top, text='打错率(%)：', font=font_ui).grid(row=2, column=6, sticky='e', pady=(6, 0))
        self.error_var = tk.StringVar(value='1')
        ttk.Spinbox(top, from_=0, to=30, increment=0.5, width=5, textvariable=self.error_var,
                    font=font_ui).grid(row=2, column=7, sticky='w', pady=(6, 0))

        # 3: 每字间隔（跟着目标速度自动算，也可以自己改）+ 测试时间
        ttk.Label(top, text='每字间隔(秒)：', font=font_ui).grid(row=3, column=0, sticky='w', pady=(6, 0))
        self.interval_var = tk.StringVar(value='0.3')
        self.interval_box = ttk.Spinbox(top, from_=0.02, to=5, increment=0.005, width=7,
                                        textvariable=self.interval_var, font=font_ui)
        self.interval_box.grid(row=3, column=1, sticky='w', pady=(6, 0))
        ttk.Label(top, text='测试时间(分)：', font=font_ui).grid(row=3, column=4, sticky='e', pady=(6, 0))
        self.minutes_var = tk.StringVar(value='5')
        self.minutes_box = ttk.Spinbox(top, from_=1, to=50, width=4, textvariable=self.minutes_var,
                                       font=font_ui)
        self.minutes_box.grid(row=3, column=5, sticky='w', pady=(6, 0))
        self.time_hint = tk.StringVar()
        ttk.Label(top, textvariable=self.time_hint, font=font_ui, foreground='#b06000'
                  ).grid(row=3, column=6, columnspan=2, sticky='w', pady=(6, 0), padx=(8, 0))

        # 4: 换算说明（自己占一行，窄窗口时也不会把别的控件挤掉）
        self.rhythm_var = tk.StringVar()
        ttk.Label(top, textvariable=self.rhythm_var, font=font_ui, foreground='#0a8a0a'
                  ).grid(row=4, column=0, columnspan=8, sticky='w', pady=(6, 0))

        self._sync = False          # 正在程序内部改值，别让 trace 递归
        self.spd_source = 'speed'   # 最后一次是谁在主导：'speed' 还是 'interval'
        self.speed_var.trace_add('write', lambda *a: self.apply_speed('speed'))
        self.error_var.trace_add('write', lambda *a: self.apply_speed('error'))
        self.interval_var.trace_add('write', lambda *a: self.apply_speed('interval'))
        self.wobble_var.trace_add('write', lambda *a: self.update_rhythm_hint())
        self.apply_speed('speed')   # 初始：按默认目标速度把间隔算出来

        # 5: 开关
        opts = ttk.Frame(top)
        opts.grid(row=5, column=0, columnspan=4, sticky='w', pady=(8, 0))
        self.show_browser = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text='显示浏览器窗口', variable=self.show_browser).pack(side='left')

        # 6: 按钮（整行右对齐，窄窗口时也不会互相挤）
        btns = ttk.Frame(top)
        btns.grid(row=6, column=0, columnspan=8, sticky='e', pady=(8, 0))
        self.start_btn = ttk.Button(btns, text='开始测试', width=11, command=self.on_start)
        self.start_btn.pack(side='left')
        self.pause_typing_btn = ttk.Button(btns, text='暂停出字', width=8, state='disabled',
                                           command=lambda: self.on_pause('typing'))
        self.pause_typing_btn.pack(side='left', padx=(5, 0))
        self.pause_all_btn = ttk.Button(btns, text='暂停全部', width=8, state='disabled',
                                        command=lambda: self.on_pause('all'))
        self.pause_all_btn.pack(side='left', padx=5)
        ttk.Button(btns, text='停止', width=6, command=self.on_stop).pack(side='left')

        # 站点统计（窗口变窄时自动换行，不会被裁掉）
        bar = ttk.Frame(self.root, padding=(8, 0))
        bar.pack(fill='x')
        self.stat_var = tk.StringVar(value='倒计时 --:--    速度 -    正确率 -%    错误 - 字    总字数 - 字')
        self.stat_label = ttk.Label(bar, textvariable=self.stat_var, justify='left',
                                    font=('Microsoft YaHei UI', 11, 'bold'), foreground='#0b5fa5')
        self.stat_label.pack(anchor='w', fill='x')
        bar.bind('<Configure>', lambda e: self.stat_label.configure(wraplength=max(e.width - 16, 200)))

        # 实时测试界面
        mid = ttk.LabelFrame(self.root, text='实时测试界面（与网页同步）', padding=6)
        mid.pack(fill='both', expand=True, padx=8, pady=6)
        self.text = tk.Text(mid, wrap='char', font=font_text, height=12, width=30, relief='flat',
                            background='#fbfbf7', spacing1=3, spacing3=3, padx=8, pady=6)
        sb = ttk.Scrollbar(mid, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.text.tag_configure('plain', foreground='#666666')
        self.text.tag_configure('ok', foreground='#0a8a0a')
        self.text.tag_configure('bad', foreground='#d02020', underline=True)
        self.text.tag_configure('cur', background='#fff3c4')
        self.text.configure(state='disabled')

        # 当前输入
        cur = ttk.Frame(self.root, padding=(8, 0))
        cur.pack(fill='x')
        ttk.Label(cur, text='当前输入：', font=font_ui).pack(side='left')
        self.cur_var = tk.StringVar()
        e = ttk.Entry(cur, textvariable=self.cur_var, font=font_ui, state='readonly')
        e.pack(side='left', fill='x', expand=True)

        # 日志
        logf = ttk.LabelFrame(self.root, text='运行日志', padding=4)
        logf.pack(fill='both', padx=8, pady=(0, 8))
        self.log = tk.Text(logf, height=5, width=30, font=('Consolas', 9), relief='flat',
                           background='#f4f4f4', wrap='char')
        lsb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set, state='disabled')
        self.log.pack(side='left', fill='both', expand=True)
        lsb.pack(side='right', fill='y')

    # ---------- 文章 / 竞赛列表 ----------
    def apply_speed(self, source):
        """目标速度、打错率、每字间隔三者联动换算。

        速度是站点"速度"栏的口径（字/分）。谁在主导就听谁的：
        source='speed'/'error' 时按目标速度把间隔算出来（打错率会让速度变慢，
        所以间隔要按打错率反向补偿）；source='interval' 时反过来，按间隔算速度。
        """
        if self._sync:
            return
        try:
            err = max(0.0, float(self.error_var.get()))
        except ValueError:
            err = 0.0
        if source == 'speed':
            self.spd_source = 'speed'
        elif source == 'interval':
            self.spd_source = 'interval'
        if self.spd_source == 'speed':
            try:
                speed = float(self.speed_var.get())
            except ValueError:
                return
            if speed <= 0:
                return
            avg = max(0.02, interval_for_speed(speed, err))
            self._sync = True
            self.interval_var.set('%.3f' % avg)
            self._sync = False
        else:
            try:
                avg = float(self.interval_var.get())
            except ValueError:
                return
            if avg <= 0:
                return
            speed = speed_for_interval(avg, err)
            self._sync = True
            self.speed_var.set('%d' % round(speed))
            self._sync = False
        self.update_rhythm_hint()

    def update_rhythm_hint(self):
        """显示换算结果：目标/实际速度、每字间隔与波动范围、打错补偿。"""
        self.update_unit_label()
        try:
            avg = max(float(self.interval_var.get()), 0.01)
            err = max(0.0, float(self.error_var.get()))
        except ValueError:
            self.rhythm_var.set('')
            return
        got = speed_for_interval(avg, err)
        try:
            wobble = max(0.0, float(self.wobble_var.get()))
        except ValueError:
            wobble = 0.0
        low, high = delay_range(avg, avg * wobble / 100.0)
        try:
            target = float(self.speed_var.get())
        except ValueError:
            target = got
        parts = ['实际约 %d 字/分' % round(got)]
        if abs(got - target) >= 1:
            parts.append('（目标 %s）' % self.speed_var.get())
        if err > 0:
            parts.append('已补偿 %.1f%% 打错' % err)
        parts.append('· 每字 %.3f 秒，波动 %.3f~%.3f 秒（±%.0f%%）' % (avg, low, high, wobble))
        self.rhythm_var.set(' '.join(parts))

    def update_unit_label(self):
        """站点"速度"栏的标签：中文测试写 WPM、英文测试写 KPM（数值都是字/分）。"""
        self.unit_label.configure(text='字/分（站点速度栏写作 %s）'
                                       % ('KPM' if self.type_var.get() == 'en' else 'WPM'))

    def refresh_art_list(self):
        kind = self.type_var.get()
        self.update_unit_label()          # 中英文测试站点的速度标签不一样
        self.code_entry.configure(state='normal' if kind == 'group2' else 'disabled')
        if kind == 'group2':
            self.art_combo.configure(state='disabled')
            self.art_combo['values'] = []
            self.art_combo.set('')
            self.minutes_box.configure(state='disabled')
            self.time_hint.set('时长由邀请码对应的竞赛决定，本地改不了')
            return
        self.art_combo.configure(state='readonly')
        if kind == 'group':
            values = ['%s（%s）' % (c['name'], c['info']) for c in self.competitions]
        else:
            values = ['%s（ID %s）' % (name, aid) for aid, name in (self.articles.get(kind) or [])]
        self.art_combo['values'] = values
        if values:
            self.art_combo.current(0)
        else:
            self.art_combo.set('')
        if kind == 'group':
            self.sync_competition_time()
        else:
            self.minutes_box.configure(state='normal')
            self.time_hint.set('')

    def sync_competition_time(self):
        """竞赛时长由竞赛本身决定、服务端说了算（前端改了也不会被采纳，
        实测把表单里的 time 改成 1，测试页依然是竞赛自带的 3 分钟）。
        所以这里把真实时长显示出来，并把输入框锁上，免得白改。"""
        if self.type_var.get() != 'group':
            return
        idx = self.art_combo.current()
        if 0 <= idx < len(self.competitions):
            minutes = self.competitions[idx]['minutes']
            self.minutes_var.set(str(minutes))
            self.time_hint.set('竞赛固定 %d 分钟，本地改不了' % minutes)
        else:
            self.time_hint.set('')
        self.minutes_box.configure(state='disabled')

    def pick_random(self):
        n = len(self.art_combo['values'])
        if n:
            self.art_combo.current(random.randrange(n))

    def current_art_id(self):
        kind = self.type_var.get()
        idx = self.art_combo.current()
        if kind == 'group2':
            return 0                      # 由邀请码决定文章，服务端来查
        if kind == 'group':
            return self.competitions[idx]['id'] if 0 <= idx < len(self.competitions) else None
        items = self.articles.get(kind) or []
        return items[idx][0] if 0 <= idx < len(items) else None

    # ---------- 事件 ----------
    def on_login(self):
        user = self.user_entry.get().strip()
        if not user:
            self.append_log('请先填用户名；没有账号的话可以点【微信扫码登录】。')
            return
        self.cmd_q.put(('login', (user, self.pass_entry.get())))

    def on_qr_login(self):
        self.append_log('即将打开浏览器窗口显示二维码，请用手机微信扫码。')
        self.cmd_q.put(('qr_login',))

    def on_stop(self):
        # 直接置位，不排队：工作线程正在逐字敲的时候没空处理命令队列
        self.worker.stop_flag.set()
        self.append_log('已请求停止（当前这个字敲完就停）。')

    def on_pause(self, mode):
        """暂停/继续出字。mode='typing' 只停出字，mode='all' 连网页一起停。
        同样直接置位，不走命令队列（工作线程正卡在逐字敲的循环里）。"""
        if not self.running:
            return
        if self.worker.pause_flag.is_set():
            self.worker.pause_flag.clear()
            self.set_pause_buttons(None)
        else:
            self.worker.pause_web = (mode == 'all')
            self.worker.pause_flag.set()
            self.set_pause_buttons(mode)
            self.append_log('已请求暂停（%s），当前这个字敲完就停住。'
                            % ('只停出字' if mode == 'typing' else '连网页一起停'))

    def set_pause_buttons(self, mode):
        """mode：None=没暂停，'typing'=只暂停出字，'all'=全部暂停。
        暂停中把当前那个按钮变成【继续】，另一个置灰，避免按错。"""
        state = 'normal' if self.running else 'disabled'
        if mode is None:
            self.pause_typing_btn.configure(text='暂停出字', state=state)
            self.pause_all_btn.configure(text='暂停全部', state=state)
            return
        typing_on = (mode == 'typing')
        self.pause_typing_btn.configure(text='继续' if typing_on else '暂停出字',
                                        state=state if typing_on else 'disabled')
        self.pause_all_btn.configure(text='继续' if not typing_on else '暂停全部',
                                     state=state if not typing_on else 'disabled')

    def on_start(self):
        if self.running:
            return
        try:
            minutes = max(1, min(50, int(float(self.minutes_var.get()))))
            interval = max(0.02, float(self.interval_var.get()))
            wobble = max(0.0, float(self.wobble_var.get()))
            error_rate = max(0.0, float(self.error_var.get()))
        except ValueError:
            self.append_log('测试时间/目标速度/每字间隔/打错率必须是数字。')
            return
        cfg = {
            'type': self.type_var.get(),
            'art': self.current_art_id(),
            'code': self.code_entry.get().strip(),
            'minutes': minutes,
            'avg': interval,
            'jitter': interval * wobble / 100.0,     # 波动幅度按间隔的百分比折算成 ±秒
            'error_rate': error_rate,
            'speed': round(speed_for_interval(interval, error_rate)),
            'headless': not self.show_browser.get(),
        }
        if cfg['type'] == 'group2':
            if not cfg['code']:
                self.append_log('竞赛(邀请码)要先填邀请码。')
                return
        elif cfg['art'] is None:
            self.append_log('还没读到列表（文章/竞赛），等浏览器就绪或先登录后再试。')
            return
        if not self.login_name:
            self.append_log('提示：当前是游客身份，这次成绩不会计入账号；可以先登录再测试。')
        self.cmd_q.put(('start', cfg))

    def on_close(self):
        self.worker.stop_flag.set()      # 正在打字时也能立刻停下
        self.cmd_q.put(('quit',))
        self.root.destroy()

    # ---------- 与工作线程通信 ----------
    def pump(self):
        """一次把队列抽干；积压的旧统计只留最新那条（界面卡一下也不会把队列堆起来）。

        30 毫秒取一次：每敲完一个字网页那边就推一次状态，取勤一点界面才不会有明显延迟。
        """
        evs = []
        try:
            while True:
                evs.append(self.ev_q.get_nowait())
        except queue.Empty:
            pass
        last_state = -1
        for i, ev in enumerate(evs):
            if ev.get('type') == 'state':
                last_state = i
        for i, ev in enumerate(evs):
            if i != last_state and ev.get('type') == 'state':
                continue
            self.handle_event(ev)
        self.root.after(PUMP_INTERVAL, self.pump)

    def handle_event(self, ev):
        kind = ev.get('type')
        if kind == 'log':
            self.append_log(ev['text'])
        elif kind == 'articles':
            self.articles = {'cn': ev['arts'].get('cn') or [], 'en': ev['arts'].get('en') or []}
            self.refresh_art_list()
        elif kind == 'competitions':
            self.competitions = ev['list'] or []
            if self.type_var.get() == 'group':
                self.refresh_art_list()
        elif kind == 'lines':
            self.show_lines(ev['lines'])
        elif kind == 'login_state':
            self.set_login_state(ev.get('name') or '', ev.get('msg') or '')
        elif kind == 'state':
            self.update_state(ev)
        elif kind == 'busy':
            self.running = True
            self.start_btn.configure(state='disabled')
            self.set_pause_buttons(None)
        elif kind == 'idle':
            self.running = False
            self.start_btn.configure(state='normal')
            self.worker.pause_flag.clear()
            self.set_pause_buttons(None)

    def set_login_state(self, name, msg):
        if name and not name.startswith(GUEST_PREFIX):
            self.login_name = name
            self.login_var.set('已登录：%s' % name)
            self.login_label.configure(foreground='#0a8a0a')
        else:
            self.login_name = ''
            self.login_var.set('未登录（游客身份，成绩不计入账号）')
            self.login_label.configure(foreground='#b06000')
        if msg:
            self.append_log('登录提示：%s' % msg)

    def append_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('[%H:%M:%S] ') + text + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > LOG_MAX_LINES:   # 超了就丢掉最前面一半
            self.log.delete('1.0', '%d.0' % (LOG_MAX_LINES // 2))
        self.log.see('end')
        self.log.configure(state='disabled')

    # ---------- 实时界面 ----------
    def show_lines(self, lines):
        self.lines = lines
        self.rows = list(range(1, len(lines) + 1))
        self.prev_vals = [''] * len(lines)
        self.cur_row = None
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        for i, line in enumerate(lines):
            self.text.insert('end', line + '\n')
            self.text.tag_add('plain', '%d.0' % (i + 1), '%d.end' % (i + 1))
        self.text.configure(state='disabled')
        self.cur_var.set('')

    def update_state(self, ev):
        vals = ev.get('vals') or []
        act = ev.get('act', -1)
        if len(vals) != len(self.lines):
            return
        for i, typed in enumerate(vals):
            if typed != self.prev_vals[i]:
                self.color_line(i, typed)
                self.prev_vals[i] = typed
        # 当前行高亮 + 跟随滚动
        if act != self.cur_row:
            for r in self.rows:
                self.text.tag_remove('cur', '%d.0' % r, '%d.end' % r)
            if 0 <= act < len(self.rows):
                row = self.rows[act]
                self.text.tag_add('cur', '%d.0' % row, '%d.end' % row)
                self.text.see('%d.0' % row)
                self.cur_var.set(vals[act])
            self.cur_row = act
        elif 0 <= act < len(vals):
            self.cur_var.set(vals[act])
        self.stat_var.set(self.format_stat(ev.get('stat') or ''))

    def color_line(self, i, typed):
        row = self.rows[i]
        target = self.lines[i]
        start, end = '%d.0' % row, '%d.end' % row
        self.text.tag_remove('ok', start, end)
        self.text.tag_remove('bad', start, end)
        for j in range(min(len(typed), len(target))):
            tag = 'ok' if typed[j] == target[j] else 'bad'
            self.text.tag_add(tag, '%d.%d' % (row, j), '%d.%d' % (row, j + 1))

    @staticmethod
    def format_stat(stat):
        if not stat:
            return '倒计时 --:--    速度 -    正确率 -%    错误 - 字    总字数 - 字'
        got = {}
        for key, pattern in STAT_PATTERNS.items():
            m = re.search(pattern, stat)
            if m:
                got[key] = m.groups()
        left = got.get('left', ['--:--'])[0]
        speed = got.get('speed')
        acc = got.get('acc', ['-'])[0]
        err = got.get('err', ['-'])[0]
        chars = got.get('chars', ['-'])[0]
        back = got.get('back', ['-'])[0]
        speed_txt = '%s %s' % (speed[0], speed[1]) if speed else '-'
        return '倒计时 %s    速度 %s    正确率 %s%%    错误 %s 字    总字数 %s 字    退格 %s 次' % (
            left, speed_txt, acc, err, chars, back)


def relaunch_without_console():
    """双击运行时是 python.exe 起头的，会跟一个黑窗口；用同目录的 pythonw.exe 重新拉起自己，
    然后把带控制台的这个进程结束掉。已经用 pythonw 运行时什么都不做。"""
    if os.name != 'nt' or '--console' in sys.argv:
        return False
    exe = (sys.executable or '').lower()
    if not exe.endswith('python.exe'):
        return False
    pythonw = sys.executable[:-len('python.exe')] + 'pythonw.exe'
    if not os.path.exists(pythonw):
        return False
    args = [pythonw, os.path.abspath(__file__)] + [a for a in sys.argv[1:] if a != '--console']
    subprocess.Popen(args, cwd=os.path.dirname(os.path.abspath(__file__)),
                     creationflags=0x00000008,          # DETACHED_PROCESS：不跟着控制台
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, close_fds=True)
    return True


def main():
    if relaunch_without_console():
        return
    root = tk.Tk()
    app = App(root)
    root.mainloop()
    app.worker.join(timeout=20)      # 等浏览器真的退出，免得残留进程占着用户目录


if __name__ == '__main__':
    main()
