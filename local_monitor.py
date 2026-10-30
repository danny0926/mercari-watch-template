"""Run locally while cloud monitoring is paused, then return encrypted history."""
import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

import mercari_watch as app
from handoff_state import SLOTS, pack_states, read_state, split_payload, unpack_states, write_state

BASE = Path(__file__).resolve().parent
ROOT = BASE / ".state/local-monitor"
FINISHED = "cloud"


class HandoffError(RuntimeError):
    pass


class LocalLock:
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise HandoffError("已有本機監聽或交接正在執行。") from None
        return self

    def __exit__(self, *_):
        self.file.close()


class GitHub:
    def __init__(self, repository):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository):
            raise HandoffError("請在 .env 設定 MONITOR_GITHUB_REPOSITORY=owner/repo。")
        self.repository = repository
        self.executable = shutil.which("gh")
        if not self.executable:
            raise HandoffError("找不到 GitHub CLI；請先安裝 gh 並執行 gh auth login。")

    def call(self, *arguments, input=None, optional=False):
        try:
            result = subprocess.run([self.executable, *arguments], input=input, capture_output=True,
                                    encoding="utf-8", errors="strict", timeout=60,
                                    cwd=BASE, env={**os.environ, "GH_PROMPT_DISABLED": "1"})
        except (OSError, subprocess.SubprocessError, UnicodeError):
            if optional:
                return None
            raise HandoffError("GitHub 指令未完成；請確認登入與網路。") from None
        if result.returncode:
            if optional:
                return None
            raise HandoffError("GitHub 指令失敗；請確認 repo 權限、登入與網路。")
        return result.stdout

    def json(self, *arguments):
        return json.loads(self.call(*arguments))

    def flags(self):
        values = self.json("variable", "list", "--repo", self.repository,
                           "--json", "name,value")
        return {row["name"]: row["value"] for row in values}

    def flag(self, name, value):
        self.call("variable", "set", name, "--repo", self.repository, "--body", value)

    def runs(self, workflow):
        return self.json("run", "list", "--repo", self.repository, "--workflow", workflow,
                         "--limit", "100", "--json", "databaseId,status,conclusion,displayTitle,headBranch")

    def active(self, workflow):
        return [run for run in self.runs(workflow) if run["status"] != "completed"]

    def dispatch(self, workflow, **inputs):
        args = ["workflow", "run", workflow, "--repo", self.repository, "--ref", "main"]
        for name, value in inputs.items():
            args.extend(("-f", f"{name}={value}"))
        return self.call(*args)


class LocalMonitor:
    def __init__(self, github, key, interval=1800, root=ROOT):
        self.gh, self.key, self.interval = github, key, interval
        self.root = Path(root)
        self.journal = self.root / "session.json"
        self.stop = threading.Event()
        self.claim = None

    def save(self, **changes):
        self.claim.update(changes)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.claim), encoding="utf-8")
        temporary.replace(self.journal)

    def previous(self):
        if not self.journal.exists():
            return None
        claim = json.loads(self.journal.read_text(encoding="utf-8"))
        if (claim.get("repository") != self.gh.repository or claim.get("schema") != 1
                or str(uuid.UUID(claim["session"])) != claim["session"]
                or not isinstance(claim.get("was_enabled"), bool)):
            raise HandoffError("本機交接紀錄無法確認；請檢查指定 repo 與 session.json。")
        return claim

    def paths(self):
        directory = self.root / self.claim["session"]
        return {slot: directory / f"{slot}.enc" for slot in SLOTS}

    def preflight(self):
        Fernet(self.key.encode("ascii"))
        if self.interval < 60:
            raise HandoffError("本機監聽間隔至少為 60 秒。")
        watches = app.load_watchlist()
        if not watches:
            raise HandoffError("尚未啟用私人監聽條件，不暫停雲端。")
        line = [bool(os.environ.get(name, "").strip()) for name in ("LINE_CHANNEL_ACCESS_TOKEN", "LINE_USER_ID")]
        if any(line) and not all(line):
            raise HandoffError("LINE 通知設定不完整，不暫停雲端。")
        for watch in watches:
            route = app.webhook_env_for(watch)
            if not os.environ.get(route, "").strip() and not (route == app.DEFAULT_WEBHOOK_ENV and all(line)):
                raise HandoffError("私人條件缺少通知目的地，不暫停雲端。")
        app.mercari_link_mode()
        workflow = self.gh.json("api", f"repos/{self.gh.repository}/actions/workflows/monitor-handoff.yml")
        if workflow.get("state") != "active":
            raise HandoffError("請先將交接 workflow 部署到指定 repo 的 main 並啟用。")

    def drain(self):
        print("正在停止雲端計時器，等待既有監聽完成與保存紀錄……", flush=True)
        deadline = time.monotonic() + 900
        while True:
            clocks = self.gh.active("monitor-clock.yml")
            for run in clocks:
                self.gh.call("run", "cancel", str(run["databaseId"]), "--repo", self.gh.repository, optional=True)
            monitors = self.gh.active("market-monitor.yml")
            if not clocks and not monitors:
                return
            if time.monotonic() > deadline:
                raise HandoffError("雲端仍有執行中的工作，本機尚未接手。")
            time.sleep(5)

    def transfer(self, mode):
        field = f"{mode}_run"
        run_id = self.claim.get(field)
        title = f"State handoff {mode} {self.claim['session']}"
        if not run_id:
            output = self.gh.dispatch("monitor-handoff.yml", mode=mode, session=self.claim["session"])
            match = re.search(r"/actions/runs/(\d+)", output)
            if match:
                run_id = int(match[1])
            else:
                for _ in range(12):
                    matches = [run for run in self.gh.runs("monitor-handoff.yml")
                               if run["displayTitle"] == title and run["headBranch"] == "main"]
                    if matches:
                        run_id = max(run["databaseId"] for run in matches)
                        break
                    time.sleep(5)
            if not run_id:
                raise HandoffError("無法確認交接工作編號；請稍後使用 --resume-cloud。")
            self.save(**{field: run_id})
        deadline = time.monotonic() + 900
        while True:
            result = self.gh.json("run", "view", str(run_id), "--repo", self.gh.repository,
                                  "--json", "status,conclusion,jobs")
            if result["status"] == "completed":
                jobs = {job["name"]: job["conclusion"] for job in result["jobs"]}
                if (result["conclusion"] != "success"
                        or jobs != {"state-core": "success", "state-surugaya": "success"}):
                    # A recovery must create a new attempt after correcting the failure.
                    self.save(**{field: None})
                    raise HandoffError("加密紀錄交接未成功；保留原有紀錄，請查看交接 workflow。")
                return run_id
            if time.monotonic() > deadline:
                raise HandoffError("交接工作尚未完成；請稍後使用 --resume-cloud。")
            time.sleep(5)

    def download(self, run_id):
        states = {}
        for slot in SLOTS:
            destination = self.root / self.claim["session"] / "download" / slot
            destination.mkdir(parents=True, exist_ok=True)
            self.gh.call("run", "download", str(run_id), "--repo", self.gh.repository,
                         "--name", f"handoff-{slot}", "--dir", str(destination))
            token = (destination / "handoff.enc").read_text(encoding="ascii")
            values = unpack_states(token, self.claim["session"], self.key)
            if set(values) != {slot}:
                raise HandoffError("雲端紀錄的來源分組無法確認。")
            states.update(values)
        # Validate both artifacts before replacing either local source history.
        for slot, path in self.paths().items():
            write_state(path, self.key, states[slot])
        self.save(states_ready=True, phase="local")

    def import_history(self):
        states = {slot: read_state(path, self.key) for slot, path in self.paths().items()}
        chunks = split_payload(pack_states(states, self.claim["session"], self.key))
        for name, value in chunks.items():
            if value:
                self.gh.call("secret", "set", name, "--repo", self.gh.repository, input=value)
            else:
                # Missing secrets evaluate to empty strings in the workflow.
                self.gh.call("secret", "delete", name, "--repo", self.gh.repository, optional=True)
        self.save(phase="importing")
        self.transfer("import")
        self.save(phase="imported")

    def restore(self):
        if self.claim["phase"] == FINISHED:
            return
        print("正在交回加密紀錄並恢復原本的雲端設定……", flush=True)
        if self.claim.get("states_ready") and self.claim["phase"] not in ("imported", "starting-cloud"):
            self.import_history()
        self.gh.flag("LOCAL_MONITOR_ACTIVE", "false")
        enabled = "true" if self.claim["was_enabled"] else "false"
        self.gh.flag("MONITOR_ENABLED", enabled)
        self.save(phase="starting-cloud")
        flags = self.gh.flags()
        if flags.get("LOCAL_MONITOR_ACTIVE") != "false" or flags.get("MONITOR_ENABLED") != enabled:
            raise HandoffError("雲端開關尚未確認，請使用 --resume-cloud。")
        if self.claim["was_enabled"] and not self.gh.active("monitor-clock.yml"):
            self.gh.dispatch("monitor-clock.yml", bootstrap="false")
        self.save(phase=FINISHED)
        for name in split_payload("cleanup"):
            self.gh.call("secret", "delete", name, "--repo", self.gh.repository, optional=True)
        print("交接完成，雲端已恢復。" if self.claim["was_enabled"] else "交接完成，雲端維持原先的停用設定。", flush=True)

    def cycle(self):
        errors = 0
        groups = {"core": ["jp", "tw", "yahoo_fleamarket"], "surugaya": ["surugaya"]}
        previous_seen = app.SEEN
        previous_path = os.environ.get("MONITOR_STATE_PATH")
        try:
            for slot, sources in groups.items():
                app.SEEN = self.paths()[slot]
                os.environ["MONITOR_STATE_PATH"] = str(app.SEEN)
                try:
                    errors += asyncio.run(app.check_once(only_sources=sources))
                except Exception as error:
                    print(f"本機 {slot} 本輪未完成：{type(error).__name__}（私人細節省略）", flush=True)
                    errors += 1
        finally:
            app.SEEN = previous_seen
            if previous_path is None:
                os.environ.pop("MONITOR_STATE_PATH", None)
            else:
                os.environ["MONITOR_STATE_PATH"] = previous_path
        return errors

    def start(self, once=False, handoff_only=False):
        self.preflight()
        previous = self.previous()
        if previous and previous["phase"] != FINISHED:
            raise HandoffError("前次交接尚未完成，請先執行 python local_monitor.py --resume-cloud。")
        flags = self.gh.flags()
        if flags.get("LOCAL_MONITOR_ACTIVE", "false") != "false":
            raise HandoffError("已有本機持有監聽權；請在原電腦執行 --resume-cloud。")
        if flags.get("MONITOR_ENABLED") not in ("true", "false"):
            raise HandoffError("請先確認 repo 的 MONITOR_ENABLED 開關。")
        self.claim = {"schema": 1, "session": str(uuid.uuid4()), "repository": self.gh.repository,
                      "was_enabled": flags["MONITOR_ENABLED"] == "true", "phase": "pausing",
                      "states_ready": False}
        self.save()
        errors = 0
        try:
            self.gh.flag("LOCAL_MONITOR_ACTIVE", "true")
            self.gh.flag("MONITOR_ENABLED", "false")
            self.drain()
            self.save(phase="exporting")
            self.download(self.transfer("export"))
            if not handoff_only:
                print("本機已接手。按 Ctrl+C 會完成當輪後交還雲端，請勿直接關閉視窗。", flush=True)
                while not self.stop.is_set():
                    errors = self.cycle()
                    if once or self.stop.wait(self.interval):
                        break
        finally:
            self.restore()
        return 1 if errors else 0

    def recover(self):
        Fernet(self.key.encode("ascii"))
        self.claim = self.previous()
        if not self.claim:
            raise HandoffError("找不到本機交接紀錄，無法安全交回歷史。")
        if self.claim["phase"] != FINISHED:
            # Reestablish the pause before recovering an interrupted transfer.
            self.gh.flag("LOCAL_MONITOR_ACTIVE", "true")
            self.gh.flag("MONITOR_ENABLED", "false")
            self.drain()
            self.restore()


def main():
    load_dotenv(BASE / ".env", override=False, interpolate=False)
    parser = argparse.ArgumentParser(description="本機監聽與 GitHub 雲端交接")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="執行一輪本機監聽後交回雲端")
    modes.add_argument("--handoff-only", action="store_true", help="驗證實際交接，不搜尋或發商品通知")
    modes.add_argument("--resume-cloud", action="store_true", help="將前次本機紀錄交回並恢復雲端")
    modes.add_argument("--status", action="store_true", help="唯讀查看雲端開關與本機交接階段")
    args = parser.parse_args()
    try:
        github = GitHub(os.environ.get("MONITOR_GITHUB_REPOSITORY", "").strip())
        monitor = LocalMonitor(github, os.environ.get("MONITOR_STATE_KEY", "").strip(),
                               int(os.environ.get("LOCAL_MONITOR_INTERVAL_SECONDS", "1800")))
        if args.status:
            flags = github.flags()
            claim = monitor.previous()
            print(json.dumps({"cloud_enabled": flags.get("MONITOR_ENABLED"),
                              "local_active": flags.get("LOCAL_MONITOR_ACTIVE", "false"),
                              "phase": claim.get("phase") if claim else "none"}))
            return 0
        with LocalLock(ROOT / "launcher.lock"):
            def stop(*_):
                if not monitor.stop.is_set():
                    print("收到停止要求，完成當輪及交接後離開……", flush=True)
                monitor.stop.set()
            signal.signal(signal.SIGINT, stop)
            if os.name != "nt":
                signal.signal(signal.SIGTERM, stop)
            if args.resume_cloud:
                monitor.recover()
                return 0
            return monitor.start(args.once, args.handoff_only)
    except Exception as error:
        print(str(error) if isinstance(error, HandoffError) else f"本機交接未完成：{type(error).__name__}（私人細節省略）")
        print("若雲端尚未恢復，請在同一電腦執行：python local_monitor.py --resume-cloud")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
