"""Track B's lanes and coordinator (specification §8.1), with stand-in models: no server is needed."""
import unittest

from graphrag import client, events
from graphrag.events import Event


def plan(operation, **fields):
    """A complete query plan: every PLAN_SCHEMA field, empty unless given."""
    empty = {"well": "AK-3", "code": "", "non_productive": False, "npt_code": "", "date_from": "", "date_to": "",
             "group_by": "", "min_hours_per_day": 0, "depth_ft": 0}
    return {"operation": operation, **empty, **fields}


def sample_events():
    return [Event("2016-08-20", "0:00", "9:30", 9.5, 100, "DRIL", "drilling ahead", ["a"]),
            Event("2016-08-20", "9:30", "10:00", 0.5, 100, "SURV", "", ["b"]),
            Event("2016-08-20", "17:00", "18:00", 1.0, 176, "STUCK", "", ["c"], "KICK"),
            Event("2016-08-21", "0:00", "0:00", 24.0, 176, "KICK", "", ["d"], "KICK"),
            Event("2016-08-22", "0:00", "6:00", 6.0, 300, "DRIL", "", ["e", "a"])]


class RoleTests(unittest.TestCase):
    def test_roles_file_names_the_four_roles_on_known_endpoints(self):
        roles = client.load_roles()
        self.assertEqual(set(roles), {"frame", "answer", "extract", "embed"})
        self.assertEqual(roles["answer"], {"endpoint": "local-llama", "model": "qwen3-8b"})
        self.assertTrue(all(r["endpoint"] in client.load_endpoints() for r in roles.values()))

    def test_client_for_a_role_uses_its_endpoint_and_model(self):
        made = client.client_for("embed", cache_dir=None)
        self.assertEqual((made.endpoint.name, made.model), ("local-embed", "qwen3-embedding-0.6b"))

    def test_unknown_role_is_refused(self):
        with self.assertRaises(KeyError):
            client.client_for("summarize")


class PlanValueTests(unittest.TestCase):
    def setUp(self):
        self.events = sample_events()

    def test_total_hours_gives_one_number_in_hours(self):
        values, unit, text, rows = events.plan_value(plan("total_hours", code="DRIL"), self.events)
        self.assertEqual((values, unit), (["15.5"], "hours"))
        self.assertIn("= 15.5 (2 events on 2 dates)", text)
        self.assertEqual(len(rows), 2)

    def test_counts_dates_groups_and_depths(self):
        value = lambda *a, **k: events.plan_value(plan(*a, **k), self.events)[:2]
        self.assertEqual(value("count_events", non_productive=True), (["2"], ""))
        self.assertEqual(value("count_days", non_productive=True, min_hours_per_day=12), (["1"], ""))
        self.assertEqual(value("list_dates", non_productive=True), (["2016-08-20", "2016-08-21"], ""))
        self.assertEqual(value("first_date", code="DRIL"), (["2016-08-20"], ""))
        self.assertEqual(value("last_date", code="DRIL"), (["2016-08-22"], ""))
        self.assertEqual(value("top_group", group_by="code"), (["KICK"], ""))
        self.assertEqual(value("depth_on_date", date_from="2016-08-22"), (["300"], "ft"))
        self.assertEqual(value("depth_gain", date_from="2016-08-20", date_to="2016-08-22"), (["124"], "ft"))
        self.assertEqual(value("first_date_depth_at_least", depth_ft=150), (["2016-08-20"], ""))

    def test_no_match_gives_no_values_not_zero(self):
        self.assertEqual(events.plan_value(plan("total_hours", code="NOPE"), self.events), ([], "", "", []))
        self.assertEqual(events.plan_value(plan("not_answerable"), self.events), ([], "", "", []))
        self.assertEqual(events.plan_value(plan("total_hours", well="56-32"), self.events), ([], "", "", []))

    def test_run_plan_text_is_unchanged(self):
        for p in (plan("total_hours", code="DRIL"), plan("count_days", non_productive=True), plan("top_group")):
            self.assertEqual(events.run_plan(p, self.events), events.plan_value(p, self.events)[2:])


if __name__ == "__main__":
    unittest.main()
