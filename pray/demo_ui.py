import asyncio
import uuid
from datetime import datetime
from typing import Optional

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table

from pray.pray_core.engine import WishEngine
from pray.pray_core.manager import WishDataManager, GuildWishData
# 导入你提供的基础组件
from pray.pray_core.models import Wish, WishState, WishCategory, UserRole, UserContext
from pray.pray_core.ports import IWishExternalAdapter, IWishRepository

console = Console()

class WishRepoAdapter(IWishRepository):
    """
    适配器：将 WishDataManager (多服务器管理)
    桥接到 IWishRepository (单服务器业务逻辑接口)
    """
    def __init__(self, manager: WishDataManager, guild_id: int):
        self.manager = manager
        self.guild_id = guild_id

    def _get_guild_data(self) -> GuildWishData:
        # 确保该服务器的数据对象存在
        return self.manager.ensure_guild(self.guild_id)

    def get(self, wish_id: str) -> Optional[Wish]:
        return self._get_guild_data().wishes.get(wish_id)

    def get_all(self) -> list[Wish]:
        return list(self._get_guild_data().wishes.values())

    def save(self, wish: Wish):
        # 将愿望存入该服务器的字典中
        self._get_guild_data().wishes[wish.id] = wish
        # 触发底层 DataManager 的异步节流保存任务
        # 注意：这里调用的是异步任务的同步触发器
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.manager.save_data())
        except RuntimeError:
            # 如果不在异步循环中（如初始化），则不处理或同步写
            pass

# --- 兼容性适配器：模拟 Discord 通知到 Rich 日志 ---
class SimpleAdapter(IWishExternalAdapter):
    """日志适配器，将系统动作存入内存列表用于展示"""

    def __init__(self):
        self.logs = []

    def _add_log(self, msg: str):
        t = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[dim][{t}][/] {msg}")
        if len(self.logs) > 8: self.logs.pop(0)

    def create_discussion_thread(self, wish: Wish):
        self._add_log(f"🧵 [yellow]Thread:[/] 为 '{wish.title}' 开启讨论")
        return f"thr_{wish.id}"

    def lock_discussion_thread(self, thread_id: str):
        self._add_log(f"🔒 [red]Thread:[/] 锁定 {thread_id}")

    def unlock_discussion_thread(self, thread_id: str):
        self._add_log(f"🔓 [green]Thread:[/] 解锁 {thread_id}")

    def send_notification(self, target_user_id: str, message: str):
        self._add_log(f"✉️ [私信 @{target_user_id}]: {message}")

    def broadcast_event(self, message: str):
        self._add_log(f"📢 [广播]: {message}")


# --- UI 渲染逻辑 ---
def draw_ui(wishes: list[Wish], logs: list[str]):
    """绘制整个 UI 布局"""
    # 1. 愿望表格
    table = Table(box=box.ROUNDED, expand=True, show_header=True)
    table.add_column("简短ID", style="dim", width=10)
    table.add_column("状态", justify="center", width=12)
    table.add_column("支持", justify="center", width=8)
    table.add_column("标题", style="bold white")
    table.add_column("认领人", style="blue", width=15)

    colors = {
        WishState.ACTIVE: "cyan",
        WishState.IN_DISCUSSION: "yellow",
        WishState.IN_PROGRESS: "magenta",
        WishState.FULFILLED: "green",
        WishState.CLOSED: "red"
    }

    for w in wishes:
        table.add_row(
            w.id,
            f"[{colors.get(w.state, 'white')}]{w.state.value}[/]",
            f"{len(w.supporters)}/5",
            w.title,
            str(w.claimer_id or "-")
        )

    # 2. 构造布局
    layout = Layout()
    layout.split_column(
        Layout(Panel("🎮 许愿池逻辑实验室 | 输入 [bold reverse]help[/] 查看指令", style="magenta"), size=3),
        Layout(Panel(table, title="✨ 实时愿望清单"), name="main"),
        Layout(Panel("\n".join(logs), title="📡 系统日志", border_style="dim"), size=11)
    )
    return layout


async def interactive_loop():
    # 初始化数据

    data_manager: WishDataManager = WishDataManager.get_instance()
    CURRENT_GID = 12345
    repo = WishRepoAdapter(data_manager, CURRENT_GID)
    adapter = SimpleAdapter()
    engine = WishEngine(repo, adapter)

    # 模拟环境
    GID = 8888
    me = UserContext(user_id="10086", role=UserRole.ADMIN)  # 给个管理员权限方便测试

    while True:
        # 1. 清屏并重绘
        console.clear()
        wishes = repo.get_all()
        console.print(draw_ui(wishes, adapter.logs))

        # 2. 获取输入 (使用 asyncio.to_thread 防止阻塞事件循环)
        # 这样既保证了输入不被覆盖，又能让底层的异步保存任务运行
        prompt = "\n[bold yellow]请输入指令 (help/new/vote/claim/done/exit) > [/]"
        raw_cmd = await asyncio.to_thread(console.input, prompt)

        parts = raw_cmd.strip().split()
        if not parts: continue

        cmd = parts[0].lower()
        try:
            if cmd == "exit":
                adapter._add_log("正在强制保存并退出...")
                await data_manager.force_save()
                break

            elif cmd == "help":
                adapter._add_log("可用指令: [bold]new[/] <标题>, [bold]vote[/] <ID>, [bold]claim[/] <ID>, [bold]done[/] <ID>, [bold]exit[/]")

            elif cmd == "new":
                title = " ".join(parts[1:]) if len(parts) > 1 else "神秘愿望"
                engine.create_wish(me, WishCategory.BOT_FEATURE, title, "无内容")
                adapter._add_log(f"✅ 创建愿望成功: {title}")

            elif cmd == "vote":
                if len(parts) < 2: raise ValueError("请输入ID")
                wid = parts[1]
                # 模拟一个新用户去投票
                fake_uid = uuid.uuid4().int % 10000
                engine.support_wish(UserContext(user_id=str(fake_uid), role=UserRole.NORMAL), wid)
                adapter._add_log(f"👍 用户 {fake_uid} 投了一票给 {wid}")

            elif cmd == "claim":
                if len(parts) < 2: raise ValueError("请输入ID")
                engine.claim_wish(me, parts[1], "https://proposal.link")
                adapter._add_log(f"🛠️ 你认领了愿望 {parts[1]}")

            elif cmd == "done":
                if len(parts) < 2: raise ValueError("请输入ID")
                engine.admin_resolve_proposal(me, parts[1], True)
                adapter._add_log(f"🎉 标记 {parts[1]} 为已实现！")

            else:
                adapter._add_log(f"[red]未知指令:[/] {cmd}")

        except Exception as e:
            adapter._add_log(f"[bold red]错误:[/] {str(e)}")
            # 给用户一点时间看清错误
            await asyncio.sleep(1)


# --- 主程序 ---
if __name__ == "__main__":
    asyncio.run(interactive_loop())