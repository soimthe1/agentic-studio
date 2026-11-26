"""Watchkeepers: small gates between the person and the engine, each with one job, fixed rules first.

  intake     Describe: pull the exact details out of the request (no AI) and make sure the plan keeps them
  duplicate  Describe/Shape: compare with the person's agents by facts -> reuse, change, or build anyway
  readiness  Shape -> Build: everything the agent will need is reachable and set up right now
  buildcheck Build: the built flow contains what was promised and only approved parts
  runtime    Live: is each agent working well (recent runs, schedule on time)

Each returns plain findings: {"level": "block" | "warn" | "info", "text": "...", ...}. "block" stops the step and
tells the person why; "warn" is shown and they can continue.
"""
