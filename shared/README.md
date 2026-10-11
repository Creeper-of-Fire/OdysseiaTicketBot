# discord-bot-shared

> ⚠️ **本文件**位于 `_shared/` 仓库的根目录；通过 `git subtree --prefix shared` 被引入到当前 bot 仓库的 `shared/` 子目录中。它不是当前 bot 项目本身的文档——bot 项目说明请看仓库根目录的 `README`。

三个 Discord Bot 仓库（NewsBot / OdysseiaTicketBot / RoleBot）共享的**运行时代码**的 source of truth。

不是 PyPI 包、不是 git submodule、不是 monorepo —— 只是一个版本化的独立仓库，配合 `git subtree` 让三个 bot 仓库各持有一份本地副本。

`shared/` 里的所有文件都是普通的本地副本，可以独立编辑（push 不会被自动同步，要双向流动请显式 `git subtree push`）。

## 里面有什么

- `app_command_group.py` — 命令命名与命令名格式化（`prefixed_group` / `prefixed_name` / `ManagedGroup`）
- `config/toml_manager.py`、`config/toml_command.py`、`config/toml_merge.py` — toml 配置读写与合并
- `data/json_manager.py` — `AsyncJsonDataManager` 等异步 JSON 数据持久化
- `ui/paginated_view.py` — `PaginatedView` 分页视图基类
- `ui/views.py` — `ConfirmationView` 通用确认按钮

## 不包含

- 各 bot 的 `main.py` / `config.py` / `config_data.py`
- 各 bot 的 `CoreCog`（职责已分叉，不强行抽象）
- 各 bot 的业务 Cog（honor、ticket、role_jukebox 等）
- deploy 脚本（各 bot 保留自己的 Dockerfile / docker-compose.yml）
- **维护者文档**：subtree 工作流、设计决策等属于 workspace 层，不在这里——它们会被原样分发给 bot 的 fork 用户，对 fork 用户无意义
