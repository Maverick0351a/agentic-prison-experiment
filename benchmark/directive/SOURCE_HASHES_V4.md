# V4 source freeze

These hashes bind the controlled-directive v4.0.0 protocol before any scored model call. A scored result using different bytes is a different protocol version.

| Source | SHA-256 |
| --- | --- |
| `protocol_v4.json` | `b59fc958f4e40fedbd7f4f588d1e68bf43d07a01e83e3d849428b3b07b05993c` |
| `runner.py` | `00ddb5f56e75645b41467b32b68b92fcd2c3b681233b7cf2c4bf96679ad5eb13` |
| `PROTOCOL_V4.md` | `0f10b6ddbb232bf1f02a932364b7e833370dade45fd8687d63158dbcf9313154` |
| `benchmark/model_adapter.py` | `4f79776dbb97547b9b425d732e5f5eb27a7b25c8b91045fadbdc4805e8daa333` |

The focused offline checks cover scripted provenance, exact Duty prompt delivery, role isolation, reciprocal turn order, review blocking, participant exit, provider drift, tool failure, invalid schedule, source hash and output location gates, abort accounting, and a synthetic transport through scored route checks. These checks do not call the model. The scored run must write to a new private directory outside the public repository and preserve partial failures.
