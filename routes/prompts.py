"""
System prompt management routes
"""
from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional, Dict, Any

from models.system_prompt import (
    SystemPromptRequest, SystemPromptResponse, PromptValidationResult,
    SeasonOverview, PromptType
)
from services.prompt_service import get_prompt_service
from utils.exceptions import (
    ValidationException, SystemPromptNotFoundException,
    handle_validation_error, handle_generic_error
)
from utils.logger import LoggerMixin
from pydantic import BaseModel


router = APIRouter(prefix="/prompts", tags=["System Prompts"])


class PromptRoutes(LoggerMixin):
    """System prompt route handlers"""
    
    def __init__(self):
        super().__init__()
        self.prompt_service = get_prompt_service()


prompt_routes = PromptRoutes()


class PromptValidationRequest(BaseModel):
    """Request model for prompt validation"""
    prompt: str


class MetadataUpdateRequest(BaseModel):
    """Request model for updating prompt metadata"""
    metadata: Dict[str, Any]


@router.post("/",
             response_model=SystemPromptResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Create system prompt",
             description="Upload a new system prompt for a specific season and episode")
async def create_system_prompt(prompt_request: SystemPromptRequest):
    """
    Create or update a system prompt
    
    - **season**: Season number (1-10)
    - **episode**: Episode number (1-7)
    - **prompt**: System prompt content (10-5000 characters)
    - **prompt_type**: Type of prompt (learning, assessment, conversation, review)
    - **metadata**: Additional metadata (optional)
    """
    try:
        prompt_response = await prompt_routes.prompt_service.create_system_prompt(prompt_request)
        
        prompt_routes.log_info(f"System prompt created: Season {prompt_request.season}, Episode {prompt_request.episode}")
        return prompt_response
        
    except ValidationException as e:
        prompt_routes.log_warning(f"Prompt creation validation failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except Exception as e:
        prompt_routes.log_error(f"Failed to create prompt S{prompt_request.season}E{prompt_request.episode}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{season}/{episode}",
            response_model=SystemPromptResponse,
            summary="Get system prompt",
            description="Retrieve system prompt for specific season and episode")
async def get_system_prompt(season: int, episode: int):
    """
    Get system prompt for a specific season and episode
    
    - **season**: Season number
    - **episode**: Episode number
    """
    try:
        prompt_response = await prompt_routes.prompt_service.get_system_prompt(season, episode)
        
        prompt_routes.log_info(f"System prompt retrieved: Season {season}, Episode {episode}")
        return prompt_response
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except SystemPromptNotFoundException as e:
        prompt_routes.log_warning(f"Prompt not found: Season {season}, Episode {episode}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "System Prompt Not Found",
                "message": e.message,
                "season": season,
                "episode": episode,
                "code": e.error_code
            }
        )
    
    except Exception as e:
        prompt_routes.log_error(f"Failed to get prompt S{season}E{episode}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{season}/{episode}/content",
            summary="Get prompt content",
            description="Get raw prompt content for OpenAI (internal use)")
async def get_prompt_content(season: int, episode: int):
    """
    Get raw prompt content for OpenAI integration
    
    - **season**: Season number
    - **episode**: Episode number
    """
    try:
        content = await prompt_routes.prompt_service.get_prompt_content(season, episode)
        
        return {
            "season": season,
            "episode": episode,
            "content": content,
            "character_count": len(content)
        }
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except SystemPromptNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "System Prompt Not Found",
                "message": e.message,
                "season": season,
                "episode": episode
            }
        )
    
    except Exception as e:
        prompt_routes.log_error(f"Failed to get prompt content S{season}E{episode}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{season}",
            response_model=SeasonOverview,
            summary="Get season overview",
            description="Get overview of all episodes in a season")
async def get_season_overview(season: int):
    """
    Get overview of a complete season
    
    - **season**: Season number
    """
    try:
        overview = await prompt_routes.prompt_service.get_season_overview(season)
        
        prompt_routes.log_info(f"Season overview retrieved: Season {season}")
        return overview
        
    except Exception as e:
        prompt_routes.log_error(f"Failed to get season overview for {season}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/",
            response_model=List[SeasonOverview],
            summary="Get all seasons overview",
            description="Get overview of all seasons")
async def get_all_seasons_overview():
    """
    Get overview of all seasons with completion statistics
    """
    try:
        overviews = await prompt_routes.prompt_service.get_all_seasons_overview()
        
        prompt_routes.log_info("All seasons overview retrieved")
        return overviews
        
    except Exception as e:
        prompt_routes.log_error(f"Failed to get all seasons overview: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.post("/validate",
             response_model=PromptValidationResult,
             summary="Validate prompt content",
             description="Validate prompt content and get improvement suggestions")
async def validate_prompt(validation_request: PromptValidationRequest):
    """
    Validate prompt content and provide suggestions for improvement
    
    - **prompt**: Prompt content to validate
    """
    try:
        validation_result = prompt_routes.prompt_service.validate_prompt_content(validation_request.prompt)
        
        return validation_result
        
    except Exception as e:
        prompt_routes.log_error(f"Failed to validate prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.put("/{season}/{episode}/metadata",
            response_model=SystemPromptResponse,
            summary="Update prompt metadata",
            description="Update metadata for an existing prompt")
async def update_prompt_metadata(season: int, episode: int, metadata_update: MetadataUpdateRequest):
    """
    Update prompt metadata without changing the content
    
    - **season**: Season number
    - **episode**: Episode number
    - **metadata**: New metadata to add/update
    """
    try:
        updated_prompt = await prompt_routes.prompt_service.update_prompt_metadata(
            season, episode, metadata_update.metadata
        )
        
        prompt_routes.log_info(f"Prompt metadata updated: Season {season}, Episode {episode}")
        return updated_prompt
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except SystemPromptNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "System Prompt Not Found",
                "message": e.message,
                "season": season,
                "episode": episode
            }
        )
    
    except Exception as e:
        prompt_routes.log_error(f"Failed to update metadata S{season}E{episode}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.delete("/{season}/{episode}",
               summary="Deactivate prompt",
               description="Deactivate (soft delete) a system prompt")
async def deactivate_prompt(season: int, episode: int):
    """
    Deactivate a system prompt (soft delete)
    
    - **season**: Season number
    - **episode**: Episode number
    """
    try:
        success = await prompt_routes.prompt_service.deactivate_prompt(season, episode)
        
        if success:
            prompt_routes.log_info(f"Prompt deactivated: Season {season}, Episode {episode}")
            return {
                "message": "System prompt deactivated successfully",
                "season": season,
                "episode": episode
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "Failed to deactivate prompt"}
            )
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except SystemPromptNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "System Prompt Not Found",
                "message": e.message,
                "season": season,
                "episode": episode
            }
        )
    
    except Exception as e:
        prompt_routes.log_error(f"Failed to deactivate prompt S{season}E{episode}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/search",
            response_model=List[SystemPromptResponse],
            summary="Search prompts",
            description="Search prompts by content, type, or season")
async def search_prompts(
    query: Optional[str] = Query(None, description="Text to search in prompt content"),
    prompt_type: Optional[PromptType] = Query(None, description="Filter by prompt type"),
    season: Optional[int] = Query(None, description="Filter by season")
):
    """
    Search prompts based on various criteria
    
    - **query**: Text to search in prompt content (optional)
    - **prompt_type**: Filter by prompt type (optional)
    - **season**: Filter by season (optional)
    """
    try:
        results = await prompt_routes.prompt_service.search_prompts(
            query=query,
            prompt_type=prompt_type,
            season=season
        )
        
        prompt_routes.log_info(f"Prompt search performed: query='{query}', type={prompt_type}, season={season}")
        return results
        
    except Exception as e:
        prompt_routes.log_error(f"Failed to search prompts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/{season}/{episode}/analytics",
            summary="Get prompt analytics",
            description="Get detailed analytics for a specific prompt")
async def get_prompt_analytics(season: int, episode: int):
    """
    Get analytics and statistics for a specific prompt
    
    - **season**: Season number
    - **episode**: Episode number
    """
    try:
        analytics = await prompt_routes.prompt_service.get_prompt_analytics(season, episode)
        
        prompt_routes.log_info(f"Prompt analytics retrieved: Season {season}, Episode {episode}")
        return analytics
        
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=handle_validation_error(e)
        )
    
    except SystemPromptNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "System Prompt Not Found",
                "message": e.message,
                "season": season,
                "episode": episode
            }
        )
    
    except Exception as e:
        prompt_routes.log_error(f"Failed to get prompt analytics S{season}E{episode}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=handle_generic_error(e)
        )


@router.get("/types",
            summary="Get prompt types",
            description="Get list of available prompt types")
async def get_prompt_types():
    """
    Get list of available prompt types
    """
    return {
        "prompt_types": [
            {
                "value": prompt_type.value,
                "description": f"{prompt_type.value.title()} type prompt"
            }
            for prompt_type in PromptType
        ]
    }