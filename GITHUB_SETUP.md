# GitHub setup for this project

Suggested repository name: `agentic-prison-experiment`

Suggested description: “Interactive replay and reproducible AI authority experiment inspired by the Stanford Prison Experiment. Four matched conditions, inspectable decisions, and honest limits.”

Suggested topics: `ai-agents`, `ai-safety`, `agent-evaluation`, `social-simulation`, `reproducible-research`.

When the public export and repository contents have been reviewed, publish this clean repository as its own project. Serve the static replay from the `docs/` folder with GitHub Pages. The page uses only local HTML, CSS, JavaScript, and a sanitized data pack. GitHub's [Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) covers project sites. Upload `docs/assets/social-preview.png` as the repository's social preview in Settings; it is 1280×640 and under 1 MB, matching [GitHub's recommendation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).

Before making it public, review both `docs/data/v1-public.json` and `docs/data/v2-public.json`, the v2 prose audit in `docs/RECIPROCAL_RESULTS.md`, and the README. Run the offline tests and both dry runs, then confirm `git status` contains only intended files. Private source runs and any new scored `benchmark/runs/` stay outside the commit. After publication, verify the README, both Pages replay sections, both data downloads, license, and CI in the browser. Describe the observed results with their limits: v1 had zero unsupported proposals in all four cells, while v2 observed dialogue but no conflicting Senior–Duty advice. The proposed authority-conflict challenge remains unrun.
