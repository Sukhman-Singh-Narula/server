"""
System prompt service for handling prompt-related business logic
"""
from typing import List, Dict, Any, Optional
from datetime import datetime

from models.system_prompt import (
    SystemPrompt, SystemPromptRequest, SystemPromptResponse, 
    PromptValidationResult, PromptType, SeasonOverview
)
from services.firebase_service import get_firebase_service
from utils.exceptions import SystemPromptNotFoundException, ValidationException
from utils.validators import PromptValidator
from utils.logger import LoggerMixin, log_system_prompt_upload


class PromptService(LoggerMixin):
    """Service for system prompt operations"""
    
    def __init__(self):
        super().__init__()
        self.firebase_service = get_firebase_service()
    
    async def create_system_prompt(self, prompt_request: SystemPromptRequest) -> SystemPromptResponse:
        """
        Create or update a system prompt
        
        Args:
            prompt_request: Prompt creation request
            
        Returns:
            SystemPromptResponse: Created prompt information
            
        Raises:
            ValidationException: If validation fails
        """
        # Validate season and episode
        is_valid, error_msg = PromptValidator.validate_season_episode(
            prompt_request.season, prompt_request.episode
        )
        if not is_valid:
            raise ValidationException(error_msg, "season_episode")
        
        # Validate prompt content
        validation_result = self.validate_prompt_content(prompt_request.prompt)
        if not validation_result.is_valid:
            raise ValidationException(f"Prompt validation failed: {', '.join(validation_result.errors)}")
        
        try:
            # Create prompt in Firebase
            system_prompt = await self.firebase_service.create_system_prompt(
                season=prompt_request.season,
                episode=prompt_request.episode,
                prompt=prompt_request.prompt,
                prompt_type=prompt_request.prompt_type,
                metadata=prompt_request.metadata
            )
            
            # Log upload
            log_system_prompt_upload(prompt_request.season, prompt_request.episode, len(prompt_request.prompt))
            
            self.log_info(f"System prompt created: Season {prompt_request.season}, Episode {prompt_request.episode}")
            
            return SystemPromptResponse.from_system_prompt(system_prompt)
            
        except Exception as e:
            self.log_error(f"Failed to create system prompt S{prompt_request.season}E{prompt_request.episode}: {e}")
            raise ValidationException(f"Failed to create prompt: {str(e)}")
    
    async def get_system_prompt(self, season: int, episode: int) -> SystemPromptResponse:
        """
        Get system prompt for specific season and episode
        
        Args:
            season: Season number
            episode: Episode number
            
        Returns:
            SystemPromptResponse: Prompt information
            
        Raises:
            ValidationException: If parameters are invalid
            SystemPromptNotFoundException: If prompt not found
        """
        # Validate season and episode
        is_valid, error_msg = PromptValidator.validate_season_episode(season, episode)
        if not is_valid:
            raise ValidationException(error_msg, "season_episode")
        
        # Get prompt from Firebase
        system_prompt = await self.firebase_service.get_system_prompt(season, episode)
        return SystemPromptResponse.from_system_prompt(system_prompt)
    
    async def get_prompt_content(self, season: int, episode: int) -> str:
        """
        Get raw prompt content for OpenAI
        
        Args:
            season: Season number
            episode: Episode number
            
        Returns:
            str: Raw prompt content
        """
        system_prompt = await self.firebase_service.get_system_prompt(season, episode)
        return system_prompt.prompt
    
    async def get_season_overview(self, season: int) -> SeasonOverview:
        """
        Get overview of a complete season
        
        Args:
            season: Season number
            
        Returns:
            SeasonOverview: Season information
        """
        from config.settings import get_settings
        settings = get_settings()
        
        # Get all prompts for the season
        prompts = await self.firebase_service.get_all_prompts_for_season(season)
        
        # Calculate statistics
        total_episodes = settings.episodes_per_season
        completed_episodes = len(prompts)
        
        # Get unique prompt types
        prompt_types = list(set([prompt.prompt_type.value for prompt in prompts]))
        
        # Find last updated prompt
        last_updated = None
        if prompts:
            last_updated = max([prompt.updated_at for prompt in prompts if prompt.updated_at])
        
        return SeasonOverview(
            season=season,
            total_episodes=total_episodes,
            completed_episodes=completed_episodes,
            available_prompt_types=prompt_types,
            last_updated=last_updated
        )
    
    async def get_all_seasons_overview(self) -> List[SeasonOverview]:
        """
        Get overview of all seasons
        
        Returns:
            List[SeasonOverview]: List of season overviews
        """
        from config.settings import get_settings
        settings = get_settings()
        
        overviews = []
        for season in range(1, settings.max_seasons + 1):
            try:
                overview = await self.get_season_overview(season)
                overviews.append(overview)
            except Exception as e:
                self.log_warning(f"Failed to get overview for season {season}: {e}")
                # Create empty overview for missing seasons
                overviews.append(SeasonOverview(
                    season=season,
                    total_episodes=settings.episodes_per_season,
                    completed_episodes=0,
                    available_prompt_types=[],
                    last_updated=None
                ))
        
        return overviews
    
    def validate_prompt_content(self, prompt: str) -> PromptValidationResult:
        """
        Validate prompt content and provide suggestions
        
        Args:
            prompt: Prompt content to validate
            
        Returns:
            PromptValidationResult: Validation result with errors and suggestions
        """
        is_valid, issues = PromptValidator.validate_prompt_content(prompt)
        
        result = PromptValidationResult(is_valid=is_valid)
        
        # Categorize issues
        for issue in issues:
            if "cannot be empty" in issue or "should be at least" in issue or "should not exceed" in issue:
                result.add_error(issue)
            elif "inappropriate content" in issue or "template placeholders" in issue:
                result.add_error(issue)
            else:
                result.add_suggestion(issue)
        
        # Add additional suggestions for improvement
        self._add_quality_suggestions(prompt, result)
        
        return result
    
    def _add_quality_suggestions(self, prompt: str, result: PromptValidationResult):
        """Add quality improvement suggestions"""
        prompt_lower = prompt.lower()
        
        # Check for learning-specific keywords
        learning_keywords = ['learn', 'practice', 'exercise', 'lesson', 'teach']
        if not any(keyword in prompt_lower for keyword in learning_keywords):
            result.add_suggestion("Consider adding learning-focused language (learn, practice, etc.)")
        
        # Check for engagement elements
        engagement_keywords = ['fun', 'engaging', 'interactive', 'encouraging']
        if not any(keyword in prompt_lower for keyword in engagement_keywords):
            result.add_suggestion("Consider adding engaging elements to make learning more interactive")
        
        # Check for clear instructions
        if 'help' not in prompt_lower and 'assist' not in prompt_lower:
            result.add_suggestion("Consider explicitly stating how you will help the user")
        
        # Check for age-appropriate language guidance
        if 'age' not in prompt_lower and 'level' not in prompt_lower:
            result.add_suggestion("Consider mentioning age-appropriate communication")
    
    async def update_prompt_metadata(self, season: int, episode: int, 
                                   metadata: Dict[str, Any]) -> SystemPromptResponse:
        """
        Update prompt metadata without changing the content
        
        Args:
            season: Season number
            episode: Episode number
            metadata: New metadata to add/update
            
        Returns:
            SystemPromptResponse: Updated prompt information
        """
        # Get existing prompt
        existing_prompt = await self.firebase_service.get_system_prompt(season, episode)
        
        # Merge metadata
        updated_metadata = {**existing_prompt.metadata, **metadata}
        
        # Create updated prompt
        updated_prompt = await self.firebase_service.create_system_prompt(
            season=season,
            episode=episode,
            prompt=existing_prompt.prompt,
            prompt_type=existing_prompt.prompt_type,
            metadata=updated_metadata
        )
        
        self.log_info(f"Prompt metadata updated: Season {season}, Episode {episode}")
        return SystemPromptResponse.from_system_prompt(updated_prompt)
    
    async def deactivate_prompt(self, season: int, episode: int) -> bool:
        """
        Deactivate a system prompt (soft delete)
        
        Args:
            season: Season number
            episode: Episode number
            
        Returns:
            bool: True if deactivated successfully
        """
        try:
            # Get existing prompt
            existing_prompt = await self.firebase_service.get_system_prompt(season, episode)
            
            # Update with deactivated status
            deactivated_metadata = {
                **existing_prompt.metadata,
                "deactivated_at": datetime.now().isoformat(),
                "is_active": False
            }
            
            await self.firebase_service.create_system_prompt(
                season=season,
                episode=episode,
                prompt=existing_prompt.prompt,
                prompt_type=existing_prompt.prompt_type,
                metadata=deactivated_metadata
            )
            
            self.log_info(f"Prompt deactivated: Season {season}, Episode {episode}")
            return True
            
        except Exception as e:
            self.log_error(f"Failed to deactivate prompt S{season}E{episode}: {e}")
            return False
    
    async def search_prompts(self, query: str = None, prompt_type: PromptType = None,
                           season: int = None) -> List[SystemPromptResponse]:
        """
        Search prompts based on criteria
        
        Args:
            query: Text to search in prompt content
            prompt_type: Filter by prompt type
            season: Filter by season
            
        Returns:
            List[SystemPromptResponse]: Matching prompts
        """
        # Note: This is a simplified implementation
        # In a real application, you'd implement proper Firestore text search
        
        prompts = []
        
        if season:
            # Get all prompts for specific season
            season_prompts = await self.firebase_service.get_all_prompts_for_season(season)
            for prompt in season_prompts:
                if self._matches_search_criteria(prompt, query, prompt_type):
                    prompts.append(SystemPromptResponse.from_system_prompt(prompt))
        else:
            # Would need to implement cross-season search
            self.log_info("Cross-season search would require additional Firestore queries")
        
        return prompts
    
    def _matches_search_criteria(self, prompt: SystemPrompt, query: str = None, 
                                prompt_type: PromptType = None) -> bool:
        """Check if prompt matches search criteria"""
        if prompt_type and prompt.prompt_type != prompt_type:
            return False
        
        if query and query.lower() not in prompt.prompt.lower():
            return False
        
        return True
    
    async def get_prompt_analytics(self, season: int, episode: int) -> Dict[str, Any]:
        """
        Get analytics for a specific prompt
        
        Args:
            season: Season number
            episode: Episode number
            
        Returns:
            Dict[str, Any]: Prompt analytics
        """
        prompt = await self.firebase_service.get_system_prompt(season, episode)
        
        return {
            "prompt_info": {
                "season": prompt.season,
                "episode": prompt.episode,
                "prompt_type": prompt.prompt_type.value,
                "version": prompt.version,
                "is_active": prompt.is_active
            },
            "content_analysis": {
                "character_count": len(prompt.prompt),
                "word_count": len(prompt.prompt.split()),
                "line_count": len(prompt.prompt.split('\n')),
                "avg_words_per_line": len(prompt.prompt.split()) / max(len(prompt.prompt.split('\n')), 1)
            },
            "timestamps": {
                "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
                "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None
            },
            "metadata": prompt.metadata,
            "validation": self.validate_prompt_content(prompt.prompt).dict()
        }


# Global prompt service instance
_prompt_service: Optional[PromptService] = None


def get_prompt_service() -> PromptService:
    """Get prompt service singleton"""
    global _prompt_service
    if _prompt_service is None:
        _prompt_service = PromptService()
    return _prompt_service