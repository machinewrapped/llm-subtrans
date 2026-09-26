"""
Identifies LLM-Subtrans to API routers that attribute requests to the calling app.
"""

# OpenRouter-style app attribution, also accepted by Requesty
APP_ATTRIBUTION_HEADERS : dict[str, str] = {
    'HTTP-Referer': 'https://github.com/machinewrapped/llm-subtrans',
    'X-Title': 'LLM-Subtrans',
}
