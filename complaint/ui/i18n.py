from __future__ import annotations

from typing import Literal

Locale = Literal["zh", "en"]

LOCALES: tuple[Locale, ...] = ("zh", "en")


def normalize_locale(value: str | None) -> Locale:
    """把配置或交互中传来的语言值收敛到受支持的 locale。"""
    return "en" if value == "en" else "zh"


_TEXTS: dict[str, dict[Locale, str]] = {
    # ===== 通用 =====
    "common.success_title": {"zh": "✅ 操作成功", "en": "✅ Success"},
    "common.error_title": {"zh": "❌ 操作失败", "en": "❌ Action Failed"},
    "common.not_in_guild": {"zh": "请在服务器内使用。", "en": "Please use this in a server."},
    "common.use_in_text_channel": {
        "zh": "请在文本频道内使用。",
        "en": "Please use this in a text channel.",
    },
    "common.operation_error": {
        "zh": "操作出错，请重试。",
        "en": "Something went wrong. Please try again.",
    },
    "common.operation_error_detail": {
        "zh": "操作出错：{error}",
        "en": "Something went wrong: {error}",
    },
    "common.unknown_type": {"zh": "未知类型", "en": "Unknown type"},

    # ===== 入口面板 =====
    "entry.title": {"zh": "📋 投诉中心", "en": "📋 Complaint Center"},
    "entry.description": {
        "zh": (
            "如果你在社区中遇到了问题，或对管理团队的工作有意见，可以通过本系统提交投诉或反馈。\n\n"
            "📌 **提交流程**\n"
            "1. 点击下方「提交投诉」按钮\n"
            "2. 选择投诉类型\n"
            "3. 填写投诉表单\n"
            "4. 系统将为你创建一个私密频道\n\n"
            "🔒 **隐私保护**\n"
            "仅你本人和对应处理组成员可见，其他用户无法查看你的投诉内容。"
        ),
        "en": (
            "If you have a problem in the community or feedback for the moderation team, "
            "you can submit a complaint or report through this system.\n\n"
            "📌 **How it works**\n"
            "1. Click the **Submit a Complaint** button below\n"
            "2. Choose a complaint type\n"
            "3. Fill out the complaint form\n"
            "4. The bot will create a private channel for you\n\n"
            "🔒 **Privacy**\n"
            "Only you and the relevant handling team can see your complaint. "
            "Other users cannot view its contents."
        ),
    },
    "entry.button": {"zh": "🔒 提交投诉", "en": "🔒 Submit a Complaint"},
    "entry.no_types": {
        "zh": "暂无可用的投诉类型。",
        "en": "No complaint types are currently available.",
    },
    "entry.no_channel": {"zh": "无法定位当前频道。", "en": "Could not determine the current channel."},
    "entry.no_permission": {
        "zh": "没有权限在当前频道发送消息。",
        "en": "I do not have permission to send messages in this channel.",
    },
    "entry.post_failed": {"zh": "发布失败：{error}", "en": "Failed to post: {error}"},
    "entry.posted": {
        "zh": "已在 {channel} 发布投诉入口面板。",
        "en": "Complaint entry panel posted in {channel}.",
    },

    # ===== 类型选择 =====
    "type_select.title": {"zh": "📋 选择投诉类型", "en": "📋 Choose a Complaint Type"},
    "type_select.intro": {
        "zh": "请根据你的需求选择最匹配的投诉类型。",
        "en": "Please choose the complaint type that best matches your needs.",
    },
    "type_select.placeholder": {"zh": "选择投诉类型...", "en": "Select a complaint type..."},
    "type_select.reselect": {"zh": "重新选择", "en": "Choose again"},
    "type_select.groups": {"zh": "处理组", "en": "Handled by"},
    "type_select.group_line": {
        "zh": "　　👁 处理组：{groups}",
        "en": "👁 Handled by: {groups}",
    },
    "type_select.no_groups": {"zh": "（无）", "en": "(none)"},
    "type_select.visible_groups_line": {
        "zh": "**可见管理组**：{groups}",
        "en": "**Visible team**: {groups}",
    },
    "type_select.confirm": {"zh": "✅ 确认", "en": "✅ Confirm"},
    "type_select.cancel": {"zh": "❌ 取消", "en": "❌ Cancel"},
    "type_select.click_confirm": {
        "zh": "点击 **确认** 开始填写投诉表单。",
        "en": "Click **Confirm** to fill out the complaint form.",
    },
    "type_select.not_found": {
        "zh": "投诉类型不存在，请重新选择。",
        "en": "That complaint type no longer exists. Please choose again.",
    },
    "type_select.cancelled": {"zh": "已取消选择。", "en": "Selection cancelled."},

    # ===== 二次确认 =====
    "confirm.title": {"zh": "⚠️ 确认提交", "en": "⚠️ Confirm Submission"},
    "confirm.intro": {
        "zh": "你即将提交一份 **{type}**。",
        "en": "You are about to submit a **{type}**.",
    },
    "confirm.bullets": {
        "zh": (
            "提交后系统将：\n"
            "• 创建一个仅你和对应处理组可见的私密频道\n"
            "• 通知相关处理组成员加入处理\n"
            "• 你可以在频道中与处理组直接沟通"
        ),
        "en": (
            "After submission, the bot will:\n"
            "• Create a private channel visible only to you and the handling team\n"
            "• Notify the relevant handling team members\n"
            "• Let you communicate directly with the team in that channel"
        ),
    },
    "confirm.visible_groups": {"zh": "👁 **可见处理组**：{groups}", "en": "👁 **Visible team**: {groups}"},
    "confirm.continue": {"zh": "确定要继续吗？", "en": "Do you want to continue?"},
    "confirm.submit": {"zh": "✅ 确认提交", "en": "✅ Submit"},
    "confirm.cancel": {"zh": "❌ 取消", "en": "❌ Cancel"},
    "confirm.cancelled": {"zh": "已取消提交。", "en": "Submission cancelled."},
    "confirm.type_missing": {
        "zh": "投诉类型不存在，请重新提交。",
        "en": "That complaint type no longer exists. Please submit again.",
    },
    "confirm.internal_type_lost": {
        "zh": "内部错误：投诉类型丢失。",
        "en": "Internal error: the complaint type is missing.",
    },
    "confirm.internal_config_lost": {
        "zh": "内部错误：配置丢失。",
        "en": "Internal error: the configuration is missing.",
    },

    # ===== 创建频道 =====
    "create.member_error": {
        "zh": "无法读取成员信息。",
        "en": "Could not read your member information.",
    },
    "create.creating": {"zh": "正在创建投诉频道...", "en": "Creating your complaint channel..."},
    "create.no_archive": {
        "zh": "未配置归档频道，请先使用 /{command_name} 配置服务器。",
        "en": "No archive channel is configured. Please ask an administrator to run /{command_name} to finish the bot configuration.",
    },
    "create.archive_unavailable": {
        "zh": "归档频道不可用，请检查配置。",
        "en": "The archive channel is unavailable. Please check the configuration.",
    },
    "create.failed": {"zh": "创建频道失败：{error}", "en": "Failed to create the channel: {error}"},
    "create.success": {
        "zh": "✅ 投诉频道已创建：{channel}（{ticket}）",
        "en": "✅ Complaint channel created: {channel} ({ticket})",
    },

    # ===== 管理面板 =====
    "manage.title": {"zh": "🛠️ 频道管理面板", "en": "🛠️ Ticket Management"},
    "manage.description": {
        "zh": (
            "本面板用于管理投诉频道的各项操作。\n\n"
            "• 📢 **召唤身份组**（仅管理员可用） — 邀请身份组加入本频道\n"
            "• 👤 **召唤用户**（管理员或处理组可用） — 邀请特定用户加入本频道\n"
            "• 🔀 **转接工单**（当前处理组成员或管理员可用） — 将工单转交给正确的投诉类型处理组\n"
            "• 🗑️ **关闭频道**（仅管理员可用） — 如果处理完毕，可以归档并关闭本投诉频道"
        ),
        "en": (
            "Use this panel to manage the complaint ticket.\n\n"
            "• 📢 **Add a Role** (administrators only) — Give a role access to this channel\n"
            "• 👤 **Add a User** (administrators or handling team) — Invite a specific user to this channel\n"
            "• 🔀 **Transfer Ticket** (handling team or administrators) — Move this ticket to the correct team\n"
            "• 🗑️ **Close Channel** (administrators only) — Archive and close this ticket when resolved"
        ),
    },
    "manage.summon_role": {"zh": "📢 召唤身份组", "en": "📢 Add a Role"},
    "manage.summon_user": {"zh": "👤 召唤用户", "en": "👤 Add a User"},
    "manage.transfer": {"zh": "🔀 转接工单", "en": "🔀 Transfer Ticket"},
    "manage.close": {"zh": "🗑️ 关闭频道", "en": "🗑️ Close Channel"},
    "manage.admin_only": {"zh": "仅管理员可使用此功能。", "en": "Administrators only."},
    "manage.admin_or_handler": {
        "zh": "仅管理员或当前工单处理组可使用此功能。",
        "en": "Administrators or the current handling team only.",
    },
    "manage.not_ticket_channel": {
        "zh": "当前频道不是投诉频道。",
        "en": "This channel is not a complaint ticket.",
    },
    "manage.use_in_ticket": {
        "zh": "请在投诉频道中使用。",
        "en": "Please use this in a complaint ticket.",
    },
    "manage.close_admin_only": {
        "zh": "仅管理员可关闭此频道。",
        "en": "Only administrators can close this channel.",
    },
    "manage.transfer_admin_or_handler": {
        "zh": "仅管理员或当前工单处理组可转接工单。",
        "en": "Only administrators or the current handling team can transfer this ticket.",
    },
    "manage.resent": {
        "zh": "✅ 管理面板已重新发送。",
        "en": "✅ Management panel re-sent.",
    },

    # ===== 归档 =====
    "archive.title": {"zh": "⚠️ 确认归档", "en": "⚠️ Confirm Archive"},
    "archive.description": {
        "zh": (
            "由 {operator} 发起\n\n"
            "此操作将对本投诉频道执行归档（管理员或处理组可操作）：\n"
            "• 导出频道内所有消息为归档文件并保存\n"
            "• 归档文件将发送至归档频道永久保存\n"
            "• 归档完成后，可选择删除本频道\n\n"
            "⚠️ 归档后频道内容将无法恢复，请确认所有问题已处理完毕。\n\n"
            "确定要继续吗？"
        ),
        "en": (
            "Started by {operator}\n\n"
            "This will archive the complaint ticket:\n"
            "• Export all messages in this channel to an archive file\n"
            "• Send the archive to the archive channel for permanent storage\n"
            "• After archiving, you can choose to delete this channel\n\n"
            "⚠️ Archived content cannot be restored. Please make sure the ticket is fully resolved.\n\n"
            "Do you want to continue?"
        ),
    },
    "archive.confirm": {"zh": "📦 归档频道", "en": "📦 Archive Channel"},
    "archive.admin_only": {
        "zh": "仅管理员可执行此操作。",
        "en": "Only administrators can perform this action.",
    },
    "archive.cancel": {"zh": "❌ 取消", "en": "❌ Cancel"},
    "archive.success_title": {"zh": "✅ 归档完成", "en": "✅ Archive Complete"},
    "archive.success_description": {
        "zh": (
            "本频道的所有消息已成功导出为归档文件，并发送至归档频道保存。\n\n"
            "📎 [查看归档]({url})\n\n"
            "管理员或处理组可点击下方按钮删除本频道，或保留以备后续参考。"
        ),
        "en": (
            "All messages in this channel have been exported and sent to the archive channel.\n\n"
            "📎 [View archive]({url})\n\n"
            "An administrator or handler can delete this channel below, or keep it for reference."
        ),
    },
    "archive.failed": {"zh": "归档失败：{error}", "en": "Archive failed: {error}"},
    "archive.cancelled": {"zh": "已取消归档操作。", "en": "Archive cancelled."},
    "archive.delete": {"zh": "🗑️ 删除频道", "en": "🗑️ Delete Channel"},
    "archive.delete_cancel": {"zh": "❌ 取消", "en": "❌ Cancel"},
    "archive.delete_admin_only": {
        "zh": "仅管理员可删除此频道。",
        "en": "Only administrators can delete this channel.",
    },
    "archive.delete_cancelled": {"zh": "已取消删除操作。", "en": "Deletion cancelled."},
    "delete.confirm": {"zh": "✅ 确认删除频道", "en": "✅ Confirm Delete"},
    "delete.admin_only": {
        "zh": "仅管理员可执行此操作。",
        "en": "Only administrators can perform this action.",
    },
    "delete.countdown": {
        "zh": "频道将在 {seconds} 秒后删除...",
        "en": "This channel will be deleted in {seconds} seconds...",
    },
    "delete.failed": {"zh": "删除频道失败：{error}", "en": "Failed to delete the channel: {error}"},

    # ===== 召唤身份组 / 用户 =====
    "summon.role_title": {"zh": "📢 召唤身份组", "en": "📢 Add a Role"},
    "summon.role_description": {
        "zh": (
            "选择要邀请到本频道的身份组。\n\n"
            "被选中的身份组的所有成员将被：\n"
            "• 添加到频道权限，可以查看和发送消息\n\n"
            "⚠️ 为避免骚扰大量成员，不会发送 @mention 通知。\n"
            "如有需要，请手动 @ 相关人员。"
        ),
        "en": (
            "Choose the role to invite to this channel.\n\n"
            "All members with the selected role will be able to:\n"
            "• View the channel and send messages\n\n"
            "⚠️ To avoid mass mentions, no @mention notification will be sent.\n"
            "Mention the relevant people manually if needed."
        ),
    },
    "summon.role_placeholder": {
        "zh": "选择要召唤的身份组...",
        "en": "Select a role to add...",
    },
    "summon.role_confirm": {"zh": "✅ 确认召唤", "en": "✅ Confirm"},
    "summon.role_cancelled": {"zh": "已取消召唤身份组。", "en": "Role invitation cancelled."},
    "summon.user_title": {"zh": "👤 召唤用户", "en": "👤 Add a User"},
    "summon.user_description": {
        "zh": (
            "选择要邀请到本频道的用户，最多可选择 10 位。\n\n"
            "被选中的用户将被：\n"
            "• 添加到频道权限，可以查看和发送消息\n"
            "• 收到加入通知"
        ),
        "en": (
            "Choose up to 10 users to invite to this channel.\n\n"
            "Selected users will be able to:\n"
            "• View the channel and send messages\n"
            "• Receive a notification that they were added"
        ),
    },
    "summon.user_placeholder": {
        "zh": "选择要召唤的用户...",
        "en": "Select users to add...",
    },
    "summon.user_selected": {"zh": "已选择：{names}", "en": "Selected: {names}"},
    "summon.user_confirm": {"zh": "✅ 确认召唤", "en": "✅ Confirm"},
    "summon.user_cancelled": {"zh": "已取消召唤用户。", "en": "User invitation cancelled."},

    # ===== 工单通知 =====
    "notify.title": {"zh": "🔔 新工单通知", "en": "🔔 New Ticket"},
    "notify.type": {"zh": "类型", "en": "Type"},
    "notify.ticket_number": {"zh": "工单编号", "en": "Ticket number"},
    "notify.complainant": {"zh": "投诉人", "en": "Complainant"},
    "notify.channel": {"zh": "频道", "en": "Channel"},

    # ===== 未配置责任提示 =====
    "responsibility.unconfigured": {
        "zh": (
            "⚠️ **未配置**：admin 未在 toml 中设置责任提示文案"
            "（`templates.default_responsibility_notice` 或 `[[types]].responsibility_notice`），"
            "请联系管理员。"
        ),
        "en": (
            "⚠️ **Not configured**: the administrator has not set a responsibility notice in the toml "
            "(`templates.default_responsibility_notice` or `[[types]].responsibility_notice`). "
            "Please contact an administrator."
        ),
    },
}


def t(locale: str | None, key: str, **kwargs: object) -> str:
    """按 locale 取文案；缺翻译时回退中文，保证旧配置不会显示空文本。"""
    normalized = normalize_locale(locale)
    variants = _TEXTS[key]
    text = variants.get(normalized) or variants["zh"]
    return text.format(**kwargs) if kwargs else text


def translation_keys() -> tuple[str, ...]:
    """供测试/自检遍历全部文案键。"""
    return tuple(_TEXTS)
