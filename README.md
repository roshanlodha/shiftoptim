# Shift Optimizer: Resident Shift Scheduling Exchange

Shift Optimizer is a tool designed to discover mutually beneficial shift trades among emergency medicine residents. Rather than rebuilding a schedule from scratch, this tool takes an existing schedule and identifies voluntary swaps that increase resident satisfaction without violating hard constraints.

## How the Algorithm Works

The exchange mechanism operates through a directed trade graph where each shift is a node.

1. **Graph Construction.** The algorithm draws an edge from shift A to shift B if the owner of shift A is willing and able to trade for shift B. An edge exists only if the swap maintains schedule legality, respects the owner's day-off requests, and does not decrease their satisfaction. Beyond location, time-of-day, and streak preferences, swaps that hand a resident more total hours than they started with are penalized, so count-neutral trades cannot silently increase someone's workload hours.
2. **Cycle Search.** The algorithm searches for cycles in the graph up to a maximum length (typically 2 or 3). A 2-cycle represents a direct swap between two residents. A 3-cycle represents a three-way rotation.
3. **Greedy Execution.** The algorithm identifies all valid cycles that are strictly Pareto-improving, meaning at least one resident is happier and no resident is worse off. It executes the trade with the highest utility gain first, updates the schedule, and rebuilds the trade graph.
4. **Termination.** This process repeats until no further Pareto-improving trades can be found, or until participants reach their individual swap budgets.

Shift Optimizer supports two execution modes:

### Limited Mode (default)

Production mode. Builds trade graph once against original schedule snapshot. Greedily selects shift-disjoint independent cycles using all-subsets checks. Keeps recommendations fully independent so chief resident can approve any subset in any order.

### Complete Mode (`--complete`)

Iterative mode. Rebuilds trade graph from mutated schedule at each step. Greedily applies best Pareto-improving cycle, locks shifts, and repeats until no cycles remain. Trades are sequentially dependent but can explore broader swap chains.

## Guarantees

The mechanism provides three core guarantees:

- **Schedule Legality.** Every proposed trade is checked against ACGME duty-hour rules (such as the 12-hour minimum rest period and the 6-day maximum consecutive work streak) and individual day-off requests. A trade that violates any rule is never executed.
- **Pareto Improvement.** A resident's utility is never decreased. Every trade makes at least one resident happier while leaving all other participants at least as satisfied as before.
- **Strict Workload Conservation.** Workloads are preserved. Residents only swap existing shifts, so everyone ends the process with the exact number of shifts they had at the start.

## Repository Structure

The project is structured as follows:

- [main.py](file:///Users/roshanlodha/Documents/shiftoptim/main.py): Command-line entrypoint.
- [requirements.txt](file:///Users/roshanlodha/Documents/shiftoptim/requirements.txt): Python dependencies.
- [shiftoptim/](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim): Core Python package.
  - [config.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/config.py): Configuration settings and defaults.
  - [models.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/models.py): Data structures for shifts, schedules, and residents.
  - [ingest.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/ingest.py): Logic to parse ICS files and preference CSVs.
  - [feasibility.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/feasibility.py): Verification of ACGME duty-hour compliance.
  - [utility.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/utility.py): Satisfaction score and adjusted utility calculation.
  - [graph.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/graph.py): Construction of the directed trade graph.
  - [optimizer.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/optimizer.py): Cycle detection and trade execution (both limited and complete modes).
  - [report.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/report.py): Plain text formatting for execution logs.
  - [render.py](file:///Users/roshanlodha/Documents/shiftoptim/shiftoptim/render.py): HTML report generator.
- [data/](file:///Users/roshanlodha/Documents/shiftmaxxer/data): Input schedules and preferences.
  - `ics/`: Input calendar files in iCalendar format.
  - `preferences.csv`: Resident preferences (location, time, streak length, weights, and days off).
- [tests/](file:///Users/roshanlodha/Documents/shiftmaxxer/tests): Automated tests.

## Installation and Usage

To set up the environment and run the optimizer:

1. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the main script to process the default data and generate an HTML report:
   ```bash
   python main.py
   ```

3. Customize execution using command-line arguments:
   ```bash
   python main.py -K 2 -n 2 --html customized_report.html
   ```

4. Run in Complete mode to iteratively rebuild the trade graph:
   ```bash
   python main.py --complete
   ```

    Key arguments:
    - `-K`, `--max-swaps-per-person`: The maximum number of swaps any single resident can be charged with as the primary beneficiary. Use -1 for unlimited.
    - `-n`, `--max-cycle`: The maximum cycle length to search for (2 for 1-for-1 swaps, 3 to include three-way rotations).
    - `--allow-jeopardy-swaps`: Allow jeopardy or backup shifts to participate in trading.
    - `--complete`: Enable Complete mode (iterative graph rebuilding).
    - `--ics`: Input calendar path. Defaults to `data/07_27_2026.ics`.
    - `--html`: Output path for the HTML report (default: `shiftswap.html`).

    Additional settings:
    - `START_DATE` (in `shiftoptim/config.py`): Scheduled shifts occurring before this date (e.g., July 27, 2026) are ignored and excluded from trading.
    - `TIME_DIFF_WEIGHT` (in `shiftoptim/config.py`): Linear penalty subtracted from a resident's utility for each net additional hour gained vs. their original schedule. Default `0.02`. Set to `0.0` to disable the penalty and treat all shift lengths as equal.
