import asyncio
from pathlib import Path

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import File, Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.star.filter.command import GreedyStr

from .jm_comic_fetcher.commands import HELP, parse_command, split_text, version_info
from .jm_comic_fetcher.config import Config
from .jm_comic_fetcher.models import UserError
from .jm_comic_fetcher.runtime import Runtime
from .jm_comic_fetcher.storage import Storage
from .jm_comic_fetcher.tasks import TaskManager


class JMComicFetcher(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.settings = Config.from_mapping(config)
        storage = Storage(StarTools.get_data_dir())
        self.runtime = Runtime(storage.root)
        self.manager = TaskManager(self.settings, storage, self.runtime.python)

    async def initialize(self):
        await self.runtime.prepare()
        await self.manager.start()

    @filter.command("jmcomic")
    async def jmcomic(self, event: AstrMessageEvent, args: GreedyStr):
        """Fetch chapter archives or inspect comic metadata. Usage: /jmcomic help."""
        event.stop_event()
        try:
            request = parse_command(str(args))
            if request is None:
                yield event.plain_result(HELP)
                return
            if request.action == "version":
                yield event.plain_result(version_info())
                return
            self.settings.authorize(str(event.get_sender_id()), str(event.get_group_id() or ""))
            if event.get_platform_name() != "aiocqhttp":
                raise UserError("This plugin currently supports OneBot/NapCat sessions only.")
            if request.action == "random":
                yield event.plain_result("Random is not implemented yet.")
                return
            session = event.unified_msg_origin

            async def notify(text: str):
                for part in split_text(text):
                    async with asyncio.timeout(30):
                        sent = await self.context.send_message(session, MessageChain([Plain(part)]))
                    if not sent:
                        raise UserError("The original messaging platform is unavailable.")

            async def deliver(path: Path):
                sent = await self.context.send_message(
                    session, MessageChain([File(name=path.name, file=str(path))])
                )
                if not sent:
                    raise UserError("The original messaging platform is unavailable.")

            await self.manager.submit(str(event.get_sender_id()), request, notify, deliver)
        except UserError as exc:
            yield event.plain_result(str(exc))

    async def terminate(self):
        await self.manager.close()
