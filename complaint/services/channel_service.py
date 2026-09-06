from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from complaint.ui.embeds import build_manage_panel_embed
from utility.helpers import try_get_member
from utility.message import send_message

if TYPE_CHECKING:
    from complaint.ComplaintCog import ComplaintCog
    from complaint.config.models import ComplaintConfig, ComplaintTypeConfig

logger = logging.getLogger(__name__)

TICKET_PREFIX = "工单"
"""工单编号前缀，用于频道名和显示文本。"""

# 【PR1新增】从表单字段值中解析用户 ID：支持 <@ID> / <@!ID> 提及与纯数字 ID，逗号/中文逗号分隔。
_USER_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")


def parse_user_ids_from_text(text: str) -> list[int]:
    """【PR1新增】从任意文本解析用户 ID 列表（提及与纯数字 ID 并收集，去重保序）。"""
    if not text:
        return []
    ids: list[int] = []
    for match in _USER_MENTION_PATTERN.finditer(text):
        ids.append(int(match.group(1)))
    for part in re.split(r"[,，\s]+", text):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return list(dict.fromkeys(ids))


async def resolve_member_by_name(guild: discord.Guild, text: str) -> tuple[discord.Member | None, str]:
    """【PR1新增】按用户名/显示名/昵称解析成员（表单填纯名字时的兜底）。

    返回 (member, 说明)；member 为 None 时说明给出原因（无命中/歧义）。
    匹配规则：用户名精确 > 显示名/昵称精确，大小写不敏感；多命中视为歧义不猜。
    """
    name = text.strip().lstrip("@").split("#")[0].strip()
    if not name:
        return None, "空文本"
    # members intent 已启用；若启动分块尚未完成则补一次
    if not guild.chunked:
        try:
            await guild.chunk()
        except discord.HTTPException:
            logger.warning("成员列表分块失败，将基于当前缓存匹配")
    lowered = name.lower()
    by_username = [m for m in guild.members if (m.name or "").lower() == lowered]
    if len(by_username) == 1:
        return by_username[0], "用户名精确匹配"
    by_display = [m for m in guild.members if (m.display_name or "").lower() == lowered]
    if len(by_display) == 1:
        return by_display[0], "显示名/昵称精确匹配"
    count = max(len(by_username), len(by_display))
    if count > 1:
        return None, f"匹配到 {count} 个同名成员，歧义无法确定（请改用 @ 提及）"
    return None, None


_MESSAGE_LINK_RE = re.compile(
    r"(?:https?://)?(?:[a-z]+\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)(?:/(\d+))?",
    re.IGNORECASE,
)


def parse_message_link(link: str) -> tuple[int, int, int] | None:
    """【PR1新增】解析 Discord 消息/频道链接 → (guild_id, channel_id, message_id)。

    message_id 为 0 表示纯频道/帖子链接（无消息段）；无法解析返回 None。
    兼容 discord.com / ptb.discord.com / canary.discord.com / discordapp.com。
    """
    m = _MESSAGE_LINK_RE.search(link or "")
    if not m:
        return None
    gid, cid, mid = m.group(1), m.group(2), m.group(3)
    return int(gid), int(cid), int(mid) if mid else 0


_PROPOSER_MARK_RE = re.compile(r"提案人\s*[:：]?\s*<@!?(\d+)>")
_ANY_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _clean_thread_title(name: str) -> str:
    """【PR1新增】去掉讨论帖名的状态前缀（如「[讨论中] xxx」→「xxx」）。"""
    name = (name or "").strip()
    cleaned = re.sub(r"^\[[^\]]+\]\s*", "", name)
    return cleaned or name


def _extract_proposer_id(text: str) -> int | None:
    """【PR1新增】从首楼文字解析提案人 ID。

    优先「提案人: <@ID>」标记行（StellariaPact 讨论帖固定模板），
    兜底取文中第一个用户提及。返回 None 表示首楼没有提及。
    """
    m = _PROPOSER_MARK_RE.search(text or "")
    if m:
        return int(m.group(1))
    m = _ANY_MENTION_RE.search(text or "")
    if m:
        return int(m.group(1))
    return None


async def resolve_proposal_link(
    bot: discord.Client,
    guild: discord.Guild,
    link: str,
) -> tuple[str, str]:
    """【PR1新增】从 Discord 链接读取提案标题与提案人。

    规则（按链接目标类型）：
    - 帖子（论坛帖/线程）→ 标题 = 帖子名（去状态前缀），提案人 = 首楼
      「提案人: <@ID>」标记；无标记时回落 链接消息作者/楼主/首楼作者（跳过 Bot）。
      注意：真实提案讨论帖的首楼由提案 BOT 按固定模板发布，楼主是 Bot 本身，
      提案人必须从首楼文字解析，不能直接用楼主。
    - 普通文字频道消息 → 标题 = 消息首行，提案人 = 消息作者。
    - 纯频道链接（无消息 ID）→ 取频道最早一条消息按上规则处理。
    返回 (title, proposer_text)；解析失败返回 ("", "")。
    proposer_text 优先 <@ID> 提及（可直接用于推送/召唤），否则回落用户名
    （由 resolve_member_by_name 兜底解析）。
    """
    parsed = parse_message_link(link)
    if parsed is None:
        logger.warning("提案链接无法解析: %r", link)
        return "", ""
    gid, cid, mid = parsed
    if gid != guild.id:
        logger.warning("提案链接不属于本服务器（链接 guild=%s）: %r", gid, link)
        return "", ""
    try:
        channel = guild.get_channel_or_thread(cid) or await bot.fetch_channel(cid)
    except discord.HTTPException as e:
        logger.warning("提案链接频道不可达 (channel=%s): %s", cid, e)
        return "", ""

    message = None
    if mid:
        try:
            message = await channel.fetch_message(mid)  # type: ignore[union-attr]
        except discord.HTTPException as e:
            logger.warning("提案链接消息不可达 (message=%s): %s", mid, e)

    # --- 首楼：帖子场景提案信息以首楼为准（链接可能指向中间楼层） ---
    first_message = message
    if isinstance(channel, discord.Thread):
        first_message = None
        try:
            first_message = await channel.fetch_message(channel.id)
        except discord.HTTPException:
            try:
                async for m in channel.history(limit=1, oldest_first=True):
                    first_message = m
                    break
            except discord.HTTPException as e:
                logger.warning("读取帖子首楼失败 (%s): %s", channel.id, e)
    elif message is None:
        # 纯频道链接：取最早一条消息
        try:
            async for m in channel.history(limit=1, oldest_first=True):  # type: ignore[union-attr]
                first_message = m
                break
        except discord.HTTPException as e:
            logger.warning("读取频道首条消息失败 (%s): %s", cid, e)

    first_content = getattr(first_message, "content", "") or ""

    # --- 提案人：首楼标记 > 首楼/消息首个提及 > 人类作者兜底（跳过 Bot） ---
    proposer_id = _extract_proposer_id(first_content)
    if proposer_id is None and message is not None:
        proposer_id = _extract_proposer_id(message.content or "")
    proposer = ""
    if proposer_id is not None:
        proposer = f"<@{proposer_id}>"
    else:
        candidates: list[discord.abc.User] = []
        if message is not None and not message.author.bot:
            candidates.append(message.author)
        starter_id = getattr(channel, "starter_id", None)
        starter = guild.get_member(starter_id) if starter_id else None
        if starter is not None and not starter.bot:
            candidates.append(starter)
        if first_message is not None and not first_message.author.bot:
            candidates.append(first_message.author)
        if candidates:
            c = candidates[0]
            proposer = c.mention if isinstance(c, discord.Member) else c.name

    # --- 标题：帖子名（去前缀）> 消息首行 > embed 标题 ---
    title = ""
    if isinstance(channel, discord.Thread):
        title = _clean_thread_title(channel.name or "")
    elif message is not None:
        for line in (message.content or "").splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                title = line[:80]
                break
    if not title and first_message is not None:
        for line in first_content.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                title = line[:80]
                break
        if not title and first_message.embeds:
            title = (first_message.embeds[0].title or "").strip()[:80]

    return title, proposer


def ticket_display(number: int) -> str:
    """将编号格式化为显示用的工单标识（如 "工单-1"）。"""
    return f"{TICKET_PREFIX}-{number}"


def parse_ticket_from_name(channel_name: str) -> int | None:
    """从频道名中解析工单编号，解析失败返回 None。"""
    prefix = f"{TICKET_PREFIX}-"
    if channel_name.startswith(prefix):
        try:
            return int(channel_name[len(prefix):])
        except ValueError:
            return None
    return None


def sanitize_channel_name(name: str) -> str:
    """清理字符串使其符合 Discord 频道名要求。"""
    name = re.sub(r"[^a-zA-Z0-9一-鿿_-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name[:90]


async def create_complaint_channel(
    cog: ComplaintCog,
    guild: discord.Guild,
    complainant: discord.Member,
    type_config: ComplaintTypeConfig,
    form_data: dict[str, str],
    full_config: ComplaintConfig,
    ticket_number: int,
) -> discord.TextChannel:
    """创建投诉频道、设置权限、发送初始消息和管理面板。"""
    from complaint.services.channel_meta import ComplaintChannelMeta
    from complaint.ui.views import ManagePanelView

    category_id = full_config.get_effective_category_id(type_config.id)
    if not category_id:
        raise RuntimeError("未配置投诉分类，请先使用 /投诉管理 配置服务器")

    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        raise RuntimeError("投诉分类频道不可用")

    target_role_ids = full_config.get_all_role_ids_for_groups(type_config.target_role_groups)

    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            read_message_history=False,
        ),
    }

    bot_member = guild.me
    overwrites[bot_member] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        manage_channels=True,
        read_message_history=True,
        attach_files=True,
    )

    overwrites[complainant] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
    )

    for role_id in target_role_ids:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
        else:
            logger.warning("角色 %s 在服务器 %s 中不存在，跳过权限设置", role_id, guild.id)

    # 【PR1新增】从指定表单字段解析用户并自动授予频道权限（如"提案人"字段）
    for field_key in type_config.auto_summon_form_fields:
        raw_value = ((form_data or {}).get(field_key) or "").strip()
        if not raw_value:
            continue
        user_ids = parse_user_ids_from_text(raw_value)
        if not user_ids:
            # 【PR1修复】纯名字输入：按用户名/显示名解析成员，唯一命中则
            # 改写表单值为 @提及（头部消息可推送 + 存档归一），并完成召唤。
            member, how = await resolve_member_by_name(guild, raw_value)
            if member is None:
                logger.warning(
                    "表单字段 %s 的值 %r 无法解析为用户（%s），跳过自动召唤",
                    field_key, raw_value, how or "无命中",
                )
                continue
            user_ids = [member.id]
            if form_data is not None:
                form_data[field_key] = member.mention
            logger.info(
                "表单字段 %s 的值 %r 按%s解析为成员 %s，已改写为 @提及",
                field_key, raw_value, how, member.id,
            )
        for user_id in user_ids:
            if user_id == complainant.id:
                continue  # 投诉人已授权，跳过
            summoned_member = await try_get_member(guild, user_id)
            if summoned_member is not None:
                overwrites[summoned_member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )
                logger.info(
                    "已自动召唤用户 %s（来源表单字段 %s）进入频道",
                    user_id, field_key,
                )
            else:
                logger.warning(
                    "表单字段 %s 中的用户 %s 不在本服务器，跳过自动召唤", field_key, user_id,
                )

    channel_name = sanitize_channel_name(ticket_display(ticket_number))

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"创建投诉频道 {ticket_display(ticket_number)}",
    )

    meta = ComplaintChannelMeta(
        complainant_id=complainant.id,
        type_id=type_config.id,
        form_data=form_data,
    )
    cog.channel_manager.register_channel(guild.id, channel.id, meta)
    await cog.channel_manager.save_data()

    header_content = _render_header(
        type_config=type_config,
        complainant=complainant,
        form_data=form_data,
        templates=full_config.templates,
        ticket_number=ticket_number,
        full_config=full_config,
        guild=guild,
    )
    await send_message(
        channel,
        content=header_content,
        allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
    )

    manage_view = ManagePanelView(cog)
    await send_message(channel, embed=build_manage_panel_embed(), view=manage_view)
    cog.bot.add_view(manage_view)

    logger.info(
        "已创建投诉频道 %s (类型: %s, 投诉人: %s)",
        channel.name, type_config.id, complainant.id,
    )

    return channel


async def transfer_complaint_channel(
    *,
    cog: ComplaintCog,
    guild: discord.Guild,
    channel: discord.TextChannel,
    operator: discord.abc.User,
    full_config: "ComplaintConfig",
    new_type_id: str,
) -> tuple["ComplaintTypeConfig" | None, "ComplaintTypeConfig"]:
    """将投诉频道转接到新的投诉类型，并差量更新目标身份组权限。"""
    meta = cog.channel_manager.get_channel_meta(guild.id, channel.id)
    if meta is None:
        raise RuntimeError("当前频道不是投诉频道。")

    old_type = full_config.get_complaint_type(meta.type_id)
    new_type = full_config.get_complaint_type(new_type_id)
    if new_type is None:
        raise RuntimeError("目标投诉类型不存在。")
    if old_type and old_type.id == new_type.id:
        raise RuntimeError("当前工单已经属于该投诉类型。")

    old_role_ids = set(full_config.get_type_target_role_ids(old_type))
    new_role_ids = set(full_config.get_type_target_role_ids(new_type))

    for role_id in sorted(old_role_ids - new_role_ids):
        role = guild.get_role(role_id)
        if role is None:
            logger.warning("转接时旧类型角色 %s 不存在，跳过移除权限", role_id)
            continue
        await channel.set_permissions(
            role,
            overwrite=None,
            reason=f"投诉工单转接：移除旧处理组 ({operator})",
        )

    for role_id in sorted(new_role_ids - old_role_ids):
        role = guild.get_role(role_id)
        if role is None:
            logger.warning("转接时新类型角色 %s 不存在，跳过授予权限", role_id)
            continue
        await channel.set_permissions(
            role,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            reason=f"投诉工单转接：加入新处理组 ({operator})",
        )

    meta.type_id = new_type.id
    await cog.channel_manager.save_data()

    logger.info(
        "投诉频道 %s 已转接: %s -> %s (operator=%s)",
        channel.id,
        old_type.id if old_type else "unknown",
        new_type.id,
        operator.id,
    )
    return old_type, new_type


def _render_header(
    *,
    type_config: ComplaintTypeConfig,
    complainant: discord.Member,
    form_data: dict[str, str],
    templates: "TemplateConfig",
    ticket_number: int,
    full_config: ComplaintConfig,
    guild: discord.Guild,
) -> str:
    """根据模板渲染频道头部消息。"""
    from complaint.config.models import TemplateConfig  # noqa

    timestamp = f"<t:{int(datetime.now().timestamp())}:f>"

    form_section = ""
    if form_data:
        lines = []
        for field in type_config.form_fields:
            value = form_data.get(field.key, "")
            if value:
                lines.append(templates.form_field_format.format(label=field.label, value=value))
        form_section = "\n".join(lines)

    custom_section = _render_header_blocks(
        header_blocks=type_config.header_blocks,
        full_config=full_config,
        guild=guild,
        type_config=type_config,
        ticket_number=ticket_number,
    )

    # 【PR1新增】类型级模板优先，回退 guild 级
    template = full_config.get_effective_header_template(type_config.id)

    # 【PR1修复】渲染顺序：先 str.format() 处理内置具名占位符（此时模板中的
    # {@group} / {form:key} 宏还没被展开，但它们不是合法 format 字段名，
    # 会抛 KeyError——所以先把这两类宏临时转义为 {{...}}，format 完成后
    # 还原为 {..} 再展开。表单值后注入，天然规避值中花括号问题。
    _PR1_MACRO = re.compile(r"\{(@[^}]*|form:[^}]*)\}")

    escaped = _PR1_MACRO.sub(lambda m: "{{" + m.group(1) + "}}", template)

    # 【PR1修复】宏注入防护：表单值（form_section）在 format 阶段进入头部消息，
    # 若用户在表单里手打 "{@组名}"，会在下方宏展开阶段被渲染成真实角色 @，
    # 构成 @广播滥用面。先扫描「模板原文不含、仅来自表单值」的宏并将其
    # 中性化为全角花括号（视觉可辨、不再匹配宏语法）。
    template_macros = set(_PR1_MACRO.findall(template))
    for field_key, field_value in (form_data or {}).items():
        for injected in set(_PR1_MACRO.findall(field_value or "")) - template_macros:
            safe = "｛" + injected + "｝"
            form_section = form_section.replace("{" + injected + "}", safe)
            # 同步改写 form_data，防止 {form:key} 宏路径二次注入
            field_value = (field_value or "").replace("{" + injected + "}", safe)
            form_data[field_key] = field_value

    header_text = escaped.format(
        complainant_mention=complainant.mention,
        type_label=type_config.label,
        type_emoji=type_config.emoji,
        timestamp=timestamp,
        form_section=form_section,
        ticket_number=ticket_number,
        custom_section=custom_section,
    )

    # 还原宏并展开 {@group}（@→角色组 mention，复用 header_blocks 的解析逻辑）
    def _replace_group_macro(match: re.Match[str]) -> str:
        key = match.group(1)
        if not key.startswith("@"):
            return match.group(0)  # 【PR1修复】{form:...} 等非@宏原样保留，交给下一步替换
        group = full_config.role_groups.get(key[1:])
        if not group:
            return ""
        mentions: list[str] = []
        for rid in group.role_ids:
            role = guild.get_role(rid)
            if role:
                mentions.append(role.mention)
        return " ".join(mentions)

    header_text = _MACRO_PATTERN.sub(_replace_group_macro, header_text)

    # 展开 {form:key} 宏 → 表单值（后注入，值中的 { } 不会再被解析）
    for field_key, field_value in (form_data or {}).items():
        header_text = header_text.replace(f"{{form:{field_key}}}", field_value)

    return header_text


# header_blocks 支持的宏：{@group_id} → 角色组 mention，
# {type_label} → 类型名，{type_emoji} → 类型 emoji，{ticket_number} → 工单编号。
_MACRO_PATTERN = re.compile(r"\{([^}]+)\}")


def _render_header_blocks(
    *,
    header_blocks: list[str],
    full_config: ComplaintConfig,
    guild: discord.Guild,
    type_config: ComplaintTypeConfig,
    ticket_number: int,
) -> str:
    """将 header_blocks 中的宏替换为实际内容，返回拼接后的文本。"""
    if not header_blocks:
        return ""

    # 纯文本宏，直接查表替换
    static_macros: dict[str, str] = {
        "type_label": type_config.label,
        "type_emoji": type_config.emoji,
        "ticket_number": str(ticket_number),
    }

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        # {@group_id} → 解析角色组并拼接角色 mention
        if key.startswith("@"):
            group_id = key[1:]
            group = full_config.role_groups.get(group_id)
            if not group:
                return ""
            mentions: list[str] = []
            for rid in group.role_ids:
                role = guild.get_role(rid)
                if role:
                    mentions.append(role.mention)
            return " ".join(mentions)
        # 纯文本宏
        return static_macros.get(key, "")

    rendered = []
    for block in header_blocks:
        rendered.append(_MACRO_PATTERN.sub(_replace, block))
    return "\n".join(rendered)


def render_notify_message(
    *,
    notify_message: str,
    full_config: ComplaintConfig,
    guild: discord.Guild,
    type_config: ComplaintTypeConfig,
    ticket_number: int,
    complainant: discord.Member,
    channel: discord.TextChannel,
) -> str:
    """将 notify_message 中的宏替换为实际内容并返回。"""
    if not notify_message:
        return ""

    static_macros: dict[str, str] = {
        "type_label": type_config.label,
        "type_emoji": type_config.emoji,
        "ticket_number": str(ticket_number),
        "complainant": complainant.mention,
        "channel": channel.mention,
    }

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key.startswith("@"):
            group_id = key[1:]
            group = full_config.role_groups.get(group_id)
            if not group:
                return ""
            mentions: list[str] = []
            for rid in group.role_ids:
                role = guild.get_role(rid)
                if role:
                    mentions.append(role.mention)
            return " ".join(mentions)
        return static_macros.get(key, "")

    return _MACRO_PATTERN.sub(_replace, notify_message)

