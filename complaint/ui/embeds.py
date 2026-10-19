from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from complaint.ui.i18n import normalize_locale, t

if TYPE_CHECKING:
    from complaint.config.models import ComplaintTypeConfig, ComplaintConfig


def build_entry_embed(locale: str = "zh") -> discord.Embed:
    """构建投诉入口面板的 Embed。"""
    return discord.Embed(
        title=t(locale, "entry.title"),
        description=t(locale, "entry.description"),
        color=0x5865F2,
    )


def resolve_responsibility_notice(
    config: "ComplaintConfig",
    type_config: "ComplaintTypeConfig",
    locale: str = "zh",
) -> str:
    """二次确认的责任/敏感提示文案。

    优先级：type 自身 → templates 默认 → 未配置提示。
    最后一项**不是合理默认值**——是 fail-loud 的"未配置"指示器，
    让 admin 看到 bot 在跑这条提示时主动去补配置。
    """
    if normalize_locale(locale) == "en":
        return (
            type_config.responsibility_notice_en.strip()
            or config.templates.default_responsibility_notice_en.strip()
            or t("en", "responsibility.unconfigured")
        )
    return (
        type_config.responsibility_notice.strip()
        or config.templates.default_responsibility_notice.strip()
        or t("zh", "responsibility.unconfigured")
    )


def _collect_target_group_labels(
    config: "ComplaintConfig",
    type_config: "ComplaintTypeConfig",
    locale: str,
) -> list[str]:
    """收集 type_config.target_role_groups 对应的身份组 label。"""
    labels: list[str] = []
    for gid in type_config.target_role_groups:
        group = config.role_groups.get(gid)
        if group:
            labels.append(group.localized_label(locale))
    return labels


def build_type_select_embed(config: ComplaintConfig, locale: str = "zh") -> discord.Embed:
    """构建投诉类型选择面板的 Embed，列出所有可选类型及其可见处理组。"""
    lines = [f"{t(locale, 'type_select.intro')}\n"]
    separator = ", " if normalize_locale(locale) == "en" else "、"
    for ct in config.types:
        group_labels = _collect_target_group_labels(config, ct, locale)
        groups_text = separator.join(group_labels) if group_labels else t(
            locale, "type_select.no_groups",
        )
        emoji_prefix = f"{ct.emoji} " if ct.emoji else ""
        line = f"{emoji_prefix}**{ct.localized_label(locale)}**"
        description = ct.localized_description(locale)
        if description:
            line += f" — {description}"
        lines.append(f"{line}\n{t(locale, 'type_select.group_line', groups=groups_text)}")
    return discord.Embed(
        title=t(locale, "type_select.title"),
        description="\n\n".join(lines),
        color=0x5865F2,
    )


def build_confirm_embed(
    config: ComplaintConfig,
    type_config: ComplaintTypeConfig,
    locale: str = "zh",
) -> discord.Embed:
    """构建提交前二次确认的 Embed，列出可见处理组 + 责任/敏感提示文案。"""
    group_labels = _collect_target_group_labels(config, type_config, locale)
    separator = ", " if normalize_locale(locale) == "en" else "、"
    groups_text = separator.join(group_labels) if group_labels else t(
        locale, "type_select.no_groups",
    )
    notice_text = resolve_responsibility_notice(config, type_config, locale)
    type_name = type_config.localized_label(locale)
    if type_config.emoji:
        type_name = f"{type_config.emoji} {type_name}"

    return discord.Embed(
        title=t(locale, "confirm.title"),
        description=(
            f"{t(locale, 'confirm.intro', type=type_name)}\n\n"
            f"{t(locale, 'confirm.bullets')}\n\n"
            f"{t(locale, 'confirm.visible_groups', groups=groups_text)}\n\n"
            f"{notice_text}\n\n"
            f"{t(locale, 'confirm.continue')}"
        ),
        color=0xFEE75C,
    )


def build_manage_panel_embed(locale: str = "zh") -> discord.Embed:
    """构建频道管理面板的 Embed。"""
    return discord.Embed(
        title=t(locale, "manage.title"),
        description=t(locale, "manage.description"),
        color=0x5865F2,
    )


def build_archive_confirm_embed(
    operator_mention: str,
    locale: str = "zh",
) -> discord.Embed:
    """构建归档确认的 Embed，可选标注操作人。"""
    return discord.Embed(
        title=t(locale, "archive.title"),
        description=t(locale, "archive.description", operator=operator_mention),
        color=0xED4245,
    )


def build_archive_success_embed(archive_url: str, locale: str = "zh") -> discord.Embed:
    """构建归档成功的 Embed，包含跳转链接。"""
    return discord.Embed(
        title=t(locale, "archive.success_title"),
        description=t(locale, "archive.success_description", url=archive_url),
        color=0x57F287,
    )


def build_summon_embed(locale: str = "zh") -> discord.Embed:
    """构建召唤身份组面板的 Embed。"""
    return discord.Embed(
        title=t(locale, "summon.role_title"),
        description=t(locale, "summon.role_description"),
        color=0x5865F2,
    )


def build_summon_user_embed(locale: str = "zh") -> discord.Embed:
    """构建召唤用户面板的 Embed。"""
    return discord.Embed(
        title=t(locale, "summon.user_title"),
        description=t(locale, "summon.user_description"),
        color=0x5865F2,
    )


def build_success_embed(message: str, locale: str = "zh") -> discord.Embed:
    """构建通用成功提示的 Embed。"""
    return discord.Embed(
        title=t(locale, "common.success_title"),
        description=message,
        color=0x57F287,
    )


def build_error_embed(message: str, locale: str = "zh") -> discord.Embed:
    """构建通用错误提示的 Embed。"""
    return discord.Embed(
        title=t(locale, "common.error_title"),
        description=message,
        color=0xED4245,
    )


def build_notify_embed(
    *,
    type_label: str,
    type_emoji: str,
    ticket_number: int,
    channel_mention: str,
    complainant_name: str,
    locale: str = "zh",
) -> discord.Embed:
    """构建工单创建通知 Embed。"""
    return discord.Embed(
        title=t(locale, "notify.title"),
        color=0x5865F2,
    ).add_field(
        name=t(locale, "notify.type"),
        value=f"{type_emoji} {type_label}",
        inline=True,
    ).add_field(
        name=t(locale, "notify.ticket_number"),
        value=str(ticket_number),
        inline=True,
    ).add_field(
        name=t(locale, "notify.complainant"),
        value=complainant_name,
        inline=True,
    ).add_field(
        name=t(locale, "notify.channel"),
        value=channel_mention,
        inline=False,
    )
