import typing

import discord
from discord import app_commands

import config
import config_data
from utility.feature_cog import FeatureCog
from .bottle_core.engine import BottleEngine
from .bottle_core.manager import BottleDataManager
from .bottle_core.models import UserContext, UserRole
from .adapters import AsyncJsonBottleRepository, DiscordBottleAdapter
from .ui.embeds import BottleEmbed, BottleUIFactory
from .ui.views import BottleCardView, CreateBottleModal


class BottleSystemCog(FeatureCog):
    """漂流瓶系统控制核心"""

    def __init__(self, bot):
        super().__init__(bot)
        self._configs = config_data.bottle_config
        self.data_manager = BottleDataManager.get_instance()

    async def cog_load(self):
        """注册持久化视图，确保 bot 重启后按钮仍然可用。"""
        self.bot.add_view(BottleCardView())
        self.logger.info("已注册 BottleCardView 持久化视图")

    # ================= 辅助方法 =================

    def _get_engine(self, guild_id: int) -> BottleEngine:
        repo = AsyncJsonBottleRepository(self.data_manager, guild_id)
        if guild_id not in self._configs:
            adapter = DiscordBottleAdapter(self.bot, config_data.GuildBottleConfig())
        else:
            adapter = DiscordBottleAdapter(self.bot, self._configs[guild_id])
        return BottleEngine(repo, adapter)

    def _get_user_context(self, interaction: discord.Interaction) -> UserContext:
        user_roles = [r.id for r in interaction.user.roles]
        role = UserRole.NORMAL
        if interaction.guild_id and interaction.guild_id in self._configs:
            guild_config = self._configs[interaction.guild_id]
            if any(r in guild_config.admin_role_ids for r in user_roles):
                role = UserRole.ADMIN
        return UserContext(user_id=str(interaction.user.id), role=role)

    # ================= 命令 =================

    bottle_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨漂流瓶",
        description="漂流瓶相关指令",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(read_messages=True),
    )

    @bottle_group.command(name="发布心愿", description="🏺 发布一个心愿漂流瓶")
    async def cmd_create_bottle(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CreateBottleModal())

    @bottle_group.command(name="我的心愿", description="📋 查看你发布的心愿列表")
    async def cmd_my_bottles(self, interaction: discord.Interaction):
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        bottles = await engine.get_user_bottles(user_ctx)
        if not bottles:
            await interaction.response.send_message(
                embed=BottleUIFactory.create_error_embed("你还没有发布过心愿漂流瓶。"),
                ephemeral=True
            )
            return

        lines = []
        for b in bottles:
            label = BottleEmbed.STATE_LABELS.get(b.state, b.state)
            lines.append(f"**{label}** | {b.title} (ID: {b.id[:8]})")

        embed = discord.Embed(
            title="你的心愿漂流瓶",
            description="\n".join(lines),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bottle_group.command(name="待揭榜", description="📋 查看所有待揭榜的心愿")
    async def cmd_available_bottles(self, interaction: discord.Interaction):
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        bottles = await engine.get_available_bottles(user_ctx)
        if not bottles:
            await interaction.response.send_message(
                embed=BottleUIFactory.create_error_embed("当前没有待揭榜的心愿漂流瓶。"),
                ephemeral=True
            )
            return

        # Show the first available bottle
        bottle = bottles[0]
        embed = BottleEmbed(bottle)
        view = BottleCardView.for_bottle(bottle, user_ctx)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ================= 业务方法 =================

    async def create_bottle(self, interaction: discord.Interaction, title: str, content: str):
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        try:
            bottle = await engine.create_bottle(user_ctx, title, content)
            await interaction.response.send_message(
                embed=BottleUIFactory.create_success_embed(f"心愿漂流瓶「{bottle.title}」已成功投放！"),
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"创建漂流瓶时发生错误: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=BottleUIFactory.create_error_embed("系统内部错误，请稍后再试"),
                ephemeral=True
            )



if typing.TYPE_CHECKING:
    from main import TicketBot


async def setup(bot: 'TicketBot'):
    """Cog的入口点。"""
    await bot.add_cog(BottleSystemCog(bot))
