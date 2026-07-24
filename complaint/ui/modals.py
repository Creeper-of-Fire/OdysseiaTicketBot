from __future__ import annotations

from typing import TYPE_CHECKING

import discord

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
