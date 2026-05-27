import typing
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import config_data
from config_data import GuildWishConfig
from utility.feature_cog import FeatureCog
from .adapters import AsyncJsonWishRepository, DiscordWishAdapter
from .pray_core.engine import WishEngine, StateTransitionError
from .pray_core.manager import WishDataManager
from .pray_core.models import UserContext, UserRole, WishCategory, ActiveWish, DiscussionWish, InProgressWish, ClosedWish, FulfilledWish, FrozenWish
from .ui.embeds import WishEmbed, WishCardView, WishManageView


class WishSystemCog(FeatureCog):
    """许愿系统控制核心"""

    def __init__(self, bot):
        super().__init__(bot)
        self.data_manager = WishDataManager.get_instance()
        self._configs: dict[int, GuildWishConfig] = config_data.config
        self.auto_freeze_task.start()

    async def cog_load(self):
        """注册持久化视图，确保 bot 重启后按钮仍然可用。"""
        self.bot.add_view(WishCardView())
        self.logger.info("已注册 WishCardView 持久化视图")

    def cog_unload(self):
        self.auto_freeze_task.cancel()

    # ================= 自动冻结后台任务 =================

    @tasks.loop(minutes=60)
    async def auto_freeze_task(self):
        """定期检查并冻结长期无活动的愿望"""
        for guild_id in list(self._configs):
            try:
                engine = self._get_engine(guild_id)
                config = self._configs.get(guild_id)
                cutoff = datetime.utcnow() - timedelta(days=config.auto_freeze_days)
                wishes = await engine.repo.get_all()
                for w in wishes:
                    if isinstance(w, (ClosedWish, FulfilledWish, FrozenWish)):
                        continue
                    if w.updated_at < cutoff:
                        try:
                            await engine.freeze_wish(w.id)
                            self.logger.info(f"自动冻结愿望 {w.id} ({w.title}) in guild {guild_id}")
                        except Exception as e:
                            self.logger.warning(f"冻结愿望 {w.id} 失败: {e}")
            except Exception as e:
                self.logger.error(f"自动冻结检查失败 guild {guild_id}: {e}")

    @auto_freeze_task.before_loop
    async def before_freeze_task(self):
        await self.bot.wait_until_ready()

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

    @staticmethod
    async def _execute_engine_call(interaction: discord.Interaction, coro):
        """统一执行引擎操作并处理业务异常"""
        try:
            return await coro
        except (PermissionError, StateTransitionError, ValueError) as e:
            # 引擎抛出的业务错误直接反馈给用户
            msg = f"❌ 操作失败: {str(e)}"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return None

    # ================= 核心交互入口 =================

    pray_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨许愿", description="许愿池相关指令",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(read_messages=True),
    )

    @pray_group.command(name="许愿", description="✨ 提出一个新的愿望")
    async def cmd_wish(self, interaction: discord.Interaction):
        """发起愿望：先选择分类，再填写内容"""
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        # 构建分类选项（不包括 ADMIN_HELP，那是引擎自动判定的）
        category_options = [
            discord.SelectOption(label=WishCategory.BOT_FEATURE.value, value=WishCategory.BOT_FEATURE.value,
                                 emoji="🤖"),
            discord.SelectOption(label=WishCategory.COMMUNITY.value, value=WishCategory.COMMUNITY.value,
                                 emoji="🏘️"),
            discord.SelectOption(label=WishCategory.SYSTEM.value, value=WishCategory.SYSTEM.value,
                                 emoji="⚙️"),
        ]

        class CategorySelectView(discord.ui.View):
            def __init__(self, outer_cog, outer_engine, outer_ctx):
                super().__init__(timeout=120)
                self.cog = outer_cog
                self.engine = outer_engine
                self.ctx = outer_ctx

            @discord.ui.select(placeholder="请选择愿望分类...", options=category_options)
            async def category_select(select_self, sel_interaction: discord.Interaction, select: discord.ui.Select):
                selected_category = WishCategory(select.values[0])
                cog = select_self.cog

                class CreateWishModal(discord.ui.Modal, title=f"许下你的愿望 — {selected_category.value}"):
                    title_input = discord.ui.TextInput(label="标题 (一句话描述)", max_length=100)
                    content_input = discord.ui.TextInput(label="详细内容", style=discord.TextStyle.paragraph)

                    async def on_submit(modal_self, m_interaction: discord.Interaction):
                        try:
                            wish = await engine.create_wish(
                                user_ctx, selected_category,
                                modal_self.title_input.value, modal_self.content_input.value
                            )
                            embed = WishEmbed(wish)
                            view = WishCardView.for_wish(wish, user_ctx)

                            guild_config = cog._configs.get(m_interaction.guild_id)
                            target_channel = (
                                cog.bot.get_channel(guild_config.wish_channel_id)
                                if guild_config else m_interaction.channel
                            )
                            await target_channel.send(embed=embed, view=view)
                            await m_interaction.response.send_message("✅ 愿望发布成功！", ephemeral=True)

                        except PermissionError as e:
                            await m_interaction.response.send_message(f"❌ 许愿失败: {e}", ephemeral=True)
                        except Exception as e:
                            cog.logger.error(f"创建愿望时发生崩溃: {e}", exc_info=True)
                            if not m_interaction.response.is_done():
                                await m_interaction.response.send_message("🚨 系统内部错误", ephemeral=True)

                await sel_interaction.response.send_modal(CreateWishModal())
                select_self.stop()

        await interaction.response.send_message(
            "请选择愿望分类：", view=CategorySelectView(self, engine, user_ctx), ephemeral=True
        )

    # --- 交互触发的 Modal ---

    class ClaimModal(discord.ui.Modal, title="认领愿望"):
        link = discord.ui.TextInput(label="提案链接", placeholder="https://...")

        def __init__(self, engine, ctx, wish_id, original_message: discord.Message):
            super().__init__()
            self.engine = engine
            self.ctx = ctx
            self.wish_id = wish_id
            self.original_message = original_message

        async def on_submit(self, itl: discord.Interaction):
            try:
                new_wish = await self.engine.claim_wish(self.ctx, self.wish_id, self.link.value)
                await self.original_message.edit(
                    embed=WishEmbed(new_wish),
                    view=WishCardView.for_wish(new_wish, self.ctx)
                )
                await itl.response.send_message("✅ 认领成功！", ephemeral=True)
            except (StateTransitionError, PermissionError, ValueError) as e:
                await itl.response.send_message(f"❌ 认领失败: {e}", ephemeral=True)

    class ForceCloseModal(discord.ui.Modal, title="强制关闭愿望"):
        reason = discord.ui.TextInput(label="关闭原因", style=discord.TextStyle.paragraph)

        def __init__(self, engine, ctx, wish_id, original_message: discord.Message):
            super().__init__()
            self.engine = engine
            self.ctx = ctx
            self.wish_id = wish_id
            self.original_message = original_message

        async def on_submit(self, itl: discord.Interaction):
            wish = await self.engine.repo.get(self.wish_id)
            new_wish = ClosedWish(
                close_reason=self.reason.value,
                **wish.model_dump(exclude={"state", "close_reason", "merged_into_id", "freeze_reason"})
            )
            if getattr(new_wish, "thread_id", None):
                await self.engine.adapter.lock_discussion_thread(new_wish.thread_id)
            await self.engine._save_and_notify(new_wish)
            try:
                await self.original_message.edit(
                    embed=WishEmbed(new_wish),
                    view=WishCardView.for_wish(new_wish, self.ctx)
                )
            except (discord.NotFound, discord.Forbidden):
                pass
            await itl.response.send_message("✅ 已强制关闭。", ephemeral=True)

    class ForceClaimModal(discord.ui.Modal, title="强制认领愿望"):
        claimer_id = discord.ui.TextInput(label="认领人用户ID")
        proposal_link = discord.ui.TextInput(label="提案链接", placeholder="https://...")

        def __init__(self, engine, ctx, wish_id, original_message: discord.Message):
            super().__init__()
            self.engine = engine
            self.ctx = ctx
            self.wish_id = wish_id
            self.original_message = original_message

        async def on_submit(self, itl: discord.Interaction):
            new_wish = await self.engine.admin_force_claim(
                self.ctx, self.wish_id, self.claimer_id.value, self.proposal_link.value)
            try:
                await self.original_message.edit(
                    embed=WishEmbed(new_wish),
                    view=WishCardView.for_wish(new_wish, self.ctx)
                )
            except (discord.NotFound, discord.Forbidden):
                pass
            await itl.response.send_message("✅ 已强制认领。", ephemeral=True)

    class MergeWishModal(discord.ui.Modal, title="合并愿望"):
        target_id = discord.ui.TextInput(label="目标愿望ID")

        def __init__(self, engine, ctx, wish_id, original_message: discord.Message):
            super().__init__()
            self.engine = engine
            self.ctx = ctx
            self.wish_id = wish_id
            self.original_message = original_message

        async def on_submit(self, itl: discord.Interaction):
            new_wish = await self.engine.admin_merge_wishes(
                self.ctx, self.wish_id, self.target_id.value)
            try:
                await self.original_message.edit(
                    embed=WishEmbed(new_wish),
                    view=WishCardView.for_wish(new_wish, self.ctx)
                )
            except (discord.NotFound, discord.Forbidden):
                pass
            await itl.response.send_message("✅ 已合并愿望。", ephemeral=True)


if typing.TYPE_CHECKING:
    from main import TicketBot


async def setup(bot: 'TicketBot'):
    """Cog的入口点。"""
    await bot.add_cog(WishSystemCog(bot))
