from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from complaint.config.loader import save_config
from complaint.config.models import ComplaintTypeConfig

if TYPE_CHECKING:
    from complaint.ComplaintCog import ComplaintCog


class ComplaintFormModal(discord.ui.Modal):
    """根据投诉类型配置动态生成表单字段。"""

    def __init__(
        self,
        cog: ComplaintCog,
        type_config: ComplaintTypeConfig,
        visibility: str,
    ):
        self.cog = cog
        self.type_config = type_config
        self.visibility = visibility
        title = f"{type_config.emoji} {type_config.label}" if type_config.emoji else type_config.label
        super().__init__(title=title[:45], timeout=300)

        self._field_keys: list[str] = []
        for field in type_config.form_fields[:5]:
            style = (
                discord.TextStyle.paragraph
                if field.style == "paragraph"
                else discord.TextStyle.short
            )
            text_input = discord.ui.TextInput(
                label=field.label[:45],
                placeholder=field.placeholder or "",
                style=style,
                required=field.required,
                max_length=1000 if style == discord.TextStyle.paragraph else 200,
                custom_id=f"complaint_form:{field.key}",
            )
            self._field_keys.append(field.key)
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        form_data: dict[str, str] = {}
        for key in self._field_keys:
            for item in self.children:
                cid = getattr(item, "custom_id", "")
                if cid == f"complaint_form:{key}":
                    form_data[key] = item.value or ""
                    break

        await self.cog.handle_form_submit(
            interaction,
            type_config=self.type_config,
            visibility=self.visibility,
            form_data=form_data,
        )


class AdminEditTemplateModal(discord.ui.Modal):
    """编辑投诉频道模板。"""

    def __init__(self, cog: ComplaintCog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id
        config = cog.get_config(guild_id)
        super().__init__(title="编辑投诉模板", timeout=300)

        self._header_input = discord.ui.TextInput(
            label="频道头部模板",
            placeholder="支持 {complainant_mention}, {type_label}, {type_emoji}, {visibility}, {timestamp}, {form_section}",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1500,
            default=config.templates.channel_header,
        )
        self.add_item(self._header_input)

        self._field_format_input = discord.ui.TextInput(
            label="表单字段格式",
            placeholder="例如：**{label}**：{value}",
            style=discord.TextStyle.short,
            required=True,
            max_length=200,
            default=config.templates.form_field_format,
        )
        self.add_item(self._field_format_input)

        self._confirm_text_input = discord.ui.TextInput(
            label="关闭确认文本",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
            default=config.templates.confirmation_text,
        )
        self.add_item(self._confirm_text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cfg = self.cog.get_config(self.guild_id)
        cfg.templates.channel_header = self._header_input.value
        cfg.templates.form_field_format = self._field_format_input.value
        cfg.templates.confirmation_text = self._confirm_text_input.value

        save_config(cfg, self.guild_id)
        await interaction.response.send_message("✅ 模板已更新并保存。", ephemeral=True)
