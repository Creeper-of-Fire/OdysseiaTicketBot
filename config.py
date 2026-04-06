import os
import typing

from dotenv import load_dotenv

from config_data import GUILD_CONFIGS

load_dotenv()
# ===================================================================
# 核心配置
# ===================================================================

# 你的机器人 Token
# 现在优先从环境变量 'DISCORD_BOT_TOKEN' 获取，如果环境变量不存在，则使用空字符串）
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# 代理设置 (如果不需要，设为 None)
# 优先从环境变量 'DISCORD_BOT_PROXY' 获取，如果环境变量不存在，则使用 None
PROXY = os.getenv("DISCORD_BOT_PROXY", None)

FORCE_REFRESH_COMMAND = False
# ===================================================================
# 模块 (Cogs) 配置
# ===================================================================

# 在这里控制加载哪些模块
COGS = {
    "core": {
        "enabled": True,
    },
}

# ===================================================================
# 其他配置
# ===================================================================

# 从GUILD_CONFIGS中提取所有服务器ID，用于命令同步
GUILD_IDS = set(list(GUILD_CONFIGS.keys()))

# 机器人状态
STATUS_TEXT = "和你一起收集财宝、建设社区"  # 显示在机器人状态上的文字
# 状态类型: 'playing', 'watching', 'listening'
STATUS_TYPE = 'playing'

# CoreCog的CommandGroup
COMMAND_GROUP_NAME = "许嘉慧"

# ===================================================================
# 新增：权限控制
# ===================================================================
# 定义一组被认为是“危险”或“敏感”的权限。
# 机器人将阻止用户通过自助服务获取包含这些权限的身份组。
# 'administrator' 权限总是被视为危险，无论是否在此列表中。
# 这些是 discord.Permissions 对象的属性名 (字符串形式)。
DANGEROUS_PERMISSIONS = {
    "manage_channels",  # 管理频道
    "manage_guild",  # 管理服务器
    "manage_roles",  # 管理身份组 (创建/编辑/删除低于此身份组的身份组)
    "manage_webhooks",  # 管理 Webhook
    "manage_emojis_and_stickers",  # 管理表情符号和贴纸
    "manage_events",  # 管理活动
    "kick_members",  # 踢出成员
    "ban_members",  # 封禁成员
    "moderate_members",  # 对成员进行定罪 (例如禁言)
    "mention_everyone",  # @everyone, @here 和所有身份组
    "mute_members",  # 使成员在语音频道中静音
    "deafen_members",  # 使成员在语音频道中闭麦
    "move_members",  # 移动语音频道中的成员
    # "manage_messages",      # 管理消息 (删除他人消息、置顶)
    # "manage_nicknames",     # 管理他人昵称
    # "view_audit_log",     # 查看审计日志 (通常被认为是安全的，除非特定场景)
    # "change_nickname",    # 更改自己昵称 (通常安全)
}

# --- 备份配置 ---
# 备份文件和状态更新将发送到这个频道
BACKUP_CHANNEL_ID = 1313410500876566578  # 替换为你的备份通知频道ID
# 备份功能将在这个服务器上运行
BACKUP_GUILD_ID = 1134557553011998840  # 替换为你的服务器ID

# --- 权限配置 ---
# 在这里硬编码拥有权限的用户和角色ID

# 超级管理员：拥有所有权限，通常是机器人所有者或最高决策者。
# 可以执行如“删除数据”等最高风险操作。
SUPER_ADMIN_USER_IDS: typing.Set[int] = {
}

# 管理员：拥有大部分管理权限，但可能无法执行最危险的操作。
# 例如，可以发送面板、刷新缓存、获取数据备份，但不能删除数据。
# 注意：这里包含角色ID和特定的用户ID。
ADMIN_ROLE_IDS: typing.Set[int] = {
    1337450755791261766,  # 管理组
}

ADMIN_USER_IDS: typing.Set[int] = {
    942388408800669707,  # 我
    # 如果某个管理员没有特定角色，也可以在这里单独添加他们的用户 ID
}