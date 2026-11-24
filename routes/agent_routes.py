"""
FinGroww Trading Intelligence — Multi-Agent Swarm REST API Blueprint.
Modularized under routes/agent_routes.py.
"""

from flask import Blueprint, request, jsonify
import fingroww_market_server as srv

agent_bp = Blueprint("agent_api", __name__)


@agent_bp.get("/api/agents/status")
def get_swarm_status():
    if not srv.swarm_orchestrator:
        return jsonify({"ok": False, "error": "Swarm orchestrator not initialized"}), 503
    return jsonify({"ok": True, "data": srv.swarm_orchestrator.get_full_status()})


@agent_bp.post("/api/agents/control")
def update_swarm_control():
    if not srv.swarm_orchestrator:
        return jsonify({"ok": False, "error": "Swarm orchestrator not initialized"}), 503
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode")
    risk_profile = payload.get("risk_profile")
    is_active = payload.get("is_active")
    updated = srv.swarm_orchestrator.update_controls(mode=mode, risk_profile=risk_profile, is_active=is_active)
    return jsonify({"ok": True, "data": updated})


@agent_bp.get("/api/agents/audit")
def get_swarm_audit():
    if not srv.swarm_orchestrator:
        return jsonify({"ok": False, "error": "Swarm orchestrator not initialized"}), 503
    limit = int(request.args.get("limit", 40))
    trail = srv.swarm_orchestrator.bus.get_audit_trail(limit=limit)
    return jsonify({"ok": True, "count": len(trail), "trail": trail})


@agent_bp.post("/api/agents/approve")
def approve_swarm_signal():
    if not srv.swarm_orchestrator:
        return jsonify({"ok": False, "error": "Swarm orchestrator not initialized"}), 503
    payload = request.get_json(silent=True) or {}
    sig_id = payload.get("signal_id")
    if not sig_id:
        return jsonify({"ok": False, "error": "Missing signal_id"}), 400
    res = srv.swarm_orchestrator.approve_signal(sig_id)
    if res:
        return jsonify({"ok": True, "message": f"Signal {sig_id} approved and sent to Execution Sniper.", "signal": res})
    return jsonify({"ok": False, "error": f"Signal {sig_id} not found in pending queue"}), 404


@agent_bp.post("/api/agents/scan")
def trigger_swarm_scan():
    if not srv.swarm_orchestrator:
        return jsonify({"ok": False, "error": "Swarm orchestrator not initialized"}), 503
    res = srv.swarm_orchestrator.trigger_manual_cycle()
    return jsonify({"ok": True, "data": res})


@agent_bp.post("/api/agents/circuit-breaker/reset")
def reset_swarm_circuit_breaker():
    if not srv.swarm_orchestrator:
        return jsonify({"ok": False, "error": "Swarm orchestrator not initialized"}), 503
    srv.swarm_orchestrator.reset_circuit_breaker()
    return jsonify({"ok": True, "message": "Circuit breaker reset successfully."})
