"""FinGroww Trading Intelligence — Modular Flask Blueprints Package."""
from .paper_routes import paper_bp
from .market_routes import market_bp
from .skills_routes import skills_bp
from .agent_routes import agent_bp

__all__ = ["paper_bp", "market_bp", "skills_bp", "agent_bp"]
