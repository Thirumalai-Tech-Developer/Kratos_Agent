"""Tests for 4-tier Cognitive Memory Architecture and Structural Output Tool Extraction."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kratos_agent.brain.tool_calls import extract_tool_calls_from_text
from kratos_agent.core.cognitive_memory import CognitiveMemoryStore, MemoryType
from kratos_agent.core.d1_client import D1DatabaseClient
from kratos_agent.core.memory import AgenticMemory
from kratos_agent.main import KratosRuntime, KRATOS_STRUCTURAL_OUTPUT_PROMPT, KRATOS_COGNITIVE_MEMORY_PROMPT
from kratos_agent.utils.tools import save_memory, read_memory, clear_memory


class TestCognitiveMemory(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_d1.db"
        self.storage_dir = self.temp_dir / "memory"
        self.db = D1DatabaseClient(local_db_path=self.db_path)
        self.db.init_schema()
        self.store = CognitiveMemoryStore(db=self.db, storage_dir=self.storage_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_store_and_recall_all_four_types(self):
        # 1. Semantic
        self.store.store(
            memory_type=MemoryType.SEMANTIC,
            key="tech_stack",
            content="FastAPI backend with React Vite frontend",
            metadata={"domain": "architecture"}
        )

        # 2. Procedural
        self.store.store(
            memory_type=MemoryType.PROCEDURAL,
            key="build_command",
            content="uv run kratos build && npm run build",
            metadata={"scope": "deployment"}
        )

        # 3. Working
        self.store.store(
            memory_type=MemoryType.WORKING,
            key="active_task",
            content="Implement Ben 10 Omnitrix component",
            session_id="session_test_01"
        )

        # 4. Episodic
        self.store.store(
            memory_type=MemoryType.EPISODIC,
            key="turn_123",
            content="Executed npm test -> Failed with missing tailwindcss -> Installed tailwindcss -> Passed",
            session_id="session_test_01"
        )

        # Verify recalls
        semantic = self.store.recall(memory_type="semantic")
        self.assertEqual(len(semantic), 1)
        self.assertEqual(semantic[0]["key"], "tech_stack")
        self.assertIn("FastAPI", semantic[0]["content"])

        procedural = self.store.recall(memory_type="procedural")
        self.assertEqual(len(procedural), 1)
        self.assertEqual(procedural[0]["key"], "build_command")

        working = self.store.recall(memory_type="working", session_id="session_test_01")
        self.assertEqual(len(working), 1)
        self.assertEqual(working[0]["key"], "active_task")

        episodic = self.store.recall(memory_type="episodic", session_id="session_test_01")
        self.assertEqual(len(episodic), 1)
        self.assertIn("tailwindcss", episodic[0]["content"])

        # Check summary
        summary = self.store.get_summary()
        self.assertEqual(summary["semantic"], 1)
        self.assertEqual(summary["procedural"], 1)
        self.assertEqual(summary["working"], 1)
        self.assertEqual(summary["episodic"], 1)

    def test_disk_mirror_persistence(self):
        self.store.store(
            memory_type=MemoryType.SEMANTIC,
            key="conventions",
            content="Use TypeScript strict mode everywhere"
        )
        disk_file = self.storage_dir / "semantic.json"
        self.assertTrue(disk_file.exists())
        data = json.loads(disk_file.read_text(encoding="utf-8"))
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]["key"], "conventions")

    def test_prompt_context_rendering(self):
        self.store.store(MemoryType.SEMANTIC, "db_engine", "Cloudflare D1 SQL")
        self.store.store(MemoryType.WORKING, "current_step", "Verifying test suite", session_id="sess_abc")

        ctx = self.store.get_prompt_context(session_id="sess_abc")
        self.assertIn("COGNITIVE MEMORY BASE", ctx)
        self.assertIn("db_engine", ctx)
        self.assertIn("current_step", ctx)

    def test_clear_memory_by_type(self):
        self.store.store(MemoryType.WORKING, "note1", "Testing", session_id="sess_1")
        self.store.store(MemoryType.SEMANTIC, "fact1", "Persistent Fact")

        self.store.clear(MemoryType.WORKING, session_id="sess_1")
        working_recalled = self.store.recall(MemoryType.WORKING, session_id="sess_1")
        self.assertEqual(len(working_recalled), 0)

        semantic_recalled = self.store.recall(MemoryType.SEMANTIC)
        self.assertEqual(len(semantic_recalled), 1)


class TestDSMLToolCallExtraction(unittest.TestCase):

    def test_extract_deepseek_dsml_tool_call(self):
        raw = (
            'Node 24 and npm 11 are available. Let me check the target directory and scaffold the Vite project.\n'
            '<tool>{"name": "run_terminal_command", "arguments": {"command": "if exist \\"C:\\\\Users\\\\thiru\\\\Documents\\\\ben 10\\" (dir \\"C:\\\\Users\\\\thiru\\\\Documents\\\\ben 10\\") else (echo DIRECTORY_DOES_NOT_EXIST)"}}</｜｜DSML｜｜ parameter>\n'
            '</｜｜DSML｜｜ invoke>\n'
            '</｜｜DSML｜｜ calls>'
        )
        clean_text, calls = extract_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "run_terminal_command")
        self.assertIn("if exist", calls[0]["args"]["command"])
        self.assertNotIn("</｜｜DSML｜｜", clean_text)
        self.assertNotIn("<tool>", clean_text)
        self.assertIn("Node 24 and npm 11 are available", clean_text)

    def test_extract_standard_tool_tag(self):
        raw = '<tool>{"name": "write_file", "arguments": {"file_path": "src/App.jsx", "content": "export default function App() {}"}}</tool>'
        clean_text, calls = extract_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "write_file")
        self.assertEqual(calls[0]["args"]["file_path"], "src/App.jsx")

    def test_extract_deepseek_v3_format(self):
        raw = (
            '<｜tool calls｜><｜tool call begin｜>function<｜tool sep｜>read_file\n'
            '```json\n'
            '{"file_path": "package.json"}\n'
            '```<｜tool call end｜>'
        )
        clean_text, calls = extract_tool_calls_from_text(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "read_file")
        self.assertEqual(calls[0]["args"]["file_path"], "package.json")


class TestMemoryToolsAndInstructions(unittest.TestCase):

    def test_memory_tools_execution(self):
        save_res = save_memory("semantic", "test_rule", "Always write unit tests first")
        self.assertIn("Successfully saved", save_res)

        read_res = read_memory(memory_type="semantic", key="test_rule")
        self.assertIn("test_rule", read_res)
        self.assertIn("Always write unit tests first", read_res)

        clear_res = clear_memory("working")
        self.assertIn("Cleared cognitive memory", clear_res)

    def test_instruction_engine_assembly(self):
        runtime = KratosRuntime()
        sections = runtime.instructions.build()
        section_names = [s["name"] for s in sections]

        self.assertIn("structural-output-enforcement", section_names)
        self.assertIn("cognitive-memory-framework", section_names)

        sys_text = runtime.instructions.as_system_text(sections)
        self.assertIn("STRUCTURAL OUTPUT & TOOL INVOCATION PROTOCOL", sys_text)
        self.assertIn("4-TIER COGNITIVE MEMORY ARCHITECTURE", sys_text)


if __name__ == "__main__":
    unittest.main()
