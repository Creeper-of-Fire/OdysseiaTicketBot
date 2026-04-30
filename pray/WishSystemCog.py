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
from .ui.embeds import WishEmbed, WishUIFactory


class WishSystemCog(FeatureCog):
    """许愿系统控制核心"""

    def __init__(self, bot):
        super().__init__(bot)
        self.data_manager = WishDataManager.get_instance()
        self._configs: dict[int, GuildWishConfig] = config_data.config
        self.auto_freeze_task.start()

    def cog_unload(self):
        self.auto_freeze_task.cancel()

    # ================= 自动冻结后台任务 =================

    @tasks.loop(minutes=60)
    async def auto_freeze_task(self):
        """定期检查并冻结长期无活动的愿望"""
        for guild_id in list(self._configs.keys()):
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

    @pray_group.command(name=”许愿”, description=”✨ 提出一个新的愿望”)
    async def cmd_wish(self, interaction: discord.Interaction):
        “””发起愿望：先选择分类，再填写内容”””
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        # 构建分类选项（不包括 ADMIN_HELP，那是引擎自动判定的）
        category_options = [
            discord.SelectOption(label=WishCategory.BOT_FEATURE.value, value=WishCategory.BOT_FEATURE.value,
                                 emoji=”🤖”),
            discord.SelectOption(label=WishCategory.COMMUNITY.value, value=WishCategory.COMMUNITY.value,
                                 emoji=”🏘️”),
            discord.SelectOption(label=WishCategory.SYSTEM.value, value=WishCategory.SYSTEM.value,
                                 emoji=”⚙️”),
        ]

        class CategorySelectView(discord.ui.View):
            def __init__(self, outer_cog, outer_engine, outer_ctx):
                super().__init__(timeout=120)
                self.cog = outer_cog
                self.engine = outer_engine
                self.ctx = outer_ctx

            @discord.ui.select(placeholder=”请选择愿望分类...”, options=category_options)
            async def category_select(select_self, sel_interaction: discord.Interaction, select: discord.ui.Select):
                selected_category = WishCategory(select.values[0])
                cog = select_self.cog

                class CreateWishModal(discord.ui.Modal, title=f”许下你的愿望 — {selected_category.value}”):
                    title_input = discord.ui.TextInput(label=”标题 (一句话描述)”, max_length=100)
                    content_input = discord.ui.TextInput(label=”详细内容”, style=discord.TextStyle.paragraph)

                    async def on_submit(modal_self, m_interaction: discord.Interaction):
                        try:
                            wish = await engine.create_wish(
                                user_ctx, selected_category,
                                modal_self.title_input.value, modal_self.content_input.value
                            )
                            embed = WishEmbed(wish)
                            view = WishUIFactory.build_view(wish, user_ctx)

                            guild_config = cog._configs.get(m_interaction.guild_id)
                            target_channel = (
                                cog.bot.get_channel(guild_config.wish_channel_id)
                                if guild_config else m_interaction.channel
                            )
                            await target_channel.send(embed=embed, view=view)
                            await m_interaction.response.send_message(“✅ 愿望发布成功！”, ephemeral=True)

                        except PermissionError as e:
                            await m_interaction.response.send_message(f”❌ 许愿失败: {e}”, ephemeral=True)
                        except Exception as e:
                            cog.logger.error(f”创建愿望时发生崩溃: {e}”, exc_info=True)
                            if not m_interaction.response.is_done():
                                await m_interaction.response.send_message(“🚨 系统内部错误”, ephemeral=True)

                await sel_interaction.response.send_modal(CreateWishModal())
                self.stop()

        await interaction.response.send_message(
            “请选择愿望分类：”, view=CategorySelectView(self, engine, user_ctx), ephemeral=True
        )

    # ================= 全局组件交互路由 =================

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """统一分发按钮交互"""
        if interaction.type != discord.InteractionType.component: return
        custom_id = interaction.data.get("custom_id", "")

        if custom_id.startswith("wish:"):
            await self._route_wish_interaction(interaction, custom_id)
        elif custom_id.startswith("manage_btn:"):
            await self._route_manage_interaction(interaction, custom_id)

    async def _route_wish_interaction(self, interaction: discord.Interaction, custom_id: str):
        """处理 wish:* 前缀的按钮"""
        _, action, wish_id = custom_id.split(":")
        engine = self._get_engine(interaction.guild_id)
        ctx = self._get_user_context(interaction)

        try:
            if action == "support":
                new_wish = await engine.support_wish(ctx, wish_id)
                await interaction.response.edit_message(
                    embed=WishEmbed(new_wish),
                    view=WishUIFactory.build_view(new_wish, ctx)
                )

            elif action == "claim":
                await self._show_claim_modal(interaction, engine, ctx, wish_id)

            elif action == "reopen":
                new_wish = await engine.admin_reopen_wish(ctx, wish_id)
                await interaction.response.edit_message(
                    embed=WishEmbed(new_wish),
                    view=WishUIFactory.build_view(new_wish, ctx)
                )

            elif action == "manage":
                await self._show_manage_panel(interaction, engine, ctx, wish_id)

        except (StateTransitionError, PermissionError, ValueError) as e:
            await interaction.response.send_message(f"❌ 操作无法执行: {e}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"未知错误: {e}", exc_info=True)

    async def _route_manage_interaction(self, interaction: discord.Interaction, custom_id: str):
        """处理 manage_btn:* 前缀的管理面板按钮"""
        parts = custom_id.split(":", 2)  # manage_btn:action:wish_id
        if len(parts) < 3: return
        _, action, wish_id = parts

        engine = self._get_engine(interaction.guild_id)
        ctx = self._get_user_context(interaction)

        try:
            if action == "withdraw":
                new_wish = await engine.withdraw_wish(ctx, wish_id)
                await interaction.message.edit(
                    embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await interaction.response.send_message("✅ 愿望已关闭。", ephemeral=True)

            elif action == "force_activate":
                new_wish = await engine.admin_force_activate(ctx, wish_id)
                await interaction.message.edit(
                    embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await interaction.response.send_message("✅ 已强制开启讨论。", ephemeral=True)

            elif action == "force_close_modal":
                await interaction.response.send_modal(
                    WishSystemCog.ForceCloseModal(engine, ctx, wish_id, interaction))

            elif action == "force_claim_modal":
                await interaction.response.send_modal(
                    WishSystemCog.ForceClaimModal(engine, ctx, wish_id, interaction))

            elif action == "merge_modal":
                await interaction.response.send_modal(
                    WishSystemCog.MergeWishModal(engine, ctx, wish_id, interaction))

            elif action == "resolve_accept":
                new_wish = await engine.admin_resolve_proposal(ctx, wish_id, "accept")
                await interaction.message.edit(
                    embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await interaction.response.send_message("✅ 提案已通过。", ephemeral=True)

            elif action == "resolve_reject_reopen":
                new_wish = await engine.admin_resolve_proposal(ctx, wish_id, "reject_reopen")
                await interaction.message.edit(
                    embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await interaction.response.send_message("✅ 已驳回并退回讨论。", ephemeral=True)

            elif action == "resolve_reject_close":
                new_wish = await engine.admin_resolve_proposal(ctx, wish_id, "reject_close")
                await interaction.message.edit(
                    embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await interaction.response.send_message("✅ 已驳回并关闭。", ephemeral=True)

            elif action == "revert_claim":
                new_wish = await engine.admin_revert_claim(ctx, wish_id)
                await interaction.message.edit(
                    embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await interaction.response.send_message("✅ 已回退认领。", ephemeral=True)

            elif action == "reopen":
                new_wish = await engine.admin_reopen_wish(ctx, wish_id)
                await interaction.message.edit(
                    embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await interaction.response.send_message("✅ 已重新开启讨论。", ephemeral=True)

        except (StateTransitionError, PermissionError, ValueError) as e:
            await interaction.response.send_message(f"❌ 操作失败: {e}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"管理面板错误: {e}", exc_info=True)

    async def _show_claim_modal(self, interaction, engine, ctx, wish_id):
        class ClaimModal(discord.ui.Modal, title="认领愿望"):
            link = discord.ui.TextInput(label="提案链接", placeholder="https://...")

            async def on_submit(self, itl: discord.Interaction):
                # 引擎负责检查 DiscussionWish 类型转换
                new_wish = await engine.claim_wish(ctx, wish_id, self.link.value)
                # 直接更新原消息
                await interaction.message.edit(
                    embed=WishEmbed(new_wish),
                    view=WishUIFactory.build_view(new_wish, ctx)
                )
                await itl.response.send_message("认领成功！", ephemeral=True)

        await interaction.response.send_modal(ClaimModal())

    async def _show_manage_panel(self, interaction, engine, ctx, wish_id):
        """根据愿望当前状态动态生成管理面板按钮"""
        wish = await engine.repo.get(wish_id)
        if not wish:
            await interaction.response.send_message("愿望不存在", ephemeral=True)
            return

        class ManagePanelView(discord.ui.View):
            def __init__(view_self):
                super().__init__(timeout=300)

                # 撤回/关闭 (非终态即可)
                if not isinstance(wish, (ClosedWish, FulfilledWish)):
                    view_self.add_item(self._make_button(
                        "撤回/关闭愿望", discord.ButtonStyle.danger, "withdraw", 0))

                # ActiveWish 管理员专属
                if isinstance(wish, ActiveWish) and ctx.role >= UserRole.ADMIN:
                    view_self.add_item(self._make_button(
                        "强制开启讨论", discord.ButtonStyle.primary, "force_activate", 0))
                    view_self.add_item(self._make_button(
                        "强制关闭(含理由)", discord.ButtonStyle.danger, "force_close_modal", 1))

                # DiscussionWish 管理员专属
                if isinstance(wish, DiscussionWish) and ctx.role >= UserRole.ADMIN:
                    view_self.add_item(self._make_button(
                        "强制关闭(含理由)", discord.ButtonStyle.danger, "force_close_modal", 0))
                    view_self.add_item(self._make_button(
                        "强制认领", discord.ButtonStyle.primary, "force_claim_modal", 0))

                # InProgressWish 管理员专属
                if isinstance(wish, InProgressWish) and ctx.role >= UserRole.ADMIN:
                    view_self.add_item(self._make_button(
                        "通过提案", discord.ButtonStyle.success, "resolve_accept", 1))
                    view_self.add_item(self._make_button(
                        "驳回退回讨论", discord.ButtonStyle.primary, "resolve_reject_reopen", 1))
                    view_self.add_item(self._make_button(
                        "驳回并关闭", discord.ButtonStyle.danger, "resolve_reject_close", 1))
                    view_self.add_item(self._make_button(
                        "回退认领", discord.ButtonStyle.secondary, "revert_claim", 2))

                # ClosedWish / FrozenWish 管理员专属
                if isinstance(wish, (ClosedWish, FrozenWish)) and ctx.role >= UserRole.ADMIN:
                    view_self.add_item(self._make_button(
                        "重新开启讨论", discord.ButtonStyle.primary, "reopen", 0))

                # 合并愿望 (Admin 通用)
                if ctx.role >= UserRole.ADMIN and not isinstance(wish, (ClosedWish, FulfilledWish)):
                    view_self.add_item(self._make_button(
                        "合并愿望", discord.ButtonStyle.secondary, "merge_modal", 3))

            @staticmethod
            def _make_button(label, style, action, row):
                return discord.ui.Button(
                    label=label, style=style, row=row,
                    custom_id=f"manage_btn:{action}:{wish_id}"
                )

        await interaction.response.send_message(
            "请选择管理操作：", view=ManagePanelView(), ephemeral=True
        )

    # --- 管理面板 Modal ---

    class ForceCloseModal(discord.ui.Modal, title="强制关闭愿望"):
        reason = discord.ui.TextInput(label="关闭原因", style=discord.TextStyle.paragraph)

        def __init__(self, engine, ctx, wish_id, original_interaction):
            super().__init__()
            self.engine = engine
            self.ctx = ctx
            self.wish_id = wish_id
            self.original_interaction = original_interaction

        async def on_submit(self, itl: discord.Interaction):
            wish = await self.engine.repo.get(self.wish_id)
            new_wish = ClosedWish(
                close_reason=self.reason.value,
                **wish.model_dump(exclude={"state", "close_reason", "merged_into_id", "freeze_reason"})
            )
            if getattr(new_wish, "thread_id", None):
                await self.engine.adapter.lock_discussion_thread(new_wish.thread_id)
            await self.engine._save_and_notify(new_wish)
            await self.original_interaction.message.edit(
                embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, self.ctx))
            await itl.response.send_message("✅ 已强制关闭。", ephemeral=True)

    class ForceClaimModal(discord.ui.Modal, title="强制认领愿望"):
        claimer_id = discord.ui.TextInput(label="认领人用户ID")
        proposal_link = discord.ui.TextInput(label="提案链接", placeholder="https://...")

        def __init__(self, engine, ctx, wish_id, original_interaction):
            super().__init__()
            self.engine = engine
            self.ctx = ctx
            self.wish_id = wish_id
            self.original_interaction = original_interaction

        async def on_submit(self, itl: discord.Interaction):
            new_wish = await self.engine.admin_force_claim(
                self.ctx, self.wish_id, self.claimer_id.value, self.proposal_link.value)
            await self.original_interaction.message.edit(
                embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, self.ctx))
            await itl.response.send_message("✅ 已强制认领。", ephemeral=True)

    class MergeWishModal(discord.ui.Modal, title="合并愿望"):
        target_id = discord.ui.TextInput(label="目标愿望ID")

        def __init__(self, engine, ctx, wish_id, original_interaction):
            super().__init__()
            self.engine = engine
            self.ctx = ctx
            self.wish_id = wish_id
            self.original_interaction = original_interaction

        async def on_submit(self, itl: discord.Interaction):
            new_wish = await self.engine.admin_merge_wishes(
                self.ctx, self.wish_id, self.target_id.value)
            await self.original_interaction.message.edit(
                embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, self.ctx))
            await itl.response.send_message("✅ 已合并愿望。", ephemeral=True)


if typing.TYPE_CHECKING:
    from main import TicketBot


async def setup(bot: 'TicketBot'):
    """Cog的入口点。"""
    await bot.add_cog(WishSystemCog(bot))
