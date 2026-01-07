"""
Prompt Generator Service — Generates research prompts from user parameters.

This service uses Semantic Kernel to generate deterministic research prompts
based on user-selected parameters (sector, signals, service lines, etc.).
"""
from __future__ import annotations
import json
import logging
from typing import Optional
from pathlib import Path
from dataclasses import dataclass, asdict

from semantic_kernel.functions import KernelFunctionFromPrompt
from semantic_kernel.functions.kernel_arguments import KernelArguments

logger = logging.getLogger(__name__)


@dataclass
class ResearchParameters:
    """Parameters for research prompt generation."""
    sector: str
    company: str = ""
    signals: str = ""
    service_lines: str = ""
    geography: str = ""
    min_value: str = ""
    time_window: str = ""
    other_context: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


class PromptGenerator:
    """Generates research prompts using Semantic Kernel."""
    
    def __init__(self):
        self.kernel = None
        self.exec_settings = None
        self.function = None
        self._load_function()
    
    def _load_function(self):
        """Load the prompt generator SK function."""
        sk_dir = Path(__file__).parent.parent / "sk_functions"
        prompt_path = sk_dir / "Prompt_Generator_prompt.txt"
        
        if not prompt_path.exists():
            logger.error(f"Prompt generator template not found: {prompt_path}")
            return
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()
        
        self.function = KernelFunctionFromPrompt(
            function_name="generate_prompt",
            plugin_name="prompt_plugin",
            description="Generates research prompts from parameters",
            prompt=template
        )
        logger.info("PromptGenerator function loaded")
    
    async def ensure_kernel_ready(self, analyst_agent):
        """Initialize kernel from analyst agent."""
        if self.kernel is None:
            await analyst_agent.ensure_kernel_ready()
            self.kernel = analyst_agent.kernel
            self.exec_settings = analyst_agent.exec_settings
            
            if self.function and self.kernel:
                try:
                    self.kernel.add_function(function=self.function, plugin_name="prompt_plugin")
                    logger.info("PromptGenerator function added to kernel")
                except Exception as e:
                    logger.warning(f"Failed to add prompt generator function: {e}")
    
    async def generate(self, params: ResearchParameters) -> str:
        """
        Generate a research prompt from parameters.
        
        Args:
            params: ResearchParameters with user inputs
            
        Returns:
            Generated prompt string
        """
        if not self.kernel or not self.function:
            logger.warning("Kernel not initialized, using fallback template")
            return self._fallback_template(params)
        
        try:
            # Build arguments for SK function
            arguments = KernelArguments(
                sector=params.sector or "General",
                company=params.company or "N/A",
                signals=params.signals or "N/A",
                service_lines=params.service_lines or "N/A",
                geography=params.geography or "N/A",
                min_value=params.min_value or "N/A",
                time_window=params.time_window or "N/A",
                other_context=params.other_context or "N/A"
            )
            
            result = await self.kernel.invoke(
                function_name="generate_prompt",
                plugin_name="prompt_plugin",
                arguments=arguments
            )
            
            generated = str(result).strip() if result else None
            
            if generated:
                logger.info(f"Generated prompt: {generated[:100]}...")
                return generated
            else:
                logger.warning("Empty result from SK, using fallback")
                return self._fallback_template(params)
                
        except Exception as e:
            logger.exception(f"Error generating prompt: {e}")
            return self._fallback_template(params)
    
    def _fallback_template(self, params: ResearchParameters) -> str:
        """Fallback template if SK invocation fails."""
        parts = []
        
        # Sector and company
        if params.company:
            parts.append(f"Research {params.sector} sector opportunities for {params.company}")
        else:
            parts.append(f"Research {params.sector} sector opportunities")
        
        # Signals
        if params.signals and params.signals.lower() != "n/a":
            parts.append(f"focusing on {params.signals} signals")
        
        # Geography and value
        filters = []
        if params.geography and params.geography.lower() != "n/a":
            filters.append(f"{params.geography} geography")
        if params.min_value and params.min_value.lower() != "n/a":
            filters.append(f"minimum ${params.min_value} value")
        if params.time_window and params.time_window.lower() != "n/a":
            filters.append(f"within {params.time_window}")
        
        if filters:
            parts.append(f"Filter for {', '.join(filters)}.")
        
        # Service lines
        if params.service_lines and params.service_lines.lower() != "n/a":
            parts.append(f"Prioritize {params.service_lines} service line opportunities.")
        
        # Other context
        if params.other_context and params.other_context.lower() != "n/a":
            parts.append(f"Additional context: {params.other_context}")
        
        return " ".join(parts)


# Global instance
prompt_generator: Optional[PromptGenerator] = None


def get_prompt_generator() -> PromptGenerator:
    """Get or create the global prompt generator instance."""
    global prompt_generator
    if prompt_generator is None:
        prompt_generator = PromptGenerator()
    return prompt_generator
