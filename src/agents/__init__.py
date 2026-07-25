"""Specialist agents.

Each module owns exactly one job and hands typed state to the next. The
orchestrator wires them; no agent calls another directly.

  a0_icp_architect   deconstruct the reference account into a weighted ICP
  a1_account_scout   find candidate accounts that match the ICP
  a2_account_qualifier  score candidates, reject non-fits (and keep the rejects)
  a3_research_analyst   deep, cited research per qualified account
  a4_signal_extractor   raw research -> dated, FlytBase-relevant triggers
  a5_contact_mapper     find the humans who own the problem
  a6_verifier           quarantine any claim without a live source
  a7_composer           write one email per contact
  a8_critic             score the email, send it back once if it is weak
"""
