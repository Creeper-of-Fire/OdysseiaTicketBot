# config_data.py

from typing import Dict, Optional, Iterator

from pydantic import BaseModel, Field, RootModel


class GuildWishConfig(BaseModel):
    """单个服务器的许愿系统配置"""
    wish_channel_id: int = Field(..., description="发布愿望展示卡的频道ID")
    discussion_parent_id: int = Field(..., description="创建讨论线程的频道或分类ID")
    broadcast_channel_id: int = Field(..., description="发布系统公告/实现的频道ID")

    # 角色权限配置
    admin_role_ids: list[int] = Field(default_factory=list, description="管理员/管理组角色ID列表")
    builder_role_ids: list[int] = Field(default_factory=list, description="社区建设者角色ID列表")

    # 业务参数
    support_threshold: int = Field(default=5, ge=1)


class WishSystemConfig(RootModel[Dict[int, GuildWishConfig]]):
    """
    全局配置容器 (根模型)
    现在你可以直接通过 config[guild_id] 访问配置
    """

    root: Dict[int, GuildWishConfig]

    def __getitem__(self, guild_id: int) -> GuildWishConfig:
        return self.root[guild_id]

    def get(self, guild_id: int, default=None) -> Optional[GuildWishConfig]:
        return self.root.get(guild_id, default)

    def __contains__(self, guild_id: int) -> bool:
        return guild_id in self.root

    def __iter__(self) -> Iterator[int]:
        return iter(self.root)


# ===================================================================
# 身份组管理模块 (`role_manager`) 的专属配置
# ===================================================================

# 所有的服务器配置，键是服务器ID (int)
GUILD_CONFIGS = {
    # --- 类脑 ---
    1134557553011998840: GuildWishConfig(  # 替换成你的第一个服务器ID
        wish_channel_id=123456789,  # 发布愿望展示卡的频道ID
        discussion_parent_id=987654321,  # 创建讨论线程的频道或分类ID
        broadcast_channel_id=123456789,  # 发布系统公告/实现的频道ID
        admin_role_ids=[111, 222],  # 管理员/管理组角色ID列表
        builder_role_ids=[333],  # 社区建设者角色ID列表
        support_threshold=5
    ),

    # --- 神人研究所 ---
    1265862009673486408: GuildWishConfig(  # 替换成你的第二个服务器ID
        wish_channel_id=1491130833480716438,  # 发布愿望展示卡的频道ID
        discussion_parent_id=1491130833480716438,  # 创建讨论线程的频道或分类ID
        broadcast_channel_id=1491130833480716438,  # 发布系统公告/实现的频道ID
        admin_role_ids=[1378704432841101423],  # 管理员/管理组角色ID列表
        builder_role_ids=[1384868859139588166],  # 社区建设者角色ID列表
        support_threshold=5
    ),
    # 你可以继续添加更多服务器的配置...
}

config = WishSystemConfig(root=GUILD_CONFIGS)
