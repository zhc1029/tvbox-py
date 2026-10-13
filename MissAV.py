# -*- coding: utf-8 -*-
"""MissAV —— TVBox / OK影视 原生 py 源（单文件，仅 Python 标准库）

由 hipy 版改写：去掉 pyquery 与 base.spider 依赖，全部用 urllib + re 实现，
可在 OK影视 / TVBox 的 Python 模块里直接跑。

配置示例（加到接口 JSON 的 sites 里）：
{"key":"py_missav","name":"MissAV","type":3,"api":"https://你的直链/MissAV.py","ext":""}

extend 用法（可选）：
  - 空：用默认域名 https://missav.ai
  - 直接写域名：https://missav.com  （站点换域名时用这个）
  - JSON：{"host":"https://missav.com"}

注意：missav 有 Cloudflare 防护，电视/盒子必须能正常打开 missav.ai，
否则这个源也抓不到数据。
"""

import json
import re
import ssl

try:
    from urllib.request import Request, urlopen
    from urllib.parse import quote
except ImportError:  # pragma: no cover
    from urllib import quote
    from urllib2 import Request, urlopen

DEBUG = False

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_SSL_CTX = ssl.create_default_context()
try:
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE
except Exception:
    pass

HOST = "https://missav.ai"


def _log(msg):
    if DEBUG:
        try:
            print("[missav] %s" % msg)
        except Exception:
            pass


def _fetch(url):
    try:
        req = Request(url, headers={"User-Agent": UA, "Referer": HOST + "/cn/"})
        resp = urlopen(req, timeout=15, context=_SSL_CTX)
        raw = resp.read()
        for enc in ("utf-8", "gbk", "gb18030"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", "ignore")
    except Exception as e:
        _log("fetch fail %s -> %s" % (url, e))
        return ""


def _clean(txt):
    if not txt:
        return ""
    txt = re.sub(r"(?is)<script.*?</script>", "", txt)
    txt = re.sub(r"(?is)<style.*?</style>", "", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'),
                 ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        txt = txt.replace(a, b)
    return re.sub(r"\s+", " ", txt).strip()


def _fix_pic(pic):
    if not pic:
        return ""
    if pic.startswith("//"):
        return "https:" + pic
    return pic


def _parse_list(html):
    """解析列表页：按条目容器切分，正则提取标题/封面/链接/时长"""
    videos = []
    if not html:
        return videos
    parts = re.split(r'<div class="relative group', html)[1:]
    for p in parts:
        chunk = p[:5000]
        m = re.search(
            r'<a[^>]*href="(/cn/[^"]+)"[^>]*class="[^"]*text-secondary', chunk)
        if not m:
            m = re.search(
                r'<a[^>]*class="[^"]*text-secondary[^"]*"[^>]*href="(/cn/[^"]+)"',
                chunk)
        if not m:
            continue
        href = m.group(1)
        vid = href.rstrip("/").split("/")[-1]
        m = re.search(
            r'class="[^"]*text-secondary[^"]*"[^>]*>(.*?)</a>', chunk, re.S)
        name = _clean(m.group(1)) if m else vid
        m = re.search(r'<img[^>]*?(?:data-src|src)="(//[^"]+|https?://[^"]+)"',
                      chunk)
        pic = _fix_pic(m.group(1)) if m else ""
        m = re.search(
            r'<span class="absolute bottom-1 right-1[^"]*"[^>]*>(.*?)</span>',
            chunk, re.S)
        remarks = _clean(m.group(1)) if m else ""
        if not name:
            continue
        videos.append({
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remarks,
        })
    return videos


class Spider(object):

    def __init__(self):
        self.extend = ""
        self.host = HOST

    def init(self, extend=""):
        global HOST
        self.extend = extend or ""
        ext = (extend or "").strip()
        host = ""
        if ext.startswith("http"):
            host = ext
        elif ext.startswith("{"):
            try:
                host = json.loads(ext).get("host") or ""
            except Exception:
                host = ""
        if host:
            self.host = host.rstrip("/")
            HOST = self.host
        else:
            self.host = HOST
        _log("init ok, host=%s" % self.host)
        return self

    def homeContent(self, filter=False):
        classes = [
            {"type_id": "new", "type_name": "最近更新"},
            {"type_id": "release", "type_name": "新作上市"},
            {"type_id": "chinese-subtitle", "type_name": "中文字幕"},
            {"type_id": "uncensored-leak", "type_name": "无码流出"},
            {"type_id": "genres/VR", "type_name": "VR"},
            {"type_id": "today-hot", "type_name": "今日热门"},
            {"type_id": "weekly-hot", "type_name": "本周热门"},
            {"type_id": "monthly-hot", "type_name": "本月热门"},
        ]
        return {"class": classes, "list": self._cat("new", 1)}

    def homeVideoContent(self):
        return {"list": self._cat("new", 1)}

    def _cat(self, tid, pg):
        html = _fetch("%s/cn/%s?page=%s" % (self.host, tid, pg))
        return _parse_list(html)

    def categoryContent(self, tid, pg, filter=False, extend=None):
        pg = int(pg or 1)
        try:
            lst = self._cat(str(tid or "new"), pg)
            return {"list": lst, "page": pg, "pagecount": 999,
                    "limit": len(lst) or 20, "total": 999}
        except Exception as e:
            _log("categoryContent err %s" % e)
            return {"list": [], "page": pg, "pagecount": 1,
                    "limit": 20, "total": 0}

    def detailContent(self, ids):
        try:
            raw = ids[0] if isinstance(ids, (list, tuple)) else ids
            vid = str(raw or "").strip()
            if not vid:
                return {"list": []}
            html = _fetch("%s/cn/%s" % (self.host, vid))
            if not html:
                return {"list": []}
            m = re.search(
                r'<h1[^>]*class="[^"]*text-base[^"]*"[^>]*>(.*?)</h1>',
                html, re.S)
            name = _clean(m.group(1)) if m else vid
            m = re.search(r'<video[^>]*poster="([^"]+)"', html)
            pic = _fix_pic(m.group(1)) if m else ""
            m = re.search(r'<div class="mt-4[^"]*"[^>]*>(.*?)</div>', html,
                          re.S)
            content = _clean(m.group(1)) if m else ""
            vod = {
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_year": "",
                "vod_area": "",
                "vod_remarks": "",
                "vod_actor": "",
                "vod_director": "",
                "vod_content": content,
                "type_name": "MissAV",
                "vod_play_from": "MissAV",
                "vod_play_url": "播放$%s" % vid,
            }
            return {"list": [vod]}
        except Exception as e:
            _log("detailContent err %s" % e)
            return {"list": []}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            key = (key or "").strip()
            if not key:
                return {"list": []}
            html = _fetch("%s/cn/search/%s" % (self.host, quote(key)))
            return {"list": _parse_list(html)}
        except Exception as e:
            _log("searchContent err %s" % e)
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            vid = (id or "").strip()
            if "$" in vid:
                vid = vid.split("$")[-1]
            if not vid:
                return {"parse": 0, "playUrl": "", "url": "", "header": ""}
            header = json.dumps(
                {"User-Agent": UA, "Referer": self.host + "/cn/"},
                ensure_ascii=False)
            html = _fetch("%s/cn/%s" % (self.host, vid))
            m = re.search(r'https?://[^\s\'"]+\.m3u8[^\s\'"]*', html or "")
            if m:
                return {"parse": 0, "playUrl": "", "url": m.group(0),
                        "header": header}
            return {"parse": 1, "playUrl": "", "url": vid, "header": header}
        except Exception as e:
            _log("playerContent err %s" % e)
            return {"parse": 0, "playUrl": "", "url": "", "header": ""}

    def localProxy(self, param):
        return None
