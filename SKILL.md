---
name: cme-auto-study
display_name: 继续教育平台自动学习（CME）
display_name_en: cme-auto-study
description: 继续教育平台自动学习技能：纯HTTP自动登录（验证码OCR）、CDP无头浏览器自动播放视频、自动答题考试、看门狗进程守护。
description_zh: 继续教育平台自动学习技能：自动登录、自动播放、自动考试、进程守护，一次配置挂机跑完。
description_en: Automated CME study skill: auto-login with captcha OCR, headless video playback, auto exam, watchdog.
category: tools
version: 1.0.0
---

# 继续教育平台自动学习技能（CME Auto Study）

## 能力
1. **自动登录**：逆向登录 AJAX 接口 + ddddocr 验证码识别，纯 HTTP 完成，失败自动重试
2. **自动播放**：CDP 控制无头 Chrome 逐单元播放，自动处理媒体挂起、签到弹层、暂停恢复
3. **自动考试**：内置答案库，答错自动更换答案重新提交，直至正确
4. **进程守护**：掉线自动重登、看门狗杀重启、Chrome 端口探活，7×24 稳定运行

## 使用流程
1. 配置：`cp config.example.json config.json`，填入平台地址与账号（或设环境变量 `CME_HOST` / `CME_USER` / `CME_PWD`）
2. 登录：`python scripts/cme_login.py`
3. 查进度：`python scripts/cme_progress.py <课程ID>`
4. 生成队列：按进度写 `ab/queue.json`（`{"items":[{"cid","cwid","title","secs"}]}`）
5. 挂课：`python scripts/cme_runner.py`
6. 考试：`python scripts/cme_auto_exam.py`
7. 守护：`python scripts/chrome_supervisor.py --port 9222 --tag chromeA`；看门狗 `scripts/cme_guard.ps1`

## 合规提示
本项目仅用于技术学习与交流。请遵守目标平台服务条款，合理使用，后果自负。
