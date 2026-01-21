"""
BD Analysis Mode for Chainlit.

Provides BD-specific handlers for the Chainlit UI:
- BD trigger form handling
- Progress updates during orchestration
- Report rendering as structured markdown
"""
import logging
from typing import Optional, Callable, Any
from datetime import datetime

import chainlit as cl

from models.bd_schemas import BDTrigger, MDReport, MDReportOpportunity
from services.bd_orchestrator import BDOrchestrator
from services.opportunity_extractor import OpportunityExtractor
from agents.credentials_agent import CredentialsAgent
from agents.final_analyst_agent import FinalAnalystAgent
from pathlib import Path

logger = logging.getLogger(__name__)

# Session keys
BD_MODE_SESSION_KEY = "bd_mode_enabled"
BD_TRIGGER_SESSION_KEY = "bd_trigger"

# Traces directory
TRACES_DIR = Path(__file__).parent.parent / "traces"


async def show_bd_mode_selection():
    """Show BD mode selection action buttons."""
    actions = [
        cl.Action(
            name="enable_bd_mode",
            label="🎯 BD Analysis Mode",
            payload={"mode": "bd"}
        ),
    ]
    await cl.Message(
        content="**BD Mode Available**: Analyze opportunities with Credentials validation",
        actions=actions
    ).send()


@cl.action_callback("enable_bd_mode")
async def on_enable_bd_mode(action: cl.Action):
    """Handle BD mode activation."""
    cl.user_session.set(BD_MODE_SESSION_KEY, True)
    await cl.Message("✓ **BD Analysis Mode** enabled").send()
    await show_bd_trigger_form()


async def show_bd_trigger_form():
    """Show the BD trigger form for parameter input."""
    # For now, use a simpler approach with actions
    # Full CustomElement form can be added later
    
    sectors = ["Defense", "Financial Services", "Healthcare", "Technology", "Energy", "General"]
    signals = ["CMMC", "Regulatory Change", "M&A Activity", "Leadership Change", "Contract Awards"]
    
    # Create sector selection
    sector_actions = [
        cl.Action(
            name="bd_set_sector",
            label=sector,
            payload={"sector": sector}
        )
        for sector in sectors
    ]
    
    await cl.Message(
        content="**Step 1**: Select target sector:",
        actions=sector_actions
    ).send()


@cl.action_callback("bd_set_sector")
async def on_bd_set_sector(action: cl.Action):
    """Handle sector selection."""
    sector = (action.payload or {}).get("sector", "General")
    
    # Store in session
    trigger_data = cl.user_session.get(BD_TRIGGER_SESSION_KEY) or {}
    trigger_data["sector"] = sector
    cl.user_session.set(BD_TRIGGER_SESSION_KEY, trigger_data)
    
    await cl.Message(f"✓ Sector: **{sector}**").send()
    
    # Show signal selection
    signals = ["CMMC", "Regulatory Change", "M&A Activity", "Leadership Change", "Contract Awards"]
    signal_actions = [
        cl.Action(
            name="bd_set_signal",
            label=signal,
            payload={"signal": signal}
        )
        for signal in signals
    ]
    
    await cl.Message(
        content="**Step 2**: Select primary signal to detect:",
        actions=signal_actions
    ).send()


@cl.action_callback("bd_set_signal")
async def on_bd_set_signal(action: cl.Action):
    """Handle signal selection and prompt for company."""
    signal = (action.payload or {}).get("signal", "CMMC")
    
    trigger_data = cl.user_session.get(BD_TRIGGER_SESSION_KEY) or {}
    trigger_data["signals"] = [signal]
    cl.user_session.set(BD_TRIGGER_SESSION_KEY, trigger_data)
    
    await cl.Message(f"✓ Signal: **{signal}**").send()
    
    await cl.Message(
        "**Step 3**: Type a target company name (optional, or type 'skip'):\n"
        "*Example: Hanwha, Lockheed Martin, General Dynamics*"
    ).send()
    
    # Mark that we're waiting for company input
    cl.user_session.set("bd_awaiting_company", True)


async def handle_bd_company_input(company_text: str) -> bool:
    """Handle company name input during BD setup.
    
    Returns True if this was BD company input, False otherwise.
    """
    if not cl.user_session.get("bd_awaiting_company"):
        return False
    
    cl.user_session.set("bd_awaiting_company", False)
    
    trigger_data = cl.user_session.get(BD_TRIGGER_SESSION_KEY) or {}
    
    if company_text.lower() != "skip":
        trigger_data["company_focus"] = company_text
        await cl.Message(f"✓ Company: **{company_text}**").send()
    else:
        await cl.Message("✓ No specific company focus").send()
    
    cl.user_session.set(BD_TRIGGER_SESSION_KEY, trigger_data)
    
    # Show final confirmation
    await cl.Message(
        "**Configuration Complete!**\n\n"
        "Now paste your Deep Research output below, or type a research question to start."
    ).send()
    
    cl.user_session.set("bd_ready_for_research", True)
    return True


async def handle_bd_research_input(research_text: str) -> bool:
    """Handle research input in BD mode.
    
    Returns True if this was handled as BD research, False otherwise.
    """
    if not cl.user_session.get(BD_MODE_SESSION_KEY):
        return False
    
    if not cl.user_session.get("bd_ready_for_research"):
        return False
    
    # Build trigger from session data
    trigger_data = cl.user_session.get(BD_TRIGGER_SESSION_KEY) or {}
    
    trigger = BDTrigger(
        sector=trigger_data.get("sector", "General"),
        signals=trigger_data.get("signals", []),
        company_focus=trigger_data.get("company_focus"),
        time_window_days=30
    )
    
    # Run orchestration
    await run_bd_orchestration(trigger, deep_research_output=research_text)
    return True


async def run_bd_orchestration(
    trigger: BDTrigger,
    deep_research_output: Optional[str] = None
):
    """Run BD orchestration with UI progress updates."""
    
    progress_msg = await cl.Message(
        content="**BD Analysis Started**\n\n⏳ Initializing..."
    ).send()
    
    async def progress_callback(message: str):
        """Update progress in Chainlit."""
        try:
            progress_msg.content = f"**BD Analysis in Progress**\n\n⏳ {message}"
            await progress_msg.update()
        except Exception as e:
            logger.warning(f"Progress update failed: {e}")
    
    try:
        # Initialize orchestrator
        orchestrator = BDOrchestrator(
            extractor=OpportunityExtractor(),
            credentials_agent=CredentialsAgent.from_env(),
            final_analyst=FinalAnalystAgent(),
            traces_dir=TRACES_DIR
        )
        
        # Run orchestration
        report = await orchestrator.run(
            trigger,
            deep_research_output=deep_research_output,
            progress_cb=progress_callback
        )
        
        # Render final report
        await render_md_report(report)
        
    except Exception as e:
        logger.exception(f"BD orchestration failed: {e}")
        await cl.Message(f"❌ **BD Analysis Failed**: {str(e)}").send()


async def render_md_report(report: MDReport):
    """Render MDReport as formatted markdown."""
    
    # Build markdown content
    lines = [
        "# 📊 BD Research Report",
        f"*Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M')}*",
        "",
        "## Executive Summary",
        report.executive_summary,
        ""
    ]
    
    # Top Opportunities
    if report.top_opportunities:
        lines.append("## Top Opportunities")
        lines.append("")
        
        for i, opp_report in enumerate(report.top_opportunities, 1):
            opp = opp_report.opportunity
            status_emoji = {
                "Validated": "✅",
                "Partial": "🔶",
                "No Internal Data": "❓"
            }.get(opp_report.validation_status, "❓")
            
            lines.append(f"### {i}. {opp.title}")
            if opp.agency:
                lines.append(f"**Agency**: {opp.agency}")
            if opp.estimated_value:
                lines.append(f"**Value**: {opp.estimated_value}")
            if opp.timeline:
                lines.append(f"**Timeline**: {opp.timeline}")
            lines.append(f"**Validation**: {status_emoji} {opp_report.validation_status}")
            
            # Show credentials if any
            if opp_report.credentials:
                lines.append("")
                lines.append("**Supporting Credentials**:")
                for cred in opp_report.credentials[:2]:
                    if cred.url:
                        lines.append(f"- [{cred.title}]({cred.url})")
                    else:
                        lines.append(f"- {cred.title}")
            
            lines.append("")
    
    # Signals Detected
    if report.signals_detected:
        lines.append("## Signals Detected")
        for signal in report.signals_detected[:5]:
            lines.append(f"• {signal}")
        lines.append("")
    
    # Recommended Actions
    if report.recommended_actions:
        lines.append("## Recommended Actions")
        for action in report.recommended_actions[:5]:
            lines.append(f"• {action}")
        lines.append("")
    
    # Confidence Note
    if report.confidence_note:
        lines.append("---")
        lines.append(f"*{report.confidence_note}*")
    
    await cl.Message("\n".join(lines)).send()


def is_bd_mode_active() -> bool:
    """Check if BD mode is currently active."""
    return cl.user_session.get(BD_MODE_SESSION_KEY, False)
