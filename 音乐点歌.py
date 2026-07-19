"""音乐点歌: QQ音乐搜索与播放（lala.fan 接口 + CK 过期主动提醒）"""

__plugin_meta__ = {
    'name': '音乐点歌',
    'author': 'lengxi',
    'description': 'QQ音乐搜索与播放，CK 过期主动提醒',
    'version': '2.0.0',
}


import asyncio
import json
import re
import time
import urllib.parse
from collections import OrderedDict

from core.network.http_compat import AsyncHttpClient
from core.plugin.decorators import handler, on_unload

# ==================== 配置（按需修改）====================
_API = 'https://lala.fan/API/qq.php'
# CK 过期时主动提醒的目标（私聊用户 + 群）
_ALERT_USER = '538389445D765D2988BFE31506C54799'
_ALERT_GROUP = '8B642C645CED489615DDD70140440459'
# 提醒去重间隔（秒），避免频繁刷屏
_ALERT_INTERVAL = 1800
# 判定 CK 是否真过期的探针关键词（热门词，CK 正常时必有结果）
_PROBE_KEYWORD = '周杰伦'
# =======================================================

_BTN = [[{'text': '再点一首', 'data': '点歌', 'enter': False, 'style': 1}]]
_STRIP_TBL = str.maketrans('', '', '"\'<>&*_~`[](){}\\/:')
# CK 过期/失效相关错误码（-3 需探针确认；-2/-10 为明确的 Cookie 问题）
_CK_ERR_CODES = {-2, -10}

_client: AsyncHttpClient | None = None
_cache: OrderedDict = OrderedDict()  # uid -> {keyword, count}
_CACHE_CAP = 100
_alert_ts: float = 0.0


async def _http():
    global _client
    if _client is None or _client.is_closed:
        _client = AsyncHttpClient(timeout=15.0)
    return _client


@on_unload
async def _cleanup():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _fetch(params: str) -> str:
    """请求接口，返回原始文本（搜索列表是纯文本，播放/错误是 JSON）。"""
    c = await _http()
    resp = await c.get(f'{_API}?{params}')
    return (resp.content or b'').decode('utf-8', 'ignore')


def _try_json(text: str):
    """能解析成 JSON 返回 dict，否则 None（纯文本搜索结果）。"""
    s = text.lstrip()
    if not s.startswith('{'):
        return None
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def _parse_search_list(text: str) -> list[str]:
    """解析纯文本搜索结果：'1、歌名 - 歌手 [免费]' 每行一首。"""
    songs = []
    for line in text.splitlines():
        m = re.match(r'^\s*\d+\s*[、..)]\s*(.+)$', line)
        if m:
            songs.append(m.group(1).strip())
    return songs


async def _ck_expired() -> bool:
    """用热门词探针确认 CK 是否真过期：探针也无结果才判为过期。"""
    try:
        text = await _fetch(f'msg={urllib.parse.quote(_PROBE_KEYWORD)}')
    except Exception:
        return False
    j = _try_json(text)
    if j is None:
        return False  # 探针拿到纯文本列表 → CK 正常
    return j.get('code') in (-2, -3, -10)


async def _alert_ck_expired(event):
    """CK 过期时主动给配置的私聊用户和群发提醒（带去重间隔）。"""
    global _alert_ts
    now = time.time()
    if now - _alert_ts < _ALERT_INTERVAL:
        return
    _alert_ts = now
    msg = '⚠ 点歌服务的 QQ音乐 Cookie 已过期，暂时点不了歌了，请尽快发「更新点歌CK」扫码更新～'
    try:
        await event.send_to_user(_ALERT_USER, msg)
    except Exception:
        pass
    try:
        # 群内 @ 管理员提醒
        await event.send_to_group(_ALERT_GROUP, f'<@{_ALERT_USER}> {msg}')
    except Exception:
        pass


def _cache_put(uid, val):
    if uid in _cache:
        _cache.move_to_end(uid)
    _cache[uid] = val
    if len(_cache) > _CACHE_CAP:
        _cache.popitem(last=False)


async def _handle_error_code(event, uid, code) -> None:
    """统一处理错误码：CK 过期则主动提醒，否则给出对应提示。"""
    if code in _CK_ERR_CODES or code == -3:
        if await _ck_expired():
            await _alert_ck_expired(event)
            await event.reply(f'<@{uid}> 点歌服务 Cookie 已过期，已通知管理员更新，稍后再试～',
                              buttons=_BTN)
        else:
            await event.reply(f'<@{uid}> 未找到相关歌曲，请尝试其他关键词', buttons=_BTN)
    elif code == -5:
        await event.reply(f'<@{uid}> 未获取到歌曲链接（可能是会员/版权限制），换一首试试吧！',
                          buttons=_BTN)
    elif code == -1:
        await event.reply(f'<@{uid}> 点歌 请输入要搜索的歌曲名')
    else:
        await event.reply(f'<@{uid}> 点歌失败，请稍后重试', buttons=_BTN)


@handler(r'^/?\s*点歌\s*(.*)$', name='点歌', desc='搜索QQ音乐')
async def search_music(event, match):
    uid = str(event.user_id)
    keyword = match.group(1).strip()
    if not keyword:
        return await event.reply(f'<@{uid}> 点歌 请输入要搜索的歌曲名')

    try:
        text = await _fetch(f'msg={urllib.parse.quote(keyword)}')
    except Exception:
        return await event.reply(f'<@{uid}> 网络请求超时，请稍后重试', buttons=_BTN)

    err = _try_json(text)
    if err is not None:
        return await _handle_error_code(event, uid, err.get('code'))

    songs = _parse_search_list(text)
    if not songs:
        return await event.reply(f'<@{uid}> 未找到相关歌曲，请尝试其他关键词', buttons=_BTN)

    count = min(len(songs), 10)
    _cache_put(uid, {'keyword': keyword, 'count': count})

    lines = []
    for i, song in enumerate(songs[:count]):
        name = song.translate(_STRIP_TBL).strip()[:50]
        lines.append(f'{i+1}. <qqbot-cmd-input text="听{i+1}" show="{name}" />')

    await event.reply(f'<@{uid}>点歌结果\n以下是搜索到的歌曲\n\n' + '\n'.join(lines) + '\n',
                      buttons=_BTN)


@handler(r'^/?\s*听\s*([0-9]+)$', name='听歌', desc='播放搜索结果中的歌曲')
async def play_music(event, match):
    uid = str(event.user_id)
    info = _cache.get(uid)
    if not info:
        return
    if uid in _cache:
        _cache.move_to_end(uid)

    idx = int(match.group(1))
    if idx < 1 or idx > info['count']:
        return await event.reply(f'<@{uid}> 序号无效，请输入 1~{info["count"]} 之间的数字')

    try:
        text = await _fetch(f'msg={urllib.parse.quote(info["keyword"])}&n={idx}')
    except Exception:
        return await event.reply(f'<@{uid}> 网络请求超时，请稍后重试', buttons=_BTN)

    data = _try_json(text)
    if data is None or data.get('code') != 0:
        code = data.get('code') if data else None
        return await _handle_error_code(event, uid, code)

    d = data.get('data') or {}
    info = d.get('base_info') or {}
    music_url = _pick_play_url(d.get('quality_list') or [])
    if not music_url:
        return await event.reply(f'<@{uid}> 未获取到歌曲链接，请换一首歌尝试吧！', buttons=_BTN)

    song_name = str(info.get('song_name') or '未知歌曲').strip()
    singer = str(info.get('singer') or '未知歌手').strip()
    album = str(info.get('album_name') or '').strip()
    cover = str(info.get('album_cover') or '').strip()
    songmid = str(info.get('songmid') or '').strip()
    link = f'https://y.qq.com/n/ryqq_v2/songDetail/{songmid}' if songmid else 'https://y.qq.com/'

    # ark24 卡片：[#DESC#, #PROMPT#, #TITLE#, #METADESC#, #IMG#, #LINK#, #SUBTITLE#]
    meta = f'{singer} · {album}' if album else singer
    ark = ['🎵 点歌', f'[音乐] {song_name}', song_name, meta, cover, link, singer]
    try:
        await event.reply_ark(24, ark)
    except Exception:
        # ark 卡片失败不影响发语音，退化为文本
        await event.reply(f'<@{uid}> 🎵 {song_name} - {singer}')

    await _send_voice(event, music_url)


def _pick_play_url(quality_list) -> str:
    """优先选 mp3 直链当语音，其次任意可用直链。"""
    mp3 = ''
    first = ''
    for q in quality_list:
        url = (q.get('play_url') or '').strip()
        if not url:
            continue
        if not first:
            first = url
        if '.mp3' in url.lower() and not mp3:
            mp3 = url
    return mp3 or first


async def _send_voice(event, url: str) -> None:
    """发语音，遇到 QQ「系统繁忙」(50015014) 等瞬时失败重试几次。

    reply_voice 失败时返回 None（不抛异常），据此重试；仍失败给出提示。
    """
    for attempt in range(3):
        try:
            res = await event.reply_voice(url)
        except Exception:
            res = None
        if res:
            return
        await asyncio.sleep(1.0 + attempt)
    uid = str(event.user_id)
    await event.reply(f'<@{uid}> 语音发送失败（QQ 接口繁忙），请稍后重发「听序号」重试～', buttons=_BTN)
