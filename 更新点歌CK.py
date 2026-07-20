"""更新点歌CK：管理员扫码登录 QQ音乐，自动把新 Cookie 推送到服务器 set_ck.php。

流程：发「更新点歌CK」→ 机器人出 QQ音乐二维码 → 管理员手机 QQ 扫码确认 →
机器人自动取到 QQ音乐 Cookie → 覆盖 p_skey.txt。

写入方式二选一：
① 同机器（推荐）：设置点歌CK文件路径 C:\\wwwroot\\lala.fan\\API\\p_skey.txt → 直接写本地文件；
② 跨机器：设置点歌CK地址 <set_ck.php的URL> + 设置点歌CK密钥 <与php一致的token> → HTTP 推送。
"""
import asyncio
import os
import re

from core.network.http_compat import AsyncHttpClient
from core.plugin.decorators import handler

from .qq_music_login import QRSession
from .store import (
    add_admin, get_admins, get_ck_file_path, get_ck_token, get_set_ck_url,
    is_admin, remove_admin, set_ck_file_path, set_ck_token, set_set_ck_url,
)

_POLL_INTERVAL = 2.0
_POLL_TIMEOUT = 120
_MAX_REFRESH = 3
# 扫码更新成功后在此群发"登录成功"提示
_NOTIFY_GROUP = '8B642C645CED489615DDD70140440459'


async def _require_admin(event) -> bool:
    if is_admin(event.user_id):
        return True
    return False  # 非管理员静默忽略


def _write_local(path: str, cookie: str) -> str:
    """机器人与 web 服务器同机时，直接覆盖本地 p_skey.txt。"""
    try:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = f.read()
                with open(path + ".bak", "w", encoding="utf-8") as f:
                    f.write(old)
            except Exception:
                pass
        with open(path, "w", encoding="utf-8") as f:
            f.write(cookie.strip())
    except Exception as exc:
        return f"❌ 写入本地文件失败：{exc}"
    return "✅ 新 CK 已写入本地 p_skey.txt，点歌恢复正常～"


async def _push_ck(cookie: str) -> str:
    """更新 CK：优先直接写本地文件（同机），否则 HTTP 推到 set_ck.php。"""
    path = get_ck_file_path()
    if path:
        return _write_local(path, cookie)

    url = get_set_ck_url()
    token = get_ck_token()
    if not url or not token:
        return ("⚠ 已拿到新 CK，但还没配置写入方式。二选一：\n"
                "① 同机器：设置点歌CK文件路径 C:\\wwwroot\\lala.fan\\API\\p_skey.txt\n"
                "② 跨机器：设置点歌CK地址 https://lala.fan/API/set_ck.php + 设置点歌CK密钥 <token>")
    client = AsyncHttpClient(timeout=15.0)
    try:
        resp = await client.post(url, data={"token": token, "ck": cookie})
        body = resp.json()
    except Exception as exc:
        return f"❌ 推送到服务器失败：{exc}"
    finally:
        await client.aclose()
    if isinstance(body, dict) and body.get("code") == 0:
        return "✅ 新 CK 已自动写入服务器 p_skey.txt，点歌恢复正常～"
    msg = body.get("msg") if isinstance(body, dict) else str(body)
    return f"❌ 服务器返回失败：{msg}"


@handler(r'^(更新点歌CK|点歌登录|点歌CK登录)$', name='更新点歌CK',
         desc='扫码登录QQ音乐并自动更新服务器CK', priority=100, block=True, ignore_at_check=True)
async def cmd_update_ck(event, match):
    if not await _require_admin(event):
        return
    qr = QRSession()
    try:
        try:
            png = await qr.fetch_qr()
        except Exception as exc:
            await event.reply(f"❌ 生成二维码失败：{exc}")
            return
        await event.reply_image(png, content="请用 QQ音乐 账号的手机 QQ「扫一扫」扫码并确认登录～")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _POLL_TIMEOUT
        scanned = False
        refreshed = 0
        while loop.time() < deadline:
            await asyncio.sleep(_POLL_INTERVAL)
            r = await qr.poll()
            st = r.get("status")
            if st == "success":
                result = await _push_ck(r["cookie"])
                await event.reply(result)
                if "✅" in result:
                    await _notify_login_ok(event)
                return
            if st == "expired":
                if refreshed < _MAX_REFRESH:
                    refreshed += 1
                    try:
                        png = await qr.fetch_qr()
                        await event.reply_image(png, content="上一张二维码过期了，这是新的，请尽快扫码～")
                        scanned = False
                        continue
                    except Exception:
                        pass
                await event.reply("⏰ 二维码已过期，请重新发「更新点歌CK」～")
                return
            if st == "error":
                await event.reply(f"❌ 登录已确认但取 CK 失败：{r.get('message')}\n请重新发「更新点歌CK」再扫一次～")
                return
            if st == "scanned" and not scanned:
                scanned = True
                await event.reply("📲 已扫码，请在手机上确认登录～")
        await event.reply("⏰ 超时未完成扫码，请重新发「更新点歌CK」～")
    finally:
        await qr.close()


async def _notify_login_ok(event):
    """扫码更新成功后，在群里发一条登录成功提示。"""
    try:
        await event.send_to_group(_NOTIFY_GROUP, "✅ 点歌CK已更新（扫码登录成功），点歌恢复正常～")
    except Exception:
        pass


@handler(r'^(点歌CK|更新CK|设置点歌CK)\s+([\s\S]+)$', name='粘贴点歌CK',
         desc='粘贴浏览器 document.cookie 直接更新 p_skey.txt', priority=100, block=True, ignore_at_check=True)
async def cmd_paste_ck(event, match):
    if not await _require_admin(event):
        return
    cookie = (match.group(2) or "").strip()
    if "qm_keyst=" not in cookie:
        await event.reply("❌ 这串 Cookie 里没有 qm_keyst，请在已登录的 y.qq.com 页面控制台执行 copy(document.cookie) 再粘贴整串～")
        return
    result = await _push_ck(cookie)
    await event.reply(result)
    if "✅" in result:
        await _notify_login_ok(event)


@handler(r'^(点歌菜单|点歌帮助)$', name='点歌菜单',
         desc='查看点歌管理操作(仅管理员)', priority=100, block=True, ignore_at_check=True)
async def cmd_menu(event, match):
    if not await _require_admin(event):
        return
    path = get_ck_file_path()
    url = get_set_ck_url()
    token_set = "已配置" if get_ck_token() else "未配置"
    admins = get_admins()
    lines = [
        "🎵 点歌管理菜单（仅管理员可见）",
        "",
        "【所有人可用】",
        "· 点歌 歌名 —— 搜索歌曲",
        "· 听N —— 播放第 N 首（如 听1）",
        "",
        "【管理员】CK 更新",
        "· 更新点歌CK —— 扫码登录QQ音乐，自动更新 p_skey.txt",
        "  别名：点歌登录 / 点歌CK登录",
        "· 点歌CK <整串Cookie> —— 浏览器登录y.qq.com后 copy(document.cookie) 粘贴，直接写入(最稳)",
        "",
        "【管理员】配置",
        "· 设置点歌CK文件路径 <路径> —— 同机直写(已内置默认)",
        "· 设置点歌CK地址 <URL> —— 跨机 set_ck.php 地址",
        "· 设置点歌CK密钥 <token> —— 跨机写入密钥",
        "",
        "【管理员】按群发送开关（默认只发卡片，需在群内发送）",
        "· 开语音发送 / 关语音发送 —— 本群播放时是否额外发语音",
        "· 开上传文件 / 关上传文件 —— 本群播放时是否额外上传 MP3（文件名为歌名）",
        "· 点歌开关状态 —— 查看本群两个开关",
        "",
        "【管理员】白名单",
        "· 添加点歌管理员 @用户 / 点歌管理员添加",
        "· 删除点歌管理员 @用户 / 点歌管理员删除",
        "· 点歌管理员列表",
        "",
        "—— 当前配置 ——",
        f"· CK 文件路径：{path}",
        f"· set_ck.php 地址：{url or '未配置'}",
        f"· 写入密钥：{token_set}",
        f"· 管理员人数：{len(admins)}",
    ]
    await event.reply("\n".join(lines))


@handler(r'^设置点歌CK文件路径\s*(\S+)$', name='设置点歌CK文件路径',
         desc='配置本机 p_skey.txt 路径(同机直写)', priority=100, block=True, ignore_at_check=True)
async def cmd_set_path(event, match):
    if not await _require_admin(event):
        return
    set_ck_file_path(match.group(1).strip())
    await event.reply("✅ 已保存本地 p_skey.txt 路径，扫码成功后会直接写这个文件～")


@handler(r'^设置点歌CK地址\s*(\S+)$', name='设置点歌CK地址',
         desc='配置 set_ck.php 地址', priority=100, block=True, ignore_at_check=True)
async def cmd_set_url(event, match):
    if not await _require_admin(event):
        return
    url = match.group(1).strip()
    if not url.startswith(("http://", "https://")):
        await event.reply("❌ 地址需以 http:// 或 https:// 开头～")
        return
    set_set_ck_url(url)
    await event.reply("✅ 已保存 set_ck.php 地址～")


@handler(r'^设置点歌CK密钥\s*(\S+)$', name='设置点歌CK密钥',
         desc='配置写入密钥(与php一致)', priority=100, block=True, ignore_at_check=True)
async def cmd_set_token(event, match):
    if not await _require_admin(event):
        return
    set_ck_token(match.group(1).strip())
    await event.reply("✅ 已保存写入密钥（请确保与 set_ck.php 里的一致）～")


@handler(r'^(添加点歌管理员|点歌管理员添加)\s*(.*)$', name='添加点歌管理员',
         desc='把用户加入点歌管理员白名单', priority=100, block=True, ignore_at_check=True)
async def cmd_add_admin(event, match):
    if not await _require_admin(event):
        return
    targets = _extract_ids(event, (match.group(2) or "").strip())
    if not targets:
        await event.reply("用法：添加点歌管理员 @用户（或 添加点歌管理员 <用户ID>）～")
        return
    added = [t for t in targets if add_admin(t)]
    await event.reply(f"✅ 已添加点歌管理员：{len(added)} 人" if added else "ℹ️ 都已在名单中～")


@handler(r'^(删除点歌管理员|点歌管理员删除)\s*(.*)$', name='删除点歌管理员',
         desc='把用户移出点歌管理员白名单', priority=100, block=True, ignore_at_check=True)
async def cmd_del_admin(event, match):
    if not await _require_admin(event):
        return
    targets = _extract_ids(event, (match.group(2) or "").strip())
    removed = [t for t in targets if remove_admin(t)]
    await event.reply(f"✅ 已移除：{len(removed)} 人" if removed else "ℹ️ 名单里没有这些用户～")


@handler(r'^点歌管理员列表$', name='点歌管理员列表',
         desc='查看点歌管理员白名单', priority=100, block=True, ignore_at_check=True)
async def cmd_list_admin(event, match):
    if not await _require_admin(event):
        return
    admins = get_admins()
    await event.reply("点歌管理员：\n" + "\n".join(f"`{a}`" for a in admins), msg_type=2)


_AT_RE = re.compile(r'<@!?([A-Za-z0-9]+)>')


def _extract_ids(event, arg: str) -> list:
    ids = []
    for m in (getattr(event, "mentions", None) or []):
        if not isinstance(m, dict):
            continue
        if m.get("is_you") or m.get("bot") or m.get("scope") == "all":
            continue
        mid = m.get("id")
        if mid:
            ids.append(str(mid))
    if arg:
        ids.extend(_AT_RE.findall(arg))
        for tok in _AT_RE.sub(" ", arg).split():
            ids.append(tok)
    seen, out = set(), []
    for i in ids:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out
