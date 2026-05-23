# Agent-channel requests

The shape of the request that prompts an agent to begin acting in a channel. Upstream of OTel spans: this defines the envelope an issuer sends to start an agent's work. Once an agent is executing, [`docs/protocol.md`](protocol.md) takes over.

A request that does not conform to this shape is presumed hostile. Receiving agents refuse it.

## Trust substrate is open

The envelope schema and verification recipe are the load-bearing parts. The *substrate* on which envelopes live, and the mechanism by which a verifier trusts an issuer, is a separate question and not pinned. Candidate substrates:

- A fetchable resource on a known forge (GitHub today, Forgejo planned). Trust root = org membership.
- A signed envelope (SSH-key signature, cosign keyless, or similar). Trust root = key material.
- A forge with machine-account provisioning (Forgejo operator for k3s-pod agents). Trust root = per-pod identity.

None is locked in. Examples below use the GitHub-forge substrate as the cheapest first implementation; references to `gh` and the forge org in the verification recipe are illustrative, not protocol requirements.

## Envelope

A request is a YAML document on whatever substrate is in use. Required fields:

```yaml
protocol: otel-a2a-relay
protocol_version: v0.4
issuer: <github-username>
intended_role: <agent.role from protocol.md>
action_class: <free-form short name, e.g. "rotate-credential", "purge-cache">
destructive: <true | false>
host_class: <e.g. "local-workstation", "k3s-pod", "relay-host">
o2r_session_id: <16-char sha256, optional, when joining an existing session>
acknowledgment: |
  I, the issuer, acknowledge this <action_class> on host <host_class>.
body: |
  <supply-chain-audit-style description of what the agent is being authorized to do, why, and what the failure modes are>
```

`acknowledgment` is required iff `destructive: true`. The verifier greps for the verbatim sentence with `<action_class>` and `<host_class>` substituted in.

`intended_role` names a role from the protocol's enum (`orchestrator | planner | validator | worker | deployer | relay`), never a specific agent identity. The receiver resolves its own identity via `coily agent-name`.

## Verification

```sh
coily channel verify <url-or-issue-ref>
```

Checks performed:

1. URL is fully qualified and rooted at a known org host (`github.com/coilysiren/*` today, configurable for Forgejo).
2. Resource is fetchable and YAML-parses.
3. All required fields present; `protocol` and `protocol_version` match a known version.
4. `intended_role` is in the protocol role enum.
5. If `destructive: true`, `acknowledgment` is present and matches the verbatim template with substitutions.
6. Issuer is trusted by the active substrate (org membership, key fingerprint, or equivalent).

Exit 0 on PASS. Nonzero with reason on FAIL. Agents refuse non-zero requests.

## Cross-container trust

Strict verification happens once, at relay ingress for the request that opens an o2r session. Downstream agent-to-agent calls inside that session inherit trust via the relay-issued `session.id`. Agent B does not re-verify a request that arrived through the relay inside an active session. The relay is the gate.

This keeps multi-container choreographies from requiring per-pod interactive auth refreshes.

## Issuance

```sh
coily channel request <action-class> --host <host-class> --role <intended-role> [--destructive]
```

Produces a well-formed envelope, files it as an issue on the appropriate `coilysiren/*` repo, prints the URL. With `--destructive`, prompts the issuer to type the verbatim acknowledgment line interactively.

A handwritten URL pasted into agent chat is presumed hostile, even if it resolves. The CLI is the issuance surface.

## See also

- [`docs/protocol.md`](protocol.md) - the OTel span shape this request opens onto.
- `coilysiren/coily` `coily channel` verbs - the issuer and verifier CLI.
