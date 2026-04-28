from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.history_store import append_closed_position, save_paper_account, save_paper_metrics
from scripts.paper_analytics import compute_metrics
from scripts.paper_strategy_feedback import build_strategy_feedback


class PaperFeedbackTest(unittest.TestCase):
    def test_metrics_include_plan_profile_and_protection_strategy_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            save_paper_account(
                output_dir,
                {
                    "starting_equity": 10000.0,
                    "current_equity": 10250.0,
                    "total_equity": 10250.0,
                    "realized_pnl": 250.0,
                },
            )
            for index in range(4):
                append_closed_position(
                    output_dir,
                    {
                        "symbol": f"SYM{index}",
                        "strategy_mode": "majors_cex" if index < 3 else "meme_onchain",
                        "plan_profile": "majors_trend_follow" if index < 3 else "meme_breakout_follow",
                        "protection_strategy": "break_even" if index < 2 else "callback",
                        "direction": "long",
                        "candidate_sources": ["alpha_hot", "key_coins"] if index < 3 else ["okx_hot"],
                        "final_score": 82 if index < 3 else 68,
                        "data_quality_score": 8,
                        "data_quality_tier": "A",
                        "narrative_labels": ["exchange"] if index < 3 else ["meme"],
                        "realized_pnl": 120.0 if index < 2 else (-50.0 if index == 2 else 30.0),
                        "tp1_hit": index != 2,
                        "exit_reason": "take_profit" if index < 2 else ("stop_loss" if index == 2 else "position_timeout"),
                    },
                )

            metrics = compute_metrics(output_dir, {"realized_pnl": 250.0}, {})
            self.assertIn("plan_profile", metrics["breakdown"])
            self.assertIn("protection_strategy", metrics["breakdown"])
            self.assertIn("majors_trend_follow", metrics["breakdown"]["plan_profile"])
            self.assertIn("break_even", metrics["breakdown"]["protection_strategy"])

    def test_strategy_feedback_generates_group_comparison_and_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            account = {
                "starting_equity": 10000.0,
                "current_equity": 9800.0,
                "total_equity": 9800.0,
                "realized_pnl": -200.0,
            }
            save_paper_account(output_dir, account)
            for index in range(6):
                append_closed_position(
                    output_dir,
                    {
                        "symbol": f"BNB{index}",
                        "strategy_mode": "majors_cex",
                        "plan_profile": "majors_breakout_confirmed",
                        "protection_strategy": "break_even",
                        "direction": "long",
                        "candidate_sources": ["alpha_hot"],
                        "final_score": 79,
                        "data_quality_score": 7,
                        "data_quality_tier": "B",
                        "narrative_labels": ["exchange"],
                        "realized_pnl": -80.0 if index < 4 else 40.0,
                        "tp1_hit": index in {0, 1, 4, 5},
                        "exit_reason": "stop_loss" if index < 4 else "take_profit",
                    },
                )
            metrics = compute_metrics(output_dir, account, {})
            save_paper_metrics(output_dir, metrics)
            feedback = build_strategy_feedback(output_dir)
            self.assertIn("plan_profile_comparison", feedback)
            self.assertIn("majors_breakout_confirmed", feedback["plan_profile_comparison"])
            self.assertTrue(feedback["suggestions"])
            self.assertIn("recent_windows", feedback)


if __name__ == "__main__":
    unittest.main()
