"""LLM model management and integration"""

from typing import Optional, Dict
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_core.language_models import BaseChatModel
from src.config.settings import settings
import structlog
import os

# Optional Groq import (may not be available due to dependency conflicts)
try:
    from langchain_groq import ChatGroq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    ChatGroq = None

logger = structlog.get_logger()


# Free LLM models configuration
FREE_LLM_MODELS = {
    "deepseek-r1": {
        "provider": "deepseek",
        "model_name": "deepseek-reasoner",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
    },
    "deepseek-v3": {
        "provider": "deepseek",
        "model_name": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
    },
    "groq-llama": {
        "provider": "groq",
        "model_name": "llama-3.1-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
    },
    "groq-mixtral": {
        "provider": "groq",
        "model_name": "mixtral-8x7b-32768",
        "api_key_env": "GROQ_API_KEY",
    },
    "ollama-llama": {
        "provider": "ollama",
        "model_name": "llama3.1",
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    },
    "ollama-qwen": {
        "provider": "ollama",
        "model_name": "qwen2.5",
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    },
}


def get_llm_for_agent(model_name: str = "deepseek-r1", provider: str = "deepseek") -> BaseChatModel:
    """
    Get LLM instance for an agent.

    - When DEEPSEEK_API_KEY is set, we **prefer DeepSeek** for faster cloud inference
      (scaling to a larger universe).
    - Otherwise we fall back to local Ollama.
    - Structured-output differences are handled in `call_llm_with_retry`, so it's
      safe to route agents/PM to DeepSeek here.
    """
    model_key = f"{provider}-{model_name}" if "-" not in model_name else model_name

    deepseek_key = os.getenv("DEEPSEEK_API_KEY") or getattr(settings, "deepseek_api_key", None)

    # If the agent requested an Ollama model but DeepSeek is available, route to
    # DeepSeek by default for better scalability. Individual agents can still
    # request a specific provider if needed.
    if deepseek_key and model_key.startswith("ollama"):
        logger.debug("Routing Ollama model to DeepSeek for scaling", original=model_key)
        model_key = "deepseek-v3"

    if model_key not in FREE_LLM_MODELS:
        logger.warning("Model not found, using default", model=model_key)
        model_key = "deepseek-v3" if deepseek_key else "ollama-llama"

    config = FREE_LLM_MODELS[model_key]
    provider_type = config["provider"]
    
    try:
        if provider_type == "deepseek":
            api_key = os.getenv(config["api_key_env"]) or getattr(settings, "deepseek_api_key", None)
            if not api_key:
                logger.warning("DeepSeek API key not found, falling back to Ollama")
                return ChatOllama(model="llama3.1", base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
            
            return ChatOpenAI(
                model=config["model_name"],
                api_key=api_key,
                base_url=config["base_url"],
            )
        
        elif provider_type == "groq":
            if not GROQ_AVAILABLE:
                logger.warning("Groq not available (dependency conflict), falling back to Ollama")
                return ChatOllama(model="llama3.1", base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
            
            api_key = os.getenv(config["api_key_env"]) or getattr(settings, "groq_api_key", None)
            if not api_key:
                logger.warning("Groq API key not found, falling back to Ollama")
                return ChatOllama(model="llama3.1", base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
            
            return ChatGroq(
                model=config["model_name"],
                api_key=api_key,
            )
        
        elif provider_type == "ollama":
            return ChatOllama(
                model=config["model_name"],
                base_url=config["base_url"],
            )
        
        else:
            logger.error("Unknown provider", provider=provider_type)
            # Fallback to Ollama
            return ChatOllama(model="llama3.1", base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    
    except Exception as e:
        logger.error("Error creating LLM, using fallback", error=str(e))
        # Fallback to Ollama
        return ChatOllama(model="llama3.1", base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))


def get_available_models() -> Dict[str, Dict]:
    """Get list of available free LLM models"""
    return FREE_LLM_MODELS.copy()

