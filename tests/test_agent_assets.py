import json
import re
import unittest
from pathlib import Path

from agent.retrieval.ollama_topk import build_entry_text, cosine_similarity


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "agent" / "knowledge" / "media_review_rules.json"
KNOWLEDGE_SOURCE_PATH = ROOT / "agent" / "knowledge" / "SOURCES.md"
DIFY_DOCUMENT_PATH = ROOT / "agent" / "knowledge" / "dify_media_review_rules.md"
OLLAMA_ACCEPTANCE_PATH = (
    ROOT / "docs" / "evidence" / "OLLAMA_KNOWLEDGE_ACCEPTANCE.md"
)
OLLAMA_RESULTS_PATH = ROOT / "docs" / "evidence" / "ollama_topk_results.json"
INPUT_SCHEMA_PATH = ROOT / "agent" / "schemas" / "agent_input.schema.json"
OUTPUT_SCHEMA_PATH = ROOT / "agent" / "schemas" / "agent_output.schema.json"
PROMPT_PATH = ROOT / "agent" / "prompts" / "review_agent_v1.md"
WORKFLOW_PATH = ROOT / "docs" / "AGENT_WORKFLOW.md"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class AgentKnowledgeAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.knowledge = load_json(KNOWLEDGE_PATH)["knowledge_base"]
        cls.entries = cls.knowledge["entries"]

    def test_knowledge_ids_and_required_fields(self) -> None:
        identifiers = [entry["knowledge_id"] for entry in self.entries]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertGreaterEqual(len(identifiers), 10)

        allowed_states = set(self.knowledge["allowed_review_states"])
        self.assertEqual(allowed_states, {"pass", "needs_review", "reject"})
        for entry in self.entries:
            self.assertRegex(entry["knowledge_id"], r"^KB-[A-Z]+-\d{3}$")
            self.assertTrue(entry["title"])
            self.assertTrue(entry["category"])
            self.assertTrue(entry["keywords"])
            self.assertIn(entry["review_recommendation"], allowed_states)
            self.assertTrue(entry["suggestions"])
            self.assertTrue(entry["required_evidence_fields"])
            self.assertIn("always_apply", entry["match"])
            self.assertIn("detected_classes", entry["match"])
            self.assertIn("metrics", entry["match"])

    def test_hybrid_retrieval_contract_includes_embedding_and_fallback(self) -> None:
        retrieval = self.knowledge["retrieval"]
        self.assertEqual(retrieval["strategy"], "hybrid")
        self.assertEqual(retrieval["embedding"]["acceptance_provider"], "ollama")
        self.assertEqual(retrieval["embedding"]["default_provider"], "ollama")
        self.assertEqual(retrieval["embedding"]["local_provider"], "ollama")
        self.assertEqual(retrieval["embedding"]["source_document"], DIFY_DOCUMENT_PATH.name)
        self.assertEqual(retrieval["embedding"]["expected_chunks"], len(self.entries))
        self.assertEqual(retrieval["embedding"]["model_env"], "OLLAMA_EMBED_MODEL")
        self.assertEqual(retrieval["vector_search"]["metric"], "cosine")
        self.assertGreater(retrieval["vector_search"]["top_k"], 0)
        self.assertGreaterEqual(retrieval["vector_search"]["min_similarity"], 0)
        self.assertLessEqual(retrieval["vector_search"]["min_similarity"], 1)
        self.assertEqual(
            retrieval["fallback"]["mode"],
            "lexical_class_metric",
        )
        self.assertEqual(retrieval["fallback"]["mark_status"], "degraded")
        self.assertEqual(
            set(retrieval["result_fields"]),
            {"knowledge_id", "similarity", "match_reasons"},
        )

    def test_knowledge_is_searchable_by_keyword_and_class(self) -> None:
        def keyword_matches(query: str) -> set[str]:
            normalized = query.casefold()
            return {
                entry["knowledge_id"]
                for entry in self.entries
                if any(normalized in keyword.casefold() for keyword in entry["keywords"])
            }

        def class_matches(class_name: str) -> set[str]:
            normalized = class_name.casefold()
            return {
                entry["knowledge_id"]
                for entry in self.entries
                if normalized
                in {
                    value.casefold()
                    for value in entry["match"]["detected_classes"]
                }
            }

        self.assertIn("KB-QUALITY-002", keyword_matches("low confidence"))
        self.assertIn("KB-CLASS-001", class_matches("person"))
        self.assertIn("KB-CLASS-002", class_matches("car"))
        self.assertGreaterEqual(
            sum(bool(entry["match"]["always_apply"]) for entry in self.entries),
            2,
        )

    def test_knowledge_has_multiple_review_categories(self) -> None:
        categories = {entry["category"] for entry in self.entries}
        self.assertGreaterEqual(len(categories), 5)
        self.assertIn("evidence_boundary", categories)
        self.assertIn("evidence_quality", categories)
        self.assertIn("detected_class", categories)
        self.assertIn("review_policy", categories)

    def test_dify_source_document_has_one_section_per_knowledge_entry(self) -> None:
        document = DIFY_DOCUMENT_PATH.read_text(encoding="utf-8")
        identifiers = [entry["knowledge_id"] for entry in self.entries]
        for identifier in identifiers:
            self.assertEqual(document.count(f"## {identifier} "), 1)
            self.assertEqual(document.count(f"知识条目 ID：{identifier}"), 1)
        self.assertEqual(document.count("\n---\n"), len(identifiers))

        sources = KNOWLEDGE_SOURCE_PATH.read_text(encoding="utf-8")
        for source_id in ("SRC-PROJECT-001", "SRC-COURSE-001", "SRC-RULES-001"):
            self.assertIn(source_id, sources)

    def test_ollama_acceptance_contains_real_topk_results(self) -> None:
        acceptance = OLLAMA_ACCEPTANCE_PATH.read_text(encoding="utf-8")
        result = load_json(OLLAMA_RESULTS_PATH)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(result["top_k"], 5)
        self.assertEqual(result["document_count"], len(self.entries))
        self.assertGreater(result["vector_dimension"], 0)
        self.assertEqual(len(result["queries"]), 2)
        for query in result["queries"]:
            self.assertEqual(len(query["results"]), 5)
            self.assertTrue(
                all(item["match_reasons"] for item in query["results"])
            )
        self.assertEqual(
            result["queries"][0]["results"][0]["knowledge_id"],
            "KB-QUALITY-001",
        )
        self.assertEqual(
            result["queries"][1]["results"][0]["knowledge_id"],
            "KB-QUALITY-002",
        )
        self.assertIn("Top-K | `5`", acceptance)
        self.assertIn("未人工填写相似度", acceptance)

    def test_local_embedding_text_and_cosine_helpers(self) -> None:
        text = build_entry_text(self.entries[0])
        self.assertIn(self.entries[0]["knowledge_id"], text)
        self.assertIn(self.entries[0]["title"], text)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)


class AgentSchemaAndPromptTests(unittest.TestCase):
    def test_input_schema_matches_current_report_contract(self) -> None:
        schema = load_json(INPUT_SCHEMA_PATH)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            set(schema["required"]),
            {"schema_version", "job_id", "provider", "analysis_report"},
        )
        report = schema["properties"]["analysis_report"]
        self.assertTrue(
            {"duration", "total_sampled_frames", "keyframes", "segments"}.issubset(
                report["required"]
            )
        )
        provider_types = set(
            schema["properties"]["provider"]["properties"]["type"]["enum"]
        )
        self.assertEqual(provider_types, {"ollama", "dify", "coze", "rule_only"})

    def test_output_schema_contains_required_business_and_trace_fields(self) -> None:
        schema = load_json(OUTPUT_SCHEMA_PATH)
        required = set(schema["required"])
        self.assertTrue(
            {
                "summary",
                "tags",
                "suggestions",
                "review",
                "evidence_refs",
                "knowledge_refs",
                "trace",
                "errors",
            }.issubset(required)
        )
        review_states = set(
            schema["properties"]["review"]["properties"]["recommendation"]["enum"]
        )
        self.assertEqual(review_states, {"pass", "needs_review", "reject"})
        tool_names = set(
            schema["properties"]["trace"]["properties"]["tools"]["items"]["properties"][
                "name"
            ]["enum"]
        )
        self.assertEqual(
            tool_names,
            {
                "report_parser",
                "knowledge_retriever",
                "advice_generator",
                "rule_validator",
            },
        )

    def test_prompt_is_portable_and_enforces_evidence_boundaries(self) -> None:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.assertIn("{{job_id}}", prompt)
        self.assertIn("{{visual_summary_json}}", prompt)
        self.assertIn("{{knowledge_context_json}}", prompt)
        self.assertIn("evidence_refs", prompt)
        self.assertIn("knowledge_refs", prompt)
        self.assertIn("needs_review", prompt)
        self.assertRegex(prompt, re.compile(r"禁止生成.*击杀.*爆头"))

        workflow = WORKFLOW_PATH.read_text(encoding="utf-8").casefold()
        for provider in ("ollama", "dify", "coze", "rule_only"):
            self.assertIn(provider, workflow)
        for retrieval_term in ("embedding", "余弦相似度", "top-k", "degraded"):
            self.assertIn(retrieval_term, workflow)
        self.assertNotIn("sk-", workflow)


if __name__ == "__main__":
    unittest.main()
