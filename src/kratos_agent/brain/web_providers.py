"""The browser origins explicitly supported by the local cookie connector."""

WEB_PROVIDERS = {
    "chatgpt-web": {"name": "ChatGPT", "url": "https://chatgpt.com/", "domains": ["chatgpt.com", "openai.com"]},
    "qwen-browser": {"name": "Qwen", "url": "https://chat.qwen.ai/", "domains": ["qwen.ai"]},
    "doubao-web": {"name": "Dola", "url": "https://www.dola.com/chat/", "domains": ["dola.com"]},
    "gemini-web": {"name": "Gemini", "url": "https://gemini.google.com/app", "domains": ["google.com"]},
    "deepseek-web": {"name": "DeepSeek", "url": "https://chat.deepseek.com/", "domains": ["deepseek.com"]},
    "kimi-web": {"name": "Kimi", "url": "https://www.kimi.ai/", "domains": ["kimi.ai"]},
    "muse-spark-web": {"name": "Meta AI", "url": "https://www.meta.ai/", "domains": ["meta.ai"]},
    "groq-web": {"name": "Groq Chat", "url": "https://chat.groq.com/", "domains": ["groq.com"], "anonymous": True},
    "grok-web": {"name": "Grok", "url": "https://grok.com/", "domains": ["grok.com"]},
    "claude-web": {"name": "Claude", "url": "https://claude.ai/", "domains": ["claude.ai"]},
    "perplexity-web": {"name": "Perplexity", "url": "https://www.perplexity.ai/", "domains": ["perplexity.ai"]},
    "zai-web": {"name": "Z.ai", "url": "https://chat.z.ai/", "domains": ["z.ai"]},
}

BROWSER_PROVIDERS = {"chatgpt-web", "browser-web"}
