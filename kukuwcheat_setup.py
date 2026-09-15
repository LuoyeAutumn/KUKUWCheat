# -*- coding: utf-8 -*-
"""KUKUWCheat · 安装程序（安装 / 卸载二合一）

用法
----
    KUKUWCheat_Setup.exe                                 双击，图形界面安装
    KUKUWCheat_Setup.exe /SILENT /DIR="D:\\KUKUWCheat"    静默安装到指定目录（自动化/批处理用）
    KUKUWCheat_Setup.exe /SILENT /DIR=... /NODESKTOP     静默安装且不建桌面快捷方式
    KUKUWCheat_Setup.exe /SILENT /DIR=... /LOG=D:\\i.log   静默安装并把过程写进日志
    KUKUWCheat_Setup.exe /UNINSTALL                       图形界面卸载
    KUKUWCheat_Setup.exe /UNINSTALL /SILENT               静默卸载

说明
----
* 默认装到 C:\\Program Files (x86)\\KUKUWCheat，界面上可以改成任意目录。
* 装到 Program Files 这类需要管理员权限的位置时会自动申请提权（UAC）；装到用户自己的
  目录（比如 D:\\KUKUWCheat）则不需要提权。
* 程序要装的包体（文件夹版）在打包时用 --add-data 塞在安装程序内部，安装时解到目标目录。
* 卸载只删程序目录、快捷方式和注册表项；浏览器用户目录和登录备份不在安装目录里
  （装在 Program Files 时它在 %LOCALAPPDATA%\\KUKUWCheat），卸载时会保留，免得下次还得重登。
"""

import base64
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import winreg
from tkinter import filedialog, messagebox, ttk

APP_DIR_NAME = 'KUKUWCheat'                     # 安装目录默认名
DEFAULT_DIR = 'C:\\Program Files (x86)\\' + APP_DIR_NAME
DISPLAY_NAME = 'KUKUWCheat'
VERSION = '1.0'
MAIN_EXE = 'KUKUWCheat.exe'
UNINST_EXE = 'uninstall.exe'
SHORTCUT_NAME = 'KUKUWCheat'
UNINST_KEY = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\KUKUWCheat'
PAYLOAD_NAME = 'KUKUWCheat'                      # 打包时塞进来的文件夹版目录名
SKIP_NAMES = ('.browser_profile', '.login_cookies.json')   # 运行期数据，不进安装目录


# ---------- 路径 / 权限 ----------
def payload_dir():
    """安装包里带着的文件夹版程序所在目录。"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, PAYLOAD_NAME)


def can_write(path):
    """这个目录能不能写（不存在就先试着建出来）。"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, '.write_test')
        with open(probe, 'w') as f:
            f.write('ok')
        os.remove(probe)
        return True
    except OSError:
        return False


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated(args):
    """用管理员身份重新运行自己（会弹 UAC），成功返回 True。"""
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', sys.executable, ' '.join('"%s"' % a for a in args), None, 1)
        return rc > 32
    except Exception:
        return False


def powershell_exe():
    return shutil.which('powershell') or os.path.join(
        os.environ.get('SystemRoot', r'C:\Windows'),
        r'System32\WindowsPowerShell\v1.0\powershell.exe')


def run_ps(script, timeout=60):
    """跑一段 PowerShell 脚本。

    统一用 -EncodedCommand（Base64/UTF-16LE）：-Command 直接传参时，命令里的中文
    在部分控制台代码页下会被 PowerShell 解码错（变成乱码路径），命令会悄悄失败。
    开头那句是关掉进度条输出，免得 stderr 里塞满 CLIXML 噪音、真正的错误看不清。
    """
    script = "$ProgressPreference = 'SilentlyContinue'; " + script
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return subprocess.run([powershell_exe(), '-NoProfile', '-EncodedCommand', encoded],
                          capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout)


def shell_folder(name):
    """取系统登记的真实位置。

    桌面/开始菜单可能被挪到别的盘或 OneDrive，不能只按 %USERPROFILE%\\Desktop 拼。
    """
    try:
        r = run_ps("(New-Object -ComObject WScript.Shell).SpecialFolders('%s')" % name)
        path = r.stdout.decode('gbk', 'replace').strip()
        if path and os.path.isdir(path):
            return path
    except Exception:
        pass
    return ''


def desktop_dir():
    return shell_folder('Desktop') or os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')


def start_menu_dir():
    return shell_folder('Programs') or os.path.join(
        os.environ.get('APPDATA', ''), r'Microsoft\Windows\Start Menu\Programs')


# ---------- 快捷方式 / 注册表 ----------
def make_shortcut(lnk, target, workdir):
    """创建快捷方式；返回空字符串表示成功，否则返回出错原因。"""
    try:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
    except OSError as e:
        return '建不了快捷方式所在目录：%s' % e
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
          "$s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; "
          "$s.IconLocation = '%s'; $s.Save()" % (lnk, target, workdir, target))
    try:
        r = run_ps(ps)
    except Exception as e:
        return '调用 PowerShell 失败：%s' % e
    if r.returncode != 0:
        lines = [ln.strip() for ln in r.stderr.decode('gbk', 'replace').splitlines()
                 if ln.strip() and not ln.lstrip().startswith(('#<', '<Objs', '<S ', '<TN ', '<Obj '))]
        return 'PowerShell 返回 %s：%s' % (r.returncode, (lines[0] if lines else '')[:200])
    if not os.path.exists(lnk):
        return '命令跑完了但没生成 %s' % lnk
    return ''


def write_uninstall_reg(target, size_kb):
    exe = os.path.join(target, MAIN_EXE)
    uninst = os.path.join(target, UNINST_EXE)
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINST_KEY, 0, winreg.KEY_WRITE)
    items = [('DisplayName', DISPLAY_NAME), ('DisplayVersion', VERSION),
             ('InstallLocation', target), ('DisplayIcon', exe),
             ('UninstallString', '"%s" /uninstall' % uninst),
             ('QuietUninstallString', '"%s" /uninstall /silent' % uninst)]
    for name, value in items:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    for name in ('NoModify', 'NoRepair'):
        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(key, 'EstimatedSize', 0, winreg.REG_DWORD, int(size_kb))
    winreg.CloseKey(key)


def remove_uninstall_reg():
    try:
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, UNINST_KEY)
    except OSError:
        pass


# ---------- 安装 / 卸载 ----------
def install(target, desktop_shortcut=True, log=print):
    src = payload_dir()
    if not os.path.isdir(src):
        raise RuntimeError('安装包里的程序文件缺失：%s' % src)
    log('正在复制程序文件到 %s …' % target)
    os.makedirs(target, exist_ok=True)
    total = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
        rel = os.path.relpath(root, src)
        dst_root = target if rel == '.' else os.path.join(target, rel)
        os.makedirs(dst_root, exist_ok=True)
        for name in files:
            if name in SKIP_NAMES:
                continue
            dst = os.path.join(dst_root, name)
            shutil.copy2(os.path.join(root, name), dst)
            total += os.path.getsize(dst)
    log('复制完成，共 %.1f MB' % (total / 1048576.0))

    exe = os.path.join(target, MAIN_EXE)
    if not os.path.exists(exe):
        raise RuntimeError('复制后没找到 %s，安装包可能不完整' % MAIN_EXE)

    log('正在创建快捷方式 …')
    links = [os.path.join(start_menu_dir(), SHORTCUT_NAME + '.lnk')]
    if desktop_shortcut:
        links.append(os.path.join(desktop_dir(), SHORTCUT_NAME + '.lnk'))
    warnings = []
    for lnk in links:
        err = make_shortcut(lnk, exe, target)
        if err:
            warnings.append(err)
            log('创建快捷方式失败：%s' % err)
        else:
            log('已创建快捷方式：%s' % lnk)

    log('正在写入卸载信息 …')
    shutil.copy2(sys.executable, os.path.join(target, UNINST_EXE))
    write_uninstall_reg(target, total / 1024)
    log('安装完成：%s' % target)
    return warnings


def uninstall(log=print):
    """卸载。返回 'elevated'（已提权、交给新实例继续）/ 'done' / 'nothing'。"""
    target = read_install_location()
    if not target or not os.path.isdir(target):
        log('没找到安装记录，可能已经卸载过了。')
        return 'nothing'
    if not can_write(target) and not is_admin():
        log('删除 %s 需要管理员权限，正在申请提权…' % target)
        if relaunch_elevated([sys.executable, '/UNINSTALL', '/SILENT']):
            return 'elevated'
        raise RuntimeError('没有权限删除 %s' % target)
    log('正在删除快捷方式 …')
    for lnk in (os.path.join(start_menu_dir(), SHORTCUT_NAME + '.lnk'),
                os.path.join(desktop_dir(), SHORTCUT_NAME + '.lnk')):
        try:
            os.remove(lnk)
        except OSError:
            pass
    remove_uninstall_reg()
    log('正在删除程序目录 %s …' % target)
    # 自己也在要删的目录里，得等本进程退出后再删：交给一个分离的 cmd 去干
    subprocess.Popen('ping -n 4 127.0.0.1 > nul & rmdir /s /q "%s"' % target,
                     shell=True, creationflags=0x00000008)
    return 'done'


def read_install_location():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINST_KEY)
        value = winreg.QueryValueEx(key, 'InstallLocation')[0]
        winreg.CloseKey(key)
        return value
    except OSError:
        return ''


# ---------- 命令行 ----------
def arg_value(flag):
    for a in sys.argv[1:]:
        if a.lower().startswith(flag + '='):
            return a.split('=', 1)[1].strip('"')
    return ''


def has_flag(flag):
    return any(a.lower() == flag for a in sys.argv[1:])


def file_log(path):
    """静默安装时把过程写进文件，出问题能查（/LOG=某路径）。"""
    f = open(path, 'w', encoding='utf-8')

    def log(*a):
        print(*a, file=f, flush=True)

    return log


# ---------- 图形界面 ----------
class SetupUI:
    def __init__(self, root, mode):
        self.root = root
        self.mode = mode
        root.title('%s 安装程序' % DISPLAY_NAME)
        root.resizable(False, False)
        pad = {'padx': 12, 'pady': 6}
        padx = {'padx': 12}

        ttk.Label(root, text='%s %s' % (DISPLAY_NAME, VERSION),
                  font=('Microsoft YaHei UI', 13, 'bold')).grid(row=0, column=0, columnspan=3,
                                                               sticky='w', **pad)
        ttk.Label(root, text=('选择安装位置，然后点【开始安装】：' if mode == 'install'
                              else '确定要卸载 %s 吗？' % DISPLAY_NAME),
                  font=('Microsoft YaHei UI', 10)).grid(row=1, column=0, columnspan=3,
                                                       sticky='w', **padx)

        self.dir_var = tk.StringVar(value=read_install_location() or DEFAULT_DIR)
        if mode == 'install':
            ttk.Label(root, text='安装目录：', font=('Microsoft YaHei UI', 10)
                      ).grid(row=2, column=0, sticky='w', **padx)
            ttk.Entry(root, textvariable=self.dir_var, width=44,
                      font=('Microsoft YaHei UI', 10)).grid(row=2, column=1, sticky='we', pady=6)
            ttk.Button(root, text='浏览…', width=8, command=self.browse).grid(row=2, column=2,
                                                                            padx=(6, 12), pady=6)
            self.desktop_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(root, text='创建桌面快捷方式', variable=self.desktop_var
                            ).grid(row=3, column=0, columnspan=3, sticky='w', **padx)
            ttk.Label(root, text='提示：装到 Program Files 需要管理员权限，会自动弹出 UAC 确认；'
                                 '装到自己的目录（如 D:\\Dazi）则不需要。',
                      font=('Microsoft YaHei UI', 9), foreground='#666666', wraplength=430,
                      justify='left').grid(row=4, column=0, columnspan=3, sticky='w', **padx)

        self.bar = ttk.Progressbar(root, mode='indeterminate', length=440)
        self.bar.grid(row=5, column=0, columnspan=3, sticky='we', padx=12, pady=(10, 2))
        self.status = tk.StringVar(value='')
        ttk.Label(root, textvariable=self.status, font=('Microsoft YaHei UI', 9),
                  foreground='#0a5fa5', wraplength=440, justify='left'
                  ).grid(row=6, column=0, columnspan=3, sticky='w', **padx)

        btns = ttk.Frame(root)
        btns.grid(row=7, column=0, columnspan=3, sticky='e', padx=12, pady=10)
        self.ok_btn = ttk.Button(btns, text='开始安装' if mode == 'install' else '卸载',
                                 width=12, command=self.on_ok)
        self.ok_btn.pack(side='left')
        ttk.Button(btns, text='取消', width=8, command=root.destroy).pack(side='left', padx=8)

    def browse(self):
        d = filedialog.askdirectory(title='选择安装目录', initialdir=self.dir_var.get())
        if d:
            self.dir_var.set(os.path.normpath(d))

    def log(self, text):
        self.status.set(text)
        self.root.update_idletasks()

    def on_ok(self):
        if self.mode == 'uninstall':
            if not messagebox.askyesno('确认卸载', '删除 %s 及其快捷方式？\n\n'
                                                    '（登录状态会保留）' % self.dir_var.get()):
                return
            self.ok_btn.configure(state='disabled')
            self.bar.start(12)
            threading.Thread(target=self.do_uninstall, daemon=True).start()
            return

        target = os.path.normpath(self.dir_var.get().strip() or DEFAULT_DIR)
        if not target:
            return
        if not can_write(target) and not is_admin():
            # 目标目录需要管理员权限：提权重跑一次，界面交给提权后的实例去显示
            self.log('目标目录需要管理员权限，正在申请提权…')
            extra = [] if self.desktop_var.get() else ['/NODESKTOP']
            if relaunch_elevated([sys.executable, '/INSTALL', '/DIR=' + target] + extra):
                self.root.destroy()
                return
            messagebox.showerror('无法写入', '目标目录不可写，也没能提权。\n请换一个目录，'
                                             '或以管理员身份运行本安装程序。')
            return
        self.ok_btn.configure(state='disabled')
        self.bar.start(12)
        threading.Thread(target=self.do_install, args=(target,), daemon=True).start()

    def do_install(self, target):
        try:
            warnings = install(target, self.desktop_var.get(), log=self.log)
        except Exception as e:
            self.bar.stop()
            self.root.after(0, lambda: (self.ok_btn.configure(state='normal'),
                                        messagebox.showerror('安装失败', str(e))))
            return
        self.bar.stop()
        msg = '已安装到：\n%s\n\n开始菜单和桌面都有快捷方式。' % target
        if warnings:
            msg = ('已安装到：\n%s\n\n快捷方式没能创建（%s）。\n'
                   '可以到安装目录里右键 %s → 发送到 → 桌面快捷方式。' % (target, warnings[0], MAIN_EXE))
        self.root.after(0, lambda: (self.bar.configure(mode='determinate', value=100),
                                    messagebox.showinfo('安装完成', msg),
                                    self.root.destroy()))

    def do_uninstall(self):
        try:
            status = uninstall(log=self.log)
        except Exception as e:
            self.bar.stop()
            self.root.after(0, lambda: messagebox.showerror('卸载失败', str(e)))
            return
        self.bar.stop()
        if status == 'elevated':
            self.root.after(0, lambda: (messagebox.showinfo('已申请提权',
                                                            '已弹出 UAC 确认，确认后会继续删除程序目录。'),
                                        self.root.destroy()))
            return
        if status == 'nothing':
            self.root.after(0, lambda: (messagebox.showinfo('无需卸载', '没有找到安装记录。'),
                                        self.root.destroy()))
            return
        self.root.after(0, lambda: (messagebox.showinfo('卸载完成', '程序已删除，登录状态已保留。'),
                                    self.root.destroy()))


def main():
    silent = has_flag('/silent')
    target = arg_value('/dir')
    logpath = arg_value('/log')
    log = file_log(logpath) if logpath else (lambda *a: None)
    if has_flag('/uninstall'):
        if silent:
            uninstall(log=log)
            return 0
        root = tk.Tk()
        SetupUI(root, 'uninstall')
        root.mainloop()
        return 0
    if silent:
        install(target or DEFAULT_DIR, not has_flag('/nodesktop'), log=log)
        return 0
    root = tk.Tk()
    ui = SetupUI(root, 'install')
    if target:                         # 提权重跑时会把已经选好的目录带过来
        ui.dir_var.set(target)
    if has_flag('/nodesktop'):
        ui.desktop_var.set(False)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
