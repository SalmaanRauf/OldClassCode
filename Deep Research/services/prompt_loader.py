"""
Simple prompt loader for industry-specific research instructions.
Reads Markdown prompt files and injects them into Deep Research agents.
"""

import json
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class PromptLoader:
    """Loads industry-specific prompts from markdown files."""
    
    def __init__(self, prompts_dir: Optional[Path] = None):
        if prompts_dir is None:
            prompts_dir = Path(__file__).parent.parent / "prompts"
        
        self.prompts_dir = prompts_dir
        self.metadata_path = prompts_dir / "metadata.json"
        
        # Load metadata
        if not self.metadata_path.exists():
            raise FileNotFoundError(
                f"Prompt metadata file not found: {self.metadata_path}"
            )
        
        with open(self.metadata_path) as f:
            self._metadata = json.load(f)
        
        logger.info(f"PromptLoader initialized with {len(self._metadata['prompts'])} industry prompts")
    
    def get_available_industries(self) -> Dict[str, Dict]:
        """
        Get list of available industry prompts with metadata.
        
        Returns:
            {
                "defense": {
                    "version": "1.0",
                    "display_name": " Defense",
                    "description": "SAM.gov, GAO, ...",
                    ...
                },
                ...
            }
        """
        return self._metadata["prompts"]
    
    def load_prompt(self, industry: str) -> str:
        """
        Load prompt instructions for specified industry.
        
        Args:
            industry: Industry key (e.g., "defense", "financial_services")
        
        Returns:
            Full prompt text as string
        
        Raises:
            ValueError: If industry not found
            FileNotFoundError: If prompt file missing
        """
        if industry not in self._metadata["prompts"]:
            available = list(self._metadata["prompts"].keys())
            raise ValueError(
                f"Industry '{industry}' not found. "
                f"Available: {', '.join(available)}"
            )
        
        prompt_config = self._metadata["prompts"][industry]
        prompt_file = self.prompts_dir / prompt_config["file"]
        
        if not prompt_file.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {prompt_file}"
            )
        
        logger.info(
            f"Loading prompt: {industry} v{prompt_config['version']} "
            f"(updated {prompt_config['last_updated']})"
        )
        
        with open(prompt_file, "r", encoding="utf-8") as f:
            prompt_text = f.read()
        
        return prompt_text
    
    def get_prompt_metadata(self, industry: str) -> Dict:
        """
        Get metadata for a specific industry prompt.
        
        Args:
            industry: Industry key
            
        Returns:
            Metadata dict with version, display_name, description, etc.
            
        Raises:
            ValueError: If industry not found
        """
        if industry not in self._metadata["prompts"]:
            available = list(self._metadata["prompts"].keys())
            raise ValueError(
                f"Industry '{industry}' not found. "
                f"Available: {', '.join(available)}"
            )
        return self._metadata["prompts"][industry]

