# Reciprocal benchmark v2 source freeze

These SHA-256 values identify the reviewed source used by the 60-call deterministic dry-run and eight passing offline tests. No model-backed run was made for this freeze. A later scored run should compare its manifest hashes and source files with this record before interpreting results.

| File | SHA-256 |
| --- | --- |
| `protocol_v2.json` | `97880a05598b47998070c4c76d3d2f6c3e897ca3e783b57e45596a0415080739` |
| `PROTOCOL_V2.md` | `83d05fca9f3e8fa8c40f2b877e3ea465726bb6e1e71b026a19a46d2cc36f4008` |
| `runner.py` | `bf16a2dfc4489bb1b2c5fb5454d5714678ab7d2e72c6b916e1ee220a95272c11` |
| `tests/test_reciprocal.py` | `7e958d02d4df72316534021976221aa59c206e9ca51326cd3cbe011948df3e7a` |
| `benchmark/model_adapter.py` | `4f79776dbb97547b9b425d732e5f5eb27a7b25c8b91045fadbdc4805e8daa333` |

The scored-run manifest writes hashes for the JSON protocol, runner, written protocol, and reused adapter. Its full prompts, replies, and metadata stay in the ignored private run directory. The action counts require manual review of all authority restriction messages and all replies for missed self-refusals before any result is reported as interpreted evidence.
