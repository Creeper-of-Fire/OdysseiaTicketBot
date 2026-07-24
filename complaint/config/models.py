from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from complaint.services.channel_service import TICKET_PREFIX
from shared.config.toml_merge import TomlMergeAsTableList


class FormFieldConfig(BaseModel):
    """表单字段配置。"""

    key: str
    label: str
    placeholder: str = ""
    style: Literal["short", "paragraph"] = "short"
    required: bool = True


class ComplaintTypeConfig(BaseModel):
    """投诉类型配置，定义一种投诉类型的表单、权限组等。"""

    id: str
    label: str
    emoji: str = ""
    description: str = ""
    # 选中后展示的详细说明，支持多行。为空时不追加额外内容。
    detail_description: str = ""

    @field_validator("detail_description", mode="before")
    @classmethod
    def _trim_detail(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v
    requires_confirm: bool = False
    target_role_groups: list[str] = []
    form_fields: list[FormFieldConfig] = []
    # 自定义通知块，每条一行，渲染到频道 header 末尾。
    # 支持宏：{@group_id} → 对应身份组的角色 mention，
    # {type_label}、{type_emoji}、{ticket_number} → 投诉类型信息。
    header_blocks: list[str] = []
    # 创建工单后向此频道/帖子发送通知 embed。0 = 不发送。
    notify_channel_id: int = 0
    # 通知文案模板，渲染后作为消息 content 发送（触发 @mention 推送）。
    # 支持宏：{complainant}、{channel}、{type_label}、{type_emoji}、
    # {ticket_number}、{@group_id}。也可直接写 <@&ID> / <@ID>。
    notify_message: str = ""
    # 创建工单时使用的分类频道 ID。0 = 使用 guild.category_id。
    category_id: int = 0
    # 该类型专属的归档文件发送频道 ID。0 = 使用 guild.archive_channel_id。
    archive_channel_id: int = 0


class RoleGroupConfig(BaseModel):
    """身份组配置，将多个 Discord 角色打包为一组以便引用。"""

    label: str
    role_ids: list[int] = []


class GuildConfig(BaseModel):
    """服务器级频道配置。"""

    category_id: int = 0
    archive_channel_id: int = 0


class GlobalConfig(BaseModel):
    """全局运行参数。"""

    archive_concurrent_limit: int = 2
    media_budget_mb: int = 32
    single_image_max_mb: int = 0


class TemplateConfig(BaseModel):
    """消息模板配置，控制频道头部、表单格式等文案。"""
    channel_header: str = (
        "📌 {complainant_mention} 提交了一份投诉\n"
        f"🎫 工单编号：{TICKET_PREFIX}-{{ticket_number}}\n"
        "📋 投诉类型：{type_emoji} {type_label}\n"
        "📅 时间：{timestamp}\n"
        "{form_section}\n"
        "{custom_section}"
    )
    form_field_format: str = "**{label}**：{value}"
    fallback_emoji: str = "📋"
    unknown_type_label: str = "未知"


class ComplaintConfig(BaseModel):
    """投诉系统完整配置，对应一个 TOML 文件。"""

    global_: GlobalConfig = Field(alias="global", default=GlobalConfig())
    guild: GuildConfig = GuildConfig()
    templates: TemplateConfig = TemplateConfig()
    role_groups: dict[str, RoleGroupConfig] = {}
    types: Annotated[list[ComplaintTypeConfig], TomlMergeAsTableList()] = []

    model_config = {"populate_by_name": True}

    def get_role_group(self, group_id: str) -> RoleGroupConfig | None:
        """按 ID 查找身份组配置，不存在则返回 None。"""
        return self.role_groups.get(group_id)

    def get_complaint_type(self, type_id: str) -> ComplaintTypeConfig | None:
        """按 ID 查找投诉类型配置，不存在则返回 None。"""
        for t in self.types:
            if t.id == type_id:
                return t
        return None

    def get_all_role_ids_for_groups(self, group_ids: list[str]) -> list[int]:
        """收集多个身份组包含的所有角色 ID（去重，保留首次出现顺序）。"""
        result: list[int] = []
        for gid in group_ids:
            group = self.role_groups.get(gid)
            if group:
                result.extend(group.role_ids)
        return list(dict.fromkeys(result))

    def get_type_target_role_ids(self, type_config: ComplaintTypeConfig | None) -> list[int]:
        """收集指定投诉类型对应处理组的角色 ID。"""
        if type_config is None:
            return []
        return self.get_all_role_ids_for_groups(type_config.target_role_groups)

    def get_effective_category_id(self, type_id: str) -> int:
        """获取指定类型的有效 category_id，类型级优先，回退到 guild 级。"""
        t = self.get_complaint_type(type_id)
        if t and t.category_id:
            return t.category_id
        return self.guild.category_id

    def get_effective_archive_channel_id(self, type_id: str) -> int:
        """获取指定类型的有效 archive_channel_id，类型级优先，回退到 guild 级。"""
        t = self.get_complaint_type(type_id)
        if t and t.archive_channel_id:
            return t.archive_channel_id
        return self.guild.archive_channel_id

    def get_all_category_ids(self) -> set[int]:
        """收集所有有效的投诉分类 ID（guild 级 + 各类型自定义级）。"""
        ids: set[int] = set()
        if self.guild.category_id:
            ids.add(self.guild.category_id)
        for t in self.types:
            if t.category_id:
                ids.add(t.category_id)
        return ids
