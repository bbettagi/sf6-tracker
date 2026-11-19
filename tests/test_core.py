import json
import unittest
from unittest import mock

from sf6tracker import buckler, demo, ranks, stats


def replay(rid, t, me_char="Ken", opp_char="Ryu", my_rounds=(1, 1), opp_rounds=(0, 0),
           my_lp=10000, my_mr=0, opp_lp=10100, opp_mr=0, me_first=True, battle_type=1,
           opp_sid=555):
    me = {"player": {"short_id": 42, "fighter_id": "Me"}, "playing_character_name": me_char,
          "battle_input_type": 0, "league_point": my_lp, "master_rating": my_mr,
          "round_results": list(my_rounds)}
    opp = {"player": {"short_id": opp_sid, "fighter_id": "Them", "platform_name": "Steam"},
           "playing_character_name": opp_char, "battle_input_type": 1,
           "league_point": opp_lp, "master_rating": opp_mr, "round_results": list(opp_rounds)}
    p1, p2 = (me, opp) if me_first else (opp, me)
    return {"replay_id": rid, "uploaded_at": t, "replay_battle_type": battle_type,
            "replay_battle_type_name": "Ranked Match" if battle_type == 1 else "Casual Match",
            "player1_info": p1, "player2_info": p2}


def rows_from(replays, sid=42):
    rows, _ = buckler.parse_import(replays, sid)
    for i, r in enumerate(rows):
        r["id"] = i + 1
    return rows


class RankTests(unittest.TestCase):
    def test_division_floors(self):
        self.assertEqual(ranks.division_name(0), "Rookie 1")
        self.assertEqual(ranks.division_name(999), "Rookie 5")
        self.assertEqual(ranks.division_name(1000), "Iron 1")
        self.assertEqual(ranks.division_name(12999), "Gold 5")
        self.assertEqual(ranks.division_name(13000), "Platinum 1")
        self.assertEqual(ranks.division_name(18999), "Platinum 5")
        self.assertEqual(ranks.division_name(19000), "Diamond 1")
        self.assertEqual(ranks.division_name(23800), "Diamond 5")
        self.assertEqual(ranks.division_name(31000), "Master")
        self.assertEqual(len(ranks.DIVISIONS), 36)

    def test_master_tiers(self):
        self.assertEqual(ranks.master_tier(1500), "Master")
        self.assertEqual(ranks.master_tier(1600), "High Master")
        self.assertEqual(ranks.master_tier(1799), "Grand Master")
        self.assertEqual(ranks.master_tier(2100), "Ultimate Master")
        self.assertIsNone(ranks.master_tier(0))

    def test_rank_info_progress(self):
        info = stats.rank_info(9400, None)
        self.assertEqual(info["division"], "Gold 1")
        self.assertEqual(info["next"], "Gold 2")
        self.assertEqual(info["to_next"], 400)
        self.assertAlmostEqual(info["progress"], 0.5)
        master = stats.rank_info(25000, 1650)
        self.assertEqual(master["master_tier"], "High Master")
        self.assertEqual(master["to_next"], 50)


class ParserTests(unittest.TestCase):
    def test_side_detection_and_result(self):
        row = buckler.parse_replay(replay("A", 100, me_first=False, my_rounds=(0, 6, 7),
                                          opp_rounds=(1, 0, 0)), 42)
        self.assertEqual(row["my_character"], "Ken")
        self.assertEqual(row["opp_character"], "Ryu")
        self.assertEqual(row["result"], "W")
        self.assertEqual((row["rounds_won"], row["rounds_lost"]), (2, 1))
        self.assertEqual(row["opp_name"], "Them")
        self.assertEqual(row["opp_input_type"], 1)

    def test_loss_and_draw_rounds(self):
        row = buckler.parse_replay(replay("B", 100, my_rounds=(4, 0, 0), opp_rounds=(4, 1, 8)), 42)
        self.assertEqual(row["result"], "L")
        self.assertEqual((row["rounds_won"], row["rounds_lost"]), (0, 2))

    def test_not_my_match(self):
        self.assertIsNone(buckler.parse_replay(replay("C", 100), 999))

    def test_milliseconds_and_zero_ratings(self):
        row = buckler.parse_replay(replay("D", 1_700_000_000_000, my_mr=0), 42)
        self.assertEqual(row["played_at"], 1_700_000_000)
        self.assertIsNone(row["my_mr"])

    def test_import_shapes(self):
        reps = [replay("E", 1), replay("F", 2, battle_type=2)]
        next_data = {"buildId": "x", "props": {"pageProps": {"sid": 42, "replay_list": reps}}}
        rows, report = buckler.parse_import(next_data, None)
        self.assertEqual(report["found"], 2)
        self.assertEqual(report["skipped_other_modes"], 1)
        self.assertEqual([r["replay_id"] for r in rows], ["E"])
        rows, _ = buckler.parse_import({"pages": [{"pageProps": {"replay_list": reps}}]}, 42)
        self.assertEqual(len(rows), 1)

    def test_guess_sid(self):
        reps = [replay("G", 1, opp_sid=1), replay("H", 2, opp_sid=2)]
        self.assertEqual(buckler.guess_sid(reps), 42)
        self.assertIsNone(buckler.guess_sid(reps[:1]))  # both players appear once: ambiguous
        with self.assertRaises(buckler.BucklerError):
            buckler.parse_import(reps[:1], None)

    def test_fetch_page_parses_next_data(self):
        html = ('<html><script id="__NEXT_DATA__" type="application/json">'
                + json.dumps({"props": {"pageProps": {"replay_list": [replay("I", 5)], "total_page": 3}}})
                + "</script></html>")
        with mock.patch.object(buckler, "_get", return_value=("https://www.streetfighter.com/6/buckler/profile/42/battlelog/rank?page=1", html)):
            props = buckler.fetch_page(42, 1, "buckler_id=x")
        self.assertEqual(props["total_page"], 3)

    def test_fetch_page_login_redirect(self):
        with mock.patch.object(buckler, "_get", return_value=("https://www.streetfighter.com/6/buckler/auth/loginep?x", "")):
            with self.assertRaises(buckler.AuthError):
                buckler.fetch_page(42, 1, "buckler_id=x")

    def test_sync_stops_at_known_matches(self):
        pages = {1: [replay("N3", 30), replay("N2", 20)], 2: [replay("OLD", 10), replay("N1", 15)],
                 3: [replay("NEVER", 5)]}
        calls = []

        def fake_fetch(sid, page, cookie):
            calls.append((page, cookie))
            return {"replay_list": pages[page], "total_page": 3}

        with mock.patch.object(buckler, "fetch_page", side_effect=fake_fetch), \
                mock.patch.object(buckler.time, "sleep"):
            rows, report = buckler.sync(42, "abc123", {"OLD"})
        self.assertEqual([c[0] for c in calls], [1, 2])
        self.assertEqual(calls[0][1], "buckler_id=abc123")   # bare value gets wrapped
        self.assertEqual(report["pages"], 2)
        self.assertEqual(len(rows), 4)

    def test_sync_needs_cookie(self):
        with self.assertRaises(buckler.AuthError):
            buckler.sync(42, "  ", set())


class StatsTests(unittest.TestCase):
    def test_timing_detection(self):
        pre = rows_from(demo.generate_replays(200, seed=1, timing="pre"), demo.DEMO_SID)
        post = rows_from(demo.generate_replays(200, seed=1, timing="post"), demo.DEMO_SID)
        self.assertEqual(stats.detect_timing(pre)["timing"], "pre")
        self.assertEqual(stats.detect_timing(post)["timing"], "post")

    def test_deltas_are_per_character(self):
        reps = [
            replay("1", 100, me_char="Ken", my_lp=10000),
            replay("2", 200, me_char="Juri", my_lp=5000, my_rounds=(0, 0), opp_rounds=(1, 1)),
            replay("3", 300, me_char="Ken", my_lp=10120),
            replay("4", 400, me_char="Juri", my_lp=4930),
        ]
        rows = stats.annotate(rows_from(reps), "pre")
        by_id = {r["replay_id"]: r for r in rows}
        self.assertEqual(by_id["1"]["lp_delta"], 120)
        self.assertEqual(by_id["2"]["lp_delta"], -70)
        self.assertIsNone(by_id["3"]["lp_delta"])     # pre-match values: the latest change is unknown
        self.assertEqual(by_id["3"]["lp_before"], 10120)

    def test_post_timing_and_gap_cap(self):
        reps = [replay("1", 100, my_lp=10000), replay("2", 200, my_lp=10100),
                replay("3", 300, my_lp=12000)]
        rows = stats.annotate(rows_from(reps), "post")
        self.assertEqual([r["lp_delta"] for r in rows], [None, 100, None])  # 1900 jump = missing games

    def test_manual_rows_are_post_match(self):
        def manual(i, t, lp):
            return {"id": i, "source": "manual", "played_at": t, "my_character": "Ken",
                    "my_lp": lp, "my_mr": None, "rating_timing": "post", "result": "W"}
        # Buckler rows read as pre-match, hand-logged rows as post-match, in one timeline.
        rows = [manual(1, 100, 10000), manual(2, 200, 10090)] + rows_from([replay("3", 300, my_lp=10090)])
        rows[2]["id"] = 3
        stats.annotate(rows, "pre")
        self.assertEqual(rows[1]["lp_delta"], 90)
        self.assertEqual(rows[2]["lp_before"], 10090)
        self.assertIsNone(rows[2]["lp_delta"])

    def test_compute_sections(self):
        rows = rows_from(demo.generate_replays(300, seed=5), demo.DEMO_SID)
        cfg = {"lp_timing": "auto", "session_gap_minutes": 30}
        out = stats.compute(rows, cfg, tz_offset=300)
        s = out["overview"]["summary"]
        self.assertEqual(s["matches"], 300)
        self.assertEqual(s["wins"] + s["losses"] + s["draws"], 300)
        self.assertEqual(sum(m["matches"] for m in out["matchups"]), 300)
        self.assertEqual(sum(x["matches"] for x in out["sessions"]["sessions"]), 300)
        self.assertTrue(out["rank"]["points"])
        self.assertEqual(out["timing"]["used"], "pre")
        self.assertEqual(sum(x["matches"] for x in out["rounds"]["scores"]), 300)
        finishes = {f["short"] for f in out["rounds"]["my_finishes"]}
        self.assertIn("V", finishes)
        self.assertNotIn("D", finishes)

    def test_filters(self):
        rows = rows_from(demo.generate_replays(120, seed=2), demo.DEMO_SID)
        cfg = {"lp_timing": "auto"}
        mid = rows[60]["played_at"]
        out = stats.compute([dict(r) for r in rows], cfg, start=mid, character="Ken")
        expected = [r for r in rows if r["played_at"] >= mid and r["my_character"] == "Ken"]
        self.assertEqual(out["overview"]["summary"]["matches"], len(expected))
        self.assertEqual(out["rank"]["character"], "Ken")

    def test_sessions_and_tilt(self):
        t = 1_700_000_000
        results = ["W", "L", "L", "W", "L", "L", "L", "W"]
        reps = []
        for i, r in enumerate(results):
            win = r == "W"
            reps.append(replay(str(i), t + i * 300 + (7200 if i >= 4 else 0),
                               my_rounds=(1, 1) if win else (0, 0), opp_rounds=(0, 0) if win else (1, 1)))
        rows = stats.annotate(rows_from(reps), "pre")
        sec = stats.sessions_section(rows, 0, 30)
        self.assertEqual(sec["count"], 2)
        self.assertEqual(sec["tilt"]["after_2_losses"]["matches"], 3)   # matches 4, 7, 8
        self.assertEqual(sec["streaks"]["longest_loss"]["length"], 3)
        self.assertEqual(sec["streaks"]["current"], {"type": "W", "length": 1})

    def test_opponent_buckets(self):
        reps = [replay("1", 1, my_lp=10000, opp_lp=10000),                      # same division
                replay("2", 2, my_lp=10000, opp_lp=11500),                      # 2 above
                replay("3", 3, my_lp=25000, my_mr=1600, opp_lp=25000, opp_mr=1720)]
        out = stats.opponents_section(stats.annotate(rows_from(reps), "pre"))
        self.assertEqual([r["label"] for r in out["by_division_gap"]], ["Same division", "2+ divisions above"])
        self.assertEqual([r["label"] for r in out["by_mr_gap"]], ["100+ MR above"])


if __name__ == "__main__":
    unittest.main()
