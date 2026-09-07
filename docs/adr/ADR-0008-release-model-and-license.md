# ADR-0008: Public open-source release under Apache-2.0, detector-neutral

- Status: Accepted
- Date: 2026-09-05
- Owners: project owner
- Supersedes: none

## Context

Phase 00 must state the intended release model before any dependency is added, because a dependency's licence can constrain the whole project's release posture retroactively. `docs/architecture/system-design.md` section 16 requires the licensing path to be a release-level decision rather than a consequence of a dependency file.

The repository's own framing settles the intent: `docs/architecture/system-design.md` section 1 describes a portfolio story about designed contracts and measured behaviour, `docs/architecture/original-blueprint-corrections.md` frames the work as something to explain in an interview, and Phase 13 is named "Benchmark, demo, and portfolio release". A portfolio artifact that cannot be read is not a portfolio artifact, so the project is public.

That leaves which licence, and the answer interacts with ADR-0007: Ultralytics offers AGPL-3.0 or Enterprise terms, and AGPL-3.0 absorbs permissively licensed code one way only.

## Decision

**Release model: fully open-source public portfolio, detector-neutral.** The repository is public, and the base installation depends on nothing whose licence contradicts the declared one.

**First-party licence: Apache-2.0**, in `LICENSE`, verbatim from `https://www.apache.org/licenses/LICENSE-2.0.txt`, with the appendix copyright line completed.

**Third-party posture:** `THIRD_PARTY_NOTICES.md` records the licence posture of every component the project depends on or deliberately gates. From Phase 01 its dependency table is derived from `uv.lock`, not from memory, and any component whose licence conflicts with Apache-2.0 distribution is either gated out of the base install or removed.

**Media and weights are never committed and never redistributed.** Benchmark and demo inputs are restricted to self-created footage and FFmpeg-generated synthetic clips, per `docs/product-contract.md` section 7.

**Attribution placeholder:** the copyright line currently reads "The Automated Cinematography Analyzer Authors". Replacing it with the owner's legal name or entity is required before public publication and is owned by Phase 13.

## Alternatives considered

**MIT.** A reasonable choice and nearly equivalent in effect. Rejected for lacking an express patent grant and any trademark provision, both of which matter more in a project that integrates computer-vision and model dependencies.

**AGPL-3.0 now.** Rejected: it forecloses the most options for the least present benefit. Apache-2.0 can be incorporated into an AGPL-3.0 work later if ADR-0007 resolves that way; AGPL-3.0 cannot be walked back to permissive terms once third parties have received the code. Choosing AGPL-3.0 now would spend an option to buy nothing.

**Private prototype, all rights reserved.** Rejected: it contradicts the stated portfolio purpose, and it would leave the Ultralytics question unanswered rather than resolved, because the AGPL-3.0 network-use provision would still apply if the system were ever offered over a network.

**Dual licensing.** Rejected as unjustified overhead for a solo project with no commercial licensees.

**Defer the licence to Phase 13.** Rejected: dependencies get added in Phase 01, and an undeclared licence is the state in which an incompatible dependency slips in unnoticed. This is the phase whose job is to close that door.

## Consequences

Easier: the code is reusable and quotable, the patent grant reduces ambiguity for anyone adopting it, and the base install can be published without a licence audit at release time.

Harder: every dependency addition now carries a compatibility question, which is a check in the release checklist rather than a judgement call at merge time. The AGPL-3.0 path in ADR-0007 becomes a deliberate relicensing decision rather than a quiet default — which is the intent.

Irreversible in practice: code already published under Apache-2.0 stays available under Apache-2.0 to everyone who received it. Future versions may be relicensed, but past releases cannot be recalled.

## Verification

`LICENSE` matches the canonical Apache-2.0 text apart from the completed appendix copyright line. From Phase 01, a check asserts that no base-install dependency resolved from `uv.lock` carries a copyleft licence incompatible with Apache-2.0 distribution. The release checklist requires the attribution placeholder to be replaced and the notices table to be regenerated from the lockfile before publication.

## Revisit trigger

Any of: ADR-0007 resolves toward the AGPL-3.0 path, which makes relicensing the combined distribution a deliberate follow-on decision; a required capability exists only under incompatible terms; or the owner decides to commercialise, which would reopen the release model rather than only the licence.
