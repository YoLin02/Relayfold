import argparse
import asyncio
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from time import time

# The embedded runtime can launch a worker installed in the update cache.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import api_identity, normalize_options, platform_settings, publish_api
from browser import Browser, DouyinListedWork, DouyinRejected, RetainedDouyin
from catalog import PLATFORMS
from publish_content import IMAGE_EXTENSIONS, local_file, resolve_content
import session_backup
from store import Store, new_id, validate_schedule


DECLARATIONS = {
    "无需添加自主声明", "内容由AI生成", "内容为个人观点或见解", "内容为转载信息",
    "内容含营销推广信息", "虚构演绎，仅供娱乐",
}


class SessionError(ValueError):
    pass


def send(payload):
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def remove_managed_folders(root, ids):
    for identifier in ids:
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            continue
        try:
            shutil.rmtree(root / identifier)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logging.warning("Could not clean up deleted local data (%s)", type(exc).__name__)


class Worker:
    def __init__(self, root, browser_factory=Browser):
        root.mkdir(parents=True, exist_ok=True)
        self.media = root / "media"
        self.media.mkdir(exist_ok=True)
        self.profiles = root / "profiles"
        self.store = Store(root / "publisher.sqlite3")
        self.browser = browser_factory(self.profiles)
        self.locks = {}
        self.followups = set()
        self.queued = asyncio.Event()
        self.queued.set()

    def changed(self):
        send({"event": "changed"})

    def lock(self, binding_id):
        return self.locks.setdefault(binding_id, asyncio.Lock())

    def binding_with_settings(self, binding_id):
        binding = self.store.binding(binding_id)
        if PLATFORMS[binding["platform"]].mode != "browser":
            try:
                binding["settings"] = session_backup.load(self.profiles / binding_id, binding_id, "settings.dat") or {}
            except (OSError, ValueError) as exc:
                raise ValueError("无法读取此账号的加密配置，请新建会话并重新配置。") from exc
        return binding

    async def session_identity(self, binding, page):
        if page is None:
            return await api_identity(binding)
        result = await self.browser.identity(page, binding)
        if binding["platform"] == "xiaohongshu":
            for _ in range(4):
                if result and result.get("account_proof"):
                    break
                await asyncio.sleep(0.75)
                result = await self.browser.identity(page, binding)
        return result

    async def check(self, binding, page):
        try:
            result = await self.session_identity(binding, page)
            stable = binding.get("account_proof")
            matches = result and (result.get("account_proof") == stable if stable else result["proof"] == binding["session_proof"])
            if matches and result.get("account_proof") and (not stable or result["proof"] != binding["session_proof"]):
                self.store.bind(binding["id"], binding["label"], result["proof"], account_proof=result["account_proof"])
                binding.update(session_proof=result["proof"], account_proof=result["account_proof"])
                try:
                    await self.browser.save_session(binding, page)
                except Exception as exc:
                    logging.warning("Could not refresh the verified Xiaohongshu session backup (%s)", type(exc).__name__)
        except ValueError as exc:
            self.store.login_status(binding["id"], "attention")
            self.changed()
            raise SessionError(str(exc)) from exc
        if not matches:
            self.store.login_status(binding["id"], "attention")
            self.changed()
            if binding["platform"] == "xiaohongshu":
                if result:
                    raise SessionError("小红书网页会话无法匹配原绑定。请在原账号的创作后台核对后再验证。")
                raise SessionError("暂未能从小红书创作后台核对登录身份。请打开后台检查登录后重试。")
            raise SessionError("当前平台登录已过期或与原绑定不一致。请在此账号卡片重新扫码确认。")
        self.store.login_status(binding["id"], "ready")
        return result

    async def account_command(self, method, data):
        binding_id = data["id"]
        label = data.get("label")
        binding = (self.store.binding(binding_id) if method in {"accounts.replace", "accounts.delete"}
                   else self.binding_with_settings(binding_id))
        mode = PLATFORMS[binding["platform"]].mode
        lock = self.lock(binding_id)
        if lock.locked():
            raise ValueError("这个账号正在执行任务，请稍后再操作。")
        async with lock:
            held = self.browser.retained.get(binding_id)
            if held:
                if method == "accounts.manage":
                    await held.page.bring_to_front()
                    return
                raise ValueError("抖音提交页面仍在等待核对，请先查看或关闭该页面。")
            if method == "accounts.configure":
                if binding["session_proof"]:
                    raise ValueError("请新建会话后再更换站点或 API 凭据。")
                binding["settings"] = platform_settings(binding["platform"], data.get("settings") or {})
                if mode == "api":
                    result = await api_identity(binding)
                    self.store.bind(binding_id, label or result["name"], result["proof"])
                directory = self.profiles / binding_id
                directory.mkdir(parents=True, exist_ok=True)
                try:
                    session_backup.save(directory, binding_id, binding["settings"], "settings.dat")
                except OSError as exc:
                    if mode == "api":
                        self.store.login_status(binding_id, "attention")
                    raise ValueError("无法保存此账号的加密配置。") from exc
                if mode == "custom_browser":
                    await self.open_browser(binding)
            elif method == "accounts.open":
                await self.open_browser(binding)
            elif method == "accounts.manage":
                if not binding["session_proof"]:
                    raise ValueError("请先确认账号绑定。")
                if mode == "api":
                    raise ValueError("请在该站点的后台人工核对。")
                await self.check(binding, await self.open_browser(binding, manage=True))
            elif method == "accounts.confirm":
                page = await self.browser.active_page(binding)
                result = await self.session_identity(binding, page)
                if not result:
                    raise ValueError("还没识别到平台登录。请先扫码并等创作者后台加载完成。")
                self.store.bind(binding_id, label or result["name"], result["proof"], account_proof=result.get("account_proof"))
                try:
                    await self.browser.save_session(binding, page)
                except Exception as exc:
                    self.store.login_status(binding_id, "saved")
                    self.changed()
                    raise ValueError("账号已绑定，但无法保存加密会话备份。请检查本地目录权限后重新确认。") from exc
                await self.browser.close(binding_id)
            elif method == "accounts.check":
                if not binding["session_proof"]:
                    raise ValueError("请先完成账号绑定。")
                page = None if mode == "api" else await self.open_browser(binding)
                try:
                    await self.check(binding, page)
                finally:
                    await self.browser.close(binding_id)
            elif method == "accounts.delete":
                self.store.delete_binding(binding_id)
                await self.browser.close(binding_id)
                await asyncio.to_thread(remove_managed_folders, self.profiles, [binding_id])
            elif method == "accounts.replace":
                await self.browser.close(binding_id)
                self.store.replace_binding(binding_id)
        self.changed()

    async def open_browser(self, binding, *, manage=False, douyin_video=False):
        try:
            if douyin_video:
                return await self.browser.open(binding, manage=manage, douyin_video=True)
            return await self.browser.open(binding, manage=manage)
        except Exception as exc:
            logging.warning("Platform %s could not be opened: %s", binding["platform"], type(exc).__name__)
            raise ValueError(f"无法打开{PLATFORMS[binding['platform']].label}后台。请检查站点配置、本机 Chrome 和网络。") from exc

    async def create_tasks(self, data):
        group = data["group_id"]
        self.store.require_group(group)
        scheduled_at = data.get("scheduled_at")
        if scheduled_at is not None:
            validate_schedule(scheduled_at)
        targets = data["binding_ids"]
        if not isinstance(targets, list) or not targets or len(set(targets)) != len(targets):
            raise ValueError("请选择去重后至少一个发布账号。")
        selected = [self.store.binding(binding_id) for binding_id in targets]
        kind = data.get("kind", "video")
        platforms = {row["platform"] for row in selected}
        if kind not in {"video", "image", "article"} or any(kind not in PLATFORMS[key].kinds for key in platforms):
            raise ValueError("所选平台不支持此发布类型。")
        if any(row["group_id"] != group or row["login_status"] not in {"ready", "saved"} for row in selected):
            raise ValueError("发布目标必须属于此发布组，并且已绑定登录。")
        declaration = data.get("declaration")
        if declaration is not None and declaration not in DECLARATIONS:
            raise ValueError("请选择有效的抖音作品声明。")
        if "douyin" in platforms and not declaration:
            raise ValueError("请选择抖音作品声明。")
        options = normalize_options(platforms, data.get("options") or {})
        media_paths = data.get("media_paths")
        if media_paths is None:
            media_paths = [data["media_path"]] if data.get("media_path") else []
        if not isinstance(media_paths, list):
            raise ValueError("素材列表无效。")
        if kind == "video" and len(media_paths) != 1:
            raise ValueError("请选择一个视频。")
        if kind == "image" and not 1 <= len(media_paths) <= 18:
            raise ValueError("请选择 1–18 张图片。")
        if kind == "article" and (len(media_paths) > 18 or (media_paths and "wangyi" not in platforms)):
            raise ValueError("文章本地配图仅用于网易号，最多 18 张。")
        extensions = {".mp4", ".mov"} if kind == "video" else IMAGE_EXTENSIONS
        sources = [local_file(path, extensions) for path in media_paths]
        contents = resolve_content(data, selected, kind, sources)
        batch = new_id()
        folder = self.media / batch
        unique_sources = dict.fromkeys(sources + [content["cover"] for content in contents.values() if content["cover"]])
        saved = {source: folder / f"{index:02}-{source.name}" for index, source in enumerate(unique_sources, 1)}
        paths = [saved[source] for source in sources]
        for content in contents.values():
            content["cover"] = str(saved[content["cover"]]) if content["cover"] else ""
        try:
            if saved:
                folder.mkdir()
                for source, path in saved.items():
                    await asyncio.to_thread(shutil.copyfile, source, path)
            media_name = sources[0].name if len(paths) == 1 else (f"{len(paths)} 张图片" if paths else "")
            title = data.get("title", "")
            description = data.get("description", "")
            self.store.enqueue(batch, group, targets, title.strip(), description.strip(), declaration,
                               paths[0] if paths else "", media_name, kind=kind, files=[str(p) for p in paths],
                               options=options, contents=contents, scheduled_at=scheduled_at)
        except OSError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise ValueError("无法保存本地素材副本。请检查读取权限和磁盘空间。") from exc
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        self.queued.set()
        self.changed()
        return {"id": batch}

    async def review(self, args):
        task = self.store.task(args["id"])
        binding_id = task["binding_id"]
        async with self.lock(binding_id):
            current = self.store.task(task["id"])["status"]
            held = self.browser.retained.get(binding_id)
            if held and held.task_id == task["id"] and args["result"] == "missing":
                raise ValueError("请先核对抖音后台并关闭保留的发布窗口，再确认未收稿。")
            if args["result"] == "found" and current in {"draft_ready", "needs_review"}:
                status, detail = "submitted", "已在平台后台人工核对到作品。"
            elif args["result"] == "missing" and current == "needs_review":
                status, detail = "failed", "已人工确认平台未收到，可重试。"
            else:
                raise ValueError("无效的核对结果。")
            self.store.transition(task["id"], current, status, detail)
            if held and held.task_id == task["id"]:
                await self.browser.close(binding_id, review_task=task["id"])
        self.changed()

    async def complete_retained(self, binding_id, held):
        result = await held.result
        async with self.lock(binding_id):
            if self.store.task_status(held.task_id) != "needs_review":
                return
            if result is None:
                self.store.record_task_event(held.task_id, "保留的抖音页面已关闭，未得到明确回执。")
                self.store.transition(held.task_id, "needs_review", "needs_review",
                                      "发布页面已关闭，仍未收到明确回执。请在抖音后台核对。")
            elif isinstance(result, DouyinRejected):
                self.store.transition(held.task_id, "needs_review", "failed", str(result))
            elif isinstance(result, DouyinListedWork):
                self.store.transition(held.task_id, "needs_review", "submitted",
                                      "已在抖音作品管理核对到本次投稿。", result.receipt)
            else:
                self.store.transition(held.task_id, "needs_review", "submitted", "等待超时后收到抖音作品回执。", result)
            if result is not None and self.browser.retained.get(binding_id) is held:
                await self.browser.close(binding_id, review_task=held.task_id)
        self.changed()

    async def delete_group(self, group_id):
        binding_ids = self.store.group_binding_ids(group_id)
        if any((self.locks.get(key) and self.locks[key].locked()) or key in self.browser.retained for key in binding_ids):
            raise ValueError("此发布组有账号正在执行操作，请稍后再删除。")
        batch_ids = self.store.delete_group(group_id)
        self.changed()
        await asyncio.gather(*(self.browser.close(binding_id) for binding_id in binding_ids))
        for binding_id in binding_ids:
            self.locks.pop(binding_id, None)
        await asyncio.gather(
            asyncio.to_thread(remove_managed_folders, self.profiles, binding_ids),
            asyncio.to_thread(remove_managed_folders, self.media, batch_ids),
        )

    async def delete_task(self, task_id):
        binding_id = self.store.task(task_id)["binding_id"]
        lock = self.lock(binding_id)
        if lock.locked():
            raise ValueError("此账号正在执行操作，请稍后删除记录。")
        async with lock:
            held = self.browser.retained.get(binding_id)
            if held and held.task_id == task_id:
                raise ValueError("请先核对并关闭保留的发布窗口，再删除这条记录。")
            orphaned_batch = self.store.delete_task(task_id)
        if orphaned_batch:
            await asyncio.to_thread(remove_managed_folders, self.media, [orphaned_batch])
        self.changed()

    async def dispatch(self, method, args):
        if method == "state":
            return self.store.state()
        if method == "groups.create":
            group_id = self.store.create_group(args["name"], args.get("mode", "regular"))
            self.store.select_group(group_id)
            self.changed()
            return {"id": group_id}
        if method == "groups.select":
            self.store.select_group(args["id"])
            self.changed()
            return
        if method == "groups.rename":
            self.store.rename_group(args["id"], args["name"])
            self.changed()
            return
        if method == "groups.delete":
            return await self.delete_group(args["id"])
        if method == "settings.region":
            self.store.set_platform_region(args.get("region"))
            self.changed()
            return
        if method == "settings.theme":
            self.store.set_accent_theme(args.get("theme"))
            self.changed()
            return
        if method == "accounts.add":
            self.store.add_accounts(args["group_id"], args.get("platform"), args.get("count"))
            self.changed()
            return
        if method in {"accounts.open", "accounts.confirm", "accounts.check", "accounts.manage",
                      "accounts.replace", "accounts.delete", "accounts.configure"}:
            return await self.account_command(method, args)
        if method == "tasks.create":
            return await self.create_tasks(args)
        if method in {"tasks.reschedule", "tasks.cancelSchedule"}:
            if method == "tasks.reschedule":
                validate_schedule(args.get("scheduled_at"))
            self.store.change_schedule(args["batch_id"], args.get("scheduled_at") if method == "tasks.reschedule" else None)
            self.changed()
            return
        if method == "tasks.retry":
            self.store.retry(args["id"])
            self.queued.set()
            self.changed()
            return
        if method == "tasks.review":
            return await self.review(args)
        if method == "tasks.history":
            return self.store.history(args["group_id"], args.get("start"), args.get("end"), args.get("page", 0))
        if method == "tasks.delete":
            return await self.delete_task(args["id"])
        if method == "tasks.diagnostics":
            return self.store.task_diagnostics(args["id"])
        raise ValueError("本地 Worker 收到未知操作。")

    async def run_task(self, task):
        task_id = task["id"]
        binding_id = task["binding_id"]
        phase = "running"
        identity_error = None
        step = ""
        self.store.transition(task_id, "queued", phase, "正在检查原账号并准备内容。")
        self.changed()

        try:
            async with self.lock(binding_id):
                if binding_id in self.browser.retained:
                    raise SessionError("同一抖音账号仍有保留的发布页面。请核对该页面后重试这条任务。")
                binding = self.binding_with_settings(binding_id)
                if binding["group_id"] != task["group_id"] or not binding["session_proof"]:
                    raise SessionError("这条任务的原账号已不可用。")
                required_files = [*task["media_files"], *([task["cover"]] if task["cover"] else [])]
                if any(not Path(path).is_file() for path in required_files):
                    raise ValueError("本地素材副本已丢失，请重新选择文件。")
                await self.browser.close(binding_id)
                try:
                    xhs_video = binding["platform"] == "xiaohongshu" and task["kind"] == "video"
                    async with asyncio.timeout(1200 if xhs_video else 900) as deadline:
                        using_api = PLATFORMS[binding["platform"]].mode == "api"
                        douyin = binding["platform"] == "douyin"
                        douyin_video = douyin and task["kind"] == "video"
                        page = None if using_api else await self.open_browser(binding, douyin_video=douyin_video)
                        await self.check(binding, page)

                        async def before_submit():
                            nonlocal phase, identity_error
                            try:
                                if page is not None:
                                    current_page = await self.browser.active_page(binding)
                                    await self.check(binding, current_page)
                            except SessionError as exc:
                                identity_error = exc
                                raise
                            self.store.transition(task_id, phase, "submitting", "已核对目标账号，正在提交至平台。")
                            phase = "submitting"
                            if douyin:
                                # The bounded click and receipt wait must get their full time after preparation.
                                deadline.reschedule(None)
                            self.changed()

                        def progress(detail):
                            nonlocal phase, step
                            if detail != step:
                                if douyin and phase == "submitting":
                                    self.store.transition(task_id, phase, "verifying", detail)
                                    phase = "verifying"
                                self.store.record_task_event(task_id, detail, progress=True)
                                step = detail
                                self.changed()

                        def record(detail):
                            self.store.record_task_event(task_id, detail)
                            self.changed()

                        if using_api:
                            receipt = await publish_api(binding, task, before_submit)
                        else:
                            receipt = await self.browser.publish(
                                page, binding, task, before_submit, progress=progress,
                                record=record)
                finally:
                    await self.browser.close(binding_id)
            if identity_error:
                raise identity_error
            if phase == "running":
                raise ValueError("平台未完成素材或表单准备，还未提交。")
            if receipt == "draft":
                self.store.transition(task_id, phase, "draft_ready", "已保存草稿，请到平台后台检查并发布。")
            elif isinstance(receipt, RetainedDouyin):
                detail = ("自动核对尚未确认本次作品。发布页面已保留。"
                          if phase == "verifying" else
                          "抖音尚未明确返回，发布页面已保留。可打开后台核对，诊断记录中可查看请求和响应。")
                self.store.transition(task_id, phase, "needs_review",
                                      detail)
                followup = asyncio.create_task(self.complete_retained(binding_id, receipt))
                self.followups.add(followup)
                followup.add_done_callback(self.followups.discard)
            elif isinstance(receipt, DouyinListedWork):
                self.store.transition(task_id, phase, "submitted",
                                      "已在抖音作品管理核对到本次投稿。公开状态以平台审核为准。", receipt.receipt)
            elif receipt:
                self.store.transition(task_id, phase, "submitted", "平台已返回作品回执。公开状态以平台审核为准。", receipt)
            else:
                self.store.transition(task_id, phase, "needs_review", "已尝试提交，暂未收到明确回执。请到平台后台核对。")
        except Exception as exc:
            logging.warning("Task %s interrupted (%s)", task_id, type(exc).__name__)
            if isinstance(exc, DouyinRejected):
                self.store.transition(task_id, phase, "failed", str(exc))
            elif phase in {"submitting", "verifying"}:
                self.store.transition(task_id, phase, "needs_review", "提交阶段发生异常，请先核对平台后台。")
            elif isinstance(exc, SessionError):
                self.store.transition(task_id, phase, "action_required", str(exc))
            else:
                message = str(exc) if isinstance(exc, ValueError) else "本地发布准备中断，还未提交。"
                if step:
                    message = f"{step} {message}"
                    self.store.record_task_event(task_id, message)
                self.store.transition(task_id, phase, "failed", message)
        self.changed()

    async def consume(self):
        while True:
            await self.queued.wait()
            task = self.store.next_task()
            if task:
                await self.run_task(task)
            else:
                self.queued.clear()

    async def schedule(self):
        while True:
            if self.store.release_scheduled(int(time())):
                self.queued.set()
                self.changed()
            await asyncio.sleep(1)


async def serve(root, browser_factory=Browser):
    worker = Worker(root, browser_factory)
    consumer = asyncio.create_task(worker.consume())
    scheduler = asyncio.create_task(worker.schedule())
    calls = set()

    async def answer(request):
        response = {"id": request.get("id")}
        try:
            response["result"] = await worker.dispatch(request["method"], request.get("args") or {})
        except ValueError as exc:
            response["error"] = str(exc)
        except Exception as exc:
            logging.warning("Worker command failed: %s", type(exc).__name__)
            response["error"] = "本地操作失败，请重试。"
        send(response)

    send({"event": "ready"})
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue
            if request.get("method") == "shutdown":
                break
            call = asyncio.create_task(answer(request))
            calls.add(call)
            call.add_done_callback(calls.discard)
    finally:
        pending = [consumer, scheduler, *calls]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await worker.browser.shutdown()
        await asyncio.gather(*worker.followups, return_exceptions=True)
        worker.store.db.close()


def main(browser_factory=Browser):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    options = parser.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(serve(options.data_dir, browser_factory))


if __name__ == "__main__":
    main()
