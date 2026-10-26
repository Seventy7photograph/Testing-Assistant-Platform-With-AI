"""真实运行生成的 pytest 项目，证明模板不只是文本占位。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from app.core.config import Settings
from app.repository import Repository
from app.schemas.execution import AutomationCreateRequest
from app.services.api_service import ApiService
from app.services.execution_service import ExecutionService

FIXTURES = Path(__file__).parent / "fixtures" / "openapi"


class _PetHandler(BaseHTTPRequestHandler):
    paths: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 - HTTP handler contract
        self.paths.append(self.path)
        if self.path.split("?", 1)[0] != "/pets":
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(
            [{"id": 1, "name": "Ada", "status": "available"}]
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def test_generated_pytest_project_runs_against_local_mock_api() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        settings = Settings(
            storage_dir=root / "storage",
            storage_backend="json",
            llm_provider="none",
            llm_api_key="",
        )
        settings.ensure_dirs()
        repository = Repository(settings)
        imported = ApiService(settings, repository).import_spec(
            filename="petstore.yaml",
            data=(FIXTURES / "petstore.yaml").read_bytes(),
        )
        positive = next(
            case
            for case in repository.api_cases.list_recent(1000)
            if case.spec_id == imported.spec.spec_id
            and case.operation_id == "listPets"
            and case.category == "positive"
        )
        service = ExecutionService(settings, repository)
        artifact = service.create_artifact(
            AutomationCreateRequest(
                spec_id=imported.spec.spec_id,
                case_ids=[positive.case_id],
            )
        )
        content, _filename = service.artifact_download(artifact.artifact_id)
        project = root / "project"
        project.mkdir()
        with ZipFile(__import__("io").BytesIO(content)) as archive:
            archive.extractall(project)

        server = ThreadingHTTPServer(("127.0.0.1", 0), _PetHandler)
        _PetHandler.paths.clear()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = os.environ.copy()
            env["baseUrl"] = f"http://127.0.0.1:{server.server_port}"
            env["authToken"] = "test-token"
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)

        assert result.returncode == 0, (
            f"requests={_PetHandler.paths}\n{result.stdout}\n{result.stderr}"
        )
        assert "1 passed" in result.stdout
