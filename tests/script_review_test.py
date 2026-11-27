import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from script_review import compare_script, word_text


def cue(text, start=0, end=1_000):
    return {"text": text, "startMs": start, "endMs": end}


class ScriptReviewTest(unittest.TestCase):
    def test_word_paragraphs_and_tables_follow_document_order(self):
        xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:r><w:t>欢迎</w:t></w:r><w:r><w:t>收看</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:del><w:r><w:delText>已删除</w:delText></w:r></w:del>
        <w:r><w:t>表格内容</w:t><w:br/><w:t>同段换行</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        </w:body></w:document>"""
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "测试脚本.docx"
            with ZipFile(file, "w") as document:
                document.writestr("word/document.xml", xml.encode())
            self.assertEqual(word_text(str(file)), ("测试脚本.docx", "欢迎收看\n表格内容\n同段换行"))

    def test_ignores_format_but_preserves_decimal_and_uses_continuous_text(self):
        script = "欢迎使用 ＡＢＣ！结果是 12.5%。"
        matching = [cue("欢迎使用 a"), cue("bc结果是12.5%", 1_000, 2_000)]
        self.assertEqual(compare_script(script, matching)["total"], 0)
        different = [cue("欢迎使用 a"), cue("bc结果是125%", 1_000, 2_000)]
        results = compare_script(script, different)
        self.assertEqual(results["total"], 1)
        self.assertEqual(results["differences"][0]["startMs"], 1_000)

    def test_word_differences_map_to_cue_times_and_nearby_anchors(self):
        script = "欢迎来到海港。今天安排是巡查仓库。随后召开会议。请穿戴手套。最后登记访客。谢谢配合。"
        cues = [
            cue("欢迎来到海港"),
            cue("今天安排是巡查车库", 1_000, 2_000),
            cue("随后召开会议", 2_000, 3_000),
            cue("最后登记访客", 4_000, 5_000),
            cue("请关闭窗户", 5_000, 6_000),
            cue("谢谢配合", 6_000, 7_000),
        ]
        result = compare_script(script, cues)
        self.assertEqual(result["counts"], {"changed": 1, "script-only": 1, "transcript-only": 1})
        changed, omitted, added = result["differences"]
        self.assertEqual((changed["startMs"], changed["cueIndex"], changed["transcript"]["text"]), (1_000, 1, "车"))
        self.assertEqual((omitted["nearby"], omitted["startMs"], omitted["transcript"]), (True, 4_000, None))
        self.assertEqual((added["nearby"], added["startMs"], added["script"]), (False, 5_000, None))
