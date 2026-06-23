# A Bounded Pareto-Improving Exchange Mechanism for Resident Shift Scheduling

## Abstract

Emergency medicine residents work schedules that are simultaneously constrained
by federal duty-hour regulations and shaped by strong individual preferences
about *where* they work, *when* they work, and *how many days in a row* they
work. Hand-built schedules are rarely able to satisfy everyone, yet they often
contain latent, mutually beneficial trades: pairs or small groups of residents
who would each be happier swapping shifts. We present a mechanism that
automatically discovers and ranks such trades. The method models the schedule as
a directed *trade graph*, searches for short improving cycles, and applies them
greedily under two firm guarantees: every executed trade strictly improves total
satisfaction while making *no resident worse off* (a Pareto improvement), and
every resulting schedule remains compliant with ACGME duty-hour rules and each
resident's hard day-off requests. The number and complexity of trades are both
user-controllable. The approach is transparent, auditable, and produces
human-readable swap recommendations rather than an opaque re-optimized schedule.

---

## 1. Problem Statement

Consider a residency program (here, the 15-resident Harvard-Affiliated Emergency
Medicine Residency) with a fixed block schedule already assigning every clinical
shift to a resident. We do not wish to rebuild this schedule from scratch — it
encodes staffing decisions, seniority, and educational requirements that are
expensive to re-derive and politically sensitive to overturn. Instead we ask a
narrower, safer question:

> Given the existing schedule, what set of voluntary shift trades would make the
> group happier, without harming any individual and without violating any rule?

Three design commitments follow from this framing:

1. **Conservation of workload.** Trades move shifts between residents but never
   create or delete them. Each resident ends with exactly as many shifts as they
   started with; only the *composition* changes. No one is handed extra work.

2. **No forced losses.** A resident will never be assigned a trade that lowers
   their own satisfaction. This is what makes the recommendations socially
   acceptable: participation is rational for everyone involved.

3. **Hard rules are inviolable.** Duty-hour law and personal day-off requests are
   constraints, not preferences. A trade that breaks them is never proposed,
   regardless of how much happiness it would create.

---

## 2. Preferences and Satisfaction

Each resident completes a short form expressing three preferences, each paired
with a subjective weight:

- **Location** — MGH, BWH, or no preference.
- **Time of day** — Morning, Swing, Overnight, or no preference.
- **Streak length** — the ideal number of consecutive days worked (3–6).

Additionally, residents list specific **days off** that they require to remain
shift-free.

### 2.1 Satisfaction scores

For a resident $i$ with assigned shift set $A_i$, we define three normalized
satisfaction scores, each in $[0,1]$:

$$
\phi_{\text{loc}}(A_i)=\frac{|\{s\in A_i : \mathrm{loc}(s)=p_{\text{loc},i}\}|}{|A_i|},
\qquad
\phi_{\text{type}}(A_i)=\frac{|\{s\in A_i : \mathrm{type}(s)=p_{\text{type},i}\}|}{|A_i|}.
$$

The streak score penalizes deviation from the preferred run length
$p_{\text{str},i}$. Let $\mathcal{B}(A_i)$ be the set of maximal consecutive-day
runs in $A_i$:

$$
\phi_{\text{str}}(A_i)=\max\!\left(0,\;
1-\frac{1}{\beta\,|\mathcal{B}(A_i)|}\sum_{B\in\mathcal{B}(A_i)}\bigl|\,|B|-p_{\text{str},i}\bigr|\right),
\qquad \beta = 5,
$$

where $\beta$ is the maximum possible per-run deviation (run lengths lie in
$[1,6]$, targets in $[3,6]$), guaranteeing $\phi_{\text{str}}\in[0,1]$. If a
resident states no preference on a dimension, that score is set to $1$.

Some shifts are *attribute-agnostic*. Backup ("jeopardy") shifts have no
meaningful location or time of day; they are fully tradeable, but they are
excluded from the location and time sums above (they appear in neither the
numerator nor the denominator). They are, however, ordinary worked days and so
contribute to the consecutive-day runs $\mathcal{B}(A_i)$ that drive
$\phi_{\text{str}}$ and the feasibility checks of Section 3.

### 2.2 Individual utility

Weights are normalized per resident so that
$w_{\text{loc},i}+w_{\text{type},i}+w_{\text{str},i}=1$. This is essential: it
places every resident's happiness on a common $[0,1]$ scale so that gains are
comparable across people and the mechanism does not systematically favor whoever
happened to enter the largest raw weights. The total utility is

$$
U_i(A_i)=w_{\text{loc},i}\,\phi_{\text{loc}}(A_i)
        +w_{\text{type},i}\,\phi_{\text{type}}(A_i)
        +w_{\text{str},i}\,\phi_{\text{str}}(A_i)\;\in[0,1].
$$

---

## 3. Hard Constraints

A shift set $A_i$ is **feasible**, written $V(A_i)=1$, iff all three hold:

- **Minimum rest.** Sorting $A_i$ by start time, every chronologically adjacent
  pair $(s_x,s_{x+1})$ satisfies
  $t_{\text{start}}(s_{x+1})-t_{\text{end}}(s_x)\ge 12$ hours. (This also forbids
  overlapping shifts.)
- **Maximum streak.** Every maximal consecutive-day run has length $\le 6$.
- **Day-off respect.** No shift falls on a date the resident declared off.

The day-off rule deserves emphasis because it is the mechanism's hardest "no": if
a resident has reserved a date, *any* candidate trade that would place a shift on
that date is rejected outright, before utility is ever considered.

---

## 4. The Trade Graph

The central object is a **directed trade graph** $G=(S,E)$ whose nodes are the
individual shifts. We draw an edge $u\!\to\!v$ when the owner of $u$ would be
willing and able to give up $u$ in exchange for $v$. Formally, if $u\in A_i$ and
$v\in A_j$ with $i\ne j$, and $A_i'=(A_i\setminus\{u\})\cup\{v\}$, then

$$
(u\to v)\in E
\iff
V(A_i')=1
\;\wedge\;
\mathrm{date}(v)\notin \text{DaysOff}_i
\;\wedge\;
U_i(A_i')\ge U_i(A_i).
$$

In words: the edge exists only if receiving $v$ keeps resident $i$ legal,
respects their days off, and does not lower their happiness.

A **trade** corresponds to a directed cycle in this graph. A 2-cycle
$u\!\to\!v\!\to\!u$ is a simple 1-for-1 swap. A 3-cycle
$u\!\to\!v\!\to\!w\!\to\!u$ is a three-way rotation: $u$'s owner takes $v$, $v$'s
owner takes $w$, $w$'s owner takes $u$. Because each resident in a cycle gives up
exactly one shift and receives exactly one, workload is conserved automatically.

This construction is a bounded, preference-aware variant of the classic *Top
Trading Cycles* idea from matching theory, restricted to short cycles for
tractability and transparency.

---

## 5. The Algorithm

Two hyperparameters give the scheduler direct control:

- $K$ — the **swap budget**: the total number of shifts allowed to change hands.
- $n_{\max}$ — the **maximum cycle length**: $2$ for 1-for-1 trades only, $3$ to
  also allow three-way rotations.

The mechanism iterates:

1. **Build** the trade graph $G$ from the current schedule.
2. **Enumerate** all simple cycles of length $\le n_{\max}$. For $n_{\max}=2$ this
   is just a search for mutual edges; for $n_{\max}=3$ a depth-limited cycle
   search suffices.
3. **Filter** to cycles that are *strictly Pareto-improving*: recompute each
   participant's post-trade utility and keep the cycle only if no participant is
   worse off and at least one is strictly better. Score each surviving cycle by
   its total happiness gain $\Delta U_{\text{total}}=\sum_{x}\Delta U_x$.
4. **Apply greedily**: execute the highest-scoring cycle that fits within the
   remaining budget, update the schedule, and return to step 1.
5. **Terminate** when no budget-fitting, Pareto-improving cycle remains.

Rebuilding the graph after each executed trade is deliberate: it keeps every
decision based on the true current state and sidesteps the bookkeeping of
overlapping candidate cycles. For a program of this size the cost is negligible.

The output is an ordered list of concrete, explainable recommendations — e.g.
*"Resident A gives their July 9 MGH swing shift and receives Resident B's July 11
MGH morning shift; both are happier"* — which a chief resident can review and
approve individually.

---

## 6. Guarantees

We state the properties the mechanism provides and argue each informally.

**Proposition 1 (Legality).** *Every schedule produced is ACGME-compliant and
respects all day-off requests.*

*Argument.* The initial schedule is assumed legal. Inductively, suppose the
schedule before a trade is legal. A cycle is applied only after step 3 recomputes
each participant's post-trade shift set and confirms $V=1$ for all of them.
Non-participants are untouched. Hence the post-trade schedule is legal. By
induction every intermediate and final schedule is legal. $\square$

**Proposition 2 (Pareto improvement).** *No resident is ever made worse off, and
each executed trade makes the group strictly better off.*

*Argument.* Step 3 admits a cycle only if $\Delta U_x\ge 0$ for every participant
$x$ and $\Delta U_x>0$ for at least one; non-participants have $\Delta U_x=0$.
Therefore each trade is a weak improvement for all residents and a strict
improvement for the total $\Delta U_{\text{total}}>0$. Composing such steps
preserves the property: no resident's utility ever decreases across the entire
run. $\square$

**Proposition 3 (Termination).** *The algorithm halts.*

*Argument.* Two independent reasons. First, the swap budget $K$ is finite and the
counter of shifts changed hands is non-decreasing, strictly increasing by at
least 2 on every executed cycle; once it would exceed $K$ no further cycle is
applied. Second, total system utility $\sum_i U_i$ is bounded above by $N$ and
strictly increases by $\Delta U_{\text{total}}>0$ at each step, so only finitely
many steps are possible even without a budget. $\square$

**Proposition 4 (Soundness of the short-cycle edge model).** *For
$n_{\max}\le 3$, the per-edge feasibility and utility checks fully characterize
each participant's post-trade state.*

*Argument.* In a simple cycle of length 2 or 3, every pair of nodes is adjacent,
and adjacency forbids shared ownership (edges require $i\ne j$). Hence all
participants in such a cycle are distinct, and each gives up exactly one shift and
receives exactly one. The single-swap set $A_i'$ used to define each edge is
therefore precisely that resident's true post-trade schedule, so the edge-level
$V$ and $U$ tests are exact. (For cycles of length $\ge 4$ a resident may appear
twice, giving up or receiving two shifts; the single-swap edge test no longer
captures their combined post-trade state. This is the formal reason the
mechanism caps $n_{\max}$ at 3 unless full per-cycle recomputation is added.)
$\square$

---

## 7. Discussion and Limitations

**Greedy, not globally optimal.** The mechanism maximizes happiness one trade at
a time. The sequence of locally best Pareto-improving trades need not reach the
globally best reachable allocation; a different ordering could in principle yield
a higher final total. We accept this: the greedy policy is transparent, fast, and
each step is independently justifiable to the residents affected — properties we
value more than a marginal optimality gain that would be hard to explain.

**Preference modeling.** Satisfaction is linear in three normalized scores. This
is interpretable and easy to elicit but cannot express interactions (e.g. "I
only mind overnights when they are at BWH"). Richer utility models slot directly
into the same graph machinery.

**Strict Pareto can be conservative.** Because no resident may lose even a little,
some globally beneficial reshuffles — where one person sacrifices slightly so
several others gain a lot — are excluded by design. This is the price of
guaranteeing voluntary, no-regret participation.

**Cycle length.** Restricting to 2- and 3-cycles keeps the search fast and the
recommendations human-comprehensible. Longer rotations are mechanically possible
but are harder to coordinate in practice and require the stronger per-cycle
recomputation noted in Proposition 4.

---

## 8. Conclusion

We framed resident schedule improvement not as a re-optimization problem but as a
*trade discovery* problem, and solved it with a bounded, Pareto-improving cycle
mechanism on a directed trade graph. The result is a tool that respects the
existing schedule, never harms anyone, never breaks the rules, and explains every
recommendation it makes — with two intuitive dials, the swap budget $K$ and the
cycle length $n_{\max}$, that let a program control exactly how aggressive the
optimization is.
