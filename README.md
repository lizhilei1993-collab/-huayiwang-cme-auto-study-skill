# CME Auto Study · 继续教育平台自动学习技能

继续教育平台的自动化学习工具集：**自动登录（验证码 OCR）→ 无头浏览器自动播放视频 → 自动答题考试 → 看门狗守护**。一次配置，挂机跑完，回来验收学分。

> 免责声明：本项目仅用于技术学习与交流，演示浏览器自动化与进程守护的工程实践。请遵守目标平台的服务条款与相关规定，因滥用造成的后果由使用者自行承担。

## 功能特性

- **纯 HTTP 自动登录**：逆向登录 AJAX 接口，ddddocr 本地识别验证码，失败自动重试；会话失效自动重登（带冷却）
- **CDP 无头浏览器播放**：双实例隔离（9222 播放 / 9223 考试），自动处理媒体挂起、签到弹层、暂停恢复、掉线重连
- **自动考试**：答案库按 qid / 题面归一化匹配，答错自动更换答案重新提交，单题 2–5 轮收敛
- **工程级守护**：看门狗监控日志停更（>12min 杀重启）、Chrome 端口探活自动拉起、Windows 计划任务承载长跑进程

## 目录结构

```
cme-auto-study/
├── SKILL.md               # 技能清单（name/description/用法）
├── README.md
├── requirements.txt
├── config.example.json    # 配置模板（复制为 config.json，已 gitignore）
├── .gitignore
├── scripts/               # 全部脚本
│   ├── config.py          #   统一配置入口（env > config.json > 默认）
│   ├── cme_login.py       #   登录（纯HTTP+OCR，浏览器兜底）
│   ├── cme_runner.py      #   队列守护：逐单元播放+异常处理
│   ├── cme_auto_exam.py   #   自动考试主流程
│   ├── cme_http_exam.py   #   纯HTTP考试（浏览器兜底）
│   ├── cme_cdp.py         #   CDP工具箱（导航/点击/状态/cookie）
│   ├── cme_captcha.py     #   验证码获取与OCR
│   ├── cme_solve.py       #   单题求解（答案库+收敛）
│   ├── cme_exam.py        #   考试页解析
│   ├── cme_progress.py    #   课程进度总览
│   ├── cme_grab.py        #   页面抓取
│   ├── cme_watch.py       #   单视频守护（agent-browser 版）
│   ├── cme_slides*.py     #   讲义图片下载
│   ├── cme_fetch_lists.py / cme_course_units.py / cme_parse_units.py / cme_goto_unit.py
│   ├── cme_netdiag.py     #   网络诊断
│   ├── chrome_supervisor.py  # Chrome 守护（计划任务运行）
│   ├── cme_guard.ps1      #   外部看门狗（PowerShell）
│   └── ab_launch.sh / ab_watch.sh / ab_watch2.sh
└── data/
    ├── answers.example.json   # 答案库示例
    └── courses.example.json   # 课程列表示例
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置（平台地址与账号；也可用环境变量 CME_HOST / CME_USER / CME_PWD）
cp config.example.json config.json

# 3. 登录（自动识别验证码，刷新 ab/cookies_latest.json）
python scripts/cme_login.py

# 4. 查看课程进度（列出待考试单元）
python scripts/cme_progress.py <课程ID>

# 5. 生成学习队列 ab/queue.json 后启动挂课
python scripts/cme_runner.py

# 6. 视频学完后自动考试
python scripts/cme_auto_exam.py
```

## 配置说明

| 配置项 | 环境变量 | 说明 |
| --- | --- | --- |
| `host` | `CME_HOST` | 平台根地址（带结尾斜杠） |
| `cdn_base` | `CME_CDN` | 讲义/CDN 地址根 |
| `user` / `password` | `CME_USER` / `CME_PWD` | 平台账号密码 |
| `data_dir` | `CME_DATA_DIR` | 运行时数据目录，默认 `./ab` |
| `alive_check` | `CME_ALIVE_CHECK` | 会话有效性探测 URL（任一需登录页面） |
| `alive_marker` | `CME_ALIVE_MARKER` | 探测页登录态特征串 |
| `courses` | - | 课程 ID → 名称映射 |
| `course_list` | - | 课程清单 `[["代码","课程名","课程ID","HTML文件名"]]` |

## 工作原理：四个暗坑与解法

1. **媒体挂起**：窗口 0×0、`visibilityState=hidden` 时 Chrome 挂起 MSE 媒体加载（`readyState=0`、零分片请求、不报错）→ 每次导航后强制 `Page.bringToFront`
2. **签到弹层冻结**：弹窗出现后播放器状态"正常"但时间戳冻住 → 以**时间戳是否前进**为唯一可信判据，90 秒不动强制重载；三级处置（可信点击 → 隐藏遮罩强制播放 → 重载）
3. **会话过期**：session cookie `expires=-1` 会导致 CDP `BINDINGS: double value expected` → 注入前清洗为 `expires>0`；失效自动重登带 300s 冷却
4. **考试硬门禁**：视频未看完时考试接口返回"请先完成课件学习" → 开播前做单元完成态预检（`data-maxtime >= data-totaltime` 且 `data-completed == 0`）

## 守护方案

- `chrome_supervisor.py`：单实例锁 + 每 20s 探活 CDP 端口，挂了自动重启 Chrome（同 profile，cookie 保留）
- `cme_guard.ps1`：外部看门狗——`runner.log` 停更 >12min 且进程 Running → 杀重启；CDP 端口不通 → 拉起 Chrome 守护
- 长跑进程建议由 **Windows 计划任务** 承载（会话内进程会被环境回收）；计划任务环境记得给 Python 设 `PYTHONUTF8=1`

## 脚本清单

| 脚本 | 用途 |
| --- | --- |
| `cme_login.py` | 登录（`login` / `check` / `captcha` / `submit`） |
| `cme_runner.py` | 队列守护播放主程序 |
| `cme_auto_exam.py` | 自动考试主流程 |
| `cme_http_exam.py` | 纯 HTTP 考试 |
| `cme_cdp.py` | CDP 工具箱（info/nav/state/click/type/cookies-out/cookies-in/...） |
| `cme_progress.py` | 课程进度总览 → `progress.json` |
| `cme_solve.py` | 单题求解（答案库 + 收敛重试） |
| `chrome_supervisor.py` | Chrome 守护 |
| `cme_guard.ps1` | 看门狗（计划任务触发） |
| `ab_watch2.sh` | agent-browser 视频守护（原生点击版） |
