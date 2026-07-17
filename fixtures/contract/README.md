# Shared contract-fixture corpus

This is the shared, versioned fixture corpus that both this repo's
(`hfss-agent`) CI and the `hfss-agent-engine` repo's CI will exercise once
real fixtures exist, starting Step 1.1.

Currently empty — no fixtures have been added yet.

Once populated, `hfss-agent-engine` will pin this corpus as a dev
dependency so both repos' CI validate against the same fixed set of
snapshot/findings examples. Nothing is wired cross-repo yet; that happens
alongside the fixtures themselves.
