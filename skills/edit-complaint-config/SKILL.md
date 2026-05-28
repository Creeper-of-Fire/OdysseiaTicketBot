# 投诉配置编辑指南

## 操作流程

收到用户发来的 TOML 配置文件后，**先不要动手编辑**。先向用户确认：

1. 你想对配置做什么操作？例如：
   - 新增 / 删除 / 修改一个投诉类型（`[[types]]`）
   - 新增 / 删除 / 修改一个身份组（`[role_groups.*]`）
   - 修改服务器频道设置（`[guild]`）
   - 修改全局运行参数（`[global]`）
   - 修改消息模板（`[templates]`）
   - 其他
2. 涉及 Discord ID（频道 ID、角色 ID）时，向用户索要具体数值，不要自行编造。
3. 确认清楚后再读取当前配置、理解现有内容、执行编辑。

## 结构

```toml
[guild]                          # 服务器频道设置
[global]                         # 全局运行参数
[templates]                      # 消息模板
[role_groups.{id}]               # 身份组定义（可多个）
[[types]]                        # 投诉类型定义（数组，每项一个 [[types]]）
```

## 各段字段详解

### `[guild]` — 服务器频道设置

- **`category_id`** (`int`)：投诉频道创建在哪个 Discord 分类频道下。用户提交投诉后，系统会在该分类下创建一个新的文字频道。
- **`archive_channel_id`** (`int`)：投诉处理完毕后，归档记录发送到哪个文字频道。同时这个频道也用于存储工单编号计数器。

### `[global]` — 全局运行参数

- **`archive_concurrent_limit`** (`int`，默认 `2`)：同时生成归档的最大任务数。防止大量归档请求同时执行拖慢服务器。
- **`media_budget_mb`** (`int`，默认 `32`)：离线归档包中所有媒体文件的总大小上限（MB）。设为 `0` 表示不限制。
- **`single_image_max_mb`** (`int`，默认 `0`)：单张图片的最大允许大小（MB）。设为 `0` 表示不限制。

### `[templates]` — 消息模板

- **`channel_header`** (`str`，多行)：投诉频道创建时发送的第一条消息模板。支持宏替换（见下方宏表）。
- **`form_field_format`** (`str`，默认 `"**{label}**：{value}"`)：每个表单字段在 channel_header 中的显示格式。`{label}` 替换为字段名，`{value}` 替换为用户填写的内容。
- **`fallback_emoji`** (`str`，默认 `"📋"`)：当投诉类型找不到对应配置时使用的回退 emoji。
- **`unknown_type_label`** (`str`，默认 `"未知"`)：当投诉类型找不到对应配置时使用的回退显示名。

### `[role_groups.{id}]` — 身份组

每个 `[role_groups.xxx]` 定义一个身份组，`xxx` 是组 ID（字符串），在投诉类型中通过此 ID 引用。可定义多个。

- **`label`** (`str`，必填)：人类可读的名称，如 `"总管理"`、`"风纪委员"`。仅用于管理面板显示。
- **`role_ids`** (`list[int]`)：该身份组包含的 Discord 角色 ID 列表。可以包含多个角色。被引用时，列表中所有角色都会获得频道访问权限。

### `[[types]]` — 投诉类型

每个 `[[types]]` 定义一种用户可选的投诉类型。注意是双括号 `[[types]]`（TOML 数组语法），每个类型占一个 `[[types]]` 段。

- **`id`** (`str`，必填)：类型的唯一标识符，如 `"personal_attack"`。不能与其他类型重复。此 ID 用于内部引用，创建后不建议修改。
- **`label`** (`str`，必填)：显示给用户的类型名称，如 `"人身攻击投诉"`。出现在类型选择器和频道头部。
- **`emoji`** (`str`，默认 `""`)：在类型选择器和频道头部中显示在 label 前的 emoji，如 `"⚔️"`。
- **`description`** (`str`，默认 `""`)：在类型选择下拉菜单中显示的简短描述，帮助用户理解该类型的用途。
- **`detail_description`** (`str`，默认 `""`)：用户选中该类型后，在确认页面展示的详细说明。支持多行文本。前后的空白字符会被自动去除。为空时不显示额外说明。
- **`requires_confirm`** (`bool`，默认 `false`)：用户提交表单后是否需要二次确认才会真正创建频道。设为 `true` 适合后果较严重的投诉类型。
- **`target_role_groups`** (`list[str]`，默认 `[]`)：引用 `[role_groups]` 中的组 ID 列表。这些组中的所有角色会获得新创建的投诉频道的查看和发言权限。
- **`form_fields`** (内联表数组，默认 `[]`)：投诉提交表单的动态字段定义，最多 5 项（Discord 限制）。每项是一个内联表：
  - **`key`** (`str`，必填)：字段内部键名，用于存储和引用。
  - **`label`** (`str`，必填)：显示给用户的字段名。
  - **`placeholder`** (`str`，默认 `""`)：输入框中的占位提示文本。
  - **`style`** (`"short"` 或 `"paragraph"`，默认 `"short"`)：`"short"` 为单行输入，`"paragraph"` 为多行文本框。
  - **`required`** (`bool`，默认 `true`)：该字段是否必填。

  写法示例：
  ```toml
  form_fields = [
      { key = "target", label = "被投诉人", style = "short", required = true, placeholder = "请输入用户名或ID" },
      { key = "description", label = "详细描述", style = "paragraph", required = true, placeholder = "请描述事件经过" },
  ]
  ```

- **`header_blocks`** (`list[str]`，默认 `[]`)：投诉频道头部消息末尾追加的自定义通知行。每条是一行文本，支持宏替换（见下方宏表）。通常用于 @通知 相关管理人员。

  写法示例：
  ```toml
  header_blocks = [
      "📢 通知 **总管理** {@total_admin} 协助处理",
      "📢 通知 **风纪委员** {@discipline} 协助处理",
  ]
  ```

## 宏

### `[templates]` 的 `channel_header`

| 宏 | 替换为 |
|---|---|
| `{complainant_mention}` | 投诉人的 Discord @mention |
| `{type_emoji}` | 该投诉类型的 emoji 字段值 |
| `{type_label}` | 该投诉类型的 label 字段值 |
| `{timestamp}` | Discord 原生时间戳格式（如 `<t:1700000000:f>`） |
| `{ticket_number}` | 工单编号（数字） |
| `{form_section}` | 根据用户填写的表单自动生成的文本 |
| `{custom_section}` | header_blocks 渲染后的结果 |

### `[templates]` 的 `form_field_format`

| 宏 | 替换为 |
|---|---|
| `{label}` | 表单字段的 label |
| `{value}` | 用户在表单中填写的内容 |

### `header_blocks` 每条字符串

| 宏 | 替换为 |
|---|---|
| `{@group_id}` | 替换为 `role_groups` 中对应 ID 的所有角色 mention（如 `<@&123456789>`） |
| `{type_label}` | 投诉类型的 label |
| `{type_emoji}` | 投诉类型的 emoji |
| `{ticket_number}` | 工单编号（数字） |

## 身份组备注

- `super_admin`（超级管理员）对应的是 admin（服务器所有者），拥有全局权限，不需要通过 `target_role_groups` 授予频道访问权限，也不需要添加到 `header_blocks` 的通知列表中。如果确实需要通知 admin，应仿照弹劾类型的写法，在 `header_blocks` 中直接 `@mention` 具体用户（如 `<@724158063984115713>`），而非使用 `{@super_admin}` 宏。

## 约束

- `form_fields` 最多 5 项（Discord Modal 限制）
- `style` 只能是 `"short"` 或 `"paragraph"`
- `id` 在所有 `[[types]]` 中必须唯一
- `target_role_groups` 和 `{@group_id}` 引用的身份组必须在 `[role_groups]` 中存在
- 不要编造 Discord ID（频道 ID、角色 ID），这些必须由用户提供
- 不要把 `[[types]]` 写成 `[types]`，前者是 TOML 数组语法
