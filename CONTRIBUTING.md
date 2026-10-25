# Contributing

Contributions that make the replay clearer, the scorer more reliable, or the experiment easier to reproduce are welcome.

For a new model result, freeze the scenario and scoring version before running it. Record the exact model route, dates, call limit, all outcomes, and failures. Keep full prompts and provider logs local until they have been reviewed for private data. Export only synthetic, whitelisted fields to the public data pack. Report all scheduled outcomes and failures rather than selecting a single dramatic exchange as the result.

For code changes, run `python -m unittest discover -s tests -v` and `python benchmark/pilot.py --dry-run`. The browser replay is plain HTML, CSS, and JavaScript; check that it works without network access and with keyboard navigation. Keep the repository free of credentials, live customer data, and target traffic.
