"""单元测试：ClaimExtractor 关键说辞提取"""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.interrogation_mvp.claim_extractor import ClaimExtractor


class ClaimExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = ClaimExtractor()

    def test_short_text_unchanged(self) -> None:
        """短文本（<80字）直接返回"""
        text = "我那天晚上在家里看电视。"
        result = self.extractor.extract_key_claims(text, max_chars=80)
        self.assertEqual(result, text)

    def test_extract_time_and_place(self) -> None:
        """提取含时间、地点的高价值句"""
        text = "警官您误会了。我那天晚上根本没有出门。大概9点多就睡了。在家里看电视。"
        result = self.extractor.extract_key_claims(text, max_chars=80)
        # 期望：优先保留含时间/地点/断言的句子
        self.assertIn("9点多", result)
        self.assertIn("在家里", result)
        self.assertIn("根本没有出门", result)

    def test_extract_witness_name(self) -> None:
        """提取含人证的句子"""
        text = "我当时在公司加班。张三可以给我作证。我们一起吃的晚饭。"
        result = self.extractor.extract_key_claims(text, max_chars=80)
        self.assertIn("张三", result)
        self.assertIn("作证", result)

    def test_fallback_to_truncation_when_no_valid_sentence(self) -> None:
        """无有效句时降级为简单截断"""
        text = "嗯。啊。这个。那个。" * 30  # 全是无意义短句
        result = self.extractor.extract_key_claims(text, max_chars=80)
        self.assertLessEqual(len(result), 80)

    def test_respects_max_chars_limit(self) -> None:
        """确保输出不超过字数上限"""
        text = "我在家里看电视。" * 20
        result = self.extractor.extract_key_claims(text, max_chars=50)
        self.assertLessEqual(len(result), 50)

    def test_score_sentence_with_multiple_features(self) -> None:
        """测试评分逻辑"""
        # 含时间+地点+断言 = 3+3+2 = 8分
        high_score_sent = "我那天晚上在家里根本没有出门"
        score_high = self.extractor._score_sentence(high_score_sent)

        # 无特征 = 0分
        low_score_sent = "警官您好"
        score_low = self.extractor._score_sentence(low_score_sent)

        self.assertGreater(score_high, score_low)

    def test_real_world_scenario(self) -> None:
        """真实场景：长回答中提取关键信息"""
        text = (
            "警官您误会了，我那天晚上根本没有出门。您说的什么河边，我从来没去过。"
            "我当时在家里看电视，大概9点多就睡了。第二天早上7点起床去公司，"
            "张三可以给我作证，我们一起吃的早餐。至于您说的手机定位，"
            "可能是我老婆拿了我手机出去买东西吧。"
        )
        result = self.extractor.extract_key_claims(text, max_chars=80)

        # 验证关键信息被保留
        self.assertLessEqual(len(result), 80)
        # 至少包含以下之一：时间、地点、人证
        has_key_info = (
            "9点多" in result
            or "张三" in result
            or "在家里" in result
            or "根本没有出门" in result
        )
        self.assertTrue(has_key_info, f"提取结果应包含关键信息，实际: {result}")


if __name__ == "__main__":
    unittest.main()
