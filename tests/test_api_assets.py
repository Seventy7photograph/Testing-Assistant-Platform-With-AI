"""V2.2：OpenAPI 导入、接口用例生成与 Postman 导出回归。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.exceptions import OpenApiParseError
from app.core.config import Settings
from app.design.api_cases import generate_api_cases
from app.exporters.postman_exporter import SCHEMA_URL, PostmanExporter
from app.parsers.openapi_parser import parse_openapi
from app.repository import Repository
from app.services.api_service import ApiService

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "openapi"


def petstore_bytes() -> bytes:
    return (FIXTURES / "petstore.yaml").read_bytes()


def parsed_petstore():
    return parse_openapi(
        petstore_bytes(),
        filename="petstore.yaml",
        spec_id="API-petstore-test",
    )


class TestOpenApiParser:
    def test_yaml_refs_and_operation_inventory(self) -> None:
        spec = parsed_petstore()
        assert spec.title == "Petstore"
        assert spec.version == "1.0.0"
        assert spec.openapi_version == "3.0.3"
        assert spec.source_format == "yaml"
        assert {item.operation_id for item in spec.operations} == {
            "listPets",
            "createPet",
            "getPet",
        }
        create = next(item for item in spec.operations if item.operation_id == "createPet")
        assert create.request_body is not None
        assert create.request_body.required is True
        assert create.security == [{"bearerAuth": []}]
        assert create.requirement_ids == ["REQ-PET-002"]
        pet_schema = next(
            response for response in create.responses if response.status_code == "201"
        ).content[0].schema_
        assert pet_schema["allOf"][0]["properties"]["name"]["type"] == "string"
        assert pet_schema["allOf"][1]["properties"]["id"]["type"] == "integer"
        assert set(pet_schema["allOf"][0]["required"]) == {"name", "status"}

    def test_circular_ref_is_warned_not_silently_dropped(self) -> None:
        spec = parse_openapi(
            (FIXTURES / "circular.yaml").read_bytes(),
            filename="circular.yaml",
            spec_id="API-circular",
        )
        assert len(spec.operations) == 1
        assert any("循环 $ref" in item for item in spec.warnings)
        result = generate_api_cases(spec)
        assert any(
            assertion.status == "manual"
            for case in result.cases
            for assertion in case.assertions
        )

    def test_missing_ref_returns_actionable_error(self) -> None:
        payload = b"""\
openapi: 3.0.3
info: {title: Broken, version: 1.0.0}
paths:
  /x:
    get:
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Missing'}
"""
        with pytest.raises(OpenApiParseError, match="无法解析"):
            parse_openapi(payload, filename="broken.yaml")

    def test_swagger_2_is_rejected_explicitly(self) -> None:
        payload = b'{"swagger":"2.0","info":{"title":"old","version":"1"},"paths":{}}'
        with pytest.raises(OpenApiParseError, match="Swagger 2.0"):
            parse_openapi(payload, filename="swagger.json")

    def test_json_is_supported(self) -> None:
        payload = {
            "openapi": "3.0.3",
            "info": {"title": "JSON API", "version": "1.0"},
            "paths": {"/ping": {"get": {"responses": {"200": {"description": "ok"}}}}},
        }
        spec = parse_openapi(
            json.dumps(payload).encode(),
            filename="api.json",
            spec_id="API-json",
        )
        assert spec.source_format == "json"
        assert spec.operations[0].path == "/ping"


class TestApiCaseGeneration:
    def test_each_operation_has_positive_and_negative_case(self) -> None:
        spec = parsed_petstore()
        result = generate_api_cases(spec)
        for operation in spec.operations:
            categories = {
                case.category for case in result.cases if case.operation_id == operation.operation_id
            }
            assert "positive" in categories
            assert categories & {"negative", "boundary", "security"}
            positive = next(
                case
                for case in result.cases
                if case.operation_id == operation.operation_id and case.category == "positive"
            )
            assert positive.execution.headers["Authorization"] == "Bearer {{authToken}}"
        assert spec.stats.cases == len(result.cases)
        assert spec.stats.positive_cases == len(spec.operations)
        assert all(
            assertion.expected < 500
            for case in result.cases
            if case.category != "positive"
            for assertion in case.assertions
            if assertion.kind == "status" and assertion.status == "defined"
        ), "负向用例应优先断言 4xx，不能把兜底 500 当成确定业务异常"

    def test_constraints_generate_boundaries_and_contract_assertions(self) -> None:
        spec = parsed_petstore()
        result = generate_api_cases(spec)
        titles = [case.title for case in result.cases]
        assert any("小于最小长度" in title for title in titles if "name" in title)
        assert any("大于最大长度" in title for title in titles if "name" in title)
        assert any("小于最小值" in title for title in titles if "limit" in title)
        assertions = [
            assertion
            for case in result.cases
            if case.operation_id == "createPet" and case.category == "positive"
            for assertion in case.assertions
        ]
        assert any(item.operator == "type" and item.path == "$.id" for item in assertions)
        assert any(item.operator == "in" and item.path == "$.status" for item in assertions)
        assert any(item.operator == "exists" and item.path == "$.name" for item in assertions)
        assert all(item.source_ref for item in assertions if item.status == "defined")

    def test_response_examples_are_not_treated_as_fixed_assertions(self) -> None:
        spec = parsed_petstore()
        result = generate_api_cases(spec)
        rendered = json.dumps(
            [
                assertion.model_dump(mode="json")
                for case in result.cases
                for assertion in case.assertions
            ],
            ensure_ascii=False,
        )
        assert "ExampleOnly" not in rendered
        assert "999" not in rendered

    def test_nullable_union_is_asserted_without_manual_branch(self) -> None:
        payload = {
            "openapi": "3.1.0",
            "info": {"title": "Nullable API", "version": "1.0"},
            "paths": {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["name"],
                                            "properties": {
                                                "name": {
                                                    "anyOf": [
                                                        {"type": "string"},
                                                        {"type": "null"},
                                                    ]
                                                }
                                            },
                                        }
                                    }
                                },
                            }
                        }
                    }
                }
            },
        }
        spec = parse_openapi(json.dumps(payload).encode(), filename="nullable.json", spec_id="API-null")
        positive = next(case for case in generate_api_cases(spec).cases if case.category == "positive")
        name_assertions = [item for item in positive.assertions if item.path == "$.name"]
        assert any(
            item.operator == "type"
            and item.expected == "string"
            and item.allow_null
            for item in name_assertions
        )
        assert any(item.operator == "nullable" for item in name_assertions)
        assert not any(item.status == "manual" for item in name_assertions)

    def test_optional_response_property_assertion_allows_absence(self) -> None:
        payload = {
            "openapi": "3.0.3",
            "info": {"title": "Optional API", "version": "1.0"},
            "paths": {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "optional_name": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            }
                        }
                    }
                }
            },
        }
        spec = parse_openapi(json.dumps(payload).encode(), filename="optional.json", spec_id="API-opt")
        positive = next(case for case in generate_api_cases(spec).cases if case.category == "positive")
        optional_assertions = [
            item for item in positive.assertions if item.path == "$.optional_name"
        ]
        assert optional_assertions
        assert all(item.allow_absent for item in optional_assertions)

    def test_secret_schema_fields_use_environment_placeholders(self) -> None:
        payload = {
            "openapi": "3.0.3",
            "info": {"title": "Auth API", "version": "1.0"},
            "servers": [{"url": "https://example.test"}],
            "paths": {
                "/login": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["password"],
                                        "properties": {
                                            "password": {
                                                "type": "string",
                                                "example": "super-secret-password",
                                            }
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        spec = parse_openapi(json.dumps(payload).encode(), filename="auth.json", spec_id="API-auth")
        result = generate_api_cases(spec)
        positive = next(case for case in result.cases if case.category == "positive")
        assert positive.execution.body["password"].startswith("{{")
        assert "super-secret-password" not in json.dumps(positive.execution.body)
        names = {item["name"] for item in positive.execution.environment_variables}
        assert "password" in names


class TestPostmanExport:
    def test_collection_2_1_is_importable_and_traceable(self) -> None:
        spec = parsed_petstore()
        cases = generate_api_cases(spec).cases
        result = PostmanExporter().export_api(spec, cases)
        collection = json.loads(result.content)
        assert result.filename.endswith(".postman_collection.json")
        assert collection["info"]["schema"] == SCHEMA_URL
        assert collection["info"]["name"] == "Petstore"
        assert len(collection["item"]) == 3
        requests = [
            request
            for folder in collection["item"]
            for request in folder["item"]
        ]
        assert all(item["request"]["url"]["raw"].startswith("{{baseUrl}}") for item in requests)
        scripts = "\n".join(
            line
            for request in requests
            for event in request.get("event", [])
            for line in event["script"]["exec"]
        )
        assert "pm.response.to.have.status" in scripts
        assert "valuesAtPath" in scripts
        assert "Array.isArray(value)" in scripts
        assert "{{authToken}}" in result.content.decode("utf-8")
        assert all(
            item["type"] in {"string", "boolean", "any", "number"}
            for item in collection["variable"]
        )

    def test_collection_never_contains_literal_credentials(self) -> None:
        spec = parsed_petstore()
        cases = generate_api_cases(spec).cases
        text = PostmanExporter().export_api(spec, cases).content.decode("utf-8")
        for forbidden in ("super-secret-token", "api_key=live", "Bearer sk-"):
            assert forbidden not in text


class TestApiAssetRoutes:
    def test_sqlite_backend_persists_spec_cases_and_cleanup(self, tmp_path: Path) -> None:
        settings = Settings(
            storage_dir=tmp_path,
            storage_backend="sqlite",
            llm_provider="none",
            llm_api_key="",
        )
        settings.ensure_dirs()
        service = ApiService(settings, Repository(settings))
        imported = service.import_spec(filename="petstore.yaml", data=petstore_bytes())
        spec_id = imported.spec.spec_id

        reopened = Repository(settings)
        assert reopened.api_specs.get(spec_id).stats.cases == imported.spec.stats.cases
        assert len(
            [case for case in reopened.api_cases.list_recent(100) if case.spec_id == spec_id]
        ) == imported.spec.stats.cases

        deleted = service.delete_spec(spec_id)
        assert deleted.deleted_cases == imported.spec.stats.cases
        assert not reopened.api_specs.exists(spec_id)

    def test_import_inspect_export_and_delete(self, client) -> None:
        upload = client.post(
            f"{API}/api-specs/import",
            files={"file": ("petstore.yaml", petstore_bytes(), "application/yaml")},
            data={"title": "Petstore API"},
        )
        assert upload.status_code == 200, upload.text
        imported = upload.json()["data"]
        spec = imported["spec"]
        assert spec["title"] == "Petstore API"
        assert spec["stats"]["operations"] == 3
        assert spec["stats"]["cases"] >= 6

        listed = client.get(f"{API}/api-specs").json()["data"]
        assert any(item["spec_id"] == spec["spec_id"] for item in listed)

        detail = client.get(f"{API}/api-specs/{spec['spec_id']}").json()["data"]
        assert len(detail["operations"]) == 3
        assert detail["source_file"] == "petstore.yaml"

        operation = client.get(
            f"{API}/api-specs/{spec['spec_id']}/operations/createPet"
        ).json()["data"]
        assert operation["request_body"]["required"] is True

        cases = client.get(
            f"{API}/api-specs/{spec['spec_id']}/cases",
            params={"operation_id": "createPet"},
        ).json()["data"]["cases"]
        assert cases
        assert all(item["operation_id"] == "createPet" for item in cases)
        assert any(item["requirement_ids"] == ["REQ-PET-002"] for item in cases)

        review = client.post(f"{API}/api-specs/{spec['spec_id']}/review")
        assert review.status_code == 200, review.text
        review_data = review.json()["data"]
        assert review_data["meta"]["used"] is True
        assert review_data["meta"]["status"] == "completed"
        assert review_data["meta"]["prompt_id"] == "api.case_review"
        assert review_data["findings"]
        persisted_review = client.get(
            f"{API}/api-specs/{spec['spec_id']}"
        ).json()["data"]["ai_review"]
        assert persisted_review["meta"]["status"] == "completed"
        duplicate_review = client.post(f"{API}/api-specs/{spec['spec_id']}/review")
        assert duplicate_review.status_code == 409
        assert duplicate_review.json()["code"] == "CONFLICT"
        unchanged = client.get(
            f"{API}/api-specs/{spec['spec_id']}/cases",
            params={"operation_id": "createPet"},
        ).json()["data"]["cases"]
        assert len(unchanged) == len(cases)

        postman = client.get(f"{API}/api-specs/{spec['spec_id']}/export/postman")
        assert postman.status_code == 200
        assert postman.headers["content-type"].startswith("application/json")
        assert json.loads(postman.content)["info"]["schema"] == SCHEMA_URL

        deleted = client.delete(f"{API}/api-specs/{spec['spec_id']}")
        assert deleted.status_code == 200
        assert deleted.json()["data"]["deleted_cases"] == spec["stats"]["cases"]
        assert client.get(f"{API}/api-specs/{spec['spec_id']}").status_code == 404

    def test_import_rejects_unsupported_extension_and_bad_ref(self, client) -> None:
        bad_ext = client.post(
            f"{API}/api-specs/import",
            files={"file": ("api.txt", b"hello", "text/plain")},
        )
        assert bad_ext.status_code == 415

        payload = b"""\
openapi: 3.0.3
info: {title: Broken, version: 1.0.0}
paths:
  /x:
    get:
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Missing'}
"""
        bad_ref = client.post(
            f"{API}/api-specs/import",
            files={"file": ("broken.yaml", payload, "application/yaml")},
        )
        assert bad_ref.status_code == 422
        assert bad_ref.json()["code"] == "OPENAPI_PARSE_FAILED"

    def test_generic_case_export_rejects_postman_with_guidance(self, client) -> None:
        suite = client.post(
            f"{API}/pipeline/generate",
            json={"text": "# API\n## 接口\n字段：必填", "methods": ["equivalence"], "use_llm": False},
        ).json()["data"]["suite"]
        response = client.post(
            f"{API}/export",
            json={"suite_id": suite["suite_id"], "format": "postman"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "BAD_REQUEST"
        assert "接口规范" in response.json()["message"]
