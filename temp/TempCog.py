from __future__ import annotations

import typing
from typing import Set, TYPE_CHECKING, List
from typing import Dict, Tuple

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from main import TicketBot


class TempCog(commands.Cog, name="Temp"):
    """临时功能Cog - 用于分析社区助力者身份组的表情反应"""

    # 硬编码配置
    ROLE_ID = 1383835973384802396  # 社区助力者身份组ID

    def __init__(self, bot: 'TicketBot'):
        self.bot = bot
        self.logger = bot.logger

    temp_group = app_commands.Group(
        name="temp",
        description="临时功能指令",
        guild_ids=[1134557553011998840],  # 请替换为你的实际服务器ID
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @temp_group.command(name="分析助力者表情", description="分析指定消息中社区助力者身份组的表情反应")
    @app_commands.describe(message_url="要分析的Discord消息链接")
    async def analyze_helper_reactions(self, interaction: discord.Interaction, message_url: str):
        """
        分析指定消息中「社区助力者」身份组成员的表情反应。
        返回按表情使用频率从高到低排序的统计列表。
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        # 1. 解析消息链接
        try:
            message = await self._fetch_message_from_url(message_url)
        except ValueError as e:
            await interaction.followup.send(f"❌ 无效的消息链接: {e}", ephemeral=True)
            return
        except Exception as e:
            self.logger.error(f"获取消息失败: {e}")
            await interaction.followup.send(f"❌ 无法获取消息，请检查链接是否正确。", ephemeral=True)
            return

        if not message.guild:
            await interaction.followup.send("❌ 该消息不在服务器中。", ephemeral=True)
            return

        # 2. 获取社区助力者身份组
        role = message.guild.get_role(self.ROLE_ID)
        if not role:
            await interaction.followup.send(
                f"❌ 找不到ID为 `{self.ROLE_ID}` 的身份组，请检查配置。",
                ephemeral=True
            )
            return

        # 3. 获取身份组成员
        role_members = [m for m in role.members if not m.bot]
        if not role_members:
            await interaction.followup.send(
                f"ℹ️ 身份组 `{role.name}` 中没有非机器人成员。",
                ephemeral=True
            )
            return

        role_member_ids = {m.id for m in role_members}

        # 4. 分析消息表情反应
        emoji_counter: Dict[str, Tuple[discord.Emoji, int]] = {}

        for reaction in message.reactions:
            emoji = reaction.emoji

            # 获取对这个表情做出反应的用户
            users = []
            async for user in reaction.users():
                if user.id in role_member_ids:
                    users.append(user)

            if users:
                key = str(emoji)
                emoji_counter[key] = (emoji, len(users))

        if not emoji_counter:
            await interaction.followup.send(
                f"ℹ️ 在消息 `{message.jump_url}` 上，身份组 `{role.name}` 的成员没有任何表情反应。",
                ephemeral=True
            )
            return

        # 5. 按数量从高到低排序
        sorted_emojis = sorted(
            emoji_counter.values(),
            key=lambda x: x[1],
            reverse=True
        )

        # 6. 构建回复
        embed = discord.Embed(
            title=f"📊 社区助力者表情反应统计",
            description=f"分析消息: [跳转]({message.jump_url})\n"
                        f"身份组: {role.mention} ({len(role_members)} 人)",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )

        lines = []
        for idx, (emoji, count) in enumerate(sorted_emojis, 1):
            # 处理自定义表情和Unicode表情的显示
            if isinstance(emoji, (discord.Emoji, discord.PartialEmoji)):
                emoji_display = str(emoji)
            else:
                emoji_display = emoji

            lines.append(f"{idx}. {emoji_display} — **{count}** 人")

        embed.add_field(
            name=f"📈 统计结果 (共 {len(sorted_emojis)} 种表情)",
            value="\n".join(lines) if lines else "无数据",
            inline=False
        )

        embed.set_footer(text=f"请求者: {interaction.user.name}")

        await interaction.followup.send(embed=embed, ephemeral=True)

        self.logger.info(
            f"表情分析完成 - 用户: {interaction.user} ({interaction.user.id}), "
            f"消息: {message.id}, 身份组: {role.name}"
        )

    @temp_group.command(name="合并分析助力者表情", description="分析两条消息中社区助力者身份组的表情反应（合并统计）")
    @app_commands.describe(
        message_url_1="第一条Discord消息链接",
        message_url_2="第二条Discord消息链接"
    )
    async def analyze_combined_reactions(
            self,
            interaction: discord.Interaction,
            message_url_1: str,
            message_url_2: str
    ):
        """
        合并分析两条消息中「社区助力者」身份组的表情反应。
        返回合并后按表情使用频率从高到低排序的统计列表。
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        # 1. 分析第一条消息
        result1 = await self._analyze_single_message(interaction, message_url_1)
        if not result1:
            return
        message1, sorted_emojis1, role, role_member_ids1 = result1

        # 2. 分析第二条消息
        result2 = await self._analyze_single_message(interaction, message_url_2, skip_role_check=True)
        if not result2:
            return
        message2, sorted_emojis2, _, role_member_ids2 = result2

        # 3. 合并统计
        combined_counter: Dict[str, Tuple[discord.Emoji, int, Set[int]]] = {}
        all_role_member_ids = role_member_ids1 | role_member_ids2

        # 处理第一条消息的反应
        for reaction in message1.reactions:
            emoji = reaction.emoji
            key = str(emoji)
            users = await self._get_role_member_reactors(reaction, all_role_member_ids)
            if users:
                combined_counter[key] = (emoji, len(users), set(users))

        # 处理第二条消息的反应
        for reaction in message2.reactions:
            emoji = reaction.emoji
            key = str(emoji)
            users = await self._get_role_member_reactors(reaction, all_role_member_ids)

            if users:
                if key in combined_counter:
                    # 合并去重
                    existing_emoji, existing_count, existing_users = combined_counter[key]
                    new_users = existing_users | set(users)
                    combined_counter[key] = (existing_emoji, len(new_users), new_users)
                else:
                    combined_counter[key] = (emoji, len(users), set(users))

        if not combined_counter:
            await interaction.followup.send(
                f"ℹ️ 在这两条消息上，身份组 `{role.name}` 的成员没有任何表情反应。",
                ephemeral=True
            )
            return

        # 4. 按数量从高到低排序
        sorted_combined = sorted(
            [(emoji, count) for emoji, count, _ in combined_counter.values()],
            key=lambda x: x[1],
            reverse=True
        )

        # 5. 构建合并回复
        embed = self._build_stats_embed(
            title="📊 社区助力者表情反应统计（合并）",
            message1=message1,
            message2=message2,
            role=role,
            role_member_count=len(all_role_member_ids),
            sorted_emojis=sorted_combined,
            is_combined=True
        )

        embed.set_footer(text=f"请求者: {interaction.user.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

        self.logger.info(
            f"合并表情分析完成 - 用户: {interaction.user} ({interaction.user.id}), "
            f"消息1: {message1.id}, 消息2: {message2.id}, 身份组: {role.name}"
        )

    async def _analyze_single_message(
            self,
            interaction: discord.Interaction,
            message_url: str,
            skip_role_check: bool = False
    ) -> Tuple[discord.Message, List[Tuple[discord.Emoji, int]], discord.Role, Set[int]] | None:
        """
        分析单条消息的表情反应。
        返回: (消息对象, 排序后的表情统计, 身份组对象, 身份组成员ID集合)
        失败时返回 None
        """
        # 1. 解析消息链接
        try:
            message = await self._fetch_message_from_url(message_url)
        except ValueError as e:
            if not skip_role_check:
                await interaction.followup.send(f"❌ 无效的消息链接: {e}", ephemeral=True)
            return None
        except Exception as e:
            self.logger.error(f"获取消息失败: {e}")
            if not skip_role_check:
                await interaction.followup.send(f"❌ 无法获取消息，请检查链接是否正确。", ephemeral=True)
            return None

        if not message.guild:
            if not skip_role_check:
                await interaction.followup.send("❌ 该消息不在服务器中。", ephemeral=True)
            return None

        # 2. 获取社区助力者身份组
        role = message.guild.get_role(self.ROLE_ID)
        if not role:
            if not skip_role_check:
                await interaction.followup.send(
                    f"❌ 找不到ID为 `{self.ROLE_ID}` 的身份组，请检查配置。",
                    ephemeral=True
                )
            return None

        # 3. 获取身份组成员
        role_members = [m for m in role.members if not m.bot]
        if not role_members:
            if not skip_role_check:
                await interaction.followup.send(
                    f"ℹ️ 身份组 `{role.name}` 中没有非机器人成员。",
                    ephemeral=True
                )
            return None

        role_member_ids = {m.id for m in role_members}

        # 4. 分析消息表情反应
        emoji_counter: Dict[str, Tuple[discord.Emoji, int]] = {}

        for reaction in message.reactions:
            users = await self._get_role_member_reactors(reaction, role_member_ids)
            if users:
                key = str(reaction.emoji)
                emoji_counter[key] = (reaction.emoji, len(users))

        if not emoji_counter and not skip_role_check:
            await interaction.followup.send(
                f"ℹ️ 在消息 `{message.jump_url}` 上，身份组 `{role.name}` 的成员没有任何表情反应。",
                ephemeral=True
            )
            return None

        # 5. 按数量从高到低排序
        sorted_emojis = sorted(
            emoji_counter.values(),
            key=lambda x: x[1],
            reverse=True
        )

        return message, sorted_emojis, role, role_member_ids

    async def _get_role_member_reactors(self, reaction: discord.Reaction, role_member_ids: Set[int]) -> List[int]:
        """获取对某个表情做出反应的身份组成员ID列表"""
        users = []
        async for user in reaction.users():
            if user.id in role_member_ids:
                users.append(user.id)
        return users

    def _build_stats_embed(
            self,
            title: str,
            role: discord.Role,
            role_member_count: int,
            sorted_emojis: List[Tuple[discord.Emoji, int]],
            is_combined: bool = False,
            message: discord.Message = None,
            message1: discord.Message = None,
            message2: discord.Message = None
    ) -> discord.Embed:
        """构建统计结果的 Embed"""
        embed = discord.Embed(
            title=title,
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )

        if is_combined:
            embed.description = (
                f"**分析消息 1:** [跳转]({message1.jump_url})\n"
                f"**分析消息 2:** [跳转]({message2.jump_url})\n"
                f"**身份组:** {role.mention} ({role_member_count} 人)\n"
                f"*注: 同一成员在两条消息中的相同表情已去重*"
            )
        else:
            embed.description = (
                f"**分析消息:** [跳转]({message.jump_url})\n"
                f"**身份组:** {role.mention} ({role_member_count} 人)"
            )

        # 分批构建，确保每段不超过 1024 字符
        if not sorted_emojis:
            embed.add_field(
                name="📈 统计结果 (共 0 种表情)",
                value="无数据",
                inline=False
            )
            return embed

        current_batch = []
        current_length = 0
        field_count = 1

        for idx, (emoji, count) in enumerate(sorted_emojis, 1):
            # 处理自定义表情和Unicode表情的显示
            if isinstance(emoji, (discord.Emoji, discord.PartialEmoji)):
                emoji_display = str(emoji)
            else:
                emoji_display = emoji

            line = f"{idx}. {emoji_display} — **{count}** 人\n"

            # 如果添加这一行会超过 1024 字符，先保存当前批次
            if current_length + len(line) > 800:
                field_name = f"📈 统计结果 (第 {field_count} 部分)" if field_count > 1 else f"📈 统计结果 (共 {len(sorted_emojis)} 种表情)"
                embed.add_field(
                    name=field_name,
                    value="".join(current_batch).rstrip("\n"),
                    inline=False
                )
                current_batch = [line]
                current_length = len(line)
                field_count += 1
            else:
                current_batch.append(line)
                current_length += len(line)

        # 添加最后一批
        if current_batch:
            field_name = f"📈 统计结果 (第 {field_count} 部分)" if field_count > 1 else f"📈 统计结果 (共 {len(sorted_emojis)} 种表情)"
            embed.add_field(
                name=field_name,
                value="".join(current_batch).rstrip("\n"),
                inline=False
            )

        return embed

    async def _fetch_message_from_url(self, url: str) -> discord.Message:
        """
        从Discord消息URL解析并获取消息对象。
        支持格式: https://discord.com/channels/{guild_id}/{channel_id}/{message_id}
        """
        # 移除可能的尾部斜杠和查询参数
        url = url.strip().rstrip('/')

        parts = url.split('/')

        # 找到 'channels' 后的部分
        try:
            channels_idx = parts.index('channels')
        except ValueError:
            raise ValueError("URL 中找不到 'channels' 部分")

        if len(parts) < channels_idx + 4:
            raise ValueError("URL 格式不正确，需要包含 guild_id/channel_id/message_id")

        guild_id = int(parts[channels_idx + 1])
        channel_id = int(parts[channels_idx + 2])
        message_id = int(parts[channels_idx + 3])

        # 验证服务器
        guild = self.bot.get_guild(guild_id)
        if not guild:
            raise ValueError(f"机器人不在该服务器中 (ID: {guild_id})")

        # 获取频道
        channel = guild.get_channel(channel_id)
        if not channel:
            # 尝试获取线程
            channel = guild.get_thread(channel_id)
        if not channel:
            raise ValueError(f"找不到频道或线程 (ID: {channel_id})")

        # 获取消息
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            raise ValueError(f"找不到消息 (ID: {message_id})")
        except discord.Forbidden:
            raise ValueError(f"机器人没有权限访问该消息")

        return message


async def setup(bot: 'TicketBot'):
    """Cog的入口点。"""
    await bot.add_cog(TempCog(bot))
