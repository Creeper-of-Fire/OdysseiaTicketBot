from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from complaint.services.channel_service import TICKET_PREFIX


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
    requires_confirm: bool = False
    target_role_groups: list[str] = []
    form_fields: list[FormFieldConfig] = []


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
        "{form_section}"
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
    types: list[ComplaintTypeConfig] = []

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
