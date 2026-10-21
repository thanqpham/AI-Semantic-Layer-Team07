"""Official provider endpoints offered in account settings."""

PROVIDERS = {
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "openai"),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "openai"),
    "openai": ("OpenAI", "https://api.openai.com/v1", "openai"),
    "anthropic": ("Anthropic (Claude)", "https://api.anthropic.com", "anthropic"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com", "openai"),
    "groq": ("Groq", "https://api.groq.com/openai/v1", "openai"),
    "mimo": ("MiMo", "https://api.xiaomimimo.com/v1", "openai"),
}
