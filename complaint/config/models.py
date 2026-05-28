from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from complaint.services.channel_service import TICKET_PREFIX


class FormFieldConfig(BaseModel):
    key: str
    label: str
    placeholder: str = ""
    style: Literal["short", "paragraph"] = "short"
    required: bool = True


class ComplaintTypeConfig(BaseModel):
    id: str
    label: str
    emoji: str = ""
    description: str = ""
    requires_confirm: bool = False
    target_role_groups: list[str] = []
    form_fields: list[FormFieldConfig] = []


class RoleGroupConfig(BaseModel):
    label: str
    role_ids: list[int] = []


class GuildConfig(BaseModel):
    category_id: int = 0
    archive_channel_id: int = 0


class GlobalConfig(BaseModel):
    archive_concurrent_limit: int = 2
    media_budget_mb: int = 32
    single_image_max_mb: int = 0


class TemplateConfig(BaseModel):
    channel_header: str = (
        "📌 {complainant_mention} 提交了一份投诉\n"
        f"🎫 工单编号：{TICKET_PREFIX}-{{ticket_number}}\n"
        "📋 投诉类型：{type_emoji} {type_label}\n"
        "📅 时间：{timestamp}\n"
        "{form_section}"
    )
    form_field_format: str = "**{label}**：{value}"
    confirmation_text: str = (
        "⚠️ 此操作将归档并永久删除本投诉频道，所有消息将导出为归档文件。确定继续吗？"
    )
    fallback_emoji: str = "📋"
    unknown_type_label: str = "未知"


class ComplaintConfig(BaseModel):
    global_: GlobalConfig = Field(alias="global", default=GlobalConfig())
    guild: GuildConfig = GuildConfig()
    templates: TemplateConfig = TemplateConfig()
    role_groups: dict[str, RoleGroupConfig] = {}
    types: list[ComplaintTypeConfig] = []

    model_config = {"populate_by_name": True}

    def get_role_group(self, group_id: str) -> RoleGroupConfig | None:
        return self.role_groups.get(group_id)

    def get_complaint_type(self, type_id: str) -> ComplaintTypeConfig | None:
        for t in self.types:
            if t.id == type_id:
                return t
        return None

    def get_all_role_ids_for_groups(self, group_ids: list[str]) -> list[int]:
        result: list[int] = []
        for gid in group_ids:
            group = self.role_groups.get(gid)
            if group:
                result.extend(group.role_ids)
        return list(dict.fromkeys(result))
