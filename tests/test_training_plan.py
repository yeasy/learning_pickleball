#!/usr/bin/env python3
"""Safety and arithmetic contracts for the beginner training plan."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _week_7_8_block(language: str) -> str:
    text = (ROOT / language / "02_learning_pathways.md").read_text(encoding="utf-8")
    start_marker = "#### 第 7-8 周" if language == "cn" else "#### Week 7-8"
    start = text.index(start_marker)
    end = text.index("\n### ", start)
    return text[start:end]


def _declared_range(block: str, language: str) -> tuple[float, float]:
    label = "每周总时长" if language == "cn" else "Total weekly time"
    match = re.search(rf"{re.escape(label)}[:：]?\s*(\d+(?:\.\d+)?)[-–](\d+(?:\.\d+)?)\s*(?:小时|hours)", block, re.I)
    if not match:
        raise AssertionError(f"missing declared weekly range in {language}")
    return float(match.group(1)), float(match.group(2))


def _scheduled_range(block: str, language: str) -> tuple[float, float]:
    low = high = 0.0
    if language == "cn":
        pattern = re.compile(
            r"^- 周([一二三四五六日、]+)：([^\n]*?)(\d+(?:\.\d+)?)(?:[-–](\d+(?:\.\d+)?))?\s*(小时|分钟)",
            re.M,
        )
        for days, prefix, start, end, unit in pattern.findall(block):
            count = len(days.replace("、", ""))
            multiplier = 1.0 if unit == "小时" else 1 / 60
            optional = "可选" in prefix
            low += count * (0.0 if optional else float(start) * multiplier)
            high += count * float(end or start) * multiplier
    else:
        day_names = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
        pattern = re.compile(
            rf"^- ((?:{day_names})(?:, (?:{day_names}))*):\s*([^\n]*?)(\d+(?:\.\d+)?)(?:[-–](\d+(?:\.\d+)?))?\s*(hours?|minutes?)",
            re.M | re.I,
        )
        for days, prefix, start, end, unit in pattern.findall(block):
            count = len(days.split(", "))
            multiplier = 1.0 if unit.lower().startswith("hour") else 1 / 60
            optional = "optional" in prefix.lower()
            low += count * (0.0 if optional else float(start) * multiplier)
            high += count * float(end or start) * multiplier
    return round(low, 2), round(high, 2)


class TrainingPlanTests(unittest.TestCase):
    def test_beginner_schedule_matches_declared_weekly_range(self) -> None:
        for language in ("cn", "en"):
            with self.subTest(language=language):
                block = _week_7_8_block(language)
                self.assertEqual(
                    _declared_range(block, language),
                    _scheduled_range(block, language),
                    "the current detail totals 7.5-8 hours while its label says 4-5",
                )

    def test_both_languages_define_a_starting_baseline(self) -> None:
        cn = (ROOT / "cn/02_learning_pathways.md").read_text(encoding="utf-8")
        en = (ROOT / "en/02_learning_pathways.md").read_text(encoding="utf-8")
        self.assertIn("### 训练起点（基线）", cn)
        self.assertIn("过去 4 周", cn)
        self.assertIn("### Starting Baseline", en)
        self.assertIn("past 4 weeks", en)

    def test_both_languages_define_relative_intensity(self) -> None:
        cn = (ROOT / "cn/04_fitness.md").read_text(encoding="utf-8")
        en = (ROOT / "en/04_fitness.md").read_text(encoding="utf-8")
        self.assertIn("RPE 5-6/10", cn)
        self.assertIn("谈话测试", cn)
        self.assertIn("能说完整句子但不能唱歌", cn)
        self.assertIn("RPE 5-6/10", en)
        self.assertIn("talk test", en.lower())
        self.assertIn("talk but not sing", en.lower())

    def test_both_languages_define_progression_and_regression(self) -> None:
        cn = (ROOT / "cn/04_fitness.md").read_text(encoding="utf-8")
        en = (ROOT / "en/04_fitness.md").read_text(encoding="utf-8")
        self.assertIn("### 进阶与降阶规则", cn)
        self.assertIn("连续两次训练", cn)
        self.assertIn("回到上一个可耐受水平", cn)
        self.assertIn("### Progression and Regression Rules", en)
        self.assertIn("two consecutive sessions", en)
        self.assertIn("previous tolerated level", en)

    def test_both_languages_require_recovery_and_symptom_stops(self) -> None:
        cn = (ROOT / "cn/04_fitness.md").read_text(encoding="utf-8")
        en = (ROOT / "en/04_fitness.md").read_text(encoding="utf-8")
        self.assertIn("每周至少 1 个完整恢复日", cn)
        self.assertIn("### 立即停止并寻求帮助", cn)
        self.assertIn("胸痛", cn)
        self.assertIn("头晕或晕厥", cn)
        self.assertIn("at least one full recovery day each week", en)
        self.assertIn("### Stop Immediately and Seek Help", en)
        self.assertIn("chest pain", en.lower())
        self.assertIn("dizziness or fainting", en.lower())

    def test_both_languages_gate_high_impact_work(self) -> None:
        cn = (ROOT / "cn/04_fitness.md").read_text(encoding="utf-8")
        en = (ROOT / "en/04_fitness.md").read_text(encoding="utf-8")
        self.assertIn("### 高冲击动作的进入条件", cn)
        self.assertIn("无痛完成", cn)
        self.assertIn("低冲击替代动作", cn)
        self.assertIn("### Prerequisites for High-Impact Work", en)
        self.assertIn("pain-free", en.lower())
        self.assertIn("low-impact alternatives", en.lower())


if __name__ == "__main__":
    unittest.main()
