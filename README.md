# KUKUWCheat

在线打字测试（[dazi.kukuw.com](https://dazi.kukuw.com/)）的自动打字助手：Python + Selenium + tkinter，
带可视化界面、按真人节奏逐字敲、实时镜像网页测试界面，并可一条命令打包成 Windows exe / 安装包。

> ⚠️ **仅供学习交流**。项目用于练习 Selenium 浏览器自动化、tkinter 界面、打包发布等工程技能。
> 在目标站点上自动打字/提交成绩可能违反其站点规则，**一切后果由使用者自行承担**，详见文末[免责声明](#免责声明)。

**下载**：[最新版本](https://github.com/LuoyeAutumn/KUKUWCheat/releases/latest) ——
安装版 `KUKUWCheat_Setup.exe`（推荐）或 单文件版 `KUKUWCheat.exe`，双击即用，**不需要装 Python**。
想从源码跑或自己打包，见[快速开始](#快速开始)与[打包成 exe](#打包成-exe)。

---

## 功能特性

- **可视化界面**：账号登录 + 参数设置 + 实时镜像 + 运行日志，一个窗口搞定
- **实时镜像测试界面**：与网页同步显示每一行文字，已输入的字按对错着色、当前行高亮；
  站点统计（倒计时/速度/正确率/错误/总字数/退格）按站点自己的刷新节奏（100 ms）同步，
  实测「网页 → 界面」延迟 **约 15 ms**
- **模拟真人打字**：不是整行粘贴，而是一个字一个字地敲（合成 `keydown → input → keyup` 事件），
  字间间隔在「平均值 ± 波动幅度」里随机抖动
- **按速度反推节奏**：直接填目标速度（站点"速度"栏的口径），自动算出每字间隔并**补偿打错率**；
  也可以手动改间隔，速度会跟着重算
- **拟真细节**：打中文时先敲一遍拼音字母（站点的按键统计不会是空的）；偶发打错字 + 退格改回，
  站点的"退格次数"和真人一样不是 0
- **登录持久化**：账号密码登录 / 微信扫码登录；浏览器用户目录 + cookie 备份双保险，下次免登录
- **暂停 / 停止**：可以只停出字（网页倒计时继续走），也可以连网页测试一起暂停；
  中途停止会自动按停网页测试，避免时间到了自动交一份低分
- **测试类型**：中文打字 / 英文打字 / 竞赛 / 竞赛(邀请码)
- **可打包发布**：一条命令打成 Windows exe（单文件版 / 文件夹版）和安装程序（默认装到 `C:\Program Files (x86)\KUKUWCheat`，路径可改，带卸载）

---

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 系统 | Windows 10 / 11（依赖系统自带 Edge 浏览器） |
| Python | 3.9+（开发与打包环境为 3.14）——**只跑 exe 的话不需要** |
| 依赖 | `selenium`（`pip install selenium`）；`tkinter` 为 Python 自带 |
| 驱动 | 无需手动装：首次运行由 Selenium Manager 自动下载匹配版本的 Edge 驱动（需联网） |

> 仓库里只有源码。源码运行需要 `pip install selenium`；`_libs/` 是给离线环境随包携带的 selenium 副本，
> 已在 `.gitignore` 中（如果你本地有，代码会优先用它，此时可以不装 selenium）。

---

## 快速开始

### 方式一：下载预编译版（不用装 Python）

到 [Releases](https://github.com/LuoyeAutumn/KUKUWCheat/releases/latest) 下载：

| 文件 | 适合 | 说明 |
| --- | --- | --- |
| `KUKUWCheat_Setup.exe` | 推荐 | 安装版：默认装到 `C:\Program Files (x86)\KUKUWCheat`，可自定义路径，建开始菜单/桌面快捷方式，可在"应用和功能"里卸载 |
| `KUKUWCheat.exe` | 便携 | 单文件版：双击即用，不写注册表、不动开始菜单；启动比安装版慢 1~3 秒（每次要解包），登录缓存在 exe 旁边 |

> 如果 Windows 弹出"Windows 已保护你的电脑"（SmartScreen），那是 PyInstaller 打包 exe 的常见误报：
> 点"更多信息 → 仍要运行"，或把文件加到杀软白名单。

### 方式二：源码运行

```bash
pip install selenium
python kukuwcheat_gui.py            # 启动图形界面
python kukuwcheat_gui.py --console  # 想保留命令行窗口看输出时用这个
```

双击 `kukuwcheat_gui.py` 也可以：程序会自己用 `pythonw.exe` 重启一遍，不留命令行黑窗口。

### 方式三：命令行版（不带界面）

```bash
python kukuwcheat_auto.py --help
python kukuwcheat_auto.py --type cn --interval 0.3 --jitter 0.1
```

### 第一次使用（三种方式都一样）

1. 打开后是**游客身份**，成绩不会计入账号
2. 填账号密码点【登录】，或点【微信扫码登录】（扫码需要能看到浏览器窗口）
3. 登录状态会缓存到本地，下次启动自动恢复；**程序不保存密码**

缓存在哪、怎么迁移或清理，见[登录与缓存位置](#登录与缓存位置)。

---

## 使用说明

### 界面参数

| 参数 | 说明 |
| --- | --- |
| 测试类型 | 中文打字 / 英文打字 / 竞赛 / 竞赛(邀请码) |
| 选择文章 | 中文或英文文章列表；竞赛类型下是竞赛列表；勾选"随机选"可随机挑一篇 |
| 邀请码 | 仅"竞赛(邀请码)"需要填 |
| **目标速度** | 站点"速度"栏那个数（每分钟正确字数）。中文测试的栏位写作 `WPM`、英文写作 `KPM`——站点把标签写反了，**数值都是字/分** |
| 波动幅度 | 每字间隔的 ± 百分比（默认 33%），间隔一变它跟着变 |
| 打错率 | 百分之多少的字先打错、顿一下、退格改回来（默认 1%） |
| 每字间隔 | 跟着目标速度自动算出来的平均值，也可以手动改（改完目标速度会重算） |
| 测试时间 | 1~50 分钟；竞赛的时长由竞赛本身决定，本地改不了（站点的规则，已实测过） |
| 显示浏览器窗口 | 勾上会额外开一个真实浏览器窗口，方便观察/手动接管（平时不用勾） |

按钮：**开始测试** / **暂停出字** / **暂停全部** / **停止**。

- 暂停出字：只停打字，网页倒计时继续走（时间到了按当时进度结算）
- 暂停全部：同时按下网页自己的暂停键，倒计时和成绩一起停住
- 暂停中对应按钮会变成【继续】，另一个按钮置灰，防止按错

### 速度换算

站点"速度"的口径（从 `typing.js` 读出来的公式）是：

```
速度 = 正确字数 ÷ 净打字时间(分钟)          # R = (k - H) / r * 60000
```

所以程序按下面这条反推每字间隔（`打错补偿系数 = 1 + (2.5+6)/2 = 5.25`，即每个错字多花 5.25 个字的时间）：

```
每字间隔 = 60 / (目标速度 × (1 + 5.25 × 打错率))
```

实测：目标 150 字/分、打错 5% 时，站点最终显示 **149**（误差 0.7%）。
短时间（几十秒）测出的速度会有几个百分点的浮动，原因是站点把"进入测试页到敲第一个字"的空转也算进用时
（约 1~2 秒），另外打错后"顿一下"是 2.5~6 倍间隔的随机值。

### 登录与缓存位置

第一次使用是**游客身份**（成绩不计入账号），需要自己登录：填账号密码点【登录】，或点【微信扫码登录】。
登录成功后程序会做两件事：浏览器用户目录里保留会话 + 把 cookie 备份成 `.login_cookies.json`；
下次启动先看首页是否已登录，没登录才用备份 cookie 恢复（不会覆盖已经有效的登录）。**程序不保存密码**。

缓存位置规则：**先看 exe 所在目录能不能写**

| 用法 | 缓存位置 |
| --- | --- |
| 单文件版（或自己打包的文件夹版）放在可写目录 | `<exe 所在目录>\.browser_profile`、`.login_cookies.json` |
| 安装版装到 `C:\Program Files (x86)\KUKUWCheat`（普通用户不可写） | `%LOCALAPPDATA%\KUKUWCheat\` |

> 卸载只删程序目录，`%LOCALAPPDATA%\KUKUWCheat` 会保留，重装不用重新登录。
> `.browser_profile` 会随使用慢慢变大（几百 MB 级），想回收直接删掉即可（会掉登录）。

---

## 命令行用法

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--type` | `cn` | `cn` 中文 / `en` 英文 / `group` 竞赛 / `group2` 竞赛(邀请码) |
| `--art` | 无 | 文章 ID；`--type group` 时是竞赛 ID |
| `--code` | 无 | 竞赛邀请码（`group2` 必填） |
| `--minutes` | `5` | 测试时间 1~50 分钟（竞赛由竞赛本身决定） |
| `--interval` | `0.3` | 每字平均间隔（秒），约 200 字/分 |
| `--jitter` | `0.1` | 每字间隔的随机浮动 ±秒（会保住平均值，不会把节奏拖慢） |
| `--error-rate` | `1.0` | 打错字的概率百分比（会自动退格改回来） |
| `--browser` | `auto` | `edge` / `chrome` / `auto` |
| `--user` / `--password` | 无 | 登录账号（不填就是游客身份） |
| `--headless` | 关 | 无界面模式运行 |
| `--close` | 关 | 跑完自动关闭浏览器 |

---

## 打包成 exe

```bash
pip install selenium pyinstaller

# 1) 文件夹版（便携）
python -m PyInstaller --noconfirm --onedir --noconsole --name KUKUWCheat ^
  --collect-all selenium ^
  --hidden-import selenium.webdriver.edge.webdriver ^
  --hidden-import selenium.webdriver.edge.options ^
  --hidden-import selenium.webdriver.edge.service ^
  --hidden-import selenium.webdriver.chrome.webdriver ^
  --hidden-import selenium.webdriver.chrome.options ^
  --hidden-import selenium.webdriver.chrome.service ^
  --distpath dist\portable kukuwcheat_gui.py

# 2) 单文件版
python -m PyInstaller --noconfirm --onefile --noconsole --name KUKUWCheat ^
  --collect-all selenium ^
  --hidden-import selenium.webdriver.edge.webdriver ^
  --hidden-import selenium.webdriver.edge.options ^
  --hidden-import selenium.webdriver.edge.service ^
  --hidden-import selenium.webdriver.chrome.webdriver ^
  --hidden-import selenium.webdriver.chrome.options ^
  --hidden-import selenium.webdriver.chrome.service ^
  --distpath dist\single kukuwcheat_gui.py

# 3) 安装程序（把上面第 1 步的文件夹版当包体塞进去）
python -m PyInstaller --noconfirm --onefile --noconsole --name KUKUWCheat_Setup ^
  --add-data "dist\portable\KUKUWCheat;KUKUWCheat" ^
  --distpath dist kukuwcheat_setup.py
```

> 产物都在 `dist/`，已在 `.gitignore` 里（不进仓库）。要发新版时把
> `dist\KUKUWCheat_Setup.exe` 和 `dist\single\KUKUWCheat.exe` 作为 Release 资产上传即可：
> 网页上拖拽，或 `gh release create v1.0.1 dist\KUKUWCheat_Setup.exe dist\single\KUKUWCheat.exe`。

两个坑（都踩过）：

1. **必须加 `--hidden-import selenium.webdriver.edge.webdriver` 那几个**。selenium 用的是惰性导入，
   PyInstaller 静态分析看不到，漏了会在运行时报 `No module named 'selenium.webdriver.edge.webdriver'`。
2. 如果你用 `_libs/` 里的 selenium（没 `pip install`），再补一个 `--paths _libs`。

安装程序还支持静默参数，方便批量部署：

```bat
KUKUWCheat_Setup.exe /SILENT /DIR="D:\KUKUWCheat" /LOG=D:\install.log
KUKUWCheat_Setup.exe /SILENT /DIR=... /NODESKTOP      :: 不建桌面快捷方式
KUKUWCheat_Setup.exe /UNINSTALL /SILENT               :: 静默卸载
```

---

## 目录结构

仓库里就这几个文件：

```
KUKUWCheat/
├─ README.md
├─ LICENSE                   # MIT
├─ .gitignore
├─ kukuwcheat_auto.py        # 核心：开浏览器、选文章、逐字打字、登录、类型/竞赛/时间选择（也是命令行版）
├─ kukuwcheat_gui.py         # 图形界面（入口）：实时镜像 + 参数联动 + 暂停/停止
└─ kukuwcheat_setup.py       # 安装程序（安装/卸载二合一），打包成 KUKUWCheat_Setup.exe
```

运行/打包之后会多出这些（都写在 `.gitignore` 里，**不会进仓库**）：

```
.browser_profile/            # 浏览器用户目录，登录状态就在里面（几百 MB 级）
.login_cookies.json          # 登录 cookie 备份
dist/  _build/               # 打包产物与构建缓存
```

---

## 常见问题

**Q：提示"浏览器用户目录被占用，本次改用临时目录"？**
上一次的浏览器没退干净（比如上个会话被强杀）。程序会先重试、再自动清理自己的残留浏览器进程；
如果同时开着两个本程序窗口，关掉多余的那个再重开。

**Q：登录丢了？**
说明当前的用户目录不可写（换过安装位置，或目录权限变了）。程序会用 `.login_cookies.json` 里的
cookie 备份自动恢复；如果你把这个文件删了，重新登录一次即可。

**Q：打字打不出来 / 不换行？**
站点改版了。需要更新的注入脚本在上面的 JS 常量里：`TYPE_CHAR_JS`（敲字）、`BACKSPACE_JS`（退格）、
`TYPO_CHAR_JS`（挑错字）、`ACTIVE_LINE_JS`（找当前行）、`READ_STATE_JS`（读状态，在 GUI 里）。

**Q：速度对不上目标？**
见上文[速度换算](#速度换算)里的说明：短时间窗口、打错后随机停顿都会造成几个百分点的浮动。

**Q：浏览器没起来 / 报驱动相关错误？**
首次运行需要联网让 Selenium Manager 下载驱动；受限网络环境下可以手动放置 `msedgedriver.exe` 并指定路径。

**Q：杀软/Defender 报毒？**
PyInstaller 打出来的 exe 被误报很常见（单文件版尤其明显）。可以改用安装版，或把文件/安装目录加入白名单。

---

## 实现原理（技术要点）

- **绕过禁止粘贴**：站点在 `typing.js` 里写死了 `document.body.onpaste = function(){return!1}`，
  真正的 Ctrl+V 会被取消。所以不使用粘贴，而是合成 `keydown → input → keyup` 三种事件，
  并在事件上用 `Object.defineProperty` 补上 `keyCode`/`which`，避免站点脚本取值时报错导致无法换行。
- **中文的拼音按键统计**：真人打中文是先敲拼音再上屏。站点会统计按键（`kn1` 字段），
  直接派发汉字（键码 229）会被它整个忽略、统计为空——本身就是破绽。所以打中文时先按页面自带的
  `pinyin` 数据敲一遍拼音字母，再上屏这个字。
- **找当前行**：站点用 CSS 类 `typing_on` 标记正在输入的那一行（写完的行仍可编辑，不能只看 `readOnly`）；
  选择器必须限定 `div.typing`，因为 input 也带 `typing` 类。
- **取目标文本**：解析 `driver.page_source`，每行是 `<div id="i_N" class="typing">`，
  里面隐藏 input 的 `value` 就是该行目标文本。
- **速度口径与反推**：从站点 `typing.js` 里读出 `R = (k - H) / r * 60000`（正确字数 ÷ 净打字时间），
  据此反推每字间隔并补偿打错率（`interval_for_speed()` / `speed_for_interval()`）。
- **随机间隔不跑偏**：`delay_range()` 保证随机区间的**平均值**始终等于设定值——
  否则当浮动范围大于平均值时，下限被抬到 0.01 秒而那侧照着抬，平均节奏会被单边撑大。
- **实时同步**：每敲完一个字立刻读一次页面状态推给界面，字与字之间再按站点刷新节奏（100 ms）补读；
  界面侧每 30 ms 取一次事件队列，并且积压的状态事件只保留最新一条（界面卡顿也不会让队列堆起来）。
- **登录持久化**：固定 `--user-data-dir` 保留会话 + cookie 备份到 JSON；恢复只在"当前不是登录态"时做，
  避免把有效登录覆盖掉。
- **打包相关**：selenium 惰性导入 + 显式 `--hidden-import`；冻结后运行期数据目录改用 exe 所在目录
  （否则单文件版每次启动都会丢登录）；PowerShell 命令统一用 `-EncodedCommand`（`-Command` 传中文路径
  在部分代码页下会被解码错）。

---

## 免责声明

1. 本项目**仅供学习与个人研究**，用于练习浏览器自动化、桌面 GUI、打包发布等技术。
2. 使用本项目在目标站点自动打字、参与竞赛或提交成绩，**可能违反目标站点的用户协议/规则**，
   由此造成的账号封禁、成绩作废、数据清空等一切后果，由使用者自行承担。
3. 请勿将本项目用于商业用途、刷榜作弊、攻击或干扰任何站点的正常服务。
4. 本项目与 dazi.kukuw.com 及其运营方**没有任何关联**，也未获得其授权或认可。
5. 请在使用前确认你的行为符合当地法律法规与站点规则；如不同意，请勿使用。

---

## 许可证

本项目采用 [MIT 许可证](LICENSE) 开源。

```
Copyright (c) 2026 KUKUWCheat Contributors
```

你可以自由使用、修改、分发本项目，但需保留版权与许可声明；软件按"原样"提供，不附带任何担保。
