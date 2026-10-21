# -*- coding: utf-8 -*-
"""统一配置入口：优先级 环境变量 > config.json > 默认值。

所有敏感信息（账号、密码、平台地址、数据目录）一律经此处读取，
各业务脚本不硬编码任何个人信息。占位域名见 config.example.json。
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR_DEFAULT = ROOT / "ab"
_CFG_PATH = ROOT / "config.json"


def _cfg():
    try:
        return json.loads(_CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get(key, env, default=None):
    v = os.environ.get(env)
    if v:
        return v
    return _cfg().get(key, default)


def host():
    """平台根地址（带结尾斜杠），如 https://cme.example.com/"""
    return (_get("host", "CME_HOST", "https://cme.example.com/") or "").rstrip("/") + "/"


def origin():
    """平台 origin（无结尾斜杠），如 https://cme.example.com"""
    return host().rstrip("/")


def site():
    """平台主机名，如 cme.example.com"""
    return urlparse(origin()).netloc


def site_key():
    """可注册域（用于 cookie domain 子串匹配），如 example.com"""
    parts = site().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else site()


def cdn_base():
    """讲义/CDN 地址根（无结尾斜杠）"""
    return _get("cdn_base", "CME_CDN", "https://cdn.example.com")


def user():
    return _get("user", "CME_USER", "")


def password():
    return _get("password", "CME_PWD", "")


def data_dir():
    """运行时数据目录（cookie/日志/队列/答案库），默认 <包根>/ab"""
    v = _get("data_dir", "CME_DATA_DIR", None)
    if v:
        p = Path(v)
        return p if p.is_absolute() else (ROOT / p)
    return DATA_DIR_DEFAULT


def alive_check():
    """会话有效性探测 URL：任一需登录才能查看的页面"""
    return _get("alive_check", "CME_ALIVE_CHECK", host() + "pages/cme.aspx")


def alive_marker():
    """alive_check 页面登录态特征串"""
    return _get("alive_marker", "CME_ALIVE_MARKER", "data-cwrid")


def courses():
    """课程 ID -> 课程名 映射"""
    return _cfg().get("courses", {}) or {}


def course_list():
    """课程清单 [["代码","课程名","课程ID","详情页HTML文件名"], ...]"""
    return _cfg().get("course_list", []) or []
