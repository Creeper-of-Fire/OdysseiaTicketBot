from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from complaint.config.loader import config_path, validate_and_save
from complaint.config.models import ComplaintTypeConfig

if TYPE_CHECKING:
    from complaint.ComplaintCog import ComplaintCog


class ComplaintFormModal(discord.ui.Modal):
    """根据投诉类型配置动态生成表单字段。"""

    def __init__(
        self,
        cog: ComplaintCog,
        type_config: ComplaintTypeConfig,
    ):
        self.cog = cog
        self.type_config = type_config
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
        """收集表单输入并转交 Cog 处理。"""
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
            form_data=form_data,
        )


class AdminEditTemplateModal(discord.ui.Modal):
    """编辑完整投诉系统 TOML 配置。"""

    def __init__(self, cog: ComplaintCog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id
        super().__init__(title="编辑投诉配置", timeout=600)

        path = config_path(guild_id)
        raw = path.read_text("utf-8") if path.exists() else ""

        self._toml_input = discord.ui.TextInput(
            label="TOML 配置",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
            default=raw,
        )
        self.add_item(self._toml_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """验证并保存编辑后的 TOML 配置。"""
        try:
            cfg = validate_and_save(
                self._toml_input.value.encode("utf-8"), self.guild_id
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ 配置验证失败：\n{e}", ephemeral=True
            )
            return

        self.cog._invalidate_config(self.guild_id)
        await interaction.response.send_message(
            f"✅ 配置已更新并生效。{len(cfg.types)} 个投诉类型，"
            f"{len(cfg.role_groups)} 个身份组。",
            ephemeral=True,
        )
