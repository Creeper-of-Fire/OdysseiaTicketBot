import typing
import discord
from discord import app_commands
from discord.ext import commands

import config
import config_data
from utility.feature_cog import FeatureCog
from .bottle_core.engine import BottleEngine
from .bottle_core.models import UserContext, UserRole, BottleConfig
from .bottle_core.repository import BottleRepository
from .ui.embeds import BottleEmbed
from .ui.views import BottleView, CreateBottleModal, ReplyBottleModal


class BottleSystemCog(FeatureCog):
    """漂流瓶系统控制核心"""

    def __init__(self, bot):
        super().__init__(bot)
        self._configs = config_data.bottle_config
        self.repository = BottleRepository.get_instance()

    # ================= 辅助方法 =================

    def _get_engine(self, guild_id: int) -> BottleEngine:
        """构建领域引擎注入依赖"""
        if guild_id not in self._configs:
            # 使用默认配置
            bottle_config = BottleConfig()
        else:
            guild_config = self._configs[guild_id]
            bottle_config = BottleConfig(
                max_bottles_per_user=guild_config.max_bottles_per_user,
                cooldown_seconds=guild_config.cooldown_seconds,
                bottle_lifetime_days=guild_config.bottle_lifetime_days
            )
        return BottleEngine(self.repository, bottle_config, guild_id)

    def _get_user_context(self, interaction: discord.Interaction) -> UserContext:
        """从 Discord 上下文解析业务权限"""
        user_roles = [r.id for r in interaction.user.roles]

        role = UserRole.NORMAL
        if interaction.guild_id and interaction.guild_id in self._configs:
            guild_config = self._configs[interaction.guild_id]
            if any(r in guild_config.admin_role_ids for r in user_roles):
                role = UserRole.ADMIN

        return UserContext(user_id=str(interaction.user.id), role=role)

    async def create_bottle(self, interaction: discord.Interaction, content: str):
        """创建漂流瓶"""
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        try:
            bottle = await engine.create_bottle(user_ctx, content)
            await interaction.response.send_message(
                embed=BottleEmbed.create_success_embed("漂流瓶已成功投放！"),
                ephemeral=True
            )
        except ValueError as e:
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed(str(e)),
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"创建漂流瓶时发生错误: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed("系统内部错误，请稍后再试"),
                ephemeral=True
            )

    async def find_bottle(self, interaction: discord.Interaction):
        """查找漂流瓶"""
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        try:
            bottle = await engine.find_bottle(user_ctx)
            if not bottle:
                await interaction.response.send_message(
                    embed=BottleEmbed.create_error_embed("暂时没有找到漂流瓶，稍后再试吧！"),
                    ephemeral=True
                )
                return

            embed = BottleEmbed.create_bottle_embed(bottle)
            view = BottleView(bottle.id)
            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"查找漂流瓶时发生错误: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed("系统内部错误，请稍后再试"),
                ephemeral=True
            )

    async def open_bottle(self, interaction: discord.Interaction, bottle_id: str):
        """打开漂流瓶"""
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        try:
            bottle = await engine.open_bottle(user_ctx, bottle_id)
            embed = BottleEmbed.create_bottle_embed(bottle)
            view = BottleView(bottle.id)
            await interaction.response.edit_message(
                embed=embed,
                view=view
            )
        except ValueError as e:
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed(str(e)),
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"打开漂流瓶时发生错误: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed("系统内部错误，请稍后再试"),
                ephemeral=True
            )

    async def reply_bottle(self, interaction: discord.Interaction, bottle_id: str, reply: str):
        """回复漂流瓶"""
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        try:
            bottle = await engine.reply_bottle(user_ctx, bottle_id, reply)
            embed = BottleEmbed.create_bottle_embed(bottle)
            view = BottleView(bottle.id)
            await interaction.response.edit_message(
                embed=embed,
                view=view
            )
            # 发送回复成功的消息
            await interaction.followup.send(
                embed=BottleEmbed.create_success_embed("回复成功！"),
                ephemeral=True
            )
        except ValueError as e:
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed(str(e)),
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"回复漂流瓶时发生错误: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed("系统内部错误，请稍后再试"),
                ephemeral=True
            )

    # ================= 命令 =================

    bottle_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨漂流瓶",
        description="漂流瓶相关指令",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(read_messages=True),
    )

    @bottle_group.command(name="扔瓶子", description="🏺 投放一个漂流瓶")
    async def cmd_throw_bottle(self, interaction: discord.Interaction):
        """投放漂流瓶：弹出输入框"""
        await interaction.response.send_modal(CreateBottleModal(self))

    @bottle_group.command(name="捞瓶子", description="🏺 捞一个漂流瓶")
    async def cmd_find_bottle(self, interaction: discord.Interaction):
        """捞漂流瓶：随机获取一个漂流瓶"""
        await self.find_bottle(interaction)

    # ================= 全局组件交互路由 =================

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """统一分发按钮交互"""
        if interaction.type != discord.InteractionType.component: return
        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("bottle:"): return

        parts = custom_id.split(":")
        if len(parts) < 2: return

        action = parts[1]
        # 从视图中获取 bottle_id
        bottle_id = None
        if hasattr(interaction.message, "components"):
            for component in interaction.message.components:
                if hasattr(component, "children"):
                    for child in component.children:
                        if hasattr(child, "view") and hasattr(child.view, "bottle_id"):
                            bottle_id = child.view.bottle_id
                            break
                    if bottle_id:
                        break

        if not bottle_id:
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed("漂流瓶信息丢失，请重新捞取"),
                ephemeral=True
            )
            return

        try:
            if action == "open":
                await self.open_bottle(interaction, bottle_id)
            elif action == "reply":
                await interaction.response.send_modal(ReplyBottleModal(self, bottle_id))
        except Exception as e:
            self.logger.error(f"处理漂流瓶交互时发生错误: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=BottleEmbed.create_error_embed("系统内部错误，请稍后再试"),
                ephemeral=True
            )


if typing.TYPE_CHECKING:
    from main import TicketBot


async def setup(bot: 'TicketBot'):
    """Cog的入口点。"""
    await bot.add_cog(BottleSystemCog(bot))