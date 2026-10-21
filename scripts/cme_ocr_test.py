# -*- coding: utf-8 -*-
"""用 ddddocr 测试验证码识别准确率（样本已知答案）。"""
import sys
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

import ddddocr

BASE = _data_dir()
SAMPLES = {
    "cap3.jpg": "32276",
    "cap4.jpg": "51145",
    "cap5.jpg": "77452",
    "cap6.jpg": "04396",
    "cap7.jpg": "58282",
    "cap8.jpg": "86859",
    "cap9.jpg": "09413",
    "captcha_exam.jpg": "17696",
    "captcha_exam2.jpg": "48538",
}


def main():
    ocr = ddddocr.DdddOcr(show_ad=False)
    ok = 0
    for name, label in SAMPLES.items():
        p = BASE / name
        if not p.exists():
            print("%-20s MISSING" % name)
            continue
        with open(p, "rb") as f:
            got = ocr.classification(f.read())
        hit = "OK " if got == label else "MISS"
        if got == label:
            ok += 1
        print("%-20s 真值=%-8s 识别=%-8s %s" % (name, label, got, hit))
    print("准确率 %d/%d" % (ok, len(SAMPLES)))


if __name__ == "__main__":
    main()
