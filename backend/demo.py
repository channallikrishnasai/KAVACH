"""Run the deterministic, local-only KAVACH demo from the backend venv."""
import asyncio

from kavach_core import (
    ActorInput,
    AgentRunInput,
    IncidentInput,
    SimulationInput,
    approve_command,
    create_kavach_incident,
    execute_command,
    inject_simulation,
    reset_state,
    run_agents,
)


async def main() -> None:
    reset_state()
    incident = await create_kavach_incident(IncidentInput(
        incident_type="collision",
        severity="high",
        description="Simulated road incident for local demonstration",
    ))
    investigation = await run_agents(AgentRunInput(incident_id=incident["incident_id"]))
    print(f"Incident: {incident['incident_id']} ({incident['data_state']})")
    print(f"Specialists: {len(investigation['agents'])}")
    print(f"Proposed route: {investigation['plan']['route']['provider']} · {investigation['plan']['route']['distance_km']} km")
    print(f"Status: {incident['status']} — waiting for explicit operator approval")

    await approve_command(incident["incident_id"], ActorInput(actor="demo_operator", role="OPERATOR"))
    execution = await execute_command(incident["incident_id"], ActorInput(actor="demo_commander", role="COMMANDER"))
    print(f"Local execution: {execution['incident']['status']} · verified={execution['incident']['verification']['passed']} · external actions sent={execution['external_actions_sent']}")

    replan = await inject_simulation(SimulationInput(event="road_block"))
    changed = replan["incident"]
    print(f"Injected road closure: replanned={replan['replanned']} · new status={changed['status']}")
    print(f"Updated route: {changed['route']['distance_km']} km · approval required again")
    await approve_command(changed["incident_id"], ActorInput(actor="demo_operator", role="OPERATOR"))
    final = await execute_command(changed["incident_id"], ActorInput(actor="demo_commander", role="COMMANDER"))
    print(f"Reapproved response: {final['incident']['status']} · verified={final['incident']['verification']['passed']}")
    print("All scenario records are SIMULATED. No emergency services or external messaging were contacted.")


if __name__ == "__main__":
    asyncio.run(main())
