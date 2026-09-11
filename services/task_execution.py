"""Concurrent task execution with FIFO exclusion for overlapping libraries."""
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import math


class TaskStopped(Exception):
    pass


class TaskTimedOut(TaskStopped):
    pass


def task_time_limit(value):
    try:
        hours = float(value or 0)
    except (ValueError, TypeError):
        raise ValueError("时间限制应为非负数，步长为 0.5 h") from None
    if not math.isfinite(hours) or hours < 0 or hours * 2 != int(hours * 2):
        raise ValueError("时间限制应为非负数，步长为 0.5 h")
    return hours


class TaskExecutor:
    def __init__(self, root):
        self.root = root
        self.condition = threading.Condition(threading.RLock())
        self.jobs = {}
        self.local = threading.local()
        self.last_result = None
        self.last_error = None

    def submit(self, key, targets, work, timeout_seconds=0):
        with self.condition:
            if key in self.jobs:
                return False
            job = dict(id=key, targets=set(targets), state="queued", stopping=False,
                       stop=threading.Event(), process=None, execution_id=secrets.token_hex(12),
                       timeout_seconds=timeout_seconds, deadline=None)
            self.jobs[key] = job
            threading.Thread(target=self._worker, args=(job, work), daemon=True,
                             name=f"Task-{key}").start()
        return True

    def _ready(self, job):
        # Earlier overlapping queued jobs have priority too, preventing starvation.
        for other in self.jobs.values():
            if other is job:
                break
            if job["targets"] & other["targets"]:
                return False
        return not any(other is not job and other["state"] == "running"
                       and job["targets"] & other["targets"] for other in self.jobs.values())

    def _worker(self, job, work):
        self.local.job = job
        try:
            with self.condition:
                self.condition.wait_for(lambda: job["stop"].is_set() or self._ready(job))
                if job["stop"].is_set():
                    raise TaskStopped()
                job["state"] = "running"
                if job["timeout_seconds"]:
                    job["deadline"] = time.monotonic() + job["timeout_seconds"]
            result = work()
            with self.condition:
                self.last_result = "stopped" if job["stop"].is_set() else result
        except TaskTimedOut:
            with self.condition:
                self.last_result = "timed_out"
                self.last_error = "任务达到时间限制，已停止"
        except TaskStopped:
            with self.condition:
                self.last_result = "stopped"
        except Exception as exc:
            with self.condition:
                self.last_error = str(exc)
        finally:
            with self.condition:
                self.jobs.pop(job["id"], None)
                self.condition.notify_all()
            del self.local.job

    def stop(self, key):
        with self.condition:
            job = self.jobs.get(key)
            if job is None:
                return False
            job["stop"].set()
            job["stopping"] = True
            process = job["process"]
            if process is not None and process.poll() is None:
                process.terminate()
            self.condition.notify_all()
        return True

    def run_process(self, module, payload):
        job = self.local.job
        with self.condition:
            if job["stop"].is_set():
                raise TaskStopped()
            remaining = None if job["deadline"] is None else job["deadline"] - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TaskTimedOut()
            env = dict(os.environ, BANGUMI_EXECUTION_ID=job["execution_id"],
                       BANGUMI_EXECUTION_SERVER=str(payload.get("server_id") or ""))
            process = subprocess.Popen(
                [sys.executable, "-m", module], stdin=subprocess.PIPE,
                text=True, encoding="utf-8", cwd=self.root, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            job["process"] = process
        try:
            try:
                process.communicate(json.dumps(payload), timeout=remaining)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise TaskTimedOut() from None
            except (BrokenPipeError, OSError):
                if job["stop"].is_set():
                    process.wait()
                    raise TaskStopped()
                raise
            if job["stop"].is_set():
                raise TaskStopped()
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, process.args)
        finally:
            with self.condition:
                job["process"] = None

    def snapshot(self):
        with self.condition:
            tasks = {key: {name: job[name] for name in ("state", "stopping")}
                     for key, job in self.jobs.items()}
            return dict(running=bool(tasks), tasks=tasks,
                        last_result=self.last_result, last_error=self.last_error)
