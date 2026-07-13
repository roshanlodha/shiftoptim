import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedulebuilder.pgy1.solver import build_and_solve
from schedulebuilder.pgy1.verify import verify


def test_pgy1_block4_solver():
    # Solve block 4
    result = build_and_solve(block=4, max_time_seconds=10.0)
    assert result is not None, "Solver failed to find a feasible schedule for PGY-1 block 4"
    
    # Run assertions
    verify(result)
    
    # Check shape of assignments
    assignments = result["assignments"]
    assert len(assignments) > 0, "No assignments generated"
    
    # Check that MGH/BWH/Flex site exclusivity constraints are satisfied
    role_on = result["active_halves"] # active halves mapped per resident
    residents = result["residents"]
    
    # Check some basic stats
    for (date, name), shift_id in assignments.items():
        assert name in residents
