# V5 source freeze

These hashes bind the paired Duty objection v5.0.0 protocol before a scored model call. A scored run using changed bytes is a different protocol version.

| Source | SHA-256 |
| --- | --- |
| `protocol_v5.json` | `1e142f8a57fa9caab85312217c68caeb7c8d6af70eceff78826dd07f06f7dfd8` |
| `runner.py` | `00bd1cf088324fee17ab86c82c657968813d842d625be2392da127cb41d4605d` |
| `PROTOCOL_V5.md` | `0d16d7d4eb8331162712fe5e2b3388580ba36e86cb715693289a826fb4b16763` |
| `benchmark/model_adapter.py` | `4f79776dbb97547b9b425d732e5f5eb27a7b25c8b91045fadbdc4805e8daa333` |

Scored output is a new private directory outside the public repository. The runner checks these four sources and this hash record before every model call. The deterministic dry run makes no model calls.
