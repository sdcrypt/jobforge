import unittest
from unittest.mock import AsyncMock

from agents.sponsorship import SponsorshipAgent
from core.job_descriptions import replace_description
from core.sponsorship import classify, update_sponsorship, validate_ai
from models.job import Job


class SponsorshipRulesTests(unittest.TestCase):
    def test_conditional_reason_records_the_actual_limiting_words(self):
        description = "Visa sponsorship may be available for eligible candidates."
        result = classify(description)
        evidence = result["evidence"][0]
        self.assertEqual(evidence["quote"], description)
        self.assertEqual(evidence["status"], "conditional")
        self.assertIn("may", evidence["triggers"])
        self.assertIn("eligible", evidence["triggers"])
        self.assertIn("may", result["notes"])
        self.assertIn("eligible", result["notes"])

    def test_refusal_reason_preserves_the_negation(self):
        result = classify("We cannot provide visa sponsorship.")
        evidence = result["evidence"][0]
        self.assertIn("cannot provide visa sponsorship", evidence["triggers"])
        self.assertIn("cannot provide visa sponsorship", evidence["reason"])

    def test_offer_reason_records_offer_wording(self):
        result = classify("We offer visa sponsorship.")
        self.assertIn("offer visa sponsorship", result["evidence"][0]["triggers"])
        self.assertIn("offer visa sponsorship", result["notes"])

    def test_transfer_reason_explains_the_limitation(self):
        result = classify("We support H1B transfers only.")
        self.assertIn("H1B transfers", result["evidence"][0]["triggers"])
        self.assertIn("visa-transfer support", result["notes"])

    def test_conflict_reason_keeps_both_original_decisions(self):
        result = classify("We offer visa sponsorship. We cannot provide visa sponsorship.")
        self.assertEqual(result["status"], "not_specified")
        self.assertIn("both an offer and a refusal", result["notes"])
        self.assertTrue(all(entry["reason"] and entry["triggers"] for entry in result["evidence"]))

    def test_unknown_does_not_invent_a_supporting_quote(self):
        result = classify("Remote work and relocation assistance provided.")
        self.assertEqual(result["evidence"], [])
        self.assertIn("No sentence", result["notes"])

    def test_explicit_offers(self):
        for description in ("We offer visa sponsorship.", "Visa sponsorship is available for this position.", "We can sponsor work visas.", "We sponsor visas.", "We have no issue providing visa sponsorship."):
            with self.subTest(description=description):
                result = classify(description)
                self.assertEqual(result["status"], "mentioned")
                self.assertEqual(result["evidence"][0]["quote"], description)

    def test_explicit_refusals_override_positive_words(self):
        for description in ("We cannot provide visa sponsorship.", "We do not offer visa sponsorship now or in the future.", "No visa sponsorship is available.", "Visa sponsorship is not available.", "Visa sponsorship will not be provided.", "We are unable to sponsor visas.", "Applicants must work without requiring sponsorship.", "We can't sponsor at this time.", "We cannot sponsor new visas and do not support H1B transfers.", "We cannot provide visa sponsorship, although we have sponsored visas in the past.", "Visa sponsorship is currently not available."):
            with self.subTest(description=description):
                result = classify(description)
                self.assertEqual(result["status"], "not_available")
                self.assertFalse(result["needs_review"])

    def test_conditional_offers_and_transfers(self):
        for description in ("Visa sponsorship may be available.", "We offer visa sponsorship for eligible candidates.", "We may consider sponsorship on a case-by-case basis.", "We support H-1B transfers only.", "We cannot sponsor new visas, but we support H1B transfers.", "Visa sponsorship is not guaranteed.", "We cannot guarantee visa sponsorship."):
            with self.subTest(description=description):
                self.assertEqual(classify(description)["status"], "conditional")

    def test_non_offers_remain_unknown(self):
        for description in ("Remote work worldwide.", "Relocation assistance provided.", "Must already have work authorization.", "US citizenship required.", "We have sponsored visas in the past.", "Visa sponsorship is not required.", "Candidates who don't require visa sponsorship are welcome.", "Our company supports local sports sponsorship.", "", "We work with an immigration advisor."):
            with self.subTest(description=description):
                self.assertEqual(classify(description)["status"], "not_specified")

    def test_unrelated_negation_does_not_override_offer(self):
        self.assertEqual(classify("We do not provide relocation, but visa sponsorship is available.")["status"], "mentioned")

    def test_questions_and_other_roles_are_not_offers(self):
        for description in ("Visa sponsorship is available?", "We offer visa sponsorship for other roles.", "Visa sponsorship is offered by some employers.", "No visa sponsorship required.", "No visa sponsorship restrictions."):
            with self.subTest(description=description):
                self.assertEqual(classify(description)["status"], "not_specified")

    def test_role_specific_refusals_and_exceptions(self):
        self.assertEqual(classify("Visa sponsorship is available but not for this role.")["status"], "not_available")
        self.assertEqual(classify("Visa sponsorship is never offered.")["status"], "not_available")
        self.assertEqual(classify("Visa sponsorship is not available unless approved by the hiring manager.")["status"], "conditional")

    def test_conflicts_are_not_presented_as_an_offer(self):
        result = classify("Visa sponsorship is available. We cannot provide visa sponsorship for this role.")
        self.assertEqual(result["status"], "not_specified")
        self.assertTrue(result["needs_review"])
        self.assertEqual(len(result["evidence"]), 2)

    def test_requirement_at_end_of_long_description_is_seen(self):
        self.assertEqual(classify("Build software. " * 2000 + "We cannot provide visa sponsorship.")["status"], "not_available")

    def test_changed_description_replaces_stale_sponsorship(self):
        job = Job(description="We offer visa sponsorship.")
        update_sponsorship(job)
        self.assertEqual(job.sponsorship_status, "mentioned")
        replace_description(job, "We cannot provide visa sponsorship now or in the future.", "listing")
        self.assertEqual(job.sponsorship_status, "not_available")

    def test_ai_cannot_override_explicit_refusal_or_conflict(self):
        for text in ("We cannot provide visa sponsorship.", "Visa sponsorship is available. We cannot provide visa sponsorship."):
            result = validate_ai(text, {"status": "mentioned", "quotes": ["Visa sponsorship is available."]})
            self.assertNotEqual(result["status"], "mentioned")

    def test_hallucinated_or_cherry_picked_quotes_rejected(self):
        text = "Immigration matters can be discussed with the recruiter."
        for proposal in ({"status": "mentioned", "quotes": ["Visa sponsorship is available."]}, {"status": "conditional", "quotes": ["Immigration matters can be discussed"]}, {"status": "mentioned", "quotes": []}, {"status": "confirmed", "quotes": [text]}):
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                validate_ai(text, proposal)

    def test_matching_quote_does_not_make_unsubstantiated_offer_valid(self):
        text = "We work with an immigration advisor."
        result = validate_ai(text, {"status": "mentioned", "quotes": [text]})
        self.assertEqual(result["status"], "not_specified")
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["evidence"][0]["quote"], text)


class SponsorshipAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_refusal_does_not_need_ai(self):
        agent = SponsorshipAgent()
        agent.chat_json = AsyncMock()
        job = Job(description="We cannot provide visa sponsorship.")
        await agent.run(job)
        self.assertEqual(job.sponsorship_status, "not_available")
        agent.chat_json.assert_not_awaited()

    async def test_invalid_ai_quote_fails_closed_without_losing_description(self):
        agent = SponsorshipAgent()
        agent.emit = AsyncMock()
        agent.chat_json = AsyncMock(return_value={"status": "mentioned", "quotes": ["Invented visa sponsorship offer."]})
        job = Job(description="We work with an immigration advisor.")
        await agent.run(job)
        self.assertEqual(job.sponsorship_status, "not_specified")
        self.assertTrue(job.sponsorship_needs_review)
        self.assertEqual(job.description, "We work with an immigration advisor.")

    async def test_valid_ambiguous_quote_is_saved_for_review_and_cached(self):
        text = "Immigration matters can be discussed with the recruiter."
        agent = SponsorshipAgent()
        agent.emit = AsyncMock()
        agent.chat_json = AsyncMock(return_value={"status": "not_specified", "quotes": [text]})
        job = Job(description=text)
        await agent.run(job)
        await agent.run(job)
        self.assertEqual(job.sponsorship_status, "not_specified")
        self.assertEqual(job.sponsorship_evidence[0]["quote"], text)
        agent.chat_json.assert_awaited_once()
