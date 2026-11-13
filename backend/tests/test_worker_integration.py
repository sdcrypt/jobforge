import asyncio
import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from core import database, runs
from core.config import settings
from core.websocket import ConnectionManager, EVENT_CHANNEL
from models.profile import UserProfile
from models.run import TaskRun
from workers.celery_app import celery_app


class WorkerImportTests(unittest.TestCase):
    def test_task_execution_restores_application_path_after_celery_loader_removes_it(self):
        backend_dir = str(Path(__file__).resolve().parents[1])
        code = """
import sys
sys.path.insert(0, sys.argv[1])
from workers import tasks
sys.path[:] = [entry for entry in sys.path if entry not in ('', sys.argv[1])]
def inspect(coroutine):
    coroutine.close()
    assert tasks.APP_DIR in sys.path
    import models
tasks.run_async = inspect
tasks.maintain_runs()
tasks.execute_run('test-run')
"""
        with TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "-c", code, backend_dir], cwd=directory,
                                    capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(os.environ.get("JOBFORGE_TEST_REDIS_URL"), "Set JOBFORGE_TEST_REDIS_URL to an isolated test Redis server")
class WorkerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_celery_worker_persists_success_failure_and_publishes_events(self):
        with TemporaryDirectory() as directory:
            redis_url = os.environ["JOBFORGE_TEST_REDIS_URL"]
            postgres_url = os.environ.get("JOBFORGE_TEST_DATABASE_URL")
            schema = f"jobforge_worker_{uuid.uuid4().hex}"
            admin_engine = create_async_engine(postgres_url) if postgres_url else None
            if admin_engine:
                async with admin_engine.begin() as connection:
                    await connection.execute(CreateSchema(schema))
            database_url = postgres_url or f"sqlite+aiosqlite:///{directory}/worker.db"
            engine = create_async_engine(database_url, connect_args={"server_settings": {"search_path": schema}} if postgres_url else {})
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            worker = None
            listener = None
            original_broker = celery_app.conf.broker_url
            original_backend = celery_app.conf.result_backend
            try:
                with patch.object(database, "engine", engine), patch.object(database, "AsyncSessionLocal", sessions), patch.object(settings, "redis_url", redis_url):
                    await database.init_db()
                    async with sessions() as db:
                        db.add(UserProfile(full_name="Worker test", email="worker@example.com"))
                        await db.commit()
                    celery_app.conf.broker_url = redis_url
                    celery_app.conf.result_backend = redis_url
                    manager = ConnectionManager()
                    websocket = AsyncMock()
                    received = []
                    websocket.send_text.side_effect = lambda value: received.append(json.loads(value))
                    await manager.connect(websocket)
                    listener = asyncio.create_task(manager.listen())
                    async with Redis.from_url(redis_url) as redis:
                        for attempt in range(50):
                            counts = await redis.pubsub_numsub(EVENT_CHANNEL)
                            if counts and counts[0][1]:
                                break
                            await asyncio.sleep(0.1)
                        else:
                            self.fail("Redis event listener did not subscribe")
                    environment = {**os.environ, "DATABASE_URL": database_url, "REDIS_URL": redis_url, "DEBUG": "false", "JOBFORGE_TEST_SCHEMA": schema if postgres_url else ""}
                    code = """
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from core import database
schema = os.environ.get('JOBFORGE_TEST_SCHEMA')
database.engine = create_async_engine(os.environ['DATABASE_URL'], connect_args={'server_settings': {'search_path': schema}} if schema else {})
database.AsyncSessionLocal = async_sessionmaker(database.engine, expire_on_commit=False)
from workers.celery_app import celery_app
from workers import tasks
from workers import handlers
import asyncio
original_perform = handlers.perform_run
async def perform(record):
    if record.kind == 'cancellation_test':
        await runs.stage('waiting', 'Waiting for the stop test')
        await asyncio.Event().wait()
    return await original_perform(record)
from core import runs
handlers.perform_run = perform
import sys
from pathlib import Path
backend_dir = str(Path(tasks.__file__).resolve().parents[1])
sys.path[:] = [entry for entry in sys.path if entry not in ('', backend_dir)]
pool = 'solo' if sys.platform == 'darwin' else 'prefork'
celery_app.worker_main(['worker', f'--pool={pool}', '--concurrency=1', '--loglevel=WARNING', '--without-gossip', '--without-mingle', '--without-heartbeat'])
"""
                    worker_log = Path(directory) / "worker.log"
                    with worker_log.open("w") as output:
                        worker = subprocess.Popen([sys.executable, "-B", "-c", code], cwd=Path(__file__).resolve().parents[1], env=environment, stdout=output, stderr=subprocess.STDOUT)
                    async with sessions() as db:
                        success, created = await runs.enqueue_run(db, "rank", max_attempts=1)
                    self.assertTrue(created)
                    for attempt in range(300):
                        async with sessions() as db:
                            record = await db.get(TaskRun, success.id)
                        if record.status in runs.TERMINAL_STATUSES:
                            break
                        self.assertIsNone(worker.poll(), "Celery worker exited unexpectedly")
                        await asyncio.sleep(0.1)
                    self.assertEqual(record.status, "succeeded", record.error or worker_log.read_text())
                    self.assertEqual(record.result["jobs_ranked"], 0)
                    self.assertTrue(any(event["data"].get("run_id") == success.id for event in received))
                    async with sessions() as db:
                        failure, created = await runs.enqueue_run(db, "unsupported_test_kind", max_attempts=1)
                    for attempt in range(300):
                        async with sessions() as db:
                            record = await db.get(TaskRun, failure.id)
                        if record.status in runs.TERMINAL_STATUSES:
                            break
                        await asyncio.sleep(0.1)
                    self.assertEqual(record.status, "failed")
                    self.assertEqual(record.error_type, "ValueError")
                    self.assertIn("Unknown task kind", record.error)
                    self.assertIsNotNone(record.finished_at)
                    # A stopped task must free the single worker slot for the next run.
                    async with sessions() as db:
                        stopped, _ = await runs.enqueue_run(db, "cancellation_test", max_attempts=1)
                    for attempt in range(300):
                        async with sessions() as db:
                            record = await db.get(TaskRun, stopped.id)
                        if record.stage == "waiting":
                            break
                        await asyncio.sleep(0.1)
                    self.assertEqual(record.stage, "waiting", worker_log.read_text())
                    async with sessions() as db:
                        await runs.cancel_run(db, stopped.id)
                        next_run, _ = await runs.enqueue_run(db, "rank", max_attempts=1)
                    for attempt in range(300):
                        async with sessions() as db:
                            record = await db.get(TaskRun, next_run.id)
                        if record.status in runs.TERMINAL_STATUSES:
                            break
                        await asyncio.sleep(0.1)
                    self.assertEqual(record.status, "succeeded", worker_log.read_text())
                    async with sessions() as db:
                        self.assertEqual((await db.get(TaskRun, stopped.id)).status, "cancelled")
            finally:
                celery_app.conf.broker_url = original_broker
                celery_app.conf.result_backend = original_backend
                if listener:
                    listener.cancel()
                    await asyncio.gather(listener, return_exceptions=True)
                if worker:
                    worker.terminate()
                    try:
                        await asyncio.to_thread(worker.wait, timeout=10)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        await asyncio.to_thread(worker.wait, timeout=5)
                await engine.dispose()
                if admin_engine:
                    async with admin_engine.begin() as connection:
                        await connection.execute(DropSchema(schema, cascade=True))
                    await admin_engine.dispose()
