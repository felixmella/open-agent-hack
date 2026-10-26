"""The setup-script runner's statement splitting (scripts/zetaris_sql.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import zetaris_sql  # noqa: E402


def test_statements_split_at_line_end_semicolons_and_keep_blocks_whole(tmp_path):
    sql = tmp_path / "x_create.sql"
    sql.write_text(
        "-- a comment\n"
        "CREATE NAMESPACE a;\n"
        "-- BEGIN STATEMENT\n"
        "COMPILE USL u DEPLOY NAMESPACE a DDL\n"
        "CREATE TABLE t1 (k varchar(5) NOT NULL PRIMARY KEY);\n"
        "CREATE TABLE t2 (k varchar(5) NOT NULL PRIMARY KEY);\n"
        "-- END STATEMENT\n"
        "SELECT 1;\n", encoding="utf-8")
    assert list(zetaris_sql.statements(sql)) == [
        "CREATE NAMESPACE a",
        "COMPILE USL u DEPLOY NAMESPACE a DDL\nCREATE TABLE t1 (k varchar(5) NOT NULL PRIMARY KEY);\n"
        "CREATE TABLE t2 (k varchar(5) NOT NULL PRIMARY KEY)",
        "SELECT 1",
    ]


def test_the_usl_script_sends_its_compile_as_one_statement():
    root = Path(__file__).resolve().parent.parent
    statements = list(zetaris_sql.statements(root / "zetaris" / "07_usl_create.sql"))
    compile_ = [s for s in statements if s.startswith("COMPILE USL")]
    assert len(compile_) == 1 and compile_[0].count("CREATE TABLE") == 3
