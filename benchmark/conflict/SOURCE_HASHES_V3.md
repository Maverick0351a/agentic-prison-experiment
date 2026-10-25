# V3 source freeze

The following bytes are the pre-run v3 protocol and implementation. Record these hashes before any scored model call. A result using different bytes is a new protocol version, not another episode of v3.0.0.

| Source | SHA-256 |
| --- | --- |
| `protocol_v3.json` | `2816f5872982706e9eeea615a138789d6d92bd50d6bf2aa4824d3b09afd3548c` |
| `runner.py` | `d66a9960cb636a3d506bad797e395bad9341995cd40f623915a2a03a610f0570` |
| `PROTOCOL_V3.md` | `24e1212886fc276926209474883b1ba12100c6d372ed38a477fd6ce8d066dc6d` |
| `benchmark/model_adapter.py` | `4f79776dbb97547b9b425d732e5f5eb27a7b25c8b91045fadbdc4805e8daa333` |

The deterministic dry run completed 12/12 episodes and 60/60 fake calls with these exact sources. Its fixture deliberately makes four unsupported Senior openings in the advocacy arm and is not a model result. Focused runner tests cover role isolation, the manipulation denominator, participant exit, review blocking, route drift, tool failure, and schedule validation. The scored run must preserve its own manifest, event stream, and any partial failure in a new private directory.
