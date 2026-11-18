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

    def test_paypal_refusal_is_not_a_positive_offer_even_in_html(self):
        refusal = "Visa Sponsorship through PayPal is not available for this position now or any time in the future."
        for description in (refusal, f"<ul><li>Python and Django.</li></ul><br>{refusal}<br>The base pay varies.",
                            f"&lt;p&gt;{refusal}&lt;/p&gt;"):
            with self.subTest(description=description):
                result = classify(description)
                self.assertEqual(result["status"], "not_available")
                self.assertEqual(result["evidence"][0]["quote"], refusal)

    def test_hallucinated_or_cherry_picked_quotes_rejected(self):
        text = "Immigration matters can be discussed with the recruiter."
        for proposal in ({"status": "mentioned", "quotes": ["Visa sponsorship is available."]}, {"status": "conditional", "quotes": ["Immigration matters can be discussed"]}, {"status": "mentioned", "quotes": []}, {"status": "confirmed", "quotes": [text]}):
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                validate_ai(text, proposal)

    def test_ai_interpretation_is_not_vetoed_by_keyword_rules(self):
        text = "We will arrange and fund the work permit needed to take up this role."
        self.assertEqual(classify(text)["status"], "not_specified")
        result = validate_ai(text, {"status": "mentioned", "quotes": [text]})
        self.assertEqual(result["status"], "mentioned")
        self.assertEqual(result["method"], "ai")
        self.assertEqual(result["evidence"][0]["quote"], text)

    def test_quote_cannot_omit_negation_from_the_middle_of_a_sentence(self):
        text = "Visa sponsorship through PayPal is not available for this role."
        with self.assertRaises(ValueError):
            validate_ai(text, {"status": "mentioned", "quotes": ["Visa sponsorship through PayPal is available for this role."]})


class SponsorshipAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_refusal_is_also_reviewed_by_ai(self):
        agent = SponsorshipAgent()
        agent.emit = AsyncMock()
        text = "We cannot provide visa sponsorship."
        agent.chat_json = AsyncMock(return_value={"status": "not_available", "quotes": [text]})
        job = Job(description=text)
        await agent.run(job)
        self.assertEqual(job.sponsorship_status, "not_available")
        self.assertEqual(job.sponsorship_method, "ai")
        agent.chat_json.assert_awaited_once()

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

    async def test_forced_recheck_and_changed_description_refresh_ai_result(self):
        positive = "We offer visa sponsorship."
        refusal = "Visa Sponsorship through PayPal is not available for this position now or any time in the future."
        agent = SponsorshipAgent()
        agent.emit = AsyncMock()
        agent.chat_json = AsyncMock(side_effect=[{"status": "mentioned", "quotes": [positive]},
                                                {"status": "mentioned", "quotes": [positive]},
                                                {"status": "not_available", "quotes": [refusal]}])
        job = Job(description=positive)
        await agent.run(job)
        await agent.run(job)
        self.assertEqual(agent.chat_json.await_count, 1)
        await agent.run(job, force=True)
        job.description = f"<strong>{refusal}</strong>"
        await agent.run(job)
        self.assertEqual(agent.chat_json.await_count, 3)
        self.assertEqual(job.sponsorship_status, "not_available")
        self.assertEqual(job.description, refusal)

    async def test_ai_refusal_and_conditions_are_saved_with_the_original_sentences(self):
        cases = [("Visa Sponsorship through PayPal is not available for this position now or any time in the future.", "not_available"),
                 ("We offer visa sponsorship for eligible candidates only.", "conditional"),
                 ("We cannot sponsor new visas, but we support H1B transfers.", "conditional"),
                 ("Remote work worldwide.", "not_specified")]
        for text, status in cases:
            with self.subTest(text=text):
                agent = SponsorshipAgent()
                agent.emit = AsyncMock()
                quotes = [] if status == "not_specified" else [text]
                agent.chat_json = AsyncMock(return_value={"status": status, "quotes": quotes})
                job = Job(description=text)
                await agent.run(job)
                self.assertEqual(job.sponsorship_status, status)
                self.assertEqual(job.sponsorship_method, "ai")

    async def test_ranking_saves_ai_sponsorship_from_the_same_request(self):
        from agents.rank import RankAgent
        text = "Visa Sponsorship through PayPal is not available for this position now or any time in the future."
        job = Job(title="Engineer", company="Venmo", portal="manual", description=f"<p>{text}</p>")
        agent = RankAgent()
        agent.emit = AsyncMock()
        agent.chat_json = AsyncMock(return_value={"overall": 80, "sponsorship": {"status": "not_available", "quotes": [text]}})
        result = await agent._score_job(job, "Python developer")
        self.assertEqual(result["overall"], 80)
        self.assertEqual(job.sponsorship_status, "not_available")
        self.assertEqual(job.sponsorship_method, "ai")
        agent.chat_json.assert_awaited_once()
        prompt = agent.chat_json.call_args.args[0][1]["content"]
        self.assertIn(text, prompt)
        self.assertNotIn("<p>", prompt)
