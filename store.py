"""点歌插件的本地配置：set_ck.php 地址、写入密钥、管理员白名单。

均存放在 json/config.json（已 gitignore），不入库、不打印密钥。
"""
import json
import os

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(PLUGIN_DIR, "json")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")

# 预置管理员（可用指令增删）
DEFAULT_ADMINS = ["538389445D765D2988BFE31506C54799"]
# 内置默认 p_skey.txt 路径（与 web 服务器同机，可用指令覆盖）
DEFAULT_CK_FILE_PATH = r"C:\wwwroot\lala.fan\API\p_skey.txt"


def _read() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(data: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def get_ck_file_path() -> str:
    """本机（与 web 服务器同机）直接写入的 p_skey.txt 路径，默认内置路径。"""
    return _read().get("ck_file_path") or DEFAULT_CK_FILE_PATH


def set_ck_file_path(path: str):
    data = _read()
    data["ck_file_path"] = path.strip()
    _write(data)


def get_set_ck_url() -> str:
    return _read().get("set_ck_url", "")


def set_set_ck_url(url: str):
    data = _read()
    data["set_ck_url"] = url.strip()
    _write(data)


def get_ck_token() -> str:
    return _read().get("ck_token", "")


def set_ck_token(token: str):
    data = _read()
    data["ck_token"] = token.strip()
    _write(data)


def get_group_features(group_id) -> dict:
    """按群的发送开关：{"voice": bool, "file": bool}，未配置默认全关。"""
    groups = _read().get("group_features")
    feats = groups.get(str(group_id)) if isinstance(groups, dict) else None
    if not isinstance(feats, dict):
        feats = {}
    return {"voice": bool(feats.get("voice")), "file": bool(feats.get("file"))}


def set_group_feature(group_id, feature: str, enabled: bool):
    data = _read()
    groups = data.get("group_features")
    if not isinstance(groups, dict):
        groups = {}
    feats = groups.get(str(group_id))
    if not isinstance(feats, dict):
        feats = {}
    feats[feature] = bool(enabled)
    groups[str(group_id)] = feats
    data["group_features"] = groups
    _write(data)


def get_admins() -> list:
    data = _read()
    admins = data.get("admins")
    if not isinstance(admins, list) or not admins:
        admins = list(DEFAULT_ADMINS)
        data["admins"] = admins
        _write(data)
    return admins


def is_admin(user_id) -> bool:
    return str(user_id) in get_admins()


def add_admin(user_id) -> bool:
    admins = get_admins()
    if str(user_id) in admins:
        return False
    admins.append(str(user_id))
    data = _read()
    data["admins"] = admins
    _write(data)
    return True


def remove_admin(user_id) -> bool:
    admins = get_admins()
    if str(user_id) not in admins:
        return False
    admins.remove(str(user_id))
    data = _read()
    data["admins"] = admins
    _write(data)
    return True
