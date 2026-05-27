from __future__ import annotations

import logging
import tomllib
from pathlib import Path

import tomlkit
from pydantic import ValidationError

from .models import ComplaintConfig

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")


def config_path(guild_id: int) -> Path:
    return DATA_DIR / f"complaint_{guild_id}.toml"


def load_config(guild_id: int) -> ComplaintConfig:
    """从 TOML 文件加载配置，用 Pydantic 验证。"""
    path = config_path(guild_id)
    if not path.exists():
        logger.warning("投诉配置文件 %s 不存在，将创建默认配置", path)
        config = ComplaintConfig()
        save_config(config, guild_id)
        return config

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    try:
        config = ComplaintConfig.model_validate(raw)
    except ValidationError as e:
        logger.error("投诉配置验证失败（guild %s）：\n%s", guild_id, e)
        raise

    logger.info(
        "投诉配置已加载（guild %s）：%d 个投诉类型，%d 个身份组",
        guild_id,
        len(config.types),
        len(config.role_groups),
    )
    return config


def save_config(config: ComplaintConfig, guild_id: int) -> None:
    """将配置写回 TOML 文件。"""
    path = config_path(guild_id)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
        _merge_into_doc(doc, data)
        with open(path, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
    else:
        with open(path, "w", encoding="utf-8") as f:
            tomlkit.dump(data, f)

    logger.info("投诉配置已保存到 %s", path)


def validate_and_save(raw_bytes: bytes, guild_id: int) -> ComplaintConfig:
    """从上传的原始字节解析、验证并保存配置。"""
    raw = tomllib.loads(raw_bytes.decode("utf-8"))

    try:
        config = ComplaintConfig.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"配置验证失败：\n{e}") from e

    # 直接写入上传的内容（保留原始格式）
    path = config_path(guild_id)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw_bytes)

    logger.info("投诉配置已从上传文件更新（guild %s）", guild_id)
    return config


def read_raw_config(guild_id: int) -> bytes | None:
    """读取原始 TOML 文件字节，用于下载。"""
    path = config_path(guild_id)
    if not path.exists():
        return None
    return path.read_bytes()


def _merge_into_doc(doc: tomlkit.TOMLDocument, data: dict) -> None:
    for key, value in data.items():
        if key == "types":
            doc[key] = tomlkit.item(_convert_lists(value))
            continue
        if key == "role_groups":
            if isinstance(value, dict):
                for rk, rv in value.items():
                    if isinstance(rv, dict):
                        if rk not in doc or not isinstance(doc.get(rk), tomlkit.TOMLDocument):
                            doc[rk] = tomlkit.table()
                        _merge_dict(doc[rk], rv)
            continue
        if isinstance(value, dict) and key in doc and isinstance(doc[key], tomlkit.TOMLDocument):
            _merge_dict(doc[key], value)
        else:
            doc[key] = value


def _merge_dict(table, data: dict) -> None:
    for k, v in data.items():
        if isinstance(v, dict) and k in table and isinstance(table.get(k), tomlkit.TOMLDocument):
            _merge_dict(table[k], v)
        else:
            table[k] = v


def _convert_lists(items: list) -> list:
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append(_convert_dict(item))
        elif isinstance(item, list):
            result.append(_convert_lists(item))
        else:
            result.append(item)
    return result


def _convert_dict(d: dict) -> dict:
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _convert_dict(v)
        elif isinstance(v, list):
            result[k] = _convert_lists(v)
        else:
            result[k] = v
    return result
