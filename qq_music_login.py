"""QQ音乐扫码登录（纯 HTTP，无需无头浏览器）。

流程（QQ 第三方 OAuth，pt_3rd_aid=100497308）：
1. ptqrshow 拿二维码图片并写入 qrsig → 用 hash33(qrsig) 算 ptqrtoken；
2. 轮询 ptqrlogin，用户手机 QQ 扫码确认后返回 check_sig 跳转地址；
3. 访问该地址由服务端 Set-Cookie 写入 p_skey 等；
4. 用 g_tk(p_skey) 向 graph.qq.com/oauth2.0/authorize 换取 code；
5. 用 code 调 music.login.LoginServer/Login 换取 musickey(qm_keyst) 与 musicid(uin)；
6. 拼成 qq.php 需要的 Cookie 串：uin/qm_keyst/qqmusic_key/ptcz/RK。
"""
import json
import re
import time
import urllib.parse
import uuid

import aiohttp

# QQ音乐 第三方登录参数（与 y.qq.com 网页扫码登录一致）
APPID = 716027609
DAID = 383
PT_3RD_AID = 100497308
CLIENT_ID = 100497308
U1 = "https://graph.qq.com/oauth2.0/login_jump"
REDIRECT_URI = "https://y.qq.com/portal/wx_redirect.html?login_type=1&surl=https%3A%2F%2Fy.qq.com%2F"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def hash33(s: str) -> int:
    """ptqrtoken 算法（种子 0）。"""
    e = 0
    for c in s:
        e += (e << 5) + ord(c)
    return e & 0x7FFFFFFF


def g_tk(p_skey: str) -> int:
    """g_tk / bkn 算法（种子 5381）。"""
    h = 5381
    for c in p_skey:
        h += (h << 5) + ord(c)
    return h & 0x7FFFFFFF


def _cookie(jar: aiohttp.CookieJar, key: str) -> str:
    for c in jar:
        if c.key == key:
            return c.value
    return ""


class QRSession:
    """一次 QQ音乐扫码登录会话，跨轮询复用同一 cookie jar。"""

    def __init__(self):
        self.jar = aiohttp.CookieJar(unsafe=True)
        self.session = aiohttp.ClientSession(cookie_jar=self.jar)
        self.qrsig = ""
        self.ptqrtoken = 0
        self.created = time.time()

    async def close(self):
        try:
            await self.session.close()
        except Exception:
            pass

    async def fetch_qr(self) -> bytes:
        t = str(time.time())
        url = (
            f"https://ssl.ptlogin2.qq.com/ptqrshow?appid={APPID}&e=2&l=M&s=3&d=72"
            f"&v=4&t={t}&daid={DAID}&pt_3rd_aid={PT_3RD_AID}"
        )
        async with self.session.get(url, headers={"Referer": "https://xui.ptlogin2.qq.com/", "User-Agent": _UA}) as resp:
            png = await resp.read()
        self.qrsig = _cookie(self.jar, "qrsig")
        if not self.qrsig:
            raise RuntimeError("获取二维码失败：未拿到 qrsig")
        self.ptqrtoken = hash33(self.qrsig)
        return png

    async def poll(self) -> dict:
        """轮询一次。返回 {status, message, cookie?}。
        status: waiting|scanned|success|expired|error。
        """
        url = (
            f"https://ssl.ptlogin2.qq.com/ptqrlogin?u1={urllib.parse.quote(U1)}"
            f"&ptqrtoken={self.ptqrtoken}&ptredirect=0&h=1&t=1&g=1&from_ui=1&ptlang=2052"
            f"&action=0-0-{int(time.time() * 1000)}&js_ver=25010716&js_type=1"
            f"&login_sig=&pt_uistyle=40&aid={APPID}&daid={DAID}&pt_3rd_aid={PT_3RD_AID}&"
        )
        try:
            async with self.session.get(url, headers={"Referer": "https://xui.ptlogin2.qq.com/", "User-Agent": _UA}) as resp:
                body = await resp.text()
        except Exception as exc:
            return {"status": "error", "message": f"轮询异常: {exc}"}

        parts = [p.strip().strip("'") for p in body[body.find("(") + 1:body.rfind(")")].split(",")]
        code = parts[0] if parts else ""
        if code == "0":
            check_url = parts[2] if len(parts) > 2 else ""
            try:
                cookie = await self._finish(check_url)
            except Exception as exc:
                return {"status": "error", "message": f"取CK失败: {exc}"}
            if not cookie or "qm_keyst=" not in cookie:
                return {"status": "error", "message": "登录成功但未取到 qm_keyst，请重试"}
            return {"status": "success", "message": "登录成功", "cookie": cookie}
        if code == "65":
            return {"status": "expired", "message": "二维码已失效，请重新登录"}
        if code == "67":
            return {"status": "scanned", "message": "已扫码，请在手机上确认登录"}
        if code == "66":
            return {"status": "waiting", "message": "二维码未失效，等待扫码"}
        return {"status": "waiting", "message": body[:80]}

    async def _finish(self, check_url: str) -> str:
        # 1) 访问 check_sig，服务端写入 p_skey / ptcz / RK 等
        if check_url:
            async with self.session.get(
                check_url, headers={"Referer": "https://xui.ptlogin2.qq.com/", "User-Agent": _UA},
                allow_redirects=True,
            ):
                pass
        p_skey = _cookie(self.jar, "p_skey") or _cookie(self.jar, "skey")
        if not p_skey:
            raise RuntimeError("未取到 p_skey")
        gtk = g_tk(p_skey)

        # 2) 用 g_tk(p_skey) 向 graph.qq.com 换取 OAuth code
        data = {
            "response_type": "code",
            "client_id": str(CLIENT_ID),
            "redirect_uri": REDIRECT_URI,
            "scope": "get_user_info,get_app_friends",
            "state": "state",
            "switch": "",
            "from_ptlogin": "1",
            "src": "1",
            "update_auth": "1",
            "openapi": "1010_1030",
            "g_tk": str(gtk),
            "auth_time": str(int(time.time() * 1000)),
            "ui": str(uuid.uuid4()),
        }
        code = ""
        async with self.session.post(
            "https://graph.qq.com/oauth2.0/authorize", data=data,
            headers={"Referer": "https://graph.qq.com/", "User-Agent": _UA},
            allow_redirects=False,
        ) as resp:
            loc = resp.headers.get("Location", "")
            body = await resp.text()
        m = re.search(r"code=([^&\"']+)", loc) or re.search(r"code=([^&\"']+)", body)
        if not m:
            raise RuntimeError("未换取到 OAuth code")
        code = m.group(1)

        # 3) 用 code 换取 musickey(qm_keyst) / musicid(uin)
        payload = {
            "comm": {"tmeAppID": "qqmusic", "tmeLoginType": 2},
            "req": {
                "module": "music.login.LoginServer",
                "method": "Login",
                "param": {"code": code},
            },
        }
        async with self.session.post(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Referer": "https://y.qq.com/", "User-Agent": _UA,
                     "Content-Type": "application/json"},
        ) as resp:
            login = json.loads(await resp.text())
        info = ((login.get("req") or {}).get("data")) or {}
        musickey = info.get("musickey") or info.get("qqmusic_key") or ""
        musicid = str(info.get("musicid") or info.get("uin") or "")
        if not musickey or not musicid:
            raise RuntimeError(f"Login 返回缺字段: {list(info.keys())}")

        ptcz = _cookie(self.jar, "ptcz")
        rk = _cookie(self.jar, "RK")
        pairs = [
            f"uin={musicid}",
            f"qm_keyst={musickey}",
            f"qqmusic_key={musickey}",
        ]
        if ptcz:
            pairs.append(f"ptcz={ptcz}")
        if rk:
            pairs.append(f"RK={rk}")
        return "; ".join(pairs)
