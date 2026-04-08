import typing

import discord
from discord import app_commands
from discord.ext import commands

import config
import config_data
from config_data import GuildWishConfig
from utility.feature_cog import FeatureCog
from .adapters import AsyncJsonWishRepository, DiscordWishAdapter
from .pray_core.engine import WishEngine, StateTransitionError
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
        """发起愿望：只负责弹出输入框，不负责逻辑校验"""
        user_ctx = self._get_user_context(interaction)
        engine = self._get_engine(interaction.guild_id)

        # 定义发起愿望的 Modal
        class CreateWishModal(discord.ui.Modal, title="许下你的愿望"):
            title_input = discord.ui.TextInput(label="标题 (一句话描述)", max_length=100)
            content_input = discord.ui.TextInput(label="详细内容", style=discord.TextStyle.paragraph)

            def __init__(self, outer_cog: 'WishSystemCog', outer_engine, outer_ctx):
                super().__init__()
                self.cog = outer_cog
                self.engine = outer_engine
                self.ctx = outer_ctx

            async def on_submit(self, m_interaction: discord.Interaction):
                try:
                    # 1. 核心逻辑交还给 Engine
                    # 引擎会根据 UserRole 决定它是 ActiveWish 还是进入 DiscussionWish (ADMIN_HELP)
                    # 引擎会检查 PermissionError
                    wish = await self.engine.create_wish(
                        self.ctx,
                        WishCategory.COMMUNITY,  # 默认分类，可根据需求增加 SelectMenu 选择分类
                        self.title_input.value,
                        self.content_input.value
                    )

                    # 2. 统一使用工厂生成 UI
                    # 如果 wish 是 DiscussionWish (例如管理组求助)，生成的 View 自动就会带上“认领”按钮
                    # 如果 wish 是 ActiveWish，自动带上“支持”按钮
                    embed = WishEmbed(wish)
                    view = WishUIFactory.build_view(wish, self.ctx)

                    # 3. 发送消息
                    guild_config = self.cog._configs.get(m_interaction.guild_id)
                    target_channel = self.cog.bot.get_channel(guild_config.wish_channel_id) if guild_config else m_interaction.channel

                    # 在目标频道发送正式卡片
                    await target_channel.send(embed=embed, view=view)
                    # 给用户一个回馈
                    await m_interaction.response.send_message(f"✅ 愿望发布成功！", ephemeral=True)

                except PermissionError as e:
                    await m_interaction.response.send_message(f"❌ 许愿失败: {e}", ephemeral=True)
                except Exception as e:
                    self.cog.logger.error(f"创建愿望时发生崩溃: {e}", exc_info=True)
                    if not m_interaction.response.is_done():
                        await m_interaction.response.send_message("🚨 系统内部错误", ephemeral=True)

        # 弹出 Modal
        await interaction.response.send_modal(CreateWishModal(self, engine, user_ctx))

    # ================= 全局组件交互路由 =================

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """统一分发按钮交互"""
        if interaction.type != discord.InteractionType.component: return
        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("wish:"): return

        _, action, wish_id = custom_id.split(":")
        engine = self._get_engine(interaction.guild_id)
        ctx = self._get_user_context(interaction)

        try:
            # 根据 custom_id 路由到不同的处理逻辑
            if action == "support":
                # 引擎会处理：是否是 ActiveWish？是否支持过？
                new_wish = await engine.support_wish(ctx, wish_id)
                await interaction.response.edit_message(
                    embed=WishEmbed(new_wish),
                    view=WishUIFactory.build_view(new_wish, ctx)
                )

            elif action == "claim":
                # 弹出 Modal 收集信息，具体的业务逻辑在 Modal 提交时调用引擎
                await self._show_claim_modal(interaction, engine, ctx, wish_id)

            elif action == "manage":
                await self._show_manage_panel(interaction, engine, ctx, wish_id)

        except (StateTransitionError, PermissionError, ValueError) as e:
            # 所有的业务校验错误统一处理
            await interaction.response.send_message(f"❌ 操作无法执行: {e}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"未知错误: {e}", exc_info=True)

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
        # 管理面板同样根据引擎返回的对象动态生成
        class ManageView(discord.ui.View):
            @discord.ui.button(label="撤回愿望", style=discord.ButtonStyle.danger)
            async def withdraw(self, itl: discord.Interaction, _):
                new_wish = await engine.withdraw_wish(ctx, wish_id)
                await interaction.message.edit(embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await itl.response.send_message("已关闭", ephemeral=True)

            @discord.ui.button(label="管理员：结算(通过)", style=discord.ButtonStyle.success)
            async def resolve_ok(self, itl: discord.Interaction, _):
                new_wish = await engine.admin_resolve_proposal(ctx, wish_id, True)
                await interaction.message.edit(embed=WishEmbed(new_wish), view=WishUIFactory.build_view(new_wish, ctx))
                await itl.response.send_message("结算完成", ephemeral=True)

        await interaction.response.send_message("管理面板", view=ManageView(), ephemeral=True)

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
