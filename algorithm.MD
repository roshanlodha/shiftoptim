# A Bounded Pareto-Improving Exchange Mechanism for Resident Shift Scheduling

## Abstract

Emergency medicine residents work schedules that are simultaneously constrained by federal duty-hour regulations and shaped by strong individual preferences about location, time of day, and consecutive-day run lengths. Hand-built schedules rarely satisfy all constraints and preferences, yet they often contain latent, mutually beneficial trades. We present a mechanism that automatically discovers and ranks these trades. By modeling the schedule as a directed trade graph, the method searches for short improving cycles and applies them greedily under two guarantees: every executed trade strictly increases total satisfaction while making no resident worse off, and every resulting schedule remains compliant with ACGME duty-hour rules and day-off requests. Users can control the number and complexity of trades. This approach is transparent, auditable, and produces human-readable swap recommendations rather than an opaque recalculated schedule.

---

## 1. Problem Statement

Consider a residency program (here, the 15-resident Harvard-Affiliated Emergency Medicine Residency) with a fixed block schedule already assigning every clinical shift to a resident. We do not wish to rebuild this schedule from scratch; it encodes staffing decisions, seniority, and educational requirements that are expensive to re-derive and politically sensitive to overturn. Instead we ask a narrower, safer question:

> Given the existing schedule, what set of voluntary shift trades would make the group happier, without harming any individual and without violating any rule?

Three design commitments follow from this framing:

1. **Conservation of workload.** Trades move shifts between residents but never create or delete them. Each resident ends with exactly as many shifts as they started with; only the composition changes. No one is handed extra work.

2. **No forced losses.** A resident will never be assigned a trade that lowers their own satisfaction. This makes the recommendations socially acceptable because participation is rational for everyone involved.

3. **Hard rules are inviolable.** Duty-hour law and personal day-off requests are constraints, not preferences. A trade that breaks them is never proposed, regardless of how much happiness it would create.

---

## 2. Preferences and Satisfaction

Each resident completes a short form expressing three preferences, each paired with a subjective weight:

- **Location** (MGH, BWH, or no preference).
- **Time of day** (Morning, Swing, Overnight, or no preference).
- **Streak length**, representing the ideal number of consecutive days worked (3 to 6).

Residents also list specific **days off** that they require to remain shift-free.

### 2.1 Satisfaction scores

For a resident $i$ with assigned shift set $A_i$, we define three normalized satisfaction scores, each in $[0,1]$:

$$
\phi_{\text{loc}}(A_i)=\frac{|\{s\in A_i : \mathrm{loc}(s)=p_{\text{loc},i}\}|}{|A_i|},
\qquad
\phi_{\text{type}}(A_i)=\frac{|\{s\in A_i : \mathrm{type}(s)=p_{\text{type},i}\}|}{|A_i|}.
$$

The streak score penalizes deviation from the preferred run length $p_{\text{str},i}$. Let $\mathcal{B}(A_i)$ be the set of maximal consecutive-day runs in $A_i$:

$$
\phi_{\text{str}}(A_i)=\max\!\left(0,\;
1-\frac{1}{\beta\,|\mathcal{B}(A_i)|}\sum_{B\in\mathcal{B}(A_i)}\bigl|\,|B|-p_{\text{str},i}\bigr|\right),
\qquad \beta = 5,
$$

where $\beta$ is the maximum possible per-run deviation (run lengths lie in $[1,6]$, targets in $[3,6]$), guaranteeing $\phi_{\text{str}}\in[0,1]$. If a resident states no preference on a dimension, that score is set to $1$.

Some shifts are *attribute-agnostic*. Backup ("jeopardy") shifts have no meaningful location or time of day; they are excluded from the location and time sums above (they appear in neither the numerator nor the denominator). These shifts are ordinary worked days and so contribute to the consecutive-day runs $\mathcal{B}(A_i)$ that drive $\phi_{\text{str}}$ and the feasibility checks of Section 3.

**Jeopardy swap isolation.** To prevent cross-type trades that would transform a light backup shift into a full clinical shift (or vice versa), jeopardy shifts may only be swapped with other jeopardy shifts. Regular (non-jeopardy) shifts may only be swapped with other regular shifts. When the toggle `ALLOW_JEOPARDY_SWAPS` is set to `False`, jeopardy shifts are pinned: they are excluded from the trade graph entirely and never participate in any trade.

**Overnight shift isolation.** Overnight shifts may only be traded with other overnight shifts; they are never swappable with Morning or Swing shifts. This prevents a trade from converting a night shift into a day shift (or vice versa), which would silently alter the on-duty overnight staffing level that the base schedule was designed to maintain.

### 2.2 Individual utility

Weights are normalized per resident so that $w_{\text{loc},i}+w_{\text{type},i}+w_{\text{str},i}=1$. This normalization is necessary to place every resident's happiness on a common $[0,1]$ scale. It ensures that gains are comparable across residents and that the mechanism does not systematically favor residents who enter larger raw weights. The total utility is

$$
U_i(A_i)=w_{\text{loc},i}\,\phi_{\text{loc}}(A_i)
        +w_{\text{type},i}\,\phi_{\text{type}}(A_i)
        +w_{\text{str},i}\,\phi_{\text{str}}(A_i)\;\in[0,1].
$$

---

## 3. Hard Constraints

A shift set $A_i$ is **feasible**, written $V(A_i)=1$, if and only if all three conditions hold:

- **Minimum rest.** Sorting $A_i$ by start time, every chronologically adjacent pair $(s_x,s_{x+1})$ satisfies $t_{\text{start}}(s_{x+1})-t_{\text{end}}(s_x)\ge 12$ hours. This condition also forbids overlapping shifts.
- **Maximum streak.** Every maximal consecutive-day run has length $\le 6$.
- **Day-off respect.** No shift falls on a date the resident declared off.

The day-off rule is the mechanism's strict constraint. If a resident has reserved a date, any candidate trade that would place a shift on that date is rejected before utility is calculated.

---

## 4. The Trade Graph

The central object is a **directed trade graph** $G=(S,E)$ whose nodes are the individual shifts. We draw an edge $u\!\to\!v$ when the owner of $u$ would be willing and able to give up $u$ in exchange for $v$. Formally, if $u\in A_i$ and $v\in A_j$ with $i\ne j$, and $A_i'=(A_i\setminus\{u\})\cup\{v\}$, then

$$
(u\to v)\in E
\iff
\mathrm{jeop}(u)=\mathrm{jeop}(v)
\;\wedge\;
\mathbb{1}[\mathrm{type}(u)=\text{Overnight}]=\mathbb{1}[\mathrm{type}(v)=\text{Overnight}]
\;\wedge\;
V(A_i')=1
\;\wedge\;
\mathrm{date}(v)\notin \text{DaysOff}_i
\;\wedge\;
U_i(A_i')\ge U_i(A_i).
$$

In words: the edge exists only if $u$ and $v$ are of the same type (both jeopardy or both regular), both are overnight or both are non-overnight, receiving $v$ keeps resident $i$ legal, respects their days off, and does not lower their utility.

When `ALLOW_JEOPARDY_SWAPS` is `False`, jeopardy shifts are removed from the node set entirely and cannot appear on either side of any edge.

A **trade** corresponds to a directed cycle in this graph. A 2-cycle $u\!\to\!v\!\to\!u$ is a simple 1-for-1 swap. A 3-cycle $u\!\to\!v\!\to\!w\!\to\!u$ is a three-way rotation: $u$'s owner takes $v$, $v$'s owner takes $w$, $w$'s owner takes $u$. Because each resident in a cycle gives up exactly one shift and receives exactly one, workload is conserved automatically.

This construction is a bounded, preference-aware variant of the classic *Top Trading Cycles* idea from matching theory, restricted to short cycles for tractability and transparency.

---

## 5. The Algorithm

Four hyperparameters control the trade search:

- $K_{\text{pp}}$, the **per-person participation cap**: the maximum number of trades any single resident may appear in (any role). Set to $-1$ for unlimited. Default is $3$. This limit ensures equity; no resident is churned through many trades while others remain unchanged. It also bounds the all-subset verification cost at $2^{K_{\text{pp}}}$ subsets per resident per candidate.
- $n_{\max}$, the **maximum cycle length**: $2$ for 1-for-1 trades only, $3$ to also allow three-way rotations.
- `ALLOW_JEOPARDY_SWAPS`: when `True`, jeopardy shifts participate in trading but are type-isolated (jeopardy trades only with jeopardy); when `False` (default), jeopardy shifts are pinned and excluded from all trading.
- `START_DATE`: a datetime threshold (or empty string `""` to allow all dates). Scheduled shifts before this date are discarded during ingestion and cannot be traded.

The mechanism runs in a single pass over a fixed snapshot of the original schedule:

1. **Build** the trade graph $G$ once from the original schedule. The schedule is not modified during the selection phase.
2. **Enumerate** all simple cycles of length $\le n_{\max}$ and evaluate each against the original snapshot: recompute each participant's post-trade utility and discard cycles where any participant is worse off or no participant is strictly better. Each surviving cycle's deltas are measured against the original, unmodified schedule.
3. **Sort** surviving cycles by total utility gain $\Delta U_{\text{total}}=\sum_{x}\Delta U_x$, descending.
4. **Select greedily**: iterate over sorted candidates and, for each, apply three acceptance tests in order:
   - **Shift-disjointness.** If any shift uid in the candidate (given or received) appears in an already-selected trade, skip. This ensures no shift is traded twice.
   - **Participation cap.** If any participant would exceed $K_{\text{pp}}$ total trades, skip (unless $K_{\text{pp}}=-1$).
   - **All-subset independence check.** For every participant $i$, let $T_i$ be the set of already-selected trades in which $i$ appears. For every non-empty subset $S \subseteq T_i \cup \{\text{candidate}\}$ that includes the candidate, reconstruct $i$'s shift set from the original by applying every move in $S$. Require (a) $V(A_i') = 1$ (ACGME-legal, day-off-respecting, no overlap) and (b) $U_i(A_i') \ge U_i(A_i^{\text{orig}})$. Subsets that do not include the candidate were verified when each earlier trade was accepted, so only subsets containing the candidate need testing. If any subset fails, skip the candidate.

   If all three tests pass, **accept** the candidate: record it, mark its shifts used, and update participant counts.
5. **Apply** all selected trades to the schedule. Because selected trades are shift-disjoint, the final schedule is the same regardless of application order.

The output is an unordered set of concrete, explainable recommendations. Because every accepted trade passed the all-subset check, a chief resident may approve any subset of recommendations, in any order, and each approved trade is guaranteed to be ACGME-legal and utility-improving for all participants involved.

---

## 6. Guarantees

We state the properties the mechanism provides and argue each informally.

**Proposition 1 (Legality).** *Every schedule produced is ACGME-compliant and respects all day-off requests.*

*Argument.* The initial schedule is assumed legal. Inductively, suppose the schedule before a trade is legal. A cycle is applied only after step 3 recomputes each participant's post-trade shift set and confirms $V=1$ for all of them. Non-participants are untouched. Hence the post-trade schedule is legal. By induction every intermediate and final schedule is legal. $\square$

**Proposition 2 (Pareto improvement).** *No resident's utility decreases, and each executed trade increases group satisfaction.*

*Argument.* Step 3 admits a cycle only if $\Delta U_x\ge 0$ for every participant $x$ and $\Delta U_x>0$ for at least one; non-participants have $\Delta U_x=0$. Therefore each trade is a weak improvement for all residents and a strict improvement for the total $\Delta U_{\text{total}}>0$. Composing such steps preserves the property: no resident's utility ever decreases across the entire run. $\square$

**Proposition 3 (Termination).** *The algorithm halts.*

*Argument.* The algorithm is a single greedy pass over a finite list of candidate cycles enumerated from a fixed graph. The number of simple cycles of length $\le 3$ in a finite graph is finite, so the candidate list is finite and the pass terminates. $\square$

**Proposition 4 (Soundness of the short-cycle edge model).** *For $n_{\max}\le 3$, the per-edge feasibility and utility checks fully characterize each participant's post-trade state.*

*Argument.* In a simple cycle of length 2 or 3, every pair of nodes is adjacent, and adjacency forbids shared ownership (edges require $i\ne j$). Hence all participants in such a cycle are distinct, and each gives up exactly one shift and receives exactly one. The single-swap set $A_i'$ used to define each edge is therefore precisely that resident's true post-trade schedule, so the edge-level $V$ and $U$ tests are exact. (For cycles of length $\ge 4$ a resident may appear twice, giving up or receiving two shifts; the single-swap edge test no longer captures their combined post-trade state. This is the formal reason the mechanism caps $n_{\max}$ at 3 unless full per-cycle recomputation is added.) $\square$

**Proposition 5 (Full independence).** *Any non-empty subset of the recommended trades, applied in any order, is ACGME-legal and leaves no participant's utility below their original value.*

*Argument.* Fix any non-empty subset $\mathcal{S}$ of recommended trades and any participant $i$ who appears in at least one trade in $\mathcal{S}$. Let $\mathcal{S}_i \subseteq \mathcal{S}$ be the trades in $\mathcal{S}$ that involve $i$. By shift-disjointness (acceptance test 1), no shift uid appears in two selected trades, so the moves of the trades in $\mathcal{S}_i$ act on disjoint shifts; the order in which they are applied is therefore irrelevant and the resulting shift set $A_i'$ depends only on $\mathcal{S}_i$, not on any other trade in $\mathcal{S}$. The all-subset independence check (acceptance test 3) required, at the moment each trade in $\mathcal{S}_i$ was accepted, that for every subset of the then-selected trades for $i$ plus the candidate—including the subset $\mathcal{S}_i$ itself—the resulting $A_i'$ satisfies $V(A_i')=1$ and $U_i(A_i') \ge U_i(A_i^{\text{orig}})$. Non-participants have $A_i' = A_i^{\text{orig}}$ and are trivially unaffected. Hence the post-trade schedule for every subset $\mathcal{S}$ is legal and Pareto-non-worsening for all residents. $\square$

---

## 7. Discussion and Limitations

**Greedy, not globally optimal.** The mechanism increases satisfaction sequentially, one trade at a time. Locally best Pareto-improving trade sequences do not necessarily reach a globally optimal allocation; a different ordering could in principle yield a higher final total. This trade-off is acceptable because the greedy policy is transparent, fast, and each step is independently justifiable to the affected residents. We value these properties more than a marginal optimality gain that is difficult to explain.

**Preference modeling.** Satisfaction is linear in three normalized scores. This formulation is interpretable and easy to elicit but cannot express interactions (e.g. "I only mind overnights when they are at BWH"). Richer utility models slot directly into the same graph machinery.

**Strict Pareto can be conservative.** Because no resident may lose utility, some globally beneficial reshuffles, where one person sacrifices slightly so several others gain a lot, are excluded by design. This is the cost of guaranteeing voluntary, no-regret participation.

**Cycle length.** Restricting to 2- and 3-cycles keeps the search fast and the recommendations human-comprehensible. Longer rotations are mechanically possible but are harder to coordinate in practice and require the stronger per-cycle recomputation noted in Proposition 4.

**Full independence via single-snapshot selection with all-subset verification.** The mechanism now builds the trade graph once against the original schedule and selects a shift-disjoint set of trades. Shift-disjointness alone prevents shift reuse but does not, by itself, guarantee subset independence: a resident who appears in two trades on two distinct shifts could still have a shift-set interaction (e.g. a streak violation) that only materializes when both trades are applied. The mechanism therefore adds an **all-subset feasibility and Pareto check** (acceptance test 3 in Section 5) at selection time. This check verifies, for every participant and every subset of their selected trades including the candidate, that the resulting schedule is ACGME-legal and utility-non-worsening relative to the original. Proposition 5 establishes that this is sufficient for full independence.

The cost of the all-subset check is $O(2^{K_{\text{pp}}})$ subsets per participant per candidate. With the default cap $K_{\text{pp}} = 3$, this is at most 8 subsets; even at $K_{\text{pp}} = 6$ it is 64 subsets, each requiring one utility evaluation and one feasibility scan—negligible for programs of this size. A conservative special case is **resident-disjoint** selection, which caps each resident at a single trade and trivially satisfies independence (no resident has two trades to interact). Resident-disjointness is not required here; the all-subset check provides the same formal guarantee with greater flexibility.

---

## 8. Future Directions

The current preference model rests on three dimensions: location, time of day, and streak length. Each treats a shift as an indivisible, equally-weighted unit of work. In practice, residents care not only about *where* and *when* they work but about *how much* a given shift costs them, and that cost varies systematically with shift length, the calendar position of the shift, and whether it falls overnight. The following extensions enrich the satisfaction model along these axes. Crucially, each one slots into the existing trade-graph machinery without altering the core guarantees of Section 6: as long as every new term enters $U_i$ as a bounded score and the per-edge utility test $U_i(A_i')\ge U_i(A_i)$ is preserved, Legality, Pareto improvement, Termination, and No shift chaining all continue to hold unchanged.

### 8.1 Factoring in shift lengths

**Motivation.** The mechanism currently treats a 8-hour shift and a 12-hour shift as interchangeable units. A 1-for-1 swap can therefore silently hand a resident more total hours even though workload is "conserved" in the sense of shift *count*. Residents experience a long shift as more burdensome than a short one, and a fair exchange should account for this asymmetry.

**Proposed plan.**

1. **Data.** Augment each shift $s$ with its duration $\ell(s)$ in hours, already implicitly available from the start/end times used in the rest-period check of Section 3.
2. **Duration-aware satisfaction.** Introduce a fourth normalized score $\phi_{\text{len}}(A_i)\in[0,1]$ that penalizes deviation of a resident's shift durations from a preferred shift length $p_{\text{len},i}$ (or rewards shorter shifts if the resident expresses a "minimize hours" preference), constructed analogously to the streak score:
   $$
   \phi_{\text{len}}(A_i)=\max\!\left(0,\;1-\frac{1}{\gamma\,|A_i|}\sum_{s\in A_i}\bigl|\,\ell(s)-p_{\text{len},i}\bigr|\right),
   $$
   where $\gamma$ is the maximum possible per-shift duration deviation, guaranteeing $\phi_{\text{len}}\in[0,1]$. A resident expressing no length preference receives $\phi_{\text{len}}=1$.
3. **Weight integration.** Extend the per-resident weight normalization to $w_{\text{loc},i}+w_{\text{type},i}+w_{\text{str},i}+w_{\text{len},i}=1$, and add the new term to $U_i$.
4. **Optional hard guard.** For programs that must conserve *hours*, not just shift counts, add a feasibility predicate that rejects any trade whose net hour delta for a resident exceeds a tolerance $\tau$ (e.g. $\pm 4$ hours). This converts duration-fairness from a soft preference into a hard constraint, at the cost of pruning otherwise Pareto-improving trades.

### 8.2 Factoring in weekend / holiday vs. weekday

**Motivation.** A Saturday shift and a Tuesday shift are nominally identical units of work but carry very different opportunity costs. Most residents strongly prefer to offload weekend and holiday shifts; a swap that quietly moves a holiday shift onto an unwilling resident, while legal and count-neutral, is socially undesirable. Conversely, some residents actively prefer weekend work (e.g. to keep weekdays free). The model should let residents express this and should value such trades accordingly.

**Proposed plan.**

1. **Calendar classification.** Tag each shift $s$ with a categorical label $\mathrm{cal}(s)\in\{\text{weekday},\text{weekend},\text{holiday}\}$, derived from its date and a configurable holiday calendar (a simple date set; institution-specific holidays such as program retreat days can be appended).
2. **Preference elicitation.** Add a preference field capturing the resident's stance on premium days, e.g. a target fraction $p_{\text{cal},i}$ of weekend/holiday shifts, or a simpler categorical "prefer fewer / indifferent / prefer more."
3. **Satisfaction score.** Define $\phi_{\text{cal}}(A_i)\in[0,1]$ measuring agreement between the resident's realized weekend/holiday load and their stated preference. For a "prefer fewer" resident this is $1-(\text{fraction of premium shifts})$ (clamped), and for "prefer more" the complement; an indifferent resident scores $1$.
4. **Weight integration.** Add $w_{\text{cal},i}$ to the normalized weight sum, exactly as in 8.1.
5. **Holiday equity reporting (optional, no model change).** Independently of utility, surface a per-resident tally of weekend/holiday shifts before and after the recommended trade set, so a chief can confirm the mechanism is not concentrating premium days on a few residents. This is a transparency feature layered on top of the existing output and requires no change to the trade search.

### 8.3 Factoring in overnights

**Motivation.** Overnights are already special-cased structurally: Section 2.1 isolates them so they may only be traded for other overnights, preserving the base schedule's nightly staffing. But isolation only governs *which* trades are legal; it says nothing about how *costly* an overnight is to the resident working it. An overnight imposes a circadian burden that is poorly captured by either the time-of-day score (which is satisfied as soon as an overnight-preferring resident gets any overnight) or the streak score (which counts a night the same as a day). Overnights deserve an explicit, separately tunable weight, conceptually nested within the broader notion of shift "cost" introduced in 8.1.

**Proposed plan.**

1. **Burden weighting, not just type matching.** Rather than treating "Overnight" purely as a categorical time-of-day value, attach to each shift an effective-burden multiplier $\rho(s)$ that scales an overnight's contribution above that of a same-length day shift (e.g. $\rho_{\text{night}}=1.3$, $\rho_{\text{day}}=1.0$). This multiplier is the natural home for the "overnights cost more than their clock hours suggest" intuition.
2. **Coupling with the length score.** Fold $\rho(s)$ into the duration term of 8.1 by replacing the raw duration $\ell(s)$ with an *effective duration* $\tilde{\ell}(s)=\rho(s)\,\ell(s)$ wherever shift cost is accumulated. This realizes the user's intent that overnight weighting "be considered within the shift-length weight": a 10-hour overnight then carries the burden of a 13-hour day shift, and the duration-fairness machinery of 8.1 automatically accounts for it without a separate normalization term.
3. **Standalone overnight preference (optional).** For residents whose feelings about nights are not reducible to burden hours, additionally expose an explicit $\phi_{\text{night}}(A_i)\in[0,1]$ scoring agreement between their realized overnight count and a preferred count $p_{\text{night},i}$, with its own weight $w_{\text{night},i}$. This is the most flexible but also the most elicitation-heavy option; the burden-multiplier route (steps 1–2) is the recommended default because it adds expressiveness with no new survey questions.
4. **Consecutive-nights guard (optional hard constraint).** Because clustered overnights are a known fatigue and safety concern, optionally add a feasibility predicate bounding the longest run of consecutive overnight shifts, analogous to the maximum-streak rule of Section 3. This keeps the mechanism from assembling a punishing string of nights even when each individual trade is locally preferred.

### 8.4 Cross-cutting implementation notes

All three extensions share the same integration pattern and therefore the same risk profile:

- **Score, then weight, then test.** Each new dimension is added as a bounded score in $[0,1]$, given a per-resident weight folded into the unit-sum normalization of Section 2.2, and then automatically respected by the existing per-edge test $U_i(A_i')\ge U_i(A_i)$. No change to the cycle-enumeration or greedy-application logic is required.
- **Guarantees are preserved by construction.** Section 6's proofs depend only on (i) feasibility being checked per participant and (ii) utility being non-decreasing per participant. Any added soft score leaves both intact; any added *hard* guard (the optional hour-tolerance, consecutive-nights, or holiday-equity constraints) only ever *shrinks* the edge set, so Legality and Termination still hold and Pareto improvement is unaffected.
- **Elicitation cost is the real constraint.** The limiting factor is not algorithmic but human: every new weight is another question on the resident survey. A sensible rollout introduces shift length and overnight burden first (they can share a single "how much do long shifts and nights bother you?" elicitation via the effective-duration coupling of 8.3), and adds the weekend/holiday dimension as a second phase once the duration model is validated.

---

## 9. Conclusion

We framed resident schedule improvement not as a re-optimization problem but as a *trade discovery* problem, and solved it with a bounded, Pareto-improving cycle mechanism on a directed trade graph. The result is a tool that respects the existing schedule, never harms anyone, never breaks the rules, and explains every recommendation it makes. Two parameters, the swap budget $K$ and the cycle length $n_{\max}$, let a program control how many swaps are executed.
