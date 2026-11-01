"""Official provider endpoints offered in account settings."""

PROVIDERS = {
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "openai"),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "openai"),
    "openai": ("OpenAI", "https://api.openai.com/v1", "openai"),
    "anthropic": ("Anthropic (Claude)", "https://api.anthropic.com", "anthropic"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com", "openai"),
    "groq": ("Groq", "https://api.groq.com/openai/v1", "openai"),
    "mimo": ("MiMo", "https://api.xiaomimimo.com/v1", "openai"),
    "mistral": ("Mistral AI", "https://api.mistral.ai/v1", "openai"),
    "xai": ("xAI (Grok)", "https://api.x.ai/v1", "openai"),
    "together": ("Together AI", "https://api.together.xyz/v1", "openai"),
    "fireworks": ("Fireworks AI", "https://api.fireworks.ai/inference/v1", "openai"),
    "perplexity": ("Perplexity", "https://api.perplexity.ai", "openai"),
    "cerebras": ("Cerebras", "https://api.cerebras.ai/v1", "openai"),
    "qwen": ("Alibaba Qwen (DashScope)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "openai"),
    "moonshot": ("Moonshot AI (Kimi)", "https://api.moonshot.ai/v1", "openai"),
        "cohere": ("Cohere", "https://api.cohere.com/compatibility/v1", "openai"),
    "glm": ("Zhipu AI (GLM)", "https://open.bigmodel.cn/api/paas/v4", "openai"),
}
