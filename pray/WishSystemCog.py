import typing

import discord
from discord import app_commands
from discord.ext import commands

import config_data
from config_data import GuildWishConfig
from utility.feature_cog import FeatureCog
from .adapters import AsyncJsonWishRepository, DiscordWishAdapter
from .pray_core.engine import WishEngine
from .pray_core.manager import WishDataManager
from .pray_core.models import UserContext, UserRole, WishCategory
from .ui.embeds import WishEmbed, WishUIFactory


class WishSystemCog(FeatureCog):
    """许愿系统控制核心"""

    def __init__(self, bot):
        super().__init__(bot)
        self.data_manager = WishDataManager.get_instance()
        # 实际开发中配置可能由数据库或 CoreCog 提供
        # 这里为了演示用一个字典模拟多服务器配置
        self._configs: dict[int, GuildWishConfig] = config_data.config

    async def update_safe_roles_cache(self):
        """实现抽象基类的强制要求"""
        self.logger.info("[WishSystem] 更新安全身份组缓存...")
        # 您的实现逻辑：比如从 CoreCog 获取最新的管理员列表更新到自己的 config 中
        pass

    # ================= 辅助方法 =================

    def _get_engine(self, guild_id: int) -> WishEngine:
        """构建领域引擎注入依赖"""
        if guild_id not in self._configs:
            # 临时生成一个默认配置防崩溃，生产环境应抛出异常或返回 None
            self._configs[guild_id] = config_data.config[guild_id]

        config = self._configs[guild_id]
        repo = AsyncJsonWishRepository(self.data_manager, guild_id)
        adapter = DiscordWishAdapter(self.bot, config)

        engine = WishEngine(repo, adapter)
        engine.SUPPORT_THRESHOLD = config.support_threshold
        return engine

    def _get_user_context(self, interaction: discord.Interaction) -> UserContext:
        """从 Discord 上下文解析业务权限"""
        if not interaction.guild_id or interaction.guild_id not in self._configs:
            self.logger.warning(f"[WishSystem] 无法找到配置: {interaction.guild_id}")
            self.logger.info(f"[WishSystem] 配置:{self._configs}")
            return UserContext(user_id=str(interaction.user.id), role=UserRole.NORMAL)

        config = self._configs[interaction.guild_id]
        user_roles = [r.id for r in interaction.user.roles]

        role = UserRole.NORMAL
        if any(r in config.admin_role_ids for r in user_roles):
            role = UserRole.ADMIN
        elif any(r in config.builder_role_ids for r in user_roles):
            role = UserRole.BUILDER

        return UserContext(user_id=str(interaction.user.id), role=role)

    # ================= 核心交互入口 =================

    @app_commands.command(name="wish", description="✨ 提出一个新的愿望")
    async def cmd_wish(self, interaction: discord.Interaction):
        user_ctx = self._get_user_context(interaction)
        if user_ctx.role < UserRole.BUILDER:
            return await interaction.response.send_message("❌ 权限不足：您至少需要是【社区建设者】才能许愿。", ephemeral=True)

        # 弹出创建模态框
        class CreateWishModal(discord.ui.Modal, title="许下你的愿望"):
            title_input = discord.ui.TextInput(label="标题 (一句话描述)", max_length=100)
            content_input = discord.ui.TextInput(label="详细内容", style=discord.TextStyle.paragraph)

            def __init__(self, cog: WishSystemCog):
                super().__init__()
                self.cog = cog

            async def on_submit(self, modal_interaction: discord.Interaction):
                engine = self.cog._get_engine(modal_interaction.guild_id)
                ctx = self.cog._get_user_context(modal_interaction)

                # 调用引擎异步创建
                wish = await engine.create_wish(
                    ctx, WishCategory.COMMUNITY, self.title_input.value, self.content_input.value
                )

                # 渲染卡片和初始UI
                embed = WishEmbed(wish)
                view = WishUIFactory.build_view(wish, ctx)

                # 发送到指定的频道
                config = self.cog._configs.get(modal_interaction.guild_id)
                channel = self.cog.bot.get_channel(config.wish_channel_id) if config else modal_interaction.channel

                await channel.send(embed=embed, view=view)
                await modal_interaction.response.send_message(f"✅ 愿望发布成功！ID: `{wish.id}`", ephemeral=True)

        await interaction.response.send_modal(CreateWishModal(self))

    # ================= 全局组件交互路由 =================

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """统一接管所有的许愿卡按钮点击事件，支持持久化操作"""
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("wish:"):
            return

        # 解析路由: wish:action:wish_id
        _, action, wish_id = custom_id.split(":")

        engine = self._get_engine(interaction.guild_id)
        user_ctx = self._get_user_context(interaction)

        try:
            if action == "support":
                await self._handle_support(interaction, engine, user_ctx, wish_id)
            elif action == "claim":
                await self._handle_claim_trigger(interaction, engine, user_ctx, wish_id)
            elif action == "manage":
                await self._handle_manage_trigger(interaction, engine, user_ctx, wish_id)
        except Exception as e:
            self.logger.error(f"处理交互失败: {e}", exc_info=True)
            # 这里的异常可能是业务的 StateTransitionError，直接反馈给用户
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠️ 操作失败: {str(e)}", ephemeral=True)

    # --- 细分处理逻辑 ---

    async def _handle_support(self, interaction: discord.Interaction, engine: WishEngine, ctx: UserContext, wish_id: str):
        wish = await engine.support_wish(ctx, wish_id)
        self.logger.info(f"User {ctx.user_id} supported wish {wish_id}")

        # 刷新原卡片
        await interaction.response.edit_message(
            embed=WishEmbed(wish),
            view=WishUIFactory.build_view(wish, ctx)
        )

    async def _handle_claim_trigger(self, interaction: discord.Interaction, engine: WishEngine, ctx: UserContext, wish_id: str):
        # 弹出输入提案链接的 Modal
        class ClaimModal(discord.ui.Modal, title="认领愿望"):
            link_input = discord.ui.TextInput(label="对应的提案区链接", placeholder="https://discord.com/channels/...")

            async def on_submit(self, m_interaction: discord.Interaction):
                wish = await engine.claim_wish(ctx, wish_id, self.link_input.value)

                # 刷新原卡片 (需要使用原来的 interaction 或是重新 fetch message，这里为了简单直接 edit)
                await interaction.message.edit(embed=WishEmbed(wish), view=WishUIFactory.build_view(wish, ctx))
                await m_interaction.response.send_message("✅ 认领成功！该愿望进入实现阶段。", ephemeral=True)

        await interaction.response.send_modal(ClaimModal())

    async def _handle_manage_trigger(self, interaction: discord.Interaction, engine: WishEngine, ctx: UserContext, wish_id: str):
        # 管理面板可以是一个临时的 View，只对点击者可见
        class ManageView(discord.ui.View):
            @discord.ui.button(label="撤回/关闭", style=discord.ButtonStyle.danger)
            async def btn_close(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                wish = await engine.withdraw_wish(ctx, wish_id)
                await interaction.message.edit(embed=WishEmbed(wish), view=WishUIFactory.build_view(wish, ctx))
                await btn_interaction.response.send_message("✅ 愿望已关闭。", ephemeral=True)

            @discord.ui.button(label="直接开启讨论(管理员)", style=discord.ButtonStyle.primary)
            async def btn_activate(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                wish = await engine.admin_force_activate(ctx, wish_id)
                await interaction.message.edit(embed=WishEmbed(wish), view=WishUIFactory.build_view(wish, ctx))
                await btn_interaction.response.send_message("✅ 已跳过支持阶段强行开启讨论。", ephemeral=True)

        await interaction.response.send_message("请选择管理操作：", view=ManageView(timeout=120), ephemeral=True)


if typing.TYPE_CHECKING:
    from main import TicketBot


async def setup(bot: 'TicketBot'):
    """Cog的入口点。"""
    await bot.add_cog(WishSystemCog(bot))
